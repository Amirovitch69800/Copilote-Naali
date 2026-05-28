# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Données embarquées des librairies
holidays_datas  = collect_data_files('holidays')
icalendar_datas = collect_data_files('icalendar')
tzdata_datas    = collect_data_files('tzdata')

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('web/templates',  'web/templates'),
        ('web/static',     'web/static'),
        ('data',           'data'),
    ] + holidays_datas + icalendar_datas + tzdata_datas,
    hiddenimports=[
        'core',
        'core.calendrier',
        'core.dashboard_data',
        'core.dn_engine',
        'core.filtres',
        'core.ics_export',
        'core.itineraire',
        'core.planning',
        'hubspot',
        'hubspot.catalogue',
        'hubspot.companies',
        'hubspot.contacts',
        'hubspot.deals',
        'hubspot.meetings',
        'hubspot.qualite',
        'hubspot.suivi',
        'jinja2.ext',
        'werkzeug.serving',
        'werkzeug.debug',
        'click',
        'concurrent.futures',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NaaliPlanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='NaaliPlanner',
)
