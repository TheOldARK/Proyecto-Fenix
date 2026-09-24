"""Ejecutable lanzador del publicador; Qt se carga desde Fenix.exe."""
from pathlib import Path
from PyInstaller.building.build_main import Analysis, EXE, PYZ

root = Path(SPEC).parent
a = Analysis(
    [str(root / "herramientas" / "publicador_launcher.py")],
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
    name="FenixPublicador",
    debug=False,
    strip=False,
    upx=False,
    # Al iniciarse desde el escritorio, la consola permite ver errores y el
    # progreso detallado aunque la ventana de Fénix se cierre inesperadamente.
    console=True,
    icon=str(root / "recursos" / "logo.ico"),
)
