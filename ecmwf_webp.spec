# PyInstaller spec for the ECMWF WebP desktop application.
from PyInstaller.utils.hooks import collect_all

datas = [
    ("map_viewer", "map_viewer"),
    ("config/settings.example.json", "config"),
]
binaries = []
hiddenimports = ["serve_map", "eccodes", "cfgrib"]
for package in ("eccodes", "cfgrib", "xarray", "scipy", "pyproj", "keyring"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["main.py"],
    pathex=["src", "."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ECMWFWebP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ECMWFWebP",
)
