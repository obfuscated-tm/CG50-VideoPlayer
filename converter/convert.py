#!/usr/bin/env python3
"""CG50 Video Converter: turns a video into a .bin file for the fx-CG50 video player.

Run it with no arguments to open the converter window. Or use it from a terminal:

    python convert.py myvideo.mp4
    python convert.py myvideo.mp4 --size 192x108 --fps 20 --colors 8 -o clip.bin
"""
import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cgvideo import estimate, names  # noqa: E402
from cgvideo.errors import Cancelled, ConvertError  # noqa: E402
from cgvideo.palettes import AUTO, FIXED_PALETTES  # noqa: E402
from cgvideo.pipeline import SAFE_SIZE, SIZE_PRESETS, Settings, convert, probe  # noqa: E402


def parse_size(text):
    for key, _, w, h in SIZE_PRESETS:
        if text.lower() == key:
            return w, h
    try:
        w, h = (int(x) for x in text.lower().split("x"))
        return w, h
    except ValueError:
        raise argparse.ArgumentTypeError("use WIDTHxHEIGHT like 128x72, or one of: %s"
                                         % ", ".join(k for k, _, _, _ in SIZE_PRESETS))


def parse_time(text):
    """Seconds, or m:ss / h:mm:ss."""
    try:
        total = 0.0
        for part in text.split(":"):
            total = total * 60 + float(part)
        return total
    except ValueError:
        raise argparse.ArgumentTypeError("use seconds (like 12.5) or minutes:seconds (like 1:30)")


def parse_fps(text):
    if text.lower() in ("original", "same", "source"):
        return None
    try:
        return float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("use a number like 15, or 'original'")


def megabytes(n):
    return "%.1f MB" % (n / (1024 * 1024)) if n >= 100 * 1024 else "%d KB" % max(1, round(n / 1024))


def build_parser():
    p = argparse.ArgumentParser(
        prog="convert.py",
        description="Convert a video for the fx-CG50 video player. Run with no arguments to open the window.")
    p.add_argument("video", help="the video to convert (.mp4, .mov, .avi, ...)")
    p.add_argument("-o", "--output", help="output file (default: a short name next to the video)")
    p.add_argument("--size", type=parse_size, default=(128, 72),
                   help="tiny (96x54), recommended (128x72), sharp (192x108), full (384x216) or WxH")
    p.add_argument("--fps", type=parse_fps, default=15.0, help="frames per second, or 'original' (default 15)")
    p.add_argument("--colors", type=int, default=4, help="number of colors for the auto palette, 2-16 (default 4)")
    p.add_argument("--palette", choices=[AUTO] + list(FIXED_PALETTES), default=AUTO,
                   help="auto picks the best colors for this video (default)")
    p.add_argument("--dither", action="store_true", help="smoother shading (makes the file bigger)")
    p.add_argument("--start", type=parse_time, default=0.0, help="start time, e.g. 12 or 0:12")
    p.add_argument("--end", type=parse_time, default=None, help="end time, e.g. 90 or 1:30")
    p.add_argument("--fit", choices=["letterbox", "crop"], default="letterbox",
                   help="letterbox shows the whole picture; crop fills the screen")
    p.add_argument("--format", type=int, choices=[1, 2], default=2, dest="fmt",
                   help="2 = smaller files for the new player (default); 1 = works with the old v2.0 player")
    p.add_argument("--title", help="name shown on the calculator (default: from the file name)")
    p.add_argument("--estimate", action="store_true", help="only estimate the file size")
    p.add_argument("-q", "--quiet", action="store_true", help="no progress output")
    p.add_argument("--debug", action="store_true", help="show full error details")
    return p


def run_cli(argv):
    args = build_parser().parse_args(argv)
    video = Path(args.video)
    settings = Settings(width=args.size[0], height=args.size[1], fps=args.fps, colors=args.colors,
                        palette=args.palette, dither=args.dither, start=args.start, end=args.end,
                        fit=args.fit, fmt=args.fmt, title=(args.title if args.title is not None else video.stem)[:24])
    try:
        info = probe(video)
        if args.estimate:
            est = estimate.estimate_size(info, settings)
            print("Estimated size: %s (%d frames)" % (megabytes(est.size), est.frames))
            return 0
        out = Path(args.output) if args.output else video.parent / names.calculator_name(video, video.parent)

        def progress(done, total):
            if args.quiet:
                return
            if total:
                print("\rConverting: %d/%d frames (%d%%)" % (done, total, min(100, 100 * done // total)),
                      end="", flush=True)
            else:
                print("\rConverting: %d frames" % done, end="", flush=True)

        result = convert(video, out, settings, progress=progress, cancel=threading.Event(), info=info)
        if not args.quiet:
            print()
        print("Done! %s: %s, %d frames at %g fps." % (out, megabytes(result.size), result.frames, result.fps))
        print("Copy it to the root folder of the calculator (USB, 'USB Flash' mode).")
        if result.oversize_frames:
            print("Warning: %d frames are too big for the old v2.0 player; use the new player, "
                  "or a smaller size / fewer colors." % result.oversize_frames)
        if result.size > SAFE_SIZE:
            print("Warning: this is bigger than %s and may not fit on the calculator." % megabytes(SAFE_SIZE))
        return 0
    except ConvertError as e:
        print("\nError: %s" % e, file=sys.stderr)
        if args.debug:
            raise
        return 1
    except (Cancelled, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as e:  # keep the message friendly unless --debug
        if args.debug:
            raise
        print("\nSomething went wrong: %s (run again with --debug for details)" % e, file=sys.stderr)
        return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from app import run_gui
        return run_gui()
    if argv == ["--selftest"]:
        from app import run_gui
        return run_gui(selftest=True)
    return run_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
