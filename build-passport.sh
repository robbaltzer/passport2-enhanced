#!/usr/bin/env bash
# SPDX-FileCopyrightText: © 2026 Rob Baltzer
# SPDX-License-Identifier: GPL-3.0-or-later
#
# build-passport.sh - Build and developer-sign Passport firmware on macOS.
#
# Usage:
#   ./build-passport.sh                 # build + sign current checkout, version = version.txt + "b1"
#   ./build-passport.sh 2.4.1           # override the version (becomes 2.4.1b1 unless a bN suffix is given)
#   ./build-passport.sh --pull          # git pull first
#   ./build-passport.sh --sd            # also copy to the microSD (auto if one is mounted, else a numbered list)
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
# Version stamped into the signed header. Default is version.txt; a "bN" beta suffix
# (one uppercase hex digit, per cosign's is_valid_version) is appended unless one was
# given, so the splash reads e.g. "Version 2.4.0b1" and the build is distinguishable
# from an official release. The header field is VERSION_LEN=8 bytes including the NUL,
# and cosign does not check the length before strcpy, so enforce <= 7 chars here.
[[ -n "$VERSION" ]] || VERSION="$(tr -d '[:space:]' < version.txt)"
[[ "$VERSION" =~ ^[0-9]\.[0-9]{1,2}\.[0-9]{1,2}(b[0-9A-F])?$ ]] || die "version '$VERSION' must be X.Y.Z or X.Y.ZbN (N = one uppercase hex digit)"
if [[ "$VERSION" != *b* ]]; then
    if [[ ${#VERSION} -le 5 ]]; then
        VERSION="${VERSION}b1"
    else
        echo "  note: '$VERSION' leaves no room for a 'b1' marker in the 7-char header field;"
        echo "        the splash will match the official version. The post-login warning page"
        echo "        and Settings > Firmware (developer-signed) still identify this build."
    fi
fi
[[ ${#VERSION} -le 7 ]] || die "version '$VERSION' is ${#VERSION} chars; the firmware header holds at most 7"

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
        # List removable volumes; auto-pick if exactly one, otherwise ask.
        candidates=()
        for v in /Volumes/*; do
            [[ -d "$v" && "$v" != "/Volumes/Macintosh HD" ]] || continue
            diskutil info "$v" 2>/dev/null | grep -q 'Removable Media: *Removable' && candidates+=("$v")
        done
        case ${#candidates[@]} in
            0) die "no removable volume mounted; insert the microSD or use --sd=/Volumes/NAME" ;;
            1) SD_MOUNT="${candidates[0]}" ;;
            *)
                bold "== Removable volumes"
                for i in "${!candidates[@]}"; do
                    size="$(diskutil info "${candidates[$i]}" 2>/dev/null | awk -F': *' '/Disk Size/ {print $2}' | awk '{print $1, $2}')"
                    printf '  %d) %s  (%s)\n' "$((i + 1))" "${candidates[$i]}" "${size:-?}"
                done
                [[ -t 0 ]] || die "multiple removable volumes and no terminal to choose from; use --sd=/Volumes/NAME"
                while :; do
                    read -r -p "Copy to which volume? [1-${#candidates[@]}, q to skip]: " pick
                    [[ "$pick" == "q" ]] && { echo "  skipped microSD copy"; SD_MOUNT=""; break; }
                    [[ "$pick" =~ ^[0-9]+$ && pick -ge 1 && pick -le ${#candidates[@]} ]] && { SD_MOUNT="${candidates[$((pick - 1))]}"; break; }
                    echo "  enter a number between 1 and ${#candidates[@]}"
                done
                ;;
        esac
    fi
fi
if [[ -n "$SD_MOUNT" ]]; then
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
