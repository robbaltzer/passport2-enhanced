<!--
SPDX-FileCopyrightText: © 2026 Rob Baltzer

SPDX-License-Identifier: GPL-3.0-or-later
-->

# CLAUDE.md — passport2-enhanced

Project context for Claude Code. Read fully before changing anything.

## What this is

Rob Baltzer's personal fork of Foundation Devices' Passport (Gen 2, color) firmware,
adding **user dice-roll entropy** to the New Seed flow. Unofficial, developer-signed,
test use only — the firmware says so on screen after login. GPLv3.

Owner: Rob (GitHub `robbaltzer`). Hardware: one Passport Gen 2 on the bench; it is
the only test device. Mac: `~/Documents/passport2-enhanced`, Apple Silicon.

## Branch layout

- `release-2.3.11` — **default and only live branch.** Equals Foundation's `v2.3.11`
  tag (their latest official release) plus the fork's commits. All work branches from
  and merges to this.
- `dev-v2.4.0` — **dead.** Based on upstream's unreleased dev branch; carries a
  manifest bug that makes it unbootable on hardware. Do not build or merge from it.
  Should be deleted.
- Feature branches (`dice-entropy*`, `fix-*`, `ui-fixes`, `ci-and-guard`) are merged
  and can be deleted.
- Upstream: `https://github.com/Foundation-Devices/passport2`. To take a new release:
  `git fetch upstream --tags`, create `release-X.Y.Z` from the tag, cherry-pick the
  fork commits, rebuild the Docker image and clean `build-Passport/` (see Build).

## The feature (what must not regress)

`ports/stm32/boards/Passport/modules/`

- `pages/dice_entropy_page.py` — keys 1-6 append a roll, `*` deletes, checkmark
  finishes; live `N rolls ~B bits / target` counter (green at target, copper `(max)`
  at the 256-roll cap); rolls shown in fives, last ~80; `extend_timeout=True`.
- `flows/new_seed_flow.py` — states `enter_dice` → `confirm_dice` between
  `confirm_generate` and `generate_seed`. Dice entry is mandatory. Confirmation shows
  count, bits, SHA-256 of the roll string as four 16-char lines, a note that hardware
  entropy is always included, and a warning below target (50 rolls / 12 words,
  100 / 24 words). Back from confirm must use `back()` not `goto()` (a `goto` traps
  the user in a loop — regression test exists). Rolls survive Back.
- `tasks/new_seed_task.py` — `seed = SHA256(hw_entropy[32] || rolls_ascii)`,
  truncated to 16/32 bytes. Hardware entropy (`noise.ALL` = avalanche + MCU RNG +
  secure element) is always included; dice can only add. Zero rolls is byte-identical
  to stock. On this base `random_bytes()` returns `False` on failure — treated as an
  error, no seed produced.
- The displayed hash is SHA-256 of the ASCII digit string (Coldcard/SeedSigner
  convention). Verified on hardware against entropylab.online: 100 rolls of `1` →
  `380b4863f69ebaac c794bfa1742a8a6d dc575e8cf0ded434 1ab9da158881ea2d`.
  It proves the rolls were received as typed; it cannot reproduce the final seed
  (the hardware bytes are never shown). A "dice only" mode was discussed, not built.
- `flows/main_flow.py` — `show_fork_warning()` runs **after** `LoginFlow`, never
  before (the pre-login path has a `Flow.run` spin on swallowed exceptions).
- `public_constants.py` — `FORK_NAME`, `DICE_BITS_PER_ROLL_MILLI = 2585`.

## The rule that bricked the device once

**Every new Python module must be added to `ports/stm32/boards/Passport/manifest.py`.**
The firmware only ships modules named there; the simulator loads from the filesystem
and will never notice an omission. `tests/test_frozen_manifest.py` enforces "every
`.py` under the frozen package dirs is in the manifest" — run it after adding any file.
Developer-only modules go in `manifest_dev.py`.

Corollary: **the simulator passing is not evidence the device boots.** Nothing is
considered working until it has been flashed and exercised on the Passport.

## Build, sign, install, recover (macOS)

- Prereqs: git, Docker Desktop (Rosetta enabled), `brew install just`, developer
  keys at `~/bin/keys/user.pem` + `user-pub.bin` (`./tools/genkeys.sh 1`; never
  commit keys; `.gitignore` covers `dist/`).
