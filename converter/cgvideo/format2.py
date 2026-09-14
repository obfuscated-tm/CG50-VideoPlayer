"""Format 2 ("CGV2"): stores only what changed since the previous frame.

See docs/FORMAT.md for the full layout. src/decode.c is the calculator's decoder;
decode_frame() below mirrors it exactly and is used by the tests and previews.
"""
import struct

import numpy as np

from .format1 import CorruptFile

MAGIC = b"CGV2"
VERSION = 2
HEADER_SIZE = 128
TITLE_BYTES = 24
_HEADER = struct.Struct(">4sBBHHHIB16H24s")  # 73 bytes, zero-padded to HEADER_SIZE

OP_END = 0xFF


def header_size(palsize=16):
    return HEADER_SIZE


def file_fps100(fps):
    return max(1, min(65535, int(round(fps * 100))))


def clean_title(title):
    text = "".join(c if 32 <= ord(c) < 127 else "?" for c in (title or ""))
    return text[:TITLE_BYTES]


def pack_header(width, height, fps100, frames, palette565, title=""):
    palette = list(palette565) + [0] * (16 - len(palette565))
    data = _HEADER.pack(MAGIC, VERSION, 0, width, height, fps100, frames, len(palette565),
                        *palette, clean_title(title).encode("ascii"))
    return data + bytes(HEADER_SIZE - len(data))


# --- Encoding -----------------------------------------------------------------

def _emit_run(out, color, length):
    while length > 0:
        if length <= 8:
            out.append((color << 3) | (length - 1))
            return
        if length <= 256:
            out += bytes((0xC0 | color, length - 1))
            return
        chunk = min(length, 65536)
        out += bytes((0xD0 | color, (chunk - 1) >> 8, (chunk - 1) & 0xFF))
        length -= chunk


def _emit_skip(out, length):
    while length > 0:
        if length <= 64:
            out.append(0x80 | (length - 1))
            return
        if length <= 256:
            out += bytes((0xE0, length - 1))
            return
        chunk = min(length, 65536)
        out += bytes((0xE1, (chunk - 1) >> 8, (chunk - 1) & 0xFF))
        length -= chunk


def _emit_literal(out, pixels):
    count = len(pixels)
    out += bytes((0xF0, count - 1))
    if count % 2:
        pixels = pixels + [0]
    out += bytes((pixels[i] << 4) | pixels[i + 1] for i in range(0, len(pixels), 2))


def encode_frame(flat, prev=None):
    """Encodes one frame (a flat uint8 index array). prev is the previous frame, or None
    for the first frame, which must not contain skips."""
    flat = np.ascontiguousarray(flat, dtype=np.uint8).ravel()
    n = flat.size
    positions = np.arange(n)

    # run_len[p]: how many pixels from p onward share p's color.
    bounds = np.append(np.flatnonzero(flat[1:] != flat[:-1]) + 1, n)
    run_len = (bounds[np.searchsorted(bounds, positions, side="right")] - positions).tolist()

    # skip_len[p]: how many pixels from p onward are unchanged since the previous frame.
    skip_len = None
    if prev is not None and prev.size == n:
        changed = np.append(np.flatnonzero(flat != prev.ravel()), n)
        skip_len = (changed[np.searchsorted(changed, positions, side="left")] - positions).tolist()

    colors = flat.tolist()
    out = bytearray()
    p = 0
    while p < n:
        r = run_len[p]
        s = skip_len[p] if skip_len is not None else 0
        if s > 0 and s >= r:
            if p + s >= n:
                break  # the rest of the frame is unchanged: OP_END says so
            _emit_skip(out, s)
            p += s
            continue
        if r >= 3:
            _emit_run(out, colors[p], r)  # also covers unchanged pixels of the same color
            p += r
            continue

        # A stretch of 1-2 pixel runs: pack it as a literal (4 bits/pixel) when that's smaller.
        q, runs = p, 0
        while q < n and q - p < 256:
            if run_len[q] >= 3 or (skip_len is not None and skip_len[q] >= 4):
                break
            q = min(q + run_len[q], p + 256)
            runs += 1
        count = q - p
        if count >= 3 and 2 + (count + 1) // 2 < runs:
            _emit_literal(out, colors[p:q])
            p = q
        else:
            while p < q:
                length = min(run_len[p], q - p)
                _emit_run(out, colors[p], length)
                p += length
    out.append(OP_END)
    return bytes(out)


