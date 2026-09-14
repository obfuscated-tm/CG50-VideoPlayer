import pytest

from cgvideo.timefmt import format_time, parse_time


@pytest.mark.parametrize("text, seconds", [
    ("", None), ("   ", None),
    ("0", 0), ("90", 90), ("12.5", 12.5), ("5.00", 5),
    ("5:00", 300), ("0:05:00", 300), ("1:30", 90), (" 1:30 ", 90), ("1:05:00", 3900),
    ("5:", 300), ("0:5", 5), ("1:30.5", 90.5),
    ("5m", 300), ("5 min", 300), ("1m30s", 90), ("1m 30s", 90), ("45s", 45), ("1h", 3600), ("1h2m3s", 3723),
    ("5M", 300),
])
def test_parse_time(text, seconds):
    assert parse_time(text) == seconds


@pytest.mark.parametrize("text", ["-1", "abc", "5x", ":30", "1:2:3:4", "1:a", "m", "5:-1"])
def test_parse_time_rejects(text):
    with pytest.raises(ValueError):
        parse_time(text)


@pytest.mark.parametrize("seconds, text", [(0, "0:00"), (5, "0:05"), (90, "1:30"), (300, "5:00"),
                                           (3723, "1:02:03"), (59.6, "1:00"), (None, "0:00")])
def test_format_time(seconds, text):
    assert format_time(seconds) == text
