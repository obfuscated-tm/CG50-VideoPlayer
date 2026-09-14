"""Encoders, the Python reference decoders and the calculator's C decoder must all agree."""
import struct

import numpy as np
import pytest

from cgvideo import format1, format2
from helpers import (MODULES, expected_screens, gradient, moving_rect, noise, palette565, read_dump,
                     run_host, solid, write_video)

CLIPS = {
    "solid": lambda: solid(128, 72, 5),
    "gradient": lambda: gradient(128, 72, 6),
    "noise16": lambda: noise(96, 54, 4, colors=16),
    "noise2": lambda: noise(128, 72, 4, colors=2, seed=3),
    "moving_rect": lambda: moving_rect(128, 72, 12),
    "one_pixel": lambda: [np.array([[i % 3]], np.uint8) for i in range(7)],
    "full_screen": lambda: moving_rect(384, 216, 4),
    "sharp": lambda: moving_rect(192, 108, 5),
    "odd_size": lambda: noise(100, 70, 3, colors=5, seed=9),
    "tall": lambda: gradient(20, 216, 3, colors=7),
}


def legacy_encode(indices):
    """The loop from the original compress.py, for byte-for-byte comparison."""
    out = bytearray()
    flat = indices.ravel()
    cur, run = flat[0], 0
    for p in flat:
        if p == cur and run < 255:
            run += 1
        else:
            out += struct.pack("BB", run, cur)
            cur, run = p, 1
    out += struct.pack("BB", run, cur)
    return bytes(out)


@pytest.mark.parametrize("name", ["solid", "gradient", "noise16", "moving_rect", "one_pixel", "full_screen"])
def test_format1_matches_original_encoder(name):
    for frame in CLIPS[name]():
        assert format1.encode_frame(frame) == legacy_encode(frame)


@pytest.mark.parametrize("fmt", [1, 2])
@pytest.mark.parametrize("name", sorted(CLIPS))
def test_python_round_trip(tmp_path, fmt, name):
    frames = CLIPS[name]()
    colors = int(max(f.max() for f in frames)) + 1
    path = write_video(tmp_path / "v.bin", fmt, frames, palette565(max(colors, 2)))
    data = path.read_bytes()
    decoded = list(MODULES[fmt].iter_frames(data))
    assert len(decoded) == len(frames)
    for got, want in zip(decoded, frames):
        np.testing.assert_array_equal(got, want)


@pytest.mark.parametrize("fmt", [1, 2])
@pytest.mark.parametrize("name", sorted(CLIPS))
@pytest.mark.parametrize("chunk", [8192, 777])
def test_c_decoder_matches(tmp_path, host_player, fmt, name, chunk):
    frames = CLIPS[name]()
    colors = int(max(f.max() for f in frames)) + 1
    pal = palette565(max(colors, 2))
    video = write_video(tmp_path / "v.bin", fmt, frames, pal)
    result = run_host(host_player, video, "--chunk", chunk, dump=tmp_path / "out.raw")
    assert result.returncode == 0, result.stdout + result.stderr
    screens = read_dump(tmp_path / "out.raw")
    expected = expected_screens(frames, pal)
    assert len(screens) == len(expected)
    for i, (got, want) in enumerate(zip(screens, expected)):
        assert np.array_equal(got, want), "frame %d differs" % i


@pytest.mark.parametrize("fmt", [1, 2])
def test_replay_gives_same_frames(tmp_path, host_player, fmt):
    frames = moving_rect(128, 72, 10)
    pal = palette565(4)
    video = write_video(tmp_path / "v.bin", fmt, frames, pal)
    result = run_host(host_player, video, "--twice", "--chunk", 1000, dump=tmp_path / "out.raw")
    assert result.returncode == 0, result.stdout + result.stderr
    screens = read_dump(tmp_path / "out.raw")
    assert len(screens) == 2 * len(frames)
    assert np.array_equal(screens[:len(frames)], screens[len(frames):])


