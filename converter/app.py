"""The CG50 Video Converter window. Start it with convert.py (no arguments)."""
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cgvideo import estimate, names  # noqa: E402
from cgvideo.errors import Cancelled, ConvertError  # noqa: E402
from cgvideo.palettes import AUTO, FIXED_PALETTES, PALETTE_LABELS  # noqa: E402
from cgvideo.pipeline import (CALCULATOR_STORAGE, FPS_CHOICES, SAFE_SIZE, SCREEN_H, SCREEN_W,  # noqa: E402
                              SIZE_PRESETS, FrameGrabber, Settings, convert, frame_to_indices,
                              make_palette, probe, screen_image)

VIDEO_TYPES = [("Videos", "*.mp4 *.mov *.m4v *.avi *.mkv *.webm *.wmv *.flv *.mpg *.mpeg *.gif"),
               ("All files", "*.*")]
PALETTE_KEYS = [AUTO] + list(FIXED_PALETTES)
SIZE_LABELS = ["Tiny: 96×54 (smallest file)", "Recommended: 128×72", "Sharp: 192×108",
               "Full screen: 384×216 (biggest file)"]
FPS_LABELS = ["Same as the video"] + ["%d fps%s" % (f, "  (recommended)" if f == 15 else "") for f in FPS_CHOICES[1:]]


def fmt_time(seconds):
    seconds = int(round(seconds or 0))
    return "%d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60) if seconds >= 3600 \
        else "%d:%02d" % (seconds // 60, seconds % 60)


def parse_time(text):
    """'' -> None; '90', '1:30', '0:01:30' -> seconds. Raises ValueError."""
    text = text.strip()
    if not text:
        return None
    total = 0.0
    for part in text.split(":"):
        total = total * 60 + float(part)
    if total < 0:
        raise ValueError(text)
    return total


def fmt_size(n):
    return "%.1f MB" % (n / (1024 * 1024)) if n >= 100 * 1024 else "%d KB" % max(1, round(n / 1024))


