from pathlib import Path
raiz = Path(SPECPATH)
a = Analysis([str(raiz / 'servicios' / 'instalador.py')], pathex=[str(raiz)],
             binaries=[], datas=[], hiddenimports=[], hookspath=[], runtime_hooks=[],
             excludes=['PySide6', 'playwright', 'certifi'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FenixUpdater',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FenixUpdater')
