"""Generates the add-in menu icons (unselected.bmp / selected.bmp).

mkg3a needs 92x64, 24-bit, uncompressed BMPs. Run from the repo root:
    python3 tools/make_icons.py
"""
import struct
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 92, 64
ROOT = Path(__file__).resolve().parent.parent


def draw_icon(selected):
    bg = (255, 200, 60) if selected else (255, 255, 255)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)

    # A little "screen" with film-strip holes and a play triangle.
    d.rounded_rectangle((10, 8, 81, 55), radius=6, fill=(30, 40, 70), outline=(0, 0, 0), width=2)
    for x in range(16, 78, 10):
        d.rectangle((x, 11, x + 4, 14), fill=(230, 230, 230))
        d.rectangle((x, 49, x + 4, 52), fill=(230, 230, 230))
    d.polygon([(38, 20), (38, 43), (58, 31)], fill=(90, 220, 120) if selected else (240, 240, 240))
    return img


def check_bmp(path):
    data = path.read_bytes()
    assert data[:2] == b"BM", path
    header_size, width, height, planes, bpp, compression = struct.unpack_from("<IiiHHI", data, 14)
    assert (header_size, width, abs(height), bpp, compression) == (40, W, H, 24, 0), path


def main():
    for name, selected in (("unselected.bmp", False), ("selected.bmp", True)):
        path = ROOT / name
        draw_icon(selected).save(path, format="BMP")
        check_bmp(path)
        print("wrote", path)


if __name__ == "__main__":
    main()