class FrameEncoder:
    def __init__(self):
        self.prev = None

    def encode(self, indices):
        flat = np.ascontiguousarray(indices, dtype=np.uint8).ravel()
        data = encode_frame(flat, self.prev)
        self.prev = flat.copy()
        return data


class Writer:
    def __init__(self, path, width, height, fps, palette565, title=""):
        self.width, self.height = width, height
        self.fps100 = file_fps100(fps)
        self.palette565 = list(palette565)
        self.title = title
        self.frames = 0
        self.largest_frame = 0
        self.oversize_frames = 0
        self._encoder = FrameEncoder()
        self._f = open(path, "wb")
        self._f.write(pack_header(width, height, self.fps100, 0, self.palette565, title))

    def add_frame(self, indices):
        data = self._encoder.encode(indices)
        self._f.write(struct.pack(">I", len(data)))
        self._f.write(data)
        self.frames += 1
        self.largest_frame = max(self.largest_frame, len(data))
        return 4 + len(data)

    def close(self):
        if self._f.closed:
            return
        self._f.seek(0)
        self._f.write(pack_header(self.width, self.height, self.fps100, self.frames, self.palette565, self.title))
        self._f.close()

    def abort(self):
        self._f.close()


# --- Decoding (reference implementation, mirrors src/decode.c) -----------------

def read_header(data):
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise CorruptFile("not a format 2 file")
    fields = _HEADER.unpack_from(data, 0)
    _, version, _flags, w, h, fps100, frames, palsize = fields[:8]
    palette = list(fields[8:8 + 16])[:palsize]
    title = fields[24].split(b"\0", 1)[0].decode("ascii", "replace")
    return {
        "format": 2, "version": version, "frames": frames, "width": w, "height": h,
        "fps100": fps100, "palette": palette, "title": title, "header_bytes": HEADER_SIZE,
    }


def max_frame_bytes(width, height):
    return width * height + 1


def decode_frame(data, prev, width, height, palsize):
    n = width * height
    out = np.array(prev, dtype=np.uint8).ravel().copy() if prev is not None else np.zeros(n, np.uint8)
    pos = i = 0
    size = len(data)

    def need(k):
        if i + k > size:
            raise CorruptFile("truncated opcode")

    def fill(color, length):
        nonlocal pos
        length = min(length, n - pos)
        out[pos:pos + length] = color if color < palsize else 0
        pos += length

    while i < size:
        op = data[i]
        i += 1
        if op == OP_END:
            break
        if op < 0x80:
            fill(op >> 3, (op & 7) + 1)
        elif op < 0xC0:
            pos = min(n, pos + (op & 0x3F) + 1)
        elif op < 0xD0:
            need(1)
            fill(op & 0x0F, data[i] + 1)
            i += 1
        elif op < 0xE0:
            need(2)
            fill(op & 0x0F, ((data[i] << 8) | data[i + 1]) + 1)
            i += 2
        elif op == 0xE0:
            need(1)
            pos = min(n, pos + data[i] + 1)
            i += 1
        elif op == 0xE1:
            need(2)
            pos = min(n, pos + ((data[i] << 8) | data[i + 1]) + 1)
            i += 2
        elif op == 0xF0:
            need(1)
            count = data[i] + 1
            i += 1
            nbytes = (count + 1) // 2
            need(nbytes)
            for k in range(count):
                byte = data[i + k // 2]
                color = (byte >> 4) if k % 2 == 0 else (byte & 0x0F)
                if pos < n:
                    out[pos] = color if color < palsize else 0
                    pos += 1
            i += nbytes
        else:
            raise CorruptFile("bad opcode 0x%02X" % op)
    return out.reshape(height, width)


def iter_frames(data):
    header = read_header(data)
    w, h, palsize = header["width"], header["height"], len(header["palette"])
    pos = HEADER_SIZE
    prev = np.zeros((h, w), np.uint8)
    for _ in range(header["frames"]):
        if pos + 4 > len(data):
            raise CorruptFile("truncated")
        (size,) = struct.unpack_from(">I", data, pos)
        pos += 4
        if size > max_frame_bytes(w, h) or pos + size > len(data):
            raise CorruptFile("bad frame length")
        prev = decode_frame(data[pos:pos + size], prev, w, h, palsize)
        pos += size
        yield prev
