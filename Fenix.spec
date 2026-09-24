# Construcción Windows: solo recursos públicos y datos base explícitos.
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, copy_metadata
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
    (str(raiz / "LEEME.txt"), "."),
    (str(navegadores), "playwright/driver/package/.local-browsers"),
]
binarios_cloudflare = []
imports_cloudflare = []
# El publicador importa boto3 dinámicamente. PyInstaller no lo detecta por el
# análisis estático, así que incluimos el SDK y sus modelos S3 explícitamente.
for paquete in ("boto3", "botocore", "s3transfer", "jmespath"):
    datos_paquete, binarios_paquete, imports_paquete = collect_all(paquete)
    datos.extend(datos_paquete)
    binarios_cloudflare.extend(binarios_paquete)
    imports_cloudflare.extend(imports_paquete)
licencia_python = Path(sys.base_prefix) / "LICENSE.txt"
if licencia_python.is_file():
    datos.append((str(licencia_python), "licencias/python"))
for nombre in ("catalogo_sia.json", "planes_estudio.json", "configuracion_libre_eleccion.json"):
    datos.append((str(raiz / "datos" / nombre), "datos"))
for paquete in ("PySide6-Essentials", "shiboken6", "playwright",
                "beautifulsoup4", "soupsieve", "pyee", "greenlet", "typing-extensions", "certifi",
                "boto3", "botocore", "s3transfer", "jmespath"):
    datos.extend(copy_metadata(paquete))

version_windows = VSVersionInfo(
    ffi=FixedFileInfo(filevers=tuple((list(map(int, VERSION.split('.'))) + [0]*4)[:4]), prodvers=tuple((list(map(int, VERSION.split('.'))) + [0]*4)[:4]),
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

a = Analysis([str(raiz / "main.py")], pathex=[str(raiz)], binaries=binarios_cloudflare, datas=datos,
             # El publicador se importa dinámicamente al pasar --publicador;
             # PyInstaller no puede detectarlo recorriendo imports estáticos.
             hiddenimports=[
                 "herramientas.publicador_main",
                 "herramientas.gestor_publicadores",
                 *imports_cloudflare,
             ], hookspath=[],
             runtime_hooks=[], excludes=[], noarchive=False)
# Chromium se copia en browser/ al lado del EXE para evitar MAX_PATH.
a.datas = [entrada for entrada in a.datas if '/.local-browsers/' not in entrada[0].replace('\\', '/')]
a.binaries = [entrada for entrada in a.binaries if '/.local-browsers/' not in entrada[0].replace('\\', '/')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Fenix", debug=False,
          strip=False, upx=False, console=False, version=version_windows,
          icon=str(raiz / "recursos" / "logo.png"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Fenix")
