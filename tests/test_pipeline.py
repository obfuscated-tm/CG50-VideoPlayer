"""Reading videos: timing, trimming, resizing, whole conversions and size estimates."""
import cv2
import numpy as np
import pytest

from cgvideo import estimate, format1, format2, names
from cgvideo.errors import ConvertError
from cgvideo.pipeline import Settings, convert, iter_source_frames, output_fps, probe, resize_frame

SRC_FPS = 29.97


def make_counting_video(path, frames=90, fps=SRC_FPS, size=(160, 120)):
    """Each frame is a flat gray whose level encodes its index (k * 2)."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    for k in range(frames):
        writer.write(np.full((size[1], size[0], 3), k * 2, np.uint8))
    writer.release()
    return path


def make_moving_video(path, seconds=6, fps=24, size=(320, 180)):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    for k in range(seconds * fps):
        img = np.full((size[1], size[0], 3), 40, np.uint8)
        x = (k * 4) % (size[0] - 60)
        cv2.rectangle(img, (x, 50), (x + 60, 110), (40, 200, 240), -1)
        cv2.circle(img, (size[0] - x - 20, 140), 18, (250, 250, 250), -1)
        writer.write(img)
    writer.release()
    return path


def frame_index(bgr):
    return int(round(bgr.mean() / 2))


@pytest.fixture(scope="module")
def counting(tmp_path_factory):
    return make_counting_video(tmp_path_factory.mktemp("v") / "count.avi")


@pytest.fixture(scope="module")
def moving(tmp_path_factory):
    return make_moving_video(tmp_path_factory.mktemp("v") / "moving.avi")


def test_probe(counting):
    info = probe(counting)
    assert abs(info.fps - SRC_FPS) < 0.01
    assert info.frame_count == 90
    assert (info.width, info.height) == (160, 120)


def test_probe_rejects_non_video(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("not a video")
    with pytest.raises(ConvertError):
        probe(bad)
    with pytest.raises(ConvertError):
        probe(tmp_path / "missing.mp4")


def test_resampling_picks_nearest_frames(counting):
    info = probe(counting)
    got = [frame_index(f) for f in iter_source_frames(info, 0.0, None, 15.0)]
    want = []
    i = 0
    while int(round((i / 15.0) * info.fps)) < 90:
        want.append(int(round((i / 15.0) * info.fps)))
        i += 1
    assert got == want


def test_trimming(counting):
    info = probe(counting)
    got = [frame_index(f) for f in iter_source_frames(info, 1.0, 2.0, 10.0)]
    assert len(got) == 10
    assert got[0] == round(1.0 * info.fps)
    assert got[-1] == round(1.9 * info.fps)


def test_format1_rounds_fps(counting):
    info = probe(counting)
    assert output_fps(Settings(fps=None, fmt=1), info) == 30.0
    assert output_fps(Settings(fps=None, fmt=2), info) == 29.97
    assert output_fps(Settings(fps=60, fmt=2), info) == 29.97  # never faster than the source


def test_letterbox_and_crop():
    wide = np.full((360, 640, 3), 255, np.uint8)
    boxed = resize_frame(wide, 96, 72, "letterbox")
    assert boxed.shape == (72, 96, 3)
    assert boxed[0].max() == 0 and boxed[-1].max() == 0 and boxed[36].min() == 255
    cropped = resize_frame(wide, 96, 72, "crop")
    assert cropped.shape == (72, 96, 3) and cropped.min() == 255


@pytest.mark.parametrize("fmt", [1, 2])
def test_convert_end_to_end(tmp_path, moving, fmt):
    out = tmp_path / "out.bin"
    settings = Settings(width=64, height=36, fps=12, colors=4, fmt=fmt, title="Moving", start=1.0, end=4.0)
    result = convert(moving, out, settings)
    data = out.read_bytes()
    module = format1 if fmt == 1 else format2
    header = module.read_header(data)
    frames = list(module.iter_frames(data))
    assert header["frames"] == result.frames == len(frames) == 36
    assert header["fps100"] == 1200
    assert (header["width"], header["height"]) == (64, 36)
    assert len(header["palette"]) <= 4
    assert header["title"] == ("Moving" if fmt == 2 else "")


def test_cancel_removes_partial_file(tmp_path, moving):
    import threading

    cancel = threading.Event()
    out = tmp_path / "out.bin"

    def progress(done, total):
        if done == 3:
            cancel.set()

    from cgvideo.errors import Cancelled
    with pytest.raises(Cancelled):
        convert(moving, out, Settings(width=32, height=18), progress=progress, cancel=cancel)
    assert not out.exists()


@pytest.mark.parametrize("fmt", [1, 2])
def test_estimate_is_close(tmp_path, moving, fmt):
    info = probe(moving)
    settings = Settings(width=128, height=72, fps=12, colors=8, fmt=fmt)
    guess = estimate.estimate_size(info, settings).size
    actual = convert(moving, tmp_path / "o.bin", settings, info=info).size
    assert abs(guess - actual) / actual < 0.25, (guess, actual)


def test_make_it_fit(moving):
    info = probe(moving)
    big = Settings(width=384, height=216, fps=None, colors=16, dither=True)
    same, est = estimate.make_it_fit(info, big, target=10 ** 9)
    assert same == big
    fitted, est = estimate.make_it_fit(info, big, target=estimate.estimate_size(info, big).size // 4)
    assert fitted is not None and fitted != big
    assert est.size <= estimate.estimate_size(info, big).size // 4
    impossible, _ = estimate.make_it_fit(info, big, target=10)
    assert impossible is None


def test_calculator_names(tmp_path):
    assert names.calculator_name("Bad Apple!! PV.mp4") == "bad_appl.bin"
    assert names.calculator_name("???.mov") == "video.bin"
    (tmp_path / "clip.bin").write_bytes(b"")
    assert names.calculator_name("clip.mp4", tmp_path) == "clip2.bin"