def show_in_folder(path):
    path = str(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        elif os.name == "nt":
            subprocess.Popen(["explorer", "/select,", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except OSError:
        pass


class App:
    POLL_MS = 50

    def __init__(self, root, dialogs=True):
        self.root = root
        self.dialogs = dialogs  # False in --selftest, where nobody can click OK
        self.info = None
        self.generation = 0
        self.palette_cache = {}
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.cancel_event = None
        self.converting = False
        self.preview_photo = None
        self.preview_image = None
        self.last_estimate = None
        self.last_result = None
        self.last_output = None
        self._update_after = None
        self._preview_after = None
        self._suspend_traces = False
        self.zoom = 2 if root.winfo_screenwidth() >= 1400 and root.winfo_screenheight() >= 900 else 1

        root.title("CG50 Video Converter")
        self._build_ui()
        threading.Thread(target=self._worker, daemon=True).start()
        root.after(self.POLL_MS, self._poll)

    # --- Layout ---------------------------------------------------------------

    def _build_ui(self):
        root = self.root
        outer = ttk.Frame(root, padding=12)
        outer.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        head = ttk.Frame(outer)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="CG50 Video Converter", font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        ttk.Label(head, text="Turn a video into a file for the fx-CG50 video player.").pack(anchor="w")

        # Step 1: open + preview
        step1 = ttk.LabelFrame(outer, text=" 1. Choose a video ", padding=8)
        step1.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        step1.columnconfigure(1, weight=1)
        self.open_btn = ttk.Button(step1, text="Open video…", command=self.choose_video)
        self.open_btn.grid(row=0, column=0, sticky="w")
        self.info_label = ttk.Label(step1, text="No video yet.")
        self.info_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        self.canvas = tk.Canvas(step1, width=SCREEN_W * self.zoom, height=SCREEN_H * self.zoom,
                                background="#202020", highlightthickness=1, highlightbackground="#808080")
        self.canvas.grid(row=1, column=0, columnspan=2, pady=(8, 4))
        self.canvas_image = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas_text = self.canvas.create_text(SCREEN_W * self.zoom // 2, SCREEN_H * self.zoom // 2,
                                                   fill="#d0d0d0", text="Open a video to see how it will\n"
                                                   "look on the calculator.", justify="center")

        pos = ttk.Frame(step1)
        pos.grid(row=2, column=0, columnspan=2, sticky="ew")
        pos.columnconfigure(1, weight=1)
        ttk.Label(pos, text="Preview at:").grid(row=0, column=0)
        self.pos_var = tk.DoubleVar(value=0.0)
        self.pos_scale = ttk.Scale(pos, from_=0, to=1, variable=self.pos_var, command=lambda _v: self._position_moved())
        self.pos_scale.grid(row=0, column=1, sticky="ew", padx=6)
        self.pos_label = ttk.Label(pos, text="0:00", width=8)
        self.pos_label.grid(row=0, column=2)

        # Step 2: settings
        step2 = ttk.LabelFrame(outer, text=" 2. Settings ", padding=8)
        step2.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        step2.columnconfigure(1, weight=1)

        ttk.Label(step2, text="Picture size").grid(row=0, column=0, sticky="w", pady=2)
        self.size_combo = ttk.Combobox(step2, values=SIZE_LABELS, state="readonly", width=34)
        self.size_combo.current(1)
        self.size_combo.grid(row=0, column=1, sticky="w")

        ttk.Label(step2, text="Frame rate").grid(row=1, column=0, sticky="w", pady=2)
        self.fps_combo = ttk.Combobox(step2, values=FPS_LABELS, state="readonly", width=34)
        self.fps_combo.current(FPS_CHOICES.index(15))
        self.fps_combo.grid(row=1, column=1, sticky="w")

        ttk.Label(step2, text="Colors").grid(row=2, column=0, sticky="w", pady=2)
        colors = ttk.Frame(step2)
        colors.grid(row=2, column=1, sticky="w")
        self.palette_combo = ttk.Combobox(colors, values=[PALETTE_LABELS[k] for k in PALETTE_KEYS],
                                          state="readonly", width=26)
        self.palette_combo.current(0)
        self.palette_combo.pack(side="left")
        self.colors_var = tk.StringVar(value="4")
        self.colors_spin = ttk.Spinbox(colors, from_=2, to=16, textvariable=self.colors_var, width=4,
                                       state="readonly")
        self.colors_spin.pack(side="left", padx=(8, 4))
        self.colors_label = ttk.Label(colors, text="colors (fewer = smaller file)")
        self.colors_label.pack(side="left")

        self.dither_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(step2, text="Smoother shading (dithering). Makes the file bigger.",
                        variable=self.dither_var).grid(row=3, column=1, sticky="w", pady=2)

        ttk.Label(step2, text="Part of the video").grid(row=4, column=0, sticky="w", pady=2)
        trim = ttk.Frame(step2)
        trim.grid(row=4, column=1, sticky="w")
        self.start_var = tk.StringVar(value="")
        self.end_var = tk.StringVar(value="")
        ttk.Label(trim, text="from").pack(side="left")
        ttk.Entry(trim, textvariable=self.start_var, width=8).pack(side="left", padx=4)
        ttk.Label(trim, text="to").pack(side="left")
        ttk.Entry(trim, textvariable=self.end_var, width=8).pack(side="left", padx=4)
        ttk.Label(trim, text="(like 0:30; leave empty for the whole video)").pack(side="left")

        self.adv_btn = ttk.Button(step2, text="Show advanced options ▸", command=self._toggle_advanced)
        self.adv_btn.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.adv = ttk.Frame(step2)
        self.adv.columnconfigure(1, weight=1)
        self.fit_var = tk.StringVar(value="letterbox")
        ttk.Label(self.adv, text="Shape").grid(row=0, column=0, sticky="w", pady=2)
        fit = ttk.Frame(self.adv)
        fit.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(fit, text="Show the whole picture", value="letterbox", variable=self.fit_var).pack(side="left")
        ttk.Radiobutton(fit, text="Fill the screen (crop edges)", value="crop", variable=self.fit_var).pack(side="left", padx=8)
        self.fmt_var = tk.IntVar(value=2)
        ttk.Label(self.adv, text="File type").grid(row=1, column=0, sticky="w", pady=2)
        fmt = ttk.Frame(self.adv)
        fmt.grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(fmt, text="New player (smaller files)", value=2, variable=self.fmt_var).pack(side="left")
        ttk.Radiobutton(fmt, text="Old player v2.0", value=1, variable=self.fmt_var).pack(side="left", padx=8)
        ttk.Label(self.adv, text="Title").grid(row=2, column=0, sticky="w", pady=2)
        self.title_var = tk.StringVar(value="")
        ttk.Entry(self.adv, textvariable=self.title_var, width=26).grid(row=2, column=1, sticky="w")

        # Step 3: save
        step3 = ttk.LabelFrame(outer, text=" 3. Convert ", padding=8)
        step3.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        step3.columnconfigure(1, weight=1)

        est = ttk.Frame(step3)
        est.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.estimate_label = ttk.Label(est, text="File size: open a video first", font=("TkDefaultFont", 12, "bold"))
        self.estimate_label.pack(side="left")
        self.fit_btn = ttk.Button(est, text="Make it fit", command=self.make_it_fit, state="disabled")
        self.fit_btn.pack(side="right")
        self.meter = tk.Canvas(step3, height=12, highlightthickness=0, background="#e0e0e0")
        self.meter.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        self.meter_bar = self.meter.create_rectangle(0, 0, 0, 12, width=0, fill="#3a3")

        ttk.Label(step3, text="Save as").grid(row=2, column=0, sticky="w")
        self.output_var = tk.StringVar(value="")
        ttk.Entry(step3, textvariable=self.output_var).grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Button(step3, text="Change…", command=self.choose_output).grid(row=2, column=2)

        actions = ttk.Frame(step3)
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        actions.columnconfigure(1, weight=1)
        self.convert_btn = ttk.Button(actions, text="Convert", command=self.start_convert, state="disabled")
        self.convert_btn.grid(row=0, column=0)
        self.progress = ttk.Progressbar(actions, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=1, sticky="ew", padx=8)
        self.cancel_btn = ttk.Button(actions, text="Cancel", command=self.cancel_convert, state="disabled")
        self.cancel_btn.grid(row=0, column=2)
        self.show_btn = ttk.Button(actions, text="Show file", state="disabled",
                                   command=lambda: show_in_folder(self.last_output))
        self.show_btn.grid(row=0, column=3, padx=(6, 0))
        self.status = ttk.Label(step3, text="", wraplength=SCREEN_W * self.zoom)
        self.status.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

        for var in (self.colors_var, self.dither_var, self.start_var, self.end_var, self.fit_var, self.fmt_var):
            var.trace_add("write", lambda *_: self._settings_changed())
        for combo in (self.size_combo, self.fps_combo, self.palette_combo):
            combo.bind("<<ComboboxSelected>>", lambda _e: self._settings_changed())
        self._sync_colors_state()

    def _toggle_advanced(self):
        if self.adv.winfo_ismapped():
            self.adv.grid_remove()
            self.adv_btn.configure(text="Show advanced options ▸")
        else:
            self.adv.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0))
            self.adv_btn.configure(text="Hide advanced options ▾")

    def _sync_colors_state(self):
        auto = PALETTE_KEYS[self.palette_combo.current()] == AUTO
        self.colors_spin.configure(state="readonly" if auto else "disabled")
        self.colors_label.configure(text="colors (fewer = smaller file)" if auto else "")

    def set_status(self, text, error=False):
        self.status.configure(text=text, foreground="#b00" if error else "")

    # --- Settings <-> widgets -------------------------------------------------

    def current_settings(self):
        _, _, w, h = SIZE_PRESETS[self.size_combo.current()]
        try:
            start = parse_time(self.start_var.get()) or 0.0
            end = parse_time(self.end_var.get())
        except ValueError:
            raise ConvertError("Times must look like 45 (seconds) or 1:30 (minutes:seconds).")
        if end is not None and end <= start:
            raise ConvertError("The end time must be after the start time.")
        return Settings(width=w, height=h, fps=FPS_CHOICES[self.fps_combo.current()],
                        colors=int(self.colors_var.get() or 4), palette=PALETTE_KEYS[self.palette_combo.current()],
                        dither=bool(self.dither_var.get()), start=start, end=end, fit=self.fit_var.get(),
                        title=self.title_var.get()[:24], fmt=int(self.fmt_var.get()))

    def apply_settings(self, s):
        self._suspend_traces = True
        try:
            sizes = [(w, h) for _, _, w, h in SIZE_PRESETS]
            if (s.width, s.height) in sizes:
                self.size_combo.current(sizes.index((s.width, s.height)))
            if s.fps in FPS_CHOICES:
                self.fps_combo.current(FPS_CHOICES.index(s.fps))
            self.palette_combo.current(PALETTE_KEYS.index(s.palette))
            self.colors_var.set(str(s.colors))
            self.dither_var.set(s.dither)
        finally:
            self._suspend_traces = False
        self._settings_changed()

    def _palette_key(self, s):
        return (self.info.path if self.info else None, s.width, s.height, s.fit, s.palette, s.colors, s.start, s.end)

    # --- Reacting to the user -------------------------------------------------

    def choose_video(self):
        path = filedialog.askopenfilename(title="Choose a video", filetypes=VIDEO_TYPES)
        if path:
            self.open_video(path)

    def open_video(self, path):
        self.generation += 1
        self.info = None
        self.convert_btn.configure(state="disabled")
        self.fit_btn.configure(state="disabled")
        self.info_label.configure(text="Opening %s…" % Path(path).name)
        self.jobs.put(("load", self.generation, path))

    def choose_output(self):
        current = Path(self.output_var.get()) if self.output_var.get() else None
        path = filedialog.asksaveasfilename(
            title="Save the calculator file as", defaultextension=".bin",
            initialdir=str(current.parent) if current else None,
            initialfile=current.name if current else "video.bin", filetypes=[("Calculator video", "*.bin")])
        if path:
            self.output_var.set(path)

    def _settings_changed(self):
        self._sync_colors_state()
        if self._suspend_traces or not self.info:
            return
        if self._update_after:
            self.root.after_cancel(self._update_after)
        self._update_after = self.root.after(400, self.request_updates)

    def _position_moved(self):
        self.pos_label.configure(text=fmt_time(self.pos_var.get()))
        if not self.info:
            return
        if self._preview_after:
            self.root.after_cancel(self._preview_after)
        self._preview_after = self.root.after(120, self._request_preview)

    def _request_preview(self):
        try:
            settings = self.current_settings()
        except ConvertError:
            return
        self.jobs.put(("preview", self.generation, settings, float(self.pos_var.get())))

    def request_updates(self):
        self._update_after = None
        try:
            settings = self.current_settings()
        except ConvertError as e:
            self.set_status(str(e), error=True)
            return
        self.set_status("")
        self.generation += 1
        self.last_estimate = None
        self.estimate_label.configure(text="File size: estimating…", foreground="")
        self.jobs.put(("preview", self.generation, settings, float(self.pos_var.get())))
        self.jobs.put(("estimate", self.generation, settings))

    def make_it_fit(self):
        try:
            settings = self.current_settings()
        except ConvertError as e:
            self.set_status(str(e), error=True)
            return
        self.fit_btn.configure(state="disabled")
        self.estimate_label.configure(text="Finding settings that fit…", foreground="")
        self.jobs.put(("fit", self.generation, settings))

    def start_convert(self):
        if not self.info or self.converting:
            return
        try:
            settings = self.current_settings()
        except ConvertError as e:
            self._error("Can't convert yet", str(e))
            return
        out = Path(self.output_var.get().strip()).expanduser()
        if not self.output_var.get().strip():
            self._error("Can't convert yet", "Choose where to save the file first.")
            return
        if out.suffix.lower() != ".bin":
            out = out.with_suffix(".bin")
            self.output_var.set(str(out))
        if not out.parent.is_dir():
            self._error("Can't convert yet", "The folder %s doesn't exist." % out.parent)
            return
        if out.exists() and self.dialogs and not messagebox.askyesno("Replace file?", "%s already exists. Replace it?" % out.name):
            return

        palette = self.palette_cache.get(self._palette_key(settings))
        info = self.info
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        self.converting = True
        self.convert_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.open_btn.configure(state="disabled")
        self.show_btn.configure(state="disabled")
        self.progress.configure(value=0)
        self.set_status("Converting…")

        def progress(done, total):
            if done == 1 or done % 5 == 0 or done == total:
                self.results.put(("progress", done, total))

        def work():
            try:
                result = convert(info.path, out, settings, progress=progress, cancel=cancel, info=info, palette=palette)
                self.results.put(("done", out, result))
            except Cancelled:
                self.results.put(("cancelled",))
            except Exception as e:  # shown to the user
                self.results.put(("convert_error", e))

        threading.Thread(target=work, daemon=True).start()

    def cancel_convert(self):
        if self.cancel_event:
            self.cancel_event.set()
            self.set_status("Cancelling…")

    def _error(self, title, text):
        self.set_status(text, error=True)
        if self.dialogs:
            messagebox.showerror(title, text)

    # --- Background work --------------------------------------------------------

    def _palette_for(self, settings, grabber):
        key = self._palette_key(settings)
        palette = self.palette_cache.get(key)
        if palette is None:
            palette = make_palette(grabber.info, settings, grabber=grabber)
            if len(self.palette_cache) > 32:
                self.palette_cache.clear()
            self.palette_cache[key] = palette
        return palette

    def _worker(self):
        """Loads videos, renders previews and estimates sizes without freezing the window."""
        grabber = None
        while True:
            batch = [self.jobs.get()]
            while True:
                try:
                    batch.append(self.jobs.get_nowait())
                except queue.Empty:
                    break
            latest = {}
            for job in batch:  # only the newest request of each kind matters
                latest[job[0]] = job
            for kind in ("load", "preview", "estimate", "fit"):
                job = latest.get(kind)
                if job is None or (kind != "load" and grabber is None):
                    continue
                gen = job[1]
                try:
                    if kind == "load":
                        info = probe(job[2])
                        if grabber:
                            grabber.close()
                        grabber = FrameGrabber(info)
                        self.results.put(("loaded", gen, info))
                    elif kind == "preview":
                        settings, t = job[2], job[3]
                        palette = self._palette_for(settings, grabber)
                        frame = grabber.frame_at(t)
                        if frame is None:
                            raise ConvertError("Couldn't read the picture at this point of the video.")
                        indices = frame_to_indices(frame, settings, palette)
                        self.results.put(("preview", gen, Image.fromarray(screen_image(indices, palette))))
                    elif kind == "estimate":
                        settings = job[2]
                        palette = self._palette_for(settings, grabber)
                        self.results.put(("estimate", gen, estimate.estimate_size(grabber.info, settings, palette=palette)))
                    elif kind == "fit":
                        fitted, est = estimate.make_it_fit(grabber.info, job[2])
                        self.results.put(("fit", gen, fitted, est))
                except Exception as e:  # reported in the window
                    self.results.put(("error", gen, kind, e))

    def _poll(self):
        try:
            while True:
                self._handle(self.results.get_nowait())
        except queue.Empty:
            pass
        self.root.after(self.POLL_MS, self._poll)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "loaded":
            _, gen, info = msg
            if gen != self.generation:
                return
            self.info = info
            name = Path(info.path).name
            length = fmt_time(info.duration) if info.duration else "unknown length"
            self.info_label.configure(text="%s: %d×%d, %g fps, %s" % (name, info.width, info.height, round(info.fps, 2), length))
            self.pos_scale.configure(to=max(0.1, (info.duration or 1.0) - 0.05))
            self.pos_var.set(min((info.duration or 0) * 0.25, 5.0))
            self.pos_label.configure(text=fmt_time(self.pos_var.get()))
            folder = Path(info.path).parent
            self.output_var.set(str(folder / names.calculator_name(info.path, folder)))
            self.title_var.set(Path(info.path).stem[:24])
            self.convert_btn.configure(state="normal")
            self.fit_btn.configure(state="normal")
            self.canvas.itemconfigure(self.canvas_text, text="")
            self.request_updates()
        elif kind == "preview":
            _, gen, img = msg
            if gen != self.generation:
                return
            if self.zoom != 1:
                img = img.resize((SCREEN_W * self.zoom, SCREEN_H * self.zoom), Image.NEAREST)
            self.preview_image = img
            self.preview_photo = ImageTk.PhotoImage(img)
            self.canvas.itemconfigure(self.canvas_image, image=self.preview_photo)
        elif kind == "estimate":
            _, gen, est = msg
            if gen == self.generation:
                self._show_estimate(est)
        elif kind == "fit":
            _, gen, fitted, est = msg
            self.fit_btn.configure(state="normal")
            if fitted is None:
                self._show_estimate(est)
                self._error("Still too big", "Even the smallest settings make a file that's too big. "
                                             "Try converting a shorter part of the video.")
            else:
                self.apply_settings(fitted)
        elif kind == "error":
            _, gen, what, err = msg
            text = str(err) if isinstance(err, ConvertError) else "Something went wrong: %s" % err
            if what == "load":
                self.info_label.configure(text="No video yet.")
                self._error("Couldn't open the video", text)
            elif gen == self.generation:
                if what == "fit":
                    self.fit_btn.configure(state="normal")
                self.set_status(text, error=True)
        elif kind == "progress":
            _, done, total = msg
            if total:
                self.progress.configure(value=min(100, 100 * done / total))
                self.set_status("Converting… %d of %d frames" % (done, total))
            else:
                self.progress.configure(mode="indeterminate")
                self.set_status("Converting… %d frames" % done)
        elif kind in ("done", "cancelled", "convert_error"):
            self.converting = False
            self.convert_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            self.open_btn.configure(state="normal")
            self.progress.configure(mode="determinate", value=100 if kind == "done" else 0)
            if kind == "done":
                _, out, result = msg
                self.last_output, self.last_result = out, result
                self.show_btn.configure(state="normal")
                text = ("Saved %s (%s, %d frames). Copy it to the calculator's main folder: connect the USB "
                        "cable, choose 'USB Flash' on the calculator, and drag the file onto the drive."
                        % (out.name, fmt_size(result.size), result.frames))
                warn = ""
                if result.oversize_frames:
                    warn += ("\n\nNote: %d frames are too big for the old v2.0 player. "
                             "They play fine with the new player." % result.oversize_frames)
                if result.size > SAFE_SIZE:
                    warn += "\n\nNote: this file may be too big for the calculator's storage."
                self.set_status(text + warn.replace("\n\n", " "))
                if self.dialogs:
                    messagebox.showinfo("Done!", text + warn)
            elif kind == "cancelled":
                self.set_status("Cancelled. No file was saved.")
            else:
                err = msg[1]
                self._error("Conversion failed", str(err) if isinstance(err, ConvertError)
                            else "Something went wrong: %s" % err)

    def _show_estimate(self, est):
        self.last_estimate = est
        fits = est.size <= SAFE_SIZE
        text = "File size: about %s  %s" % (fmt_size(est.size), "✓ fits on the calculator" if fits
                                              else "✗ too big for the calculator")
        self.estimate_label.configure(text=text, foreground="#070" if fits else "#b00")
        width = max(1, self.meter.winfo_width())
        self.meter.coords(self.meter_bar, 0, 0, width * min(1.0, est.size / CALCULATOR_STORAGE), 12)
        self.meter.itemconfigure(self.meter_bar, fill="#3a3" if fits else "#c33")


# --- Self-test (used by CI and to check an install) ------------------------------

def _make_test_video(path):
    import cv2
    import numpy as np

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 24, (160, 120))
    for k in range(48):
        img = np.full((120, 160, 3), 30, np.uint8)
        cv2.rectangle(img, (k * 2, 30), (k * 2 + 40, 80), (0, 180, 255), -1)
        writer.write(img)
    writer.release()


