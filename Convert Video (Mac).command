#!/bin/bash
# Double-click this file to open the CG50 Video Converter.
# The first time, it sets itself up (needs an internet connection and takes a minute or two).
cd "$(dirname "$0")" || exit 1

fail() {
    echo
    echo "$1"
    echo
    read -r -p "Press Return to close this window." _
    exit 1
}

# Pick the Python 3.9+ with the newest Tk (the window toolkit): Tk 8.6.12 and older react
# slowly to clicks on recent macOS.
TK_SCORE='import re, sys, tkinter
if sys.version_info < (3, 9): sys.exit(1)
v = [int(x) for x in re.findall(r"\d+", tkinter.Tcl().eval("info patchlevel"))[:3]] + [0, 0, 0]
print(v[0] * 10000 + v[1] * 100 + v[2])'
PY=""
BEST=0
for candidate in /Library/Frameworks/Python.framework/Versions/*/bin/python3 \
    /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    score="$("$candidate" -c "$TK_SCORE" 2>/dev/null)" || continue
    if [ "$score" -gt "$BEST" ]; then
        PY="$(command -v "$candidate")"
        BEST="$score"
    fi
done
[ -n "$PY" ] || fail "Python 3.9 or newer is needed. Install it from https://www.python.org/downloads/
then double-click this file again. (Homebrew's Python also works after: brew install python-tk)"
if [ "$BEST" -lt 80613 ]; then
    echo "Note: this Python's window toolkit is old, so the window may feel slow."
    echo "For a smoother window, install the latest Python from https://www.python.org/downloads/"
    echo
fi

# (Re)create the environment when it's missing or was made with a different Python.
if [ ! -x .venv/bin/python ] || [ "$(cat .venv/python-used.txt 2>/dev/null)" != "$PY" ]; then
    echo "Setting things up with $("$PY" --version). This takes a minute or two..."
    rm -rf .venv
    "$PY" -m venv .venv || fail "Couldn't create the converter's Python environment."
    echo "$PY" > .venv/python-used.txt
fi
if ! cmp -s converter/requirements.txt .venv/installed-requirements.txt; then
    .venv/bin/python -m pip install --disable-pip-version-check -q -r converter/requirements.txt ||
        fail "Couldn't download the converter's parts. Check your internet connection and try again."
    cp converter/requirements.txt .venv/installed-requirements.txt
fi

echo "Opening the converter window..."
exec .venv/bin/python converter/convert.py
