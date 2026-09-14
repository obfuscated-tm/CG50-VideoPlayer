#!/usr/bin/env bash
# Builds a Prizm (fx-CG50) SDK from source: sh3eb-elf binutils + GCC, libfxcg 0.6
# and mkg3a. Works on macOS (Apple Silicon or Intel, with Homebrew) and Linux.
#
#   tools/setup-sdk.sh                 # installs into ~/prizm-sdk
#   PRIZM_SDK=/some/dir tools/setup-sdk.sh
#
# Safe to re-run: finished stages are skipped (delete $PRIZM_SDK/.stamp-* to redo one).
# Afterwards:  export FXCGSDK="$HOME/prizm-sdk"  and run `make` in the project folder.
#
# The GCC configure flags follow libfxcg's Dockerfile.toolchain. GCC 14 is used instead of
# the 10.1 in the Windows SDK because 10.1 predates Apple Silicon. --with-system-zlib is
# needed because the zlib bundled with binutils/GCC doesn't compile against recent macOS SDKs.
set -euo pipefail

PRIZM_SDK="${PRIZM_SDK:-$HOME/prizm-sdk}"
BINUTILS_VER=2.43.1
GCC_VER=14.2.0
LIBFXCG_VER=0.6
LIBFXCG_REPO=https://github.com/Jonimoose/libfxcg.git
LIBFXCG_COMMIT=8ef28fbcafc27ae03eb72fc8f240f6a752b9c4be  # tag v0.6
MKG3A_REPO=https://gitlab.com/taricorp/mkg3a.git

# sha256 of the source archives. An empty value just prints the hash instead of checking it.
BINUTILS_SHA256=13f74202a3c4c51118b797a39ea4200d3f6cfbe224da6d1d95bb938480132dfd
GCC_SHA256=a7b39bc69cbf9e25826c5a60ab26477001f7c08d85cec04bc0e29cabed6f3cc9

SRC="$PRIZM_SDK/src"
BUILD="$PRIZM_SDK/build"
LOG="$PRIZM_SDK/setup.log"
STEP="starting"

step() { STEP="$1"; echo; echo "==> $1"; }
have() { command -v "$1" >/dev/null 2>&1; }
done_stamp() { [ -f "$PRIZM_SDK/.stamp-$1" ]; }
stamp() { touch "$PRIZM_SDK/.stamp-$1"; }

