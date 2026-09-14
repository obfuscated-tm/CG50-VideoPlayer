"""Picking palettes and mapping pixels to palette indices."""
import cv2
import numpy as np

from .palettes import snap_to_565

MAX_SAMPLE_PIXELS = 200_000

# 4x4 ordered-dither matrix. The pattern is tied to the pixel position, so still parts of
# the picture stay identical from frame to frame (which keeps files small).
_BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float32)
_BAYER_OFFSETS = (_BAYER4 + 0.5) / 16.0 - 0.5


def _luminance_order(colors):
    lum = colors[:, 0].astype(np.int32) * 299 + colors[:, 1].astype(np.int32) * 587 + colors[:, 2].astype(np.int32) * 114
    return colors[np.argsort(lum, kind="stable")]


def auto_palette(frames, n, seed=0):
    """Finds the n colors that best represent the given RGB frames (deterministic)."""
    n = max(1, min(16, int(n)))
    pixels = np.concatenate([f.reshape(-1, 3) for f in frames]) if frames else np.zeros((1, 3), np.uint8)
    if len(pixels) > MAX_SAMPLE_PIXELS:
        rng = np.random.default_rng(seed)
        pixels = pixels[rng.choice(len(pixels), MAX_SAMPLE_PIXELS, replace=False)]

    unique = np.unique(snap_to_565(np.unique(pixels, axis=0)) if len(np.unique(pixels, axis=0)) <= 4096 else pixels[:0], axis=0)
    if 0 < len(unique) <= n:
        return _luminance_order(unique)

    cv2.setRNGSeed(seed)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    k = min(n, len(pixels))
    _, _, centers = cv2.kmeans(pixels.astype(np.float32), k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    colors = snap_to_565(np.clip(np.rint(centers), 0, 255).astype(np.uint8))
    return _luminance_order(np.unique(colors, axis=0))


def dither_strength(palette):
    if len(palette) < 2:
        return 0.0
    pal = palette.astype(np.float32)
    dist = np.sqrt(((pal[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2))
    np.fill_diagonal(dist, np.inf)
    return float(np.median(dist.min(axis=1)) / np.sqrt(3.0))


def map_to_palette(rgb, palette, dither=False):
    """Returns an (h, w) uint8 array of palette indices for an (h, w, 3) RGB frame."""
    h, w, _ = rgb.shape
    px = rgb.astype(np.float32)
    if dither:
        offsets = np.tile(_BAYER_OFFSETS, (h // 4 + 1, w // 4 + 1))[:h, :w] * dither_strength(palette)
        px = px + offsets[:, :, None]
    pal = palette.astype(np.float32)
    # Plain squared distances (no matrix multiply: Apple's BLAS makes numpy print bogus warnings).
    flat = px.reshape(-1, 3)
    best = np.zeros(flat.shape[0], dtype=np.uint8)
    best_dist = np.full(flat.shape[0], np.inf, dtype=np.float32)
    for i, color in enumerate(pal):
        dist = ((flat - color) ** 2).sum(axis=1)
        closer = dist < best_dist
        best[closer] = i
        best_dist[closer] = dist[closer]
    return best.reshape(h, w)
