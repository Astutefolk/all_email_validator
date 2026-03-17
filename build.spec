# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Astute Email Validator.

Build commands:
  macOS/Linux:  pyinstaller build.spec
  Windows:      pyinstaller build.spec
"""

import sys

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'dns',
        'dns.resolver',
        'dns.rdatatype',
        'dns.name',
        'dns.exception',
        'dns.message',
        'dns.query',
        'dns.rdata',
        'dns.rdataclass',
        'dns.rrset',
        'dns.zone',
        'dns.reversename',
        'dns.inet',
        'dns.e164',
        'dns.namedict',
        'dns.tsigkeyring',
        'dns.rdtypes',
        'dns.rdtypes.ANY',
        'dns.rdtypes.IN',
        'dns.rdtypes.ANY.MX',
        'dns.rdtypes.IN.A',
        'dns.rdtypes.IN.AAAA',
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
