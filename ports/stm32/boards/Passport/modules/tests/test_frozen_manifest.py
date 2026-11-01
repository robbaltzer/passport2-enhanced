# SPDX-FileCopyrightText: © 2026 Rob Baltzer
# SPDX-License-Identifier: GPL-3.0-or-later
#
# test_frozen_manifest.py - Every module imported by a package __init__ must be
# listed in the frozen manifest. The simulator loads modules from the filesystem
# and so never notices a missing manifest entry; on the device the package import
# fails at boot (this is how pages/dice_entropy_page.py bricked the first boot).

import re
from pathlib import Path

MODULES = Path(__file__).resolve().parents[1]
MANIFEST = MODULES.parent / 'manifest.py'


def frozen_files():
    text = MANIFEST.read_text()
    return set(re.findall(r"'([^']+\.py)'", text))


def package_imports(pkg):
    init = MODULES / pkg / '__init__.py'
    mods = re.findall(r'^from \.(\w+) import', init.read_text(), re.M)
    return ['{}/{}.py'.format(pkg, m) for m in mods]


def test_package_imports_are_frozen():
    frozen = frozen_files()
    missing = []
    for pkg in ('pages', 'flows', 'tasks', 'views', 'styles'):
        if not (MODULES / pkg / '__init__.py').exists():
            continue
        for f in package_imports(pkg):
            if f not in frozen and (MODULES / f).exists():
                missing.append(f)
    assert not missing, 'imported by package __init__ but not in manifest.py: {}'.format(missing)


def test_frozen_files_exist():
    missing = [f for f in frozen_files() if f.startswith(('pages/', 'flows/', 'tasks/')) and not (MODULES / f).exists()]
    assert not missing, 'listed in manifest.py but not on disk: {}'.format(missing)
