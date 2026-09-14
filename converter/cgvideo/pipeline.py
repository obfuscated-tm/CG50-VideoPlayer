"""Reading a video and turning it into palette-index frames for the calculator."""
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import format1
from .errors import Cancelled, ConvertError
from .palettes import AUTO, FIXED_PALETTES, fixed_palette, palette_to_565
from .quantize import auto_palette, map_to_palette

SCREEN_W, SCREEN_H = 384, 216

# (key, label, width, height). All of these scale up to exactly fill the screen.
SIZE_PRESETS = [
    ("tiny", "Tiny", 96, 54),
    ("recommended", "Recommended", 128, 72),
    ("sharp", "Sharp", 192, 108),
    ("full", "Full screen", 384, 216),
]
FPS_CHOICES = [None, 30, 24, 20, 15, 12, 10]  # None = same as the video

# The fx-CG50 has 16 MB of storage; leave room for other files.
CALCULATOR_STORAGE = 16 * 1024 * 1024
SAFE_SIZE = 14 * 1024 * 1024


@dataclass
class Settings:
    width: int = 128
    height: int = 72
    fps: Optional[float] = 15.0
    colors: int = 4
    palette: str = AUTO
    dither: bool = False
    start: float = 0.0
    end: Optional[float] = None
    fit: str = "letterbox"  # or "crop"
    title: str = ""
    fmt: int = 2

    def copy(self, **changes):
        return replace(self, **changes)


@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int
    duration: Optional[float]


@dataclass
class Result:
    frames: int
    size: int
    fps: float
    oversize_frames: int = 0


def format_module(fmt):
    if fmt == 1:
        return format1
    if fmt == 2:
        from . import format2
        return format2
    raise ConvertError("Unknown file format %r (use 1 or 2)." % fmt)


def probe(path):
    path = str(path)
    if not Path(path).is_file():
        raise ConvertError("Can't find the file %s." % path)
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise ConvertError("This file couldn't be opened as a video. Try an .mp4 file.")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise ConvertError("This file opened, but no pictures could be read from it. Try converting it to .mp4 first.")
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or math.isnan(fps) or fps <= 0 or fps > 1000:
            fps = 30.0
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = count / fps if count > 0 else None
        return VideoInfo(path, frame.shape[1], frame.shape[0], float(fps), max(count, 0), duration)
    finally:
        cap.release()


def output_fps(settings, info):
    fps = settings.fps or info.fps
    fps = min(float(fps), info.fps)
    if settings.fmt == 1:
        return float(format1.file_fps(fps))
    return max(0.01, min(655.35, round(fps * 100) / 100))


def time_range(settings, info):
    start = max(0.0, float(settings.start or 0))
    end = settings.end if settings.end else info.duration
    if end is not None and end <= start:
        raise ConvertError("The end time must be after the start time.")
    return start, end


def validate(settings):
    if not (1 <= settings.width <= SCREEN_W and 1 <= settings.height <= SCREEN_H):
        raise ConvertError("The size must be at most %dx%d." % (SCREEN_W, SCREEN_H))
    if settings.palette != AUTO and settings.palette not in FIXED_PALETTES:
        raise ConvertError("Unknown palette %r." % settings.palette)
    if settings.palette == AUTO and not 2 <= settings.colors <= 16:
        raise ConvertError("Colors must be between 2 and 16.")
    if settings.fit not in ("letterbox", "crop"):
        raise ConvertError("Fit must be 'letterbox' or 'crop'.")
    format_module(settings.fmt)


