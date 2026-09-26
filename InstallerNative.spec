import platform
import sys
from pathlib import Path

raiz = Path(SPECPATH)
if sys.platform not in ('darwin', 'linux'):
    raise RuntimeError('Compilar el instalador de forma nativa en macOS o Linux.')
a = Analysis([str(raiz / 'herramientas/instalador_nativo.py')], pathex=[str(raiz)],
             datas=[(str(raiz / 'recursos/logo.png'), 'recursos')], binaries=[], hiddenimports=[],
             excludes=['playwright', 'boto3', 'botocore', 'PIL'], noarchive=False)
pyz = PYZ(a.pure)
if sys.platform == 'darwin':
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='InstalarFenix',
              console=False, strip=False, upx=False, target_arch=platform.machine())
    coll = COLLECT(exe, a.binaries, a.datas, name='InstalarFenix', strip=False, upx=False)
    app = BUNDLE(coll, name='Instalar Fenix.app', icon=str(raiz / 'build/instalador.icns'),
                 bundle_identifier='io.github.theoldark.fenix.installer', version='1.0.0',
                 info_plist={'CFBundleDisplayName': 'Instalar Fénix', 'LSMinimumSystemVersion': '14.0',
                             'NSHighResolutionCapable': True, 'NSPrincipalClass': 'NSApplication'})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='Instalar-Fenix',
              console=True, strip=False, upx=False)
