"""Finding an fx-CG calculator connected over USB ("USB Flash" mode) and how much room it has.

The calculator's 16 MB of storage is shared with everything else on it (other videos,
add-ins, programs, pictures), so the real limit is its free space, not 16 MB.
"""
import os
import shutil
import string
import sys
from dataclasses import dataclass
from pathlib import Path

# With no calculator connected, this much free space is assumed.
ASSUMED_FREE = 14 * 1024 * 1024
# Drives bigger than this are USB sticks or disks, not a calculator's 16 MB storage.
MAX_CALCULATOR_DRIVE = 64 * 1024 * 1024
# Kept free for file system overhead, so a "just fits" file really fits.
RESERVE = 64 * 1024
ADDIN_NAME = "video_player.g3a"
ADDIN_SIZE = 48 * 1024
# Files only a Casio calculator keeps in its main folder: add-ins, programs, pictures, eActivities...
CASIO_SUFFIXES = (".g3a", ".g3m", ".g3p", ".g3e", ".g3b")


@dataclass
class Calculator:
    path: Path
    free: int
    total: int
    has_player: bool


def _candidate_roots():
    if sys.platform == "darwin":
        bases = [Path("/Volumes")]
    elif os.name == "nt":
        return _windows_removable_drives()
    else:
        user = os.environ.get("USER", "")
        bases = [Path("/media") / user, Path("/run/media") / user, Path("/media"), Path("/mnt")]
    roots = []
    for base in bases:
        try:
            roots += [p for p in base.iterdir() if p.is_dir()]
        except OSError:
            pass
    return roots


def _windows_removable_drives():
    import ctypes

    drive_removable = 2
    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    roots = []
    for i, letter in enumerate(string.ascii_uppercase):
        root = "%s:\\" % letter
        if mask & (1 << i) and kernel32.GetDriveTypeW(root) == drive_removable:
            roots.append(Path(root))
    return roots


def _looks_like_calculator(root):
    try:
        for entry in os.scandir(str(root)):
            name = entry.name.lower()
            if name == "@mainmem":
                return True
            if name.endswith(CASIO_SUFFIXES) and not name.startswith(".") and entry.is_file():
                return True
    except OSError:
        pass
    return False


def find_calculator(roots=None, max_total=MAX_CALCULATOR_DRIVE):
    """The first connected calculator, or None. roots/max_total are for testing."""
    for root in roots if roots is not None else _candidate_roots():
        try:
            if Path(root).resolve() == Path(os.sep).resolve():
                continue  # e.g. /Volumes/Macintosh HD, the Mac's own disk
            if not _looks_like_calculator(root):
                continue
            usage = shutil.disk_usage(str(root))
        except OSError:
            continue
        if max_total is not None and usage.total > max_total:
            continue
        return Calculator(Path(root), usage.free, usage.total, (Path(root) / ADDIN_NAME).exists())
    return None


def available_space(calc, file_name):
    """Bytes a video called file_name can use: the calculator's free space when it's connected
    (plus the old file it would replace, minus room for the add-in if it isn't there yet),
    otherwise ASSUMED_FREE."""
    if calc is None:
        return ASSUMED_FREE
    space = calc.free - RESERVE
    try:
        existing = calc.path / file_name
        if existing.is_file():
            space += existing.stat().st_size
    except OSError:
        pass
    if not calc.has_player:
        space -= ADDIN_SIZE
    return max(0, space)


def copy_to(calc, source):
    """Copies a converted video into the calculator's main folder. A plain copy of the
    contents: no hidden "._" metadata files (which Finder would add) and no extra space used."""
    target = calc.path / Path(source).name
    shutil.copyfile(str(source), str(target))
    return target
