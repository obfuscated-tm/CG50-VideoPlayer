"""Finding a USB-connected calculator, its usable space, and copying videos onto it."""
import shutil

from cgvideo.calculator import (ADDIN_SIZE, ASSUMED_FREE, RESERVE, Calculator, available_space, copy_to,
                                find_calculator)


def make_drive(tmp_path, name, *files):
    root = tmp_path / name
    root.mkdir()
    for f in files:
        (root / f).write_bytes(b"x" * 10)
    return root


def test_finds_a_drive_with_casio_files(tmp_path):
    stick = make_drive(tmp_path, "USBSTICK", "notes.txt")
    calc_root = make_drive(tmp_path, "CASIO", "video_player.g3a", "badapple.bin")
    calc = find_calculator(roots=[stick, calc_root], max_total=None)
    assert calc.path == calc_root
    assert calc.has_player
    assert calc.free == shutil.disk_usage(str(calc_root)).free


def test_recognizes_a_calculator_by_its_main_memory_folder(tmp_path):
    root = tmp_path / "CASIO"
    (root / "@MainMem").mkdir(parents=True)
    calc = find_calculator(roots=[root], max_total=None)
    assert calc is not None and not calc.has_player


def test_ignores_drives_without_casio_files(tmp_path):
    root = make_drive(tmp_path, "STICK", "video.bin", "._game.g3a")  # hidden files don't count
    assert find_calculator(roots=[root], max_total=None) is None


def test_ignores_drives_bigger_than_a_calculator(tmp_path):
    root = make_drive(tmp_path, "BIGDISK", "backup.g3a")  # tmp_path is on the computer's own disk
    assert find_calculator(roots=[root]) is None


def test_available_space(tmp_path):
    assert available_space(None, "a.bin") == ASSUMED_FREE
    root = make_drive(tmp_path, "CASIO")
    (root / "old.bin").write_bytes(b"x" * 5000)
    calc = Calculator(root, free=1_000_000, total=16 * 2**20, has_player=True)
    assert available_space(calc, "new.bin") == 1_000_000 - RESERVE
    assert available_space(calc, "old.bin") == 1_000_000 - RESERVE + 5000  # replacing frees its space
    no_player = Calculator(root, free=1_000_000, total=16 * 2**20, has_player=False)
    assert available_space(no_player, "new.bin") == 1_000_000 - RESERVE - ADDIN_SIZE
    full = Calculator(root, free=10, total=16 * 2**20, has_player=True)
    assert available_space(full, "new.bin") == 0


def test_copy_to(tmp_path):
    root = make_drive(tmp_path, "CASIO")
    source = tmp_path / "clip.bin"
    source.write_bytes(bytes(range(256)) * 10)
    target = copy_to(Calculator(root, 10**6, 16 * 2**20, True), source)
    assert target == root / "clip.bin"
    assert target.read_bytes() == source.read_bytes()