def test_header_fields(tmp_path, host_player):
    video = write_video(tmp_path / "v.bin", 2, moving_rect(100, 70, 3), palette565(4), fps=29.97, title="Hello")
    out = run_host(host_player, video).stdout
    assert "format=2 width=100 height=70 fps100=2997 frames=3 palsize=4 scale=3 x=42 y=3 title=Hello" in out
    header = format2.read_header(video.read_bytes())
    assert (header["frames"], header["fps100"], header["title"]) == (3, 2997, "Hello")


def test_long_runs_and_skips(tmp_path, host_player):
    # 384x216 = 82944 pixels: longer than one 65536-pixel run or skip.
    a = np.zeros((216, 384), np.uint8)
    b = a.copy()
    b[-1, -1] = 1  # only the last pixel changes -> one huge skip
    c = np.ones((216, 384), np.uint8)
    frames = [a, b, b.copy(), c]
    encoded = [format2.FrameEncoder()]
    enc = encoded[0]
    sizes = [len(enc.encode(f)) for f in frames]
    assert sizes[2] == 1  # nothing changed: just the end marker
    assert sizes[1] < 10
    pal = palette565(2)
    video = write_video(tmp_path / "v.bin", 2, frames, pal)
    result = run_host(host_player, video, dump=tmp_path / "out.raw")
    assert result.returncode == 0, result.stdout
    assert np.array_equal(read_dump(tmp_path / "out.raw"), np.array(expected_screens(frames, pal)))


def test_format2_is_much_smaller_when_the_background_stays_still(tmp_path):
    background = noise(128, 72, 1, colors=8, seed=2)[0]
    frames = []
    for i in range(30):
        f = background.copy()
        f[20:30, 4 * i:4 * i + 10] = 7
        frames.append(f)
    pal = palette565(8)
    one = write_video(tmp_path / "1.bin", 1, frames, pal).stat().st_size
    two = write_video(tmp_path / "2.bin", 2, frames, pal).stat().st_size
    assert two < one / 5, (one, two)


def test_format2_is_never_bigger_on_flat_animation(tmp_path):
    frames = moving_rect(128, 72, 30)
    pal = palette565(4)
    one = write_video(tmp_path / "1.bin", 1, frames, pal).stat().st_size
    two = write_video(tmp_path / "2.bin", 2, frames, pal).stat().st_size
    assert two <= one, (one, two)


def test_literals_used_for_noise():
    frame = noise(128, 72, 1, colors=16, seed=5)[0]
    data = format2.encode_frame(frame.ravel())
    assert 0xF0 in data
    assert len(data) < frame.size * 0.6  # ~4 bits per pixel, not 16


@pytest.mark.parametrize("fmt", [1, 2])
def test_truncated_files_never_crash(tmp_path, host_player, fmt):
    video = write_video(tmp_path / "v.bin", fmt, moving_rect(24, 16, 4), palette565(4))
    data = video.read_bytes()
    bad = tmp_path / "bad.bin"
    for cut in range(0, len(data), max(1, len(data) // 150)):
        bad.write_bytes(data[:cut])
        result = run_host(host_player, bad, "--chunk", 7)
        assert result.returncode in (0, 2, 4), (cut, result.stdout, result.stderr)


@pytest.mark.parametrize("fmt", [1, 2])
def test_corrupt_files_never_crash(tmp_path, host_player, fmt):
    video = write_video(tmp_path / "v.bin", fmt, noise(40, 30, 3, colors=8) + moving_rect(40, 30, 3), palette565(8))
    data = bytearray(video.read_bytes())
    rng = np.random.default_rng(1234)
    bad = tmp_path / "bad.bin"
    for _ in range(200):
        corrupt = bytearray(data)
        for pos in rng.integers(0, len(corrupt), rng.integers(1, 6)):
            corrupt[pos] = int(rng.integers(0, 256))
        bad.write_bytes(bytes(corrupt))
        result = run_host(host_player, bad, "--chunk", 100)
        assert result.returncode in (0, 2, 4), (result.stdout, result.stderr)
