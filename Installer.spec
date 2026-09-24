from PyInstaller.building.build_main import Analysis, EXE, PYZ, COLLECT
from pathlib import Path

root = Path(SPEC).parent

a = Analysis(
    ["herramientas/instalador_windows.py"],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name="FenixSetup",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "recursos" / "logo.ico"),
)