sha256() {
    if have sha256sum; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# fetch URL FILE [SHA256] - downloads into $SRC once, verifying the hash when one is given.
fetch() {
    local url="$1" out="$SRC/$2" want="${3:-}"
    if [ ! -f "$out" ]; then
        curl -fL --retry 3 -o "$out.part" "$url"
        mv "$out.part" "$out"
    fi
    local got
    got="$(sha256 "$out")"
    if [ -n "$want" ] && [ "$got" != "$want" ]; then
        echo "Checksum mismatch for $2 (got $got). Delete $out and try again."
        return 1
    fi
    echo "sha256 $2: $got"
}

gnu_fetch() {
    fetch "https://ftpmirror.gnu.org/$1" "$2" "$3" || {
        rm -f "$SRC/$2"
        fetch "https://ftp.gnu.org/gnu/$1" "$2" "$3"
    }
}

main() {
    set -E
    trap 'echo; echo "*** Setup failed during: $STEP"; echo "*** Full log: $LOG"' ERR

    if have nproc; then JOBS="${JOBS:-$(nproc)}"; else JOBS="${JOBS:-$(sysctl -n hw.ncpu)}"; fi

    # --- Prerequisites --------------------------------------------------------
    step "Checking prerequisites"
    local extra_gcc_flags=() png_prefix=""
    case "$(uname -s)" in
    Darwin)
        if ! xcode-select -p >/dev/null 2>&1; then
            echo "Install the Xcode command line tools first:  xcode-select --install"
            return 1
        fi
        if ! have brew; then
            echo "Homebrew is required on macOS: https://brew.sh"
            return 1
        fi
        local missing=() pkg
        for pkg in gmp mpfr libmpc isl libpng cmake texinfo; do
            brew list --versions "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
        done
        if [ "${#missing[@]}" -gt 0 ]; then
            if [ "${PRIZM_NO_BREW:-0}" = 1 ]; then
                echo "Missing Homebrew packages: ${missing[*]} (PRIZM_NO_BREW=1, not installing)"
            else
                echo "Installing Homebrew packages: ${missing[*]}"
                brew install "${missing[@]}"
            fi
        fi
        # makeinfo from Homebrew's texinfo is keg-only on some setups.
        if [ -d "$(brew --prefix)/opt/texinfo/bin" ]; then
            PATH="$(brew --prefix)/opt/texinfo/bin:$PATH"
        fi
        extra_gcc_flags=(
            "--with-gmp=$(brew --prefix gmp)"
            "--with-mpfr=$(brew --prefix mpfr)"
            "--with-mpc=$(brew --prefix libmpc)"
            "--with-isl=$(brew --prefix isl)"
        )
        png_prefix="$(brew --prefix libpng)"
        ;;
    *)
        local tool
        for tool in gcc g++ make curl unzip git cmake; do
            have "$tool" || {
                echo "Missing '$tool'. On Debian/Ubuntu: sudo apt install build-essential curl unzip git cmake" \
                     "libgmp-dev libmpfr-dev libmpc-dev libisl-dev libpng-dev zlib1g-dev texinfo"
                return 1
            }
        done
        ;;
    esac
    have makeinfo || echo "note: makeinfo not found; the release tarballs ship prebuilt docs so this is usually fine"

    export PATH="$PRIZM_SDK/bin:$PATH"

    # --- binutils -------------------------------------------------------------
    if ! done_stamp binutils; then
        step "Building binutils $BINUTILS_VER (a few minutes)"
        gnu_fetch "binutils/binutils-$BINUTILS_VER.tar.xz" "binutils-$BINUTILS_VER.tar.xz" "$BINUTILS_SHA256"
        rm -rf "$BUILD/binutils-src" "$BUILD/binutils"
        mkdir -p "$BUILD/binutils-src" "$BUILD/binutils"
        tar -xf "$SRC/binutils-$BINUTILS_VER.tar.xz" -C "$BUILD/binutils-src" --strip-components=1
        (
            cd "$BUILD/binutils"
            ../binutils-src/configure --target=sh3eb-elf --prefix="$PRIZM_SDK" \
                --disable-nls --disable-werror --with-sysroot --with-system-zlib
            make -j"$JOBS"
            make install
        )
        stamp binutils
    fi

    # --- GCC ------------------------------------------------------------------
    if ! done_stamp gcc; then
        step "Building GCC $GCC_VER for sh3eb-elf (the long part: 15-40 minutes)"
        gnu_fetch "gcc/gcc-$GCC_VER/gcc-$GCC_VER.tar.xz" "gcc-$GCC_VER.tar.xz" "$GCC_SHA256"
        rm -rf "$BUILD/gcc-src" "$BUILD/gcc"
        mkdir -p "$BUILD/gcc-src" "$BUILD/gcc"
        tar -xf "$SRC/gcc-$GCC_VER.tar.xz" -C "$BUILD/gcc-src" --strip-components=1
        (
            cd "$BUILD/gcc"
            ../gcc-src/configure --target=sh3eb-elf --prefix="$PRIZM_SDK" \
                --with-pkgversion=PrizmSDK --without-headers --enable-languages=c,c++ \
                --disable-tls --disable-nls --disable-threads --disable-shared \
                --disable-libssp --disable-libvtv --disable-libada \
                --with-endian=big --with-multilib-list= --with-system-zlib \
                ${extra_gcc_flags[@]+"${extra_gcc_flags[@]}"}
            make -j"$JOBS" inhibit_libc=true all-gcc
            make install-gcc
        )
        stamp gcc
    fi

    # libgcc is small; it's built without -j because SH's extra unwind-dw2-Os-4-200.o
    # rule races with the generation of libgcc_tm.h in parallel builds.
    if ! done_stamp libgcc; then
        step "Building libgcc"
        (
            cd "$BUILD/gcc"
            make inhibit_libc=true all-target-libgcc
            make install-target-libgcc
        )
        stamp libgcc
    fi

    # --- libfxcg --------------------------------------------------------------
    # Built from source with the compiler above: the prebuilt v0.6 archives contain GCC 10
    # link-time-optimization data that GCC 14 can't read.
    if ! done_stamp libfxcg-src; then
        step "Building libfxcg $LIBFXCG_VER"
        rm -rf "$BUILD/libfxcg-src"
        git -c advice.detachedHead=false clone -q --depth 1 --branch "v$LIBFXCG_VER" "$LIBFXCG_REPO" "$BUILD/libfxcg-src"
        local commit
        commit="$(git -C "$BUILD/libfxcg-src" rev-parse HEAD)"
        if [ "$commit" != "$LIBFXCG_COMMIT" ]; then
            echo "libfxcg v$LIBFXCG_VER is commit $commit, expected $LIBFXCG_COMMIT"
            return 1
        fi
        make -C "$BUILD/libfxcg-src" -j"$JOBS"
        mkdir -p "$PRIZM_SDK/toolchain" "$PRIZM_SDK/include" "$PRIZM_SDK/lib"
        cp -R "$BUILD/libfxcg-src/include/." "$PRIZM_SDK/include/"
        cp "$BUILD/libfxcg-src/lib/libfxcg.a" "$BUILD/libfxcg-src/lib/libc.a" "$PRIZM_SDK/lib/"
        cp "$BUILD/libfxcg-src/toolchain/prizm_rules" "$BUILD/libfxcg-src/toolchain/prizm.x" "$PRIZM_SDK/toolchain/"
        stamp libfxcg-src
    fi

    # --- mkg3a ----------------------------------------------------------------
    if ! done_stamp mkg3a; then
        step "Building mkg3a"
        rm -rf "$BUILD/mkg3a" "$BUILD/mkg3a-build"
        git clone --depth 1 "$MKG3A_REPO" "$BUILD/mkg3a"
        local cmake_args=(-S "$BUILD/mkg3a" -B "$BUILD/mkg3a-build" -DCMAKE_BUILD_TYPE=Release)
        if [ -n "$png_prefix" ]; then cmake_args+=("-DCMAKE_PREFIX_PATH=$png_prefix"); fi
        cmake "${cmake_args[@]}"
        cmake --build "$BUILD/mkg3a-build" --target mkg3a -j"$JOBS"
        cp "$BUILD/mkg3a-build/src/mkg3a" "$PRIZM_SDK/bin/mkg3a"
        stamp mkg3a
    fi

    # --- Self-test ------------------------------------------------------------
    step "Self-test"
    printf 'int f(int a, int b) { return a / b; }\n' > "$BUILD/selftest.c"
    sh3eb-elf-gcc -mb -m4a-nofpu -mhitachi -nostdlib -Os -c "$BUILD/selftest.c" -o "$BUILD/selftest.o"
    sh3eb-elf-gcc --version | head -1
    [ -x "$PRIZM_SDK/bin/mkg3a" ]

    trap - ERR
    echo
    echo "Prizm SDK is ready in $PRIZM_SDK"
    echo "Add this line to your ~/.zshrc (or ~/.bashrc), then open a new terminal:"
    echo
    echo "    export FXCGSDK=\"$PRIZM_SDK\""
    echo
    echo "Then run 'make' in the CG50-VideoPlayer folder to build video_player.g3a."
}

mkdir -p "$PRIZM_SDK" "$SRC" "$BUILD"
main "$@" 2>&1 | tee -a "$LOG"
