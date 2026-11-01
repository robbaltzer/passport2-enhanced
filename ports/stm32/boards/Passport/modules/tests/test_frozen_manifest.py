# SPDX-FileCopyrightText: © 2026 Rob Baltzer
# SPDX-License-Identifier: GPL-3.0-or-later
#
# test_frozen_manifest.py - The firmware only ships Python modules named in the
# frozen manifest. The simulator loads modules from the filesystem and so never
# notices a missing entry; on the device the import fails at runtime (this is how
# pages/dice_entropy_page.py bricked the first boot).
#
# Rule enforced: every .py file under the frozen package directories must be
# listed in manifest.py (or manifest_dev.py for developer/), however it is
# imported - package __init__, lazily inside a function, or not at all.

import re
from pathlib import Path

MODULES = Path(__file__).resolve().parents[1]
BOARD = MODULES.parent
MANIFEST = BOARD / 'manifest.py'
MANIFEST_DEV = BOARD / 'manifest_dev.py'

# Directories whose contents are frozen from manifest.py.
PACKAGE_DIRS = ('pages', 'flows', 'tasks', 'views', 'styles', 'extensions', 'animations',
                'microns', 'ui', 'translations', 'data_codecs', 'foundation')

# Upstream leaves these on disk but does not freeze them: they are stale copies
# of modules that live (and are frozen) under developer/.
KNOWN_UNFROZEN = {
    'flows/delete_derived_keys_flow.py',
    'flows/spin_delay_flow.py',
}


def frozen_entries(manifest):
    """Paths named inside freeze('.../modules', (...)) tuples only - not comments."""
    text = manifest.read_text()
    entries = set()
    for m in re.finditer(r"freeze\(\s*'[^']*/modules'\s*,\s*\((.*?)\)\s*\)", text, re.S):
        body = re.sub(r'#.*', '', m.group(1))  # strip comments inside the tuple
        entries |= set(re.findall(r"'([^']+\.py)'", body))
    return entries


def on_disk(dirs):
    files = set()
    for d in dirs:
        p = MODULES / d
        if p.is_dir():
            files |= {str(f.relative_to(MODULES)) for f in p.rglob('*.py')}
    return files


def test_manifest_parses():
    assert len(frozen_entries(MANIFEST)) > 100, 'manifest parse found suspiciously few entries'


def test_every_package_module_is_frozen():
    frozen = frozen_entries(MANIFEST)
    missing = sorted((on_disk(PACKAGE_DIRS) - frozen) - KNOWN_UNFROZEN)
    assert not missing, 'on disk but not in manifest.py (will fail to import on device): {}'.format(missing)


def test_top_level_modules_are_frozen():
    frozen = frozen_entries(MANIFEST)
    top = {f.name for f in MODULES.glob('*.py')}
    missing = sorted(top - frozen)
    assert not missing, 'top-level modules not in manifest.py: {}'.format(missing)


def test_developer_modules_are_frozen_in_dev_manifest():
    if not (MODULES / 'developer').is_dir():
        return
    frozen = frozen_entries(MANIFEST_DEV) | frozen_entries(MANIFEST)
    missing = sorted(on_disk(('developer',)) - frozen)
    assert not missing, 'developer/ modules not in manifest_dev.py: {}'.format(missing)


def test_frozen_entries_exist_on_disk():
    stale = sorted(f for f in frozen_entries(MANIFEST) | frozen_entries(MANIFEST_DEV)
                   if not (MODULES / f).exists())
    assert not stale, 'listed in a manifest but not on disk (build will fail): {}'.format(stale)


def test_package_init_imports_resolve():
    """A typo in a package __init__ import must fail, not be skipped."""
    bad = []
    for d in PACKAGE_DIRS:
        init = MODULES / d / '__init__.py'
        if not init.exists():
            continue
        for mod in re.findall(r'^from \.(\w+) import', init.read_text(), re.M):
            if not (MODULES / d / (mod + '.py')).exists() and not (MODULES / d / mod).is_dir():
                bad.append('{}/__init__.py imports .{}'.format(d, mod))
    assert not bad, bad