- `./build-passport.sh [--pull] [--clean] [--sd[=/Volumes/NAME]] [X.Y.Z]`
  - Builds the Docker image only if none exists; it does **not** detect a stale
    one (2.3.11 = ubuntu:20.04; 2.4.0 was 24.04 — a stale image fails `mpy-cross`).
    After a base change, `docker rmi foundation-devices/passport2:latest` first.
    Auto-rebuild is commit `e3c75d55` on branch `fix-version-marker`, never merged.
  - `--clean` after switching branches: stale LVGL bindings in `build-Passport/`
    fail with `'ICON_LIST' undeclared`.
  - Version is stamped into a 7-char header field. `2.3.11` already fills it, so
    no `b1` marker on this base; the script says so. cosign grammar: `X.Y.Z` or
    `X.Y.ZbN` (N = one uppercase hex digit); cosign `strcpy`s without a length
    check, so the script enforces ≤ 7.
  - Output: `dist/vX.Y.Z-<branch>-<sha>-passport.bin` + `.txt` with hashes.
- Install: first time only, Settings → Advanced → Developer Pubkey → Install PubKey
  (`user-pub.bin` on the card). Then Settings → Firmware → Update Firmware.
  Hardware shows "signed by a custom Developer PubKey" — expected.
- **Recovery** (firmware won't boot): see README. Official Foundation image only,
  written **raw** with `dd ... of=/dev/diskN bs=1m` (NOT `rdiskN` — raw device
  rejects the final partial sector and silently truncates), hold **9** at the
  splash. Downgrade check passes because dev-signed builds never update the SE
  timestamp. Reformat the card afterwards. Hung UI: hold power; last resort pull
  the battery.

## Tests and CI

- `just test` builds the simulator and runs `modules/tests/` (path fixed in #10).
- Headless fixture `tests/fixtures/headless.py` runs `ports/unix/passport-mpy` in
  `--unit-test` mode without SDL; `test_dice_entropy.py` (14) uses it — exact hash
  vectors against CPython `hashlib`, key handling, Back-loop regression,
  entropy-failure path. `test_frozen_manifest.py` (6) needs no simulator.
- Simulator must be rebuilt (`make clean` in `simulator/`) when switching bases.
- Local lint: `cd ports/stm32 && just lint-py`; `reuse lint` (6 upstream files fail
  locally on this tag; CI's REUSE action passes).
- GitHub Actions: `lint.yaml` (upstream) and `simulator-tests.yaml` (ours:
  headless gate of 27 tests, upstream SDL `test_unit.py` non-blocking under xvfb,
  lint-py, pycodestyle pinned) run on PRs and on pushes to `release-2.3.11` only.
  For current status check the Actions tab — don't trust a "green" note here
  (Lint was red from #11 until #12 and nobody noticed).
- `build.yaml` (upstream) is manual-only (#13) and has **never** run on this fork:
  it targets the retired `ubuntu-20.04` runner (jobs queue until auto-cancelled
  after 24 h) and there is no `UserSigningKey` secret. CI does not produce
  firmware; every image comes from `build-passport.sh`.
- The simulator keypad shim passes `*` as the raw char; hardware sends
  `LV_KEY_BACKSPACE`. The dice page accepts both.
- The hardware keypad drops a repeat of the same key within 120 ms (upstream
  debounce; affects PIN entry too). Page says "one press per roll"; not changed.

## Hardware (for reasoning about failures)

STM32H753 (Cortex-M7, 2 MB flash, no USB compiled in), ATECC608A secure element
(PIN, seed, attempt counter, dev pubkey, firmware timestamp), avalanche noise
circuit on ADC2, 8 MB SPI flash (staged updates, settings), OVM7690 camera (QR
only), BQ27520 fuel gauge, removable battery. Bootloader is Foundation's own C
(128 KB, factory-flashed, root of trust, reads recovery image raw from SD block 0);
firmware is MicroPython + LVGL, cooperative `uasyncio`, no OS, no isolation.

## Review history (four AI reviewers, ~10 rounds) — still open

- Upstream RNG hardening on 2.3.11 (unsigned `< 0` check in `noise.c`, MCU RNG
  wait-forever) — worth cherry-picking later; don't touch C without device testing.
- Dice page title layout with a long roll list not yet photographed on device
  after #9.
- Memory is not scrubbed (`dice_rolls = None` only); documented, not fixed.
- Optional "dice only (externally verifiable)" seed mode — discussed, not built.

Review claims that turned out false (don't re-litigate): intercept callbacks need a
return value (no — C consumes them); `LV_KEY_BACKSPACE == ord('*')` (no, 8 vs 42);
SHA-256 truncation drops the dice (no — every digest bit depends on every input
bit); the default branch is `dev-v2.4.0` (no, it is `release-2.3.11`).

## Working agreements

- Commit as Rob (`Rob Baltzer <rob.baltzer01@gmail.com>`); PRs against
  `release-2.3.11`; one topic per PR; Rob merges.
- Keep `build-passport.sh` and anything not firmware out of PRs that might go
  upstream.
- Before claiming a fix works: simulator test, then **device test**. Say which was
  done.
- Nothing from this fork goes on a device holding real funds.
