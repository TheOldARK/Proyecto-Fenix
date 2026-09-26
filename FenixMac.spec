"""Fenix.app: se compila de forma nativa en Intel o Apple Silicon."""
import platform
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

if sys.platform != 'darwin':
    raise RuntimeError('Este archivo debe ejecutarse en macOS.')
raiz = Path(SPECPATH)
sys.path.insert(0, str(raiz))
from configuracion import VERSION

datos = [(str(raiz / 'recursos'), 'recursos'),
         (str(raiz / 'LICENSE'), '.'),
         (str(raiz / 'LEEME_MACOS.txt'), '.')]
for nombre in ('catalogo_sia.json', 'planes_estudio.json', 'configuracion_libre_eleccion.json'):
    datos.append((str(raiz / 'datos' / nombre), 'datos'))
binarios = []
ocultos = []
for paquete in ('boto3', 'botocore', 's3transfer', 'jmespath'):
    d, b, h = collect_all(paquete)
    datos.extend(d)
    binarios.extend(b)
    ocultos.extend(h)
for paquete in ('PySide6-Essentials', 'shiboken6', 'playwright', 'beautifulsoup4',
                'soupsieve', 'pyee', 'greenlet', 'typing-extensions', 'certifi',
                'boto3', 'botocore', 's3transfer', 'jmespath'):
    datos.extend(copy_metadata(paquete))

a = Analysis([str(raiz / 'main.py')], pathex=[str(raiz)],
             binaries=binarios, datas=datos, hiddenimports=ocultos,
             hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
# Se añade Chromium al bundle después de compilar, conservando su estructura.
a.datas = [e for e in a.datas if '/.local-browsers/' not in e[0].replace('\\', '/')]
a.binaries = [e for e in a.binaries if '/.local-browsers/' not in e[0].replace('\\', '/')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Fenix',
          debug=False, strip=False, upx=False, console=False,
          target_arch=platform.machine())
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Fenix')
app = BUNDLE(coll, name='Fenix.app', icon=str(raiz / 'build' / 'macos-icon.icns'),
             bundle_identifier='io.github.theoldark.fenix', version=VERSION,
             info_plist={'CFBundleDisplayName': 'Fénix',
                         'LSMinimumSystemVersion': '14.0',
                         'NSHighResolutionCapable': True,
                         'NSPrincipalClass': 'NSApplication',
                         'LSApplicationCategoryType': 'public.app-category.education'})
