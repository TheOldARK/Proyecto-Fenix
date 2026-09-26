"""Genera un ZIP de Fenix.app conservando permisos y enlaces del bundle."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


def main():
    if sys.platform != 'darwin':
        raise SystemExit('La compilación de Fenix.app necesita macOS.')
    raiz = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(raiz))
    from configuracion import VERSION
    import playwright
    from PIL import Image

    arquitectura = {'arm64': 'arm64', 'x86_64': 'x64'}[platform.machine()]
    salida = raiz / 'dist' / 'macos'
    trabajo = raiz / 'build' / 'macos'
    trabajo.mkdir(parents=True, exist_ok=True)
    with Image.open(raiz / 'recursos' / 'logo.png') as imagen:
        imagen.convert('RGBA').save(raiz / 'build' / 'macos-icon.icns')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    '--distpath', str(salida), '--workpath', str(trabajo),
                    str(raiz / 'FenixMac.spec')], cwd=raiz, check=True)
    app = salida / 'Fenix.app'
    navegadores = Path(playwright.__file__).parent / 'driver' / 'package' / '.local-browsers'
    candidatos = [p for p in navegadores.rglob('*') if p.is_file()
                  and p.name in ('headless_shell', 'chrome-headless-shell')]
    if len(candidatos) != 1:
        raise RuntimeError(f'Se esperaba un Chromium nativo; encontrados: {candidatos}')
    raiz_navegador = navegadores / candidatos[0].relative_to(navegadores).parts[0]
    shutil.copytree(raiz_navegador, app / 'Contents' / 'Resources' / 'browser', symlinks=True)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    # El diagnóstico ejecuta el binario final, Qt y Chromium; usa un perfil vacío.
    with tempfile.TemporaryDirectory(prefix='fenix-macos-diagnostico-') as datos:
        entorno = os.environ.copy()
        entorno.update(FENIX_DATA_DIR=datos, QT_QPA_PLATFORM='offscreen',
                       PYINSTALLER_RESET_ENVIRONMENT='1')
        proceso = subprocess.run([str(app / 'Contents' / 'MacOS' / 'Fenix'), '--diagnostico'],
                                 env=entorno, cwd=salida, timeout=120)
        informe = Path(datos) / 'logs' / 'diagnostico_instalacion.json'
        if informe.is_file():
            shutil.copy2(informe, trabajo / 'diagnostico_instalacion.json')
            resultado = json.loads(informe.read_text(encoding='utf-8'))
            print(json.dumps(resultado, ensure_ascii=False), flush=True)
        else:
            raise RuntimeError('El ejecutable no generó el informe de diagnóstico.')
        if proceso.returncode or not resultado.get('correcto') or resultado['version'] != VERSION:
            raise RuntimeError('Fenix.app no superó el diagnóstico.')

    paquete = salida / f'Fenix-{VERSION}-macos-{arquitectura}.zip'
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                    str(app), str(paquete)], check=True)
    # Reabrir el ZIP como lo haría un Mac: comprobar firma tras la extracción.
    with tempfile.TemporaryDirectory(prefix='fenix-macos-extraido-') as extraido:
        subprocess.run(['ditto', '-x', '-k', str(paquete), extraido], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict',
                        str(Path(extraido) / 'Fenix.app')], check=True)
    with paquete.open('rb') as archivo:
        digest = hashlib.file_digest(archivo, 'sha256').hexdigest()
    paquete.with_suffix('.zip.sha256').write_text(f'{digest}  {paquete.name}\n', encoding='utf-8')
    print(f'Paquete verificado: {paquete} ({paquete.stat().st_size} bytes)', flush=True)


if __name__ == '__main__':
    main()
