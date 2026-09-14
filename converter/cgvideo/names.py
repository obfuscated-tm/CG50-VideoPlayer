import re
from pathlib import Path

MAX_STEM = 8


def calculator_name(video_path, folder=None):
    """Suggests a short, calculator-safe file name like 'badapple.bin'."""
    stem = re.sub(r"[^a-z0-9]+", "_", Path(video_path).stem.lower()).strip("_")[:MAX_STEM].strip("_")
    if not stem:
        stem = "video"
    name = stem + ".bin"
    if folder is None:
        return name
    folder = Path(folder)
    counter = 2
    while (folder / name).exists():
        suffix = str(counter)
        name = stem[: MAX_STEM - len(suffix)] + suffix + ".bin"
        counter += 1
    return name
