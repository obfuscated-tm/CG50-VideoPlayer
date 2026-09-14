"""Format 1: the original video.bin layout, playable by every version of the player.

Header (big-endian): frames u32, width u16, height u16, fps u16, palette size u8,
then the palette as u16 RGB565 values. Each frame: byte length u32, then
(count u8, palette index u8) pairs covering the frame in raster order.
"""
import struct

import numpy as np

# The player from v2.0.x rejects frames larger than this; newer players have no limit.
OLD_PLAYER_MAX_FRAME = 30000

_HEADER = struct.Struct(">IHHHB")


def encode_frame(indices):
    flat = np.ascontiguousarray(indices, dtype=np.uint8).ravel()
    if flat.size == 0:
        return b""
    starts = np.concatenate(([0], np.flatnonzero(flat[1:] != flat[:-1]) + 1))
    lengths = np.diff(np.append(starts, flat.size))
    colors = flat[starts]
    full, rem = lengths // 255, lengths % 255
    pairs_per_run = full + (rem > 0)
    pair_colors = np.repeat(colors, pairs_per_run)
    pair_lengths = np.full(pair_colors.size, 255, dtype=np.uint8)
    last = np.cumsum(pairs_per_run) - 1
    pair_lengths[last[rem > 0]] = rem[rem > 0]
    out = np.empty(pair_colors.size * 2, dtype=np.uint8)
    out[0::2] = pair_lengths
    out[1::2] = pair_colors
    return out.tobytes()


def header_size(palsize):
    return _HEADER.size + 2 * palsize


def file_fps(fps):
    """Format 1 stores whole frames per second."""
    return max(1, int(round(fps)))


class FrameEncoder:
    """Same interface as format2.FrameEncoder; format 1 frames don't depend on the previous one."""

    def encode(self, indices):
        return encode_frame(indices)


class Writer:
    def __init__(self, path, width, height, fps, palette565, title=""):
        self.width, self.height = width, height
        self.frames = 0
        self.oversize_frames = 0
        self.largest_frame = 0
        self._f = open(path, "wb")
        self._f.write(_HEADER.pack(0, width, height, max(1, int(round(fps))), len(palette565)))
        for color in palette565:
            self._f.write(struct.pack(">H", color))

    def add_frame(self, indices):
        data = encode_frame(indices)
        self._f.write(struct.pack(">I", len(data)))
        self._f.write(data)
        self.frames += 1
        self.largest_frame = max(self.largest_frame, len(data))
        if len(data) > OLD_PLAYER_MAX_FRAME:
            self.oversize_frames += 1
        return 4 + len(data)

    def close(self):
        if self._f.closed:
            return
        self._f.seek(0)
        self._f.write(struct.pack(">I", self.frames))  # the real count, not OpenCV's estimate
        self._f.close()

    def abort(self):
        self._f.close()


class CorruptFile(Exception):
    pass


def read_header(data):
    frames, w, h, fps, palsize = _HEADER.unpack_from(data, 0)
    palette = list(struct.unpack_from(">%dH" % palsize, data, _HEADER.size))
    return {
        "format": 1, "frames": frames, "width": w, "height": h, "fps100": fps * 100,
        "palette": palette, "title": "", "header_bytes": _HEADER.size + 2 * palsize,
    }


def decode_frame(data, width, height, palsize):
    """Reference decoder, mirroring src/decode.c. Returns a (height, width) index array."""
    n = width * height
    if len(data) == 0 or len(data) % 2 or len(data) > 2 * n:
        raise CorruptFile("bad frame length %d" % len(data))
    out = np.zeros(n, dtype=np.uint8)
    pos = 0
    for i in range(0, len(data), 2):
        count, idx = data[i], data[i + 1]
        if idx >= palsize:
            idx = 0
        count = min(count, n - pos)
        out[pos:pos + count] = idx
        pos += count
    return out.reshape(height, width)


def iter_frames(data):
    header = read_header(data)
    pos = header["header_bytes"]
    for _ in range(header["frames"]):
        if pos + 4 > len(data):
            raise CorruptFile("truncated")
        (size,) = struct.unpack_from(">I", data, pos)
        pos += 4
        if pos + size > len(data):
            raise CorruptFile("truncated")
        yield decode_frame(data[pos:pos + size], header["width"], header["height"], len(header["palette"]))
        pos += size
