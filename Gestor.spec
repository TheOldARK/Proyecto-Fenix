"""Lanzador ligero del Gestor; reutiliza el runtime compartido de Fénix."""
from pathlib import Path
from PyInstaller.building.build_main import Analysis, EXE, PYZ

root = Path(SPEC).parent
a = Analysis(
    [str(root / "herramientas" / "gestor_launcher.py")],
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
    name="FenixGestor",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "recursos" / "logo.ico"),
)
