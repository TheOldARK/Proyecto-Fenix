"""Compila Linux y prueba el ejecutable extraído, Qt/X11 y Chromium incluidos."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile


def verificar(ejecutable, informe):
    with tempfile.TemporaryDirectory(prefix='fenix-linux-perfil-') as datos:
        entorno = os.environ.copy()
        entorno.update(FENIX_DATA_DIR=datos, PYINSTALLER_RESET_ENVIRONMENT='1')
        proceso = subprocess.run([str(ejecutable), '--diagnostico'], env=entorno,
                                 cwd=ejecutable.parent, timeout=120)
        origen = Path(datos) / 'logs' / 'diagnostico_instalacion.json'
        if not origen.is_file():
            raise RuntimeError('El ejecutable no generó el diagnóstico.')
        shutil.copy2(origen, informe)
        resultado = json.loads(origen.read_text(encoding='utf-8'))
        print(json.dumps(resultado, ensure_ascii=False), flush=True)
        from configuracion import VERSION
        if proceso.returncode or not resultado.get('correcto') or resultado['version'] != VERSION:
            raise RuntimeError('El ejecutable de Linux no superó el diagnóstico.')


def main():
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise SystemExit('Compilar de forma nativa en Linux x86_64.')
    raiz = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(raiz))
    from configuracion import VERSION
    import playwright

    salida, trabajo = raiz / 'dist/linux', raiz / 'build/linux'
    trabajo.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    '--distpath', str(salida), '--workpath', str(trabajo),
                    str(raiz / 'FenixLinux.spec')], cwd=raiz, check=True)
    app = salida / 'Fenix'
    navegadores = Path(playwright.__file__).parent / 'driver/package/.local-browsers'
    candidatos = [p for p in navegadores.rglob('*') if p.is_file()
                  and p.name in ('headless_shell', 'chrome-headless-shell')]
    if len(candidatos) != 1:
        raise RuntimeError(f'Se esperaba un Chromium nativo; encontrados: {candidatos}')
    navegador = navegadores / candidatos[0].relative_to(navegadores).parts[0]
    shutil.copytree(navegador, app / 'browser', symlinks=True)
    shutil.copy2(raiz / 'LEEME_LINUX.txt', app / 'LEEME_LINUX.txt')
    verificar(app / 'Fenix', trabajo / 'diagnostico_instalacion.json')
    paquete = salida / f'Fenix-{VERSION}-linux-x64.tar.gz'
    with tarfile.open(paquete, 'w:gz', compresslevel=6) as archivo:
        archivo.add(app, arcname='Fenix')
    # Volver a ejecutar la copia extraída, sin depender del directorio de build.
    with tempfile.TemporaryDirectory(prefix='fenix-linux-extraido-') as temporal:
        with tarfile.open(paquete, 'r:gz') as archivo:
            archivo.extractall(temporal, filter='data')
        verificar(Path(temporal) / 'Fenix/Fenix', trabajo / 'diagnostico_extraido.json')
    with paquete.open('rb') as archivo:
        digest = hashlib.file_digest(archivo, 'sha256').hexdigest()
    paquete.with_suffix('.gz.sha256').write_text(f'{digest}  {paquete.name}\n', encoding='utf-8')
    print(f'Paquete Linux verificado: {paquete} ({paquete.stat().st_size} bytes)', flush=True)


if __name__ == '__main__':
    main()
