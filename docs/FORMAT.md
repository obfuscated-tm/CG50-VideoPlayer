# Video file formats

The player accepts two layouts. Every number is **big-endian**, and every color is **RGB565** (the calculator's 16-bit color).
Pixels are numbered in raster order (left to right, top to bottom) within the video's own `width × height` area.
The player scales the video by the largest whole number that fits the 384×216 screen and centers it.

`src/decode.c` (calculator) and `converter/cgvideo/format1.py` / `format2.py` (PC) implement the formats. `tests/` checks that they agree byte for byte.

## Format 1 (original)

This is the layout `compress.py` wrote before. Every version of the player can read it.

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | frame count |
| 4 | 2 | width (1–384) |
| 6 | 2 | height (1–216) |
| 8 | 2 | frames per second (whole number) |
| 10 | 1 | palette size *P* (1–16) |
| 11 | 2·*P* | palette |

Each frame is a 4-byte length *L*, then *L* bytes of `(count, palette index)` pairs, 1 byte each.
The pairs cover the whole frame, and each pair holds 0–255 pixels.

Notes:
- *L* must be even and non-zero.
- The player from v2.0.x also requires *L* ≤ 30000; newer players have no limit.

## Format 2 ("CGV2")

The file starts with a fixed 128-byte header.

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | `CGV2` |
| 4 | 1 | version, currently 2 |
| 5 | 1 | flags, 0 (readers ignore it) |
| 6 | 2 | width (1–384) |
| 8 | 2 | height (1–216) |
| 10 | 2 | frames per second × 100 (e.g. 2997) |
| 12 | 4 | frame count |
| 16 | 1 | palette size *P* (1–16) |
| 17 | 32 | 16 palette colors; entries past *P* are 0 |
| 49 | 24 | title, ASCII, NUL-padded (shown in the video picker) |
| 73 | 55 | reserved, 0 |

Each frame is a 4-byte length *L* (at most `width·height + 1`), then *L* bytes of opcodes.
A frame only describes what **changed** since the previous frame. Pixels it doesn't cover keep their old color.
The player keeps the previous frame on the screen itself, so this needs no extra memory.

| Byte(s) | Meaning |
|---|---|
| `0ccc cLLL` | run: *L*+1 pixels (1–8) of color *c* |
| `10LL LLLL` | skip *L*+1 pixels (1–64) |
| `1100 cccc` *n* | run: *n*+1 pixels (1–256) of color *c* |
| `1101 cccc` *hi lo* | run: *n*+1 pixels (1–65536) of color *c* |
| `E0` *n* | skip *n*+1 pixels (1–256) |
| `E1` *hi lo* | skip *n*+1 pixels (1–65536) |
| `F0` *n* | literal: *n*+1 pixels (1–256), then ⌈(*n*+1)/2⌉ bytes, 2 pixels each (high nibble first) |
| `FF` | end of frame: the rest of the frame is unchanged |
| `E2`–`EF`, `F1`–`FE` | invalid (the file is corrupt) |

The frame also ends when its *L* bytes are used up. A frame with *L* = 0 means nothing changed.

Decoders:
- Stop runs, skips and literals at the end of the frame instead of wrapping around.
- Treat palette indices ≥ *P* as index 0.
- Discard any bytes left between `FF` and the end of the frame.

The encoder never uses skips in the first frame. The player clears the screen before frame 0, and again before a replay.

A file that doesn't start with `CGV2` is format 1. The first 4 bytes of a format 1 file are its frame count, which can never be `CGV2`, over a billion frames.
