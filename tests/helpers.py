"""Synthetic clips and expected-screen rendering shared by the tests."""
import subprocess

import numpy as np

from cgvideo import format1, format2
from cgvideo.pipeline import SCREEN_H, SCREEN_W, layout

MODULES = {1: format1, 2: format2}


def palette565(n):
    rng = np.random.default_rng(n)
    return [int(x) for x in rng.integers(1, 65536, n)]


def solid(w, h, frames, color=1):
    return [np.full((h, w), color, np.uint8) for _ in range(frames)]


def gradient(w, h, frames, colors=16):
    base = (np.arange(w)[None, :] * colors // w).astype(np.uint8).repeat(h, axis=0)
    return [np.roll(base, i, axis=1) for i in range(frames)]


def noise(w, h, frames, colors=16, seed=0):
    rng = np.random.default_rng(seed)
    return [rng.integers(0, colors, (h, w), dtype=np.uint8) for _ in range(frames)]


def moving_rect(w, h, frames, colors=4):
    out = []
    for i in range(frames):
        f = np.zeros((h, w), np.uint8)
        x, y = (i * 3) % max(1, w - w // 4), (i * 2) % max(1, h - h // 4)
        f[y:y + max(1, h // 4), x:x + max(1, w // 4)] = 1 + i % (colors - 1)
        out.append(f)
    return out


def write_video(path, fmt, frames, pal, fps=15.0, title="test"):
    h, w = frames[0].shape
    writer = MODULES[fmt].Writer(str(path), w, h, fps, pal, title)
    for f in frames:
        writer.add_frame(f)
    writer.close()
    return path


def expected_screens(frames, pal):
    """Renders frames the way the player does: black screen, video scaled and centered."""
    h, w = frames[0].shape
    scale, x_off, y_off = layout(w, h)
    colors = np.array(pal, dtype=np.uint16)
    out = []
    for f in frames:
        screen = np.zeros((SCREEN_H, SCREEN_W), np.uint16)
        screen[y_off:y_off + h * scale, x_off:x_off + w * scale] = colors[f].repeat(scale, 0).repeat(scale, 1)
        out.append(screen)
    return out


def run_host(host_player, video, *args, dump=None):
    cmd = [str(host_player), *map(str, args)]
    if dump is not None:
        cmd += ["--dump", str(dump)]
    cmd.append(str(video))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def read_dump(path):
    data = np.fromfile(str(path), dtype="<u2")
    return data.reshape(-1, SCREEN_H, SCREEN_W)
