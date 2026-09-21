# Construcción Windows: solo recursos públicos y datos base explícitos.
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)
import playwright

raiz = Path(SPECPATH)
sys.path.insert(0, str(raiz))
from configuracion import VERSION

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
# Evitar DLL homónimas de otras herramientas instaladas (por ejemplo ICU de
# Poppler). Qt debe resolver las bibliotecas del sistema desde Windows.
windows = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join([
    str(Path(sys.executable).parent), sys.base_prefix,
    str(windows / "System32"), str(windows),
])
navegadores = Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"
if not list(navegadores.glob("chromium_headless_shell-*")):
    raise RuntimeError("Descarga Chromium Headless Shell con construir_windows.ps1 antes de empaquetar.")

datos = [
    (str(raiz / "recursos"), "recursos"),
    (str(raiz / "LICENSE"), "."),
    (str(raiz / "LEEME_BETA.txt"), "."),
    (str(navegadores), "playwright/driver/package/.local-browsers"),
]
licencia_python = Path(sys.base_prefix) / "LICENSE.txt"
if licencia_python.is_file():
    datos.append((str(licencia_python), "licencias/python"))
for nombre in ("catalogo_sia.json", "planes_estudio.json", "configuracion_libre_eleccion.json"):
    datos.append((str(raiz / "datos" / nombre), "datos"))
for paquete in ("PySide6-Essentials", "shiboken6", "playwright",
                "beautifulsoup4", "soupsieve", "pyee", "greenlet", "typing-extensions", "certifi"):
    datos.extend(copy_metadata(paquete))

version_windows = VSVersionInfo(
    ffi=FixedFileInfo(filevers=(0, 1, 0, 8), prodvers=(0, 1, 0, 8),
                     mask=0x3F, flags=0x2, OS=0x40004, fileType=0x1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("CompanyName", "Proyecto Fénix"),
        StringStruct("FileDescription", "Fénix - Planificador académico"),
        StringStruct("FileVersion", VERSION),
        StringStruct("ProductName", "Fénix"),
        StringStruct("ProductVersion", VERSION),
        StringStruct("OriginalFilename", "Fenix.exe"),
    ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)

a = Analysis([str(raiz / "main.py")], pathex=[str(raiz)], binaries=[], datas=datos,
             hiddenimports=[], hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Fenix", debug=False,
          strip=False, upx=False, console=False, version=version_windows,
          icon=str(raiz / "recursos" / "logo.png"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Fenix")