def resize_frame(bgr, width, height, fit="letterbox"):
    """Returns an RGB frame of exactly width x height."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    sh, sw = rgb.shape[:2]
    if fit == "crop":
        scale = max(width / sw, height / sh)
        nw, nh = max(width, round(sw * scale)), max(height, round(sh * scale))
        resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
        x, y = (nw - width) // 2, (nh - height) // 2
        return np.ascontiguousarray(resized[y:y + height, x:x + width])
    scale = min(width / sw, height / sh)
    nw, nh = max(1, min(width, round(sw * scale))), max(1, min(height, round(sh * scale)))
    resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    x, y = (width - nw) // 2, (height - nh) // 2
    canvas[y:y + nh, x:x + nw] = resized
    return canvas


def iter_source_frames(info, start, end, fps, cancel=None):
    """Yields BGR frames resampled to `fps`: output frame i is the source frame nearest to
    start + i/fps. Frames are read in order, so the timing is exact (29.97 fps included)."""
    cap = cv2.VideoCapture(info.path)
    try:
        next_index = 0  # index of the frame the next read returns
        current = None
        i = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            t = start + i / fps
            if end is not None and t >= end - 1e-9:
                return
            target = int(round(t * info.fps))
            while next_index <= target:
                if next_index < target:
                    ok = cap.grab()
                else:
                    ok, frame = cap.read()
                    if ok:
                        current = frame
                if not ok:
                    return
                next_index += 1
            yield current
            i += 1
    finally:
        cap.release()


class FrameGrabber:
    """Random access to frames by time, for previews and palette sampling."""

    def __init__(self, info):
        self.info = info
        self._cap = cv2.VideoCapture(info.path)

    def frame_at(self, t):
        self._cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok, frame = self._cap.read()
        if not ok:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(t * self.info.fps) - 1))
            ok, frame = self._cap.read()
        return frame if ok else None

    def close(self):
        self._cap.release()


def sample_frames(info, settings, count=40, grabber=None):
    start, end = time_range(settings, info)
    end = end if end is not None else start + 10.0
    own = grabber is None
    grabber = grabber or FrameGrabber(info)
    try:
        frames = []
        for j in range(count):
            frame = grabber.frame_at(start + (end - start) * (j + 0.5) / count)
            if frame is not None:
                frames.append(resize_frame(frame, settings.width, settings.height, settings.fit))
        return frames
    finally:
        if own:
            grabber.close()


def make_palette(info, settings, grabber=None):
    """Returns the palette as an (n, 3) RGB array, already rounded to RGB565."""
    if settings.palette == AUTO:
        return auto_palette(sample_frames(info, settings, grabber=grabber), settings.colors)
    return fixed_palette(settings.palette)


def frame_to_indices(bgr, settings, palette):
    return map_to_palette(resize_frame(bgr, settings.width, settings.height, settings.fit), palette, settings.dither)


def layout(width, height):
    """Integer scale and centering offsets, identical to the calculator player."""
    scale = max(1, min(SCREEN_W // width, SCREEN_H // height))
    return scale, (SCREEN_W - width * scale) // 2, (SCREEN_H - height * scale) // 2


def screen_image(indices, palette):
    """What the calculator will show: a 384x216 RGB image."""
    h, w = indices.shape
    scale, x_off, y_off = layout(w, h)
    picture = palette[indices]
    if scale > 1:
        picture = picture.repeat(scale, axis=0).repeat(scale, axis=1)
    screen = np.zeros((SCREEN_H, SCREEN_W, 3), dtype=np.uint8)
    screen[y_off:y_off + h * scale, x_off:x_off + w * scale] = picture
    return screen


def expected_frames(settings, info):
    start, end = time_range(settings, info)
    if end is None:
        return None
    return max(1, math.ceil((end - start) * output_fps(settings, info) - 1e-9))


def convert(path, out_path, settings, progress=None, cancel=None, info=None, palette=None):
    """Converts a video. progress(done, total_or_None) is called after each frame."""
    validate(settings)
    info = info or probe(path)
    fps = output_fps(settings, info)
    start, end = time_range(settings, info)
    if palette is None:
        palette = make_palette(info, settings)
    module = format_module(settings.fmt)
    total = expected_frames(settings, info)

    out_path = Path(out_path)
    writer = module.Writer(str(out_path), settings.width, settings.height, fps, palette_to_565(palette), settings.title)
    try:
        for bgr in iter_source_frames(info, start, end, fps, cancel):
            writer.add_frame(frame_to_indices(bgr, settings, palette))
            if progress:
                progress(writer.frames, total)
        if writer.frames == 0:
            raise ConvertError("No pictures were found in the chosen time range.")
        writer.close()
    except BaseException:
        writer.abort()
        try:
            out_path.unlink()  # don't leave a half-written file behind
        except OSError:
            pass
        raise
    return Result(writer.frames, out_path.stat().st_size, fps, getattr(writer, "oversize_frames", 0))