def _run_selftest(app, root, result):
    tmp = Path(tempfile.mkdtemp())
    video = tmp / "selftest.avi"
    _make_test_video(video)
    app.open_video(str(video))
    started = time.time()
    state = {"stage": "loading"}

    def check():
        if time.time() - started > 120:
            print("selftest: timed out while", state["stage"])
            root.destroy()
            return
        if state["stage"] == "loading" and app.info and app.preview_photo and app.last_estimate:
            print("selftest: preview and estimate (%d bytes) ok" % app.last_estimate.size)
            app.output_var.set(str(tmp / "out.bin"))
            app.start_convert()
            state["stage"] = "converting"
        elif state["stage"] == "converting" and not app.converting and app.last_result:
            out = tmp / "out.bin"
            ok = out.exists() and out.read_bytes()[:4] == b"CGV2"
            print("selftest: conversion %s (%d frames)" % ("ok" if ok else "FAILED", app.last_result.frames))
            result["ok"] = ok
            root.destroy()
            return
        root.after(100, check)

    root.after(100, check)


def run_gui(selftest=False):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    if sys.platform.startswith("linux"):
        ttk.Style(root).theme_use("clam")
    app = App(root, dialogs=not selftest)
    result = {"ok": not selftest}
    if selftest:
        _run_selftest(app, root, result)
    root.mainloop()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(run_gui(selftest="--selftest" in sys.argv))
