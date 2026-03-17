# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Astute Email Validator.

Build:  pyinstaller build.spec --clean --noconfirm
"""

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Collect every dns.* submodule automatically so nothing is missed
dns_hiddenimports = collect_submodules('dns')

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        *dns_hiddenimports,
        'colorama',
        'validator',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='email_validator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
