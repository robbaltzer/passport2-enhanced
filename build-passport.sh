#!/usr/bin/env bash
# SPDX-FileCopyrightText: © 2026 Rob Baltzer
# SPDX-License-Identifier: GPL-3.0-or-later
#
# build-passport.sh - Build and developer-sign Passport firmware on macOS.
#
# Usage:
#   ./build-passport.sh                 # build + sign current checkout, version = version.txt + "b1"
#   ./build-passport.sh 2.4.1           # override the version stamped into the firmware header
#   ./build-passport.sh --pull          # git pull first
#   ./build-passport.sh --sd            # also copy firmware + pubkey to the mounted microSD
#   ./build-passport.sh --sd=/Volumes/PASSPORT   # explicit microSD mount point
#   ./build-passport.sh --clean         # wipe build-Passport/ before building
#
# Requirements: git, Docker Desktop (running), just, and a developer key at
#   ~/bin/keys/user.pem     (private key, used for signing)
#   ~/bin/keys/user-pub.bin (public key, installed on Passport via
#                            Settings > Advanced > Developer Pubkey)
# Generate them once with:  ./tools/genkeys.sh 1  (see DEVELOPMENT.md)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY_DIR="$HOME/bin/keys"
PRIV_KEY="$KEY_DIR/user.pem"
PUB_KEY="$KEY_DIR/user-pub.bin"
SCREEN="color"               # Gen 2 Passport. Use "mono" for Founder's Edition.
DIST_DIR="$REPO_DIR/dist"

VERSION=""
DO_PULL=0
DO_CLEAN=0
SD_MOUNT=""

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
die()   { red "ERROR: $*" >&2; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --pull)   DO_PULL=1 ;;
        --clean)  DO_CLEAN=1 ;;
        --sd)     SD_MOUNT="auto" ;;
        --sd=*)   SD_MOUNT="${arg#--sd=}" ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        -*)       die "unknown option: $arg" ;;
        *)        VERSION="$arg" ;;
    esac
done

cd "$REPO_DIR"

# ---------------------------------------------------------------- preflight
bold "== Preflight"
[[ -f Justfile && -d ports/stm32/boards/Passport ]] || die "run this from the passport2 repo root"

for tool in git docker just; do
    command -v "$tool" >/dev/null 2>&1 || die "'$tool' not found. Install: git (xcode-select --install), Docker Desktop, 'brew install just'"
done
docker info >/dev/null 2>&1 || die "Docker daemon not running. Open Docker Desktop and wait for it to finish starting."

[[ -f "$PRIV_KEY" ]] || die "signing key not found at $PRIV_KEY (run ./tools/genkeys.sh 1 and move the keys to $KEY_DIR)"
[[ -f "$PUB_KEY"  ]] || die "public key not found at $PUB_KEY"
[[ "$(stat -f '%Lp' "$KEY_DIR")" == "700" ]] || echo "  note: consider 'chmod 700 $KEY_DIR'"

# Refuse to build with key material inside the repo
if ls ./*.pem ./*-pub.bin >/dev/null 2>&1; then
    die "key files found in repo root ($(ls ./*.pem ./*-pub.bin 2>/dev/null | tr '\n' ' ')) - move them to $KEY_DIR first"
fi

if [[ $DO_PULL -eq 1 ]]; then
    bold "== git pull"
    git pull --ff-only
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "  note: working tree has uncommitted changes; build will include them"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
COMMIT="$(git rev-parse --short HEAD)"
# Default: upstream version + "b1" so the splash shows e.g. "Version 2.4.0b1" and the
# build is distinguishable from an official release. cosign allows one hex digit after "b".
[[ -n "$VERSION" ]] || VERSION="$(tr -d '[:space:]' < version.txt)b1"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9]*$ ]] || die "version '$VERSION' doesn't look like X.Y.Z"

echo "  branch:  $BRANCH @ $COMMIT"
echo "  version: $VERSION"
echo "  screen:  $SCREEN"

# Docker image present?
if ! docker image inspect foundation-devices/passport2:latest >/dev/null 2>&1; then
    bold "== Building Docker image (first time only, slow)"
    just build-docker
fi

if [[ $DO_CLEAN -eq 1 ]]; then
    bold "== Cleaning"
    rm -rf ports/stm32/build-Passport
fi

# ---------------------------------------------------------------- build + sign
bold "== Building and signing (just sign)"
# Justfile mounts ~/bin/keys at /keys inside the container.
just sign /keys/user.pem "$VERSION" "$SCREEN" 2>&1 | tee /tmp/passport-build.log

SIGNED="ports/stm32/build-Passport/v${VERSION}-beta-passport.bin"
[[ -f "$SIGNED" ]] || die "expected signed firmware at $SIGNED but it wasn't produced (see /tmp/passport-build.log)"

BUILD_HASH="$(grep 'FW Build Hash:' /tmp/passport-build.log | tail -1 | awk '{print $4}')"
DL_HASH="$(grep 'FW Download Hash:' /tmp/passport-build.log | tail -1 | awk '{print $4}')"
FILE_SHA="$(shasum -a 256 "$SIGNED" | awk '{print $1}')"

# ---------------------------------------------------------------- dist
mkdir -p "$DIST_DIR"
OUT_NAME="v${VERSION}-${BRANCH}-${COMMIT}-passport.bin"
cp "$SIGNED" "$DIST_DIR/$OUT_NAME"
cp "$PUB_KEY" "$DIST_DIR/user-pub.bin"
{
    echo "file:          $OUT_NAME"
    echo "built:         $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "branch:        $BRANCH"
    echo "commit:        $(git rev-parse HEAD)"
    echo "version:       $VERSION"
    echo "screen:        $SCREEN"
    echo "build hash:    $BUILD_HASH   (shown on Passport under Firmware info)"
    echo "download hash: $DL_HASH"
    echo "file sha256:   $FILE_SHA"
} > "$DIST_DIR/$OUT_NAME.txt"

echo
green "== Done"
echo "  firmware:   $DIST_DIR/$OUT_NAME"
echo "  pubkey:     $DIST_DIR/user-pub.bin"
echo "  build hash: $BUILD_HASH"
echo "  file sha:   $FILE_SHA"

# ---------------------------------------------------------------- microSD
if [[ -n "$SD_MOUNT" ]]; then
    if [[ "$SD_MOUNT" == "auto" ]]; then
        # Pick the single removable volume if exactly one is mounted
        candidates=()
        for v in /Volumes/*; do
            [[ -d "$v" && "$v" != "/Volumes/Macintosh HD" ]] || continue
            diskutil info "$v" 2>/dev/null | grep -q 'Removable Media: *Removable' && candidates+=("$v")
        done
        [[ ${#candidates[@]} -eq 1 ]] || die "couldn't pick a microSD automatically (${#candidates[@]} removable volumes); use --sd=/Volumes/NAME"
        SD_MOUNT="${candidates[0]}"
    fi
    [[ -d "$SD_MOUNT" ]] || die "microSD mount point not found: $SD_MOUNT"
    bold "== Copying to microSD at $SD_MOUNT"
    cp "$SIGNED" "$SD_MOUNT/"
    cp "$PUB_KEY" "$SD_MOUNT/"
    sync
    green "  copied $(basename "$SIGNED") and user-pub.bin"
    echo "  On Passport: first Settings > Advanced > Developer Pubkey > Install Pubkey (once),"
    echo "               then Settings > Firmware > Update Firmware."
    echo "  Eject with: diskutil eject \"$SD_MOUNT\""
fi
