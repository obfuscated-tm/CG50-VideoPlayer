"""Guessing the output size quickly, and shrinking settings until a video fits."""
import math
from dataclasses import dataclass

from .palettes import AUTO
from .pipeline import (SAFE_SIZE, expected_frames, format_module, frame_to_indices, iter_source_frames,
                       make_palette, output_fps, time_range)


@dataclass
class Estimate:
    size: int
    frames: int


def estimate_size(info, settings, palette=None, clips=3, clip_seconds=2.0, cancel=None):
    """Encodes a few short clips with the real encoder and scales the result up."""
    module = format_module(settings.fmt)
    fps = output_fps(settings, info)
    start, end = time_range(settings, info)
    if end is None:
        end = start + 60.0
    total_frames = expected_frames(settings, info) or max(1, math.ceil((end - start) * fps))
    if palette is None:
        palette = make_palette(info, settings)

    span = end - start
    if span <= clips * clip_seconds:
        clip_starts = [start]
        clip_seconds = span
    else:
        clip_starts = [start + (span - clip_seconds) * j / (clips - 1) for j in range(clips)]

    first_frame = None
    counted_bytes = counted_frames = 0
    for n, clip_start in enumerate(clip_starts):
        encoder = module.FrameEncoder()
        frames = iter_source_frames(info, clip_start, min(end, clip_start + clip_seconds), fps, cancel)
        for k, bgr in enumerate(frames):
            size = 4 + len(encoder.encode(frame_to_indices(bgr, settings, palette)))
            if n == 0 and k == 0:
                first_frame = size
            elif k > 0 or n == 0:
                counted_bytes += size  # later clips' first frames are full pictures; don't count them
                counted_frames += 1

    header = module.header_size(len(palette))
    if first_frame is None:
        return Estimate(header, 0)
    per_frame = counted_bytes / counted_frames if counted_frames else first_frame
    return Estimate(int(header + first_frame + per_frame * (total_frames - 1)), total_frames)


def _fewer_colors(s, auto_colors, fixed_palette):
    if s.palette == AUTO:
        return s.copy(colors=min(s.colors, auto_colors))
    if s.palette in ("standard", "gray16", "gameboy") and fixed_palette == "bw":
        return s.copy(palette="bw")
    if s.palette in ("standard", "gray16"):
        return s.copy(palette=fixed_palette)
    return s


def _max_size(s, width, height):
    return s.copy(width=width, height=height) if s.width * s.height > width * height else s


def _max_fps(s, fps):
    return s.copy(fps=fps) if s.fps is None or s.fps > fps else s


# Gentlest changes first. Each step only applies if it actually changes something.
_LADDER = [
    lambda s: s.copy(dither=False),
    lambda s: _max_fps(s, 15),
    lambda s: _fewer_colors(s, 4, "gameboy"),
    lambda s: _max_size(s, 128, 72),
    lambda s: _max_fps(s, 10),
    lambda s: _fewer_colors(s, 2, "bw"),
    lambda s: _max_size(s, 96, 54),
]


def _smaller_steps(settings):
    s = settings
    for step in _LADDER:
        smaller = step(s)
        if smaller != s:
            s = smaller
            yield s


def make_it_fit(info, settings, target=SAFE_SIZE, cancel=None, on_step=None):
    """Returns (settings, estimate) that fit under `target`, or (None, last_estimate)."""
    est = estimate_size(info, settings, cancel=cancel)
    if est.size <= target:
        return settings, est
    for candidate in _smaller_steps(settings):
        est = estimate_size(info, candidate, cancel=cancel)
        if on_step:
            on_step(candidate, est)
        if est.size <= target:
            return candidate, est
    return None, est
