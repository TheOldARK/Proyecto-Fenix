"""Distribución portable nativa para Linux x86_64 (sin datos personales)."""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

if sys.platform != 'linux':
    raise RuntimeError('Este archivo debe ejecutarse en Linux.')
raiz = Path(SPECPATH)
datos = [(str(raiz / 'recursos'), 'recursos'),
         (str(raiz / 'LICENSE'), '.'), (str(raiz / 'LEEME_LINUX.txt'), '.')]
for nombre in ('catalogo_sia.json', 'planes_estudio.json', 'configuracion_libre_eleccion.json'):
    datos.append((str(raiz / 'datos' / nombre), 'datos'))
for paquete in ('PySide6-Essentials', 'shiboken6', 'playwright', 'beautifulsoup4',
                'soupsieve', 'pyee', 'greenlet', 'typing-extensions', 'certifi'):
    datos.extend(copy_metadata(paquete))
a = Analysis([str(raiz / 'aplicacion' / 'cliente_main.py')], pathex=[str(raiz)],
             binaries=[], datas=datos, hiddenimports=[], hookspath=[], runtime_hooks=[],
             excludes=['herramientas', 'boto3', 'botocore', 's3transfer', 'jmespath'], noarchive=False)
privados = ('herramientas', 'boto3', 'botocore', 's3transfer', 'jmespath')
incluidos = [nombre for nombre, *_ in a.pure if any(nombre == p or nombre.startswith(p + '.') for p in privados)]
if incluidos:
    raise RuntimeError(f'El cliente contiene módulos privados: {incluidos[:10]}')
# Copiar Chromium intacto después: no transformar sus recursos ni bibliotecas.
a.datas = [e for e in a.datas if '/.local-browsers/' not in e[0].replace('\\', '/')]
a.binaries = [e for e in a.binaries if '/.local-browsers/' not in e[0].replace('\\', '/')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Fenix',
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Fenix')
