# Building

There are two parts:
- **The add-in** (`video_player.g3a`) is C code compiled for the calculator's SuperH CPU with [libfxcg](https://github.com/Jonimoose/libfxcg).
- **The converter** (`converter/`) is Python. It doesn't need building; see the README for how to run it.

## The add-in on a Mac (or Linux)

### 1. Set up the tools (once)

```bash
tools/setup-mac.sh
```

The script:
- Installs any missing Homebrew packages: gmp, mpfr, libmpc, isl, libpng, cmake, texinfo.
- Builds, into `~/prizm-sdk`:
  - binutils 2.43.1 and GCC 14.2 for `sh3eb-elf`
  - libfxcg v0.6
  - mkg3a

It takes 15–40 minutes. If it stops, running it again carries on where it left off. Everything is logged to `~/prizm-sdk/setup.log`.

On Linux, run `tools/setup-sdk.sh` instead. It tells you which `apt` packages to install if any are missing.

When the script finishes, add this line to `~/.zshrc` (or `~/.bashrc`) and open a new terminal:

```bash
export FXCGSDK="$HOME/prizm-sdk"
```

### 2. Build

```bash
make
```

This produces `video_player.g3a`. To start from scratch, run `make clean` first.

The link step prints how much memory the add-in uses. The `ram` line must stay under 64 KB: that's all the static memory the calculator gives add-ins, and going over is a build error.

### Notes on the toolchain

- **GCC version:** the Mac setup uses GCC 14 because GCC 10.1, used by the Windows SDK and CI, predates Apple Silicon. Both compile this code.
- **libfxcg:** built from source rather than using the prebuilt archive, because that archive contains GCC 10 link-time-optimization data that GCC 14 can't read.
- **zlib:** binutils and GCC are configured with `--with-system-zlib`, because their bundled zlib doesn't compile against recent macOS SDKs.

## The add-in with GitHub Actions

Every push builds the add-in with the official libfxcg compiler image (GCC 10.1) and runs the tests.

To get the files, open the repository's **Actions** tab, then the latest **Build** run. The **Artifacts** section has:
- `video_player`: the `.g3a`
- `converter-windows` and `converter-macos`: the converter apps

Pushing a tag that starts with `v` (e.g. `v3.0.0`) also publishes a GitHub Release with those files.

## The add-in on Windows (the original way)

This follows libfxcg's [Windows how-to](https://github.com/Jonimoose/libfxcg/blob/master/docs/howto-windows.md).

1. Download `PrizmSDK-win-0.6.zip` from the [libfxcg releases](https://github.com/Jonimoose/libfxcg/releases) and unzip it, e.g. to `C:\PrizmSDK-win-0.6`.
2. Put this project folder inside its `projects` folder.
3. Run `make.bat` in the project folder.

## Tests

```bash
python3 -m pip install -r tests/requirements-dev.txt
python3 -m pytest tests
```

The tests:
- Encode many synthetic videos in both formats.
- Decode them with the Python reference decoders **and** with `src/decode.c`, the calculator's own decoder compiled for your PC, and check the results are bit-identical.
- Feed the C decoder hundreds of truncated and corrupted files, under sanitizers, to make sure it never crashes or writes outside the screen.
- Check the converter's timing, trimming, resizing and size estimates.

`python3 converter/convert.py --selftest` opens the converter window, converts a generated clip and closes it again.

## Layout

| Path | What |
|---|---|
| `src/main.c` | The add-in: screens, keys, files, timing |
| `src/decode.c`, `src/decode.h` | Video decoding. Plain C, shared with the tests |
| `converter/` | The converter: `convert.py` (command line) and `app.py` (window) |
| `converter/cgvideo/` | Converter internals: palettes, resizing, both file formats, size estimates |
| `docs/FORMAT.md` | The `.bin` file formats |
| `tests/` | pytest tests, plus `host_player.c`, which runs the decoder on a PC |
| `tools/` | Toolchain setup and icon generation |
