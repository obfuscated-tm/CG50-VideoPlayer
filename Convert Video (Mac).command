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

# Find Python 3.9+ with Tkinter (the python.org installer includes it).
PY=""
for candidate in \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
        PY="$(command -v "$candidate")"
        break
    fi
done
[ -n "$PY" ] || fail "Python 3.9 or newer is needed. Install it from https://www.python.org/downloads/
then double-click this file again. (Homebrew's Python also works after: brew install python-tk)"

if [ ! -x .venv/bin/python ]; then
    echo "First run: setting things up. This takes a minute or two..."
    "$PY" -m venv .venv || fail "Couldn't create the converter's Python environment."
fi
if ! cmp -s converter/requirements.txt .venv/installed-requirements.txt; then
    .venv/bin/python -m pip install --disable-pip-version-check -q -r converter/requirements.txt ||
        fail "Couldn't download the converter's parts. Check your internet connection and try again."
    cp converter/requirements.txt .venv/installed-requirements.txt
fi

echo "Opening the converter window..."
exec .venv/bin/python converter/convert.py
