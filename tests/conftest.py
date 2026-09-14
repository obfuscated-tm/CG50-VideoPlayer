import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "converter"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(scope="session")
def host_player(tmp_path_factory):
    """Compiles the calculator's decoder for this PC, with memory-error checking turned on."""
    cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        if os.environ.get("REQUIRE_CC"):
            pytest.fail("no C compiler found")
        pytest.skip("no C compiler found")
    exe = tmp_path_factory.mktemp("bin") / "host_player"
    # AddressSanitizer hangs at startup on recent macOS, so Macs use UBSan plus decode.c's own
    # bounds assertions; Linux (and CI) also gets ASan. CGV_SANITIZE overrides the choice.
    sanitize = os.environ.get("CGV_SANITIZE") or ("undefined" if sys.platform == "darwin" else "address,undefined")
    cmd = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-g", "-O1", "-DCGV_CHECK_BOUNDS",
           "-fsanitize=" + sanitize, "-fno-sanitize-recover=all",
           "-I", str(ROOT / "src"), str(ROOT / "tests" / "host_player.c"), str(ROOT / "src" / "decode.c"),
           "-o", str(exe)]
    subprocess.run(cmd, check=True)
    return exe
