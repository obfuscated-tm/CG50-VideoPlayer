"""Palettes and RGB565 helpers. The calculator screen uses 16-bit RGB565 colors."""
import numpy as np

AUTO = "auto"

# The palettes from the original compress.py (which stored them as BGR; these are RGB).
FIXED_PALETTES = {
    "standard": ("Standard 16 colors", [
        (0, 0, 0), (0, 0, 128), (0, 128, 0), (0, 128, 128),
        (128, 0, 0), (128, 0, 128), (128, 128, 0), (192, 192, 192),
        (128, 128, 128), (0, 0, 255), (0, 255, 0), (0, 255, 255),
        (255, 0, 0), (255, 0, 255), (255, 255, 0), (255, 255, 255),
    ]),
    "gameboy": ("GameBoy (4 grays)", [(0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255)]),
    "gray16": ("16 grays", [(i, i, i) for i in range(0, 256, 17)]),
    "bw": ("Black & white (smallest)", [(0, 0, 0), (255, 255, 255)]),
}

PALETTE_LABELS = {AUTO: "Best colors for this video"}
PALETTE_LABELS.update({key: label for key, (label, _) in FIXED_PALETTES.items()})


def rgb_to_565(rgb):
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def rgb565_to_rgb(value):
    r5, g6, b5 = (value >> 11) & 0x1F, (value >> 5) & 0x3F, value & 0x1F
    return ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2))


def snap_to_565(colors):
    """Rounds colors to what the calculator can show, so previews match the real screen."""
    return np.array([rgb565_to_rgb(rgb_to_565(c)) for c in colors], dtype=np.uint8).reshape(-1, 3)


def palette_to_565(palette):
    return [rgb_to_565(c) for c in palette]


def fixed_palette(key):
    if key not in FIXED_PALETTES:
        raise KeyError(key)
    return snap_to_565(FIXED_PALETTES[key][1])
