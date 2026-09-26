"""Prueba el instalador compilado: descarga real, primera instalación y reinstalación."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


def main():
    raiz = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(raiz))
    from herramientas.instalacion_nativa import plataforma_nativa, nombre_raiz
    sistema = plataforma_nativa()
    salida = raiz / 'dist/instalador-nativo'
    informes = raiz / 'build/pruebas-instalador'
    informes.mkdir(parents=True, exist_ok=True)
    paquete = next(salida.glob('Fenix-Instalador-*.zip' if sistema.startswith('macos-') else 'Fenix-Instalador-*.tar.gz'))
    with paquete.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == paquete.with_name(paquete.name + '.sha256').read_text().split()[0]
    with tempfile.TemporaryDirectory(prefix='fenix prueba nativa ') as temporal:
        carpeta = Path(temporal)
        if sistema.startswith('macos-'):
            subprocess.run(['ditto', '-x', '-k', str(paquete), str(carpeta)], check=True)
            app = carpeta / 'Instalar Fenix.app'
            subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
            exe = app / 'Contents/MacOS/InstalarFenix'
        else:
            with tarfile.open(paquete, 'r:gz') as archivo:
                archivo.extractall(carpeta, filter='data')
            exe = carpeta / 'Instalar-Fenix'
        assert os.access(exe, os.X_OK)
        destino = carpeta / 'Aplicaciones con espacios' / nombre_raiz(sistema)
        perfil = carpeta / 'perfil usuario'
        perfil.mkdir()
        marcador = perfil / 'horario.json'
        marcador.write_text('{"conservar": true}', encoding='utf-8')
        entorno = os.environ.copy()
        entorno['FENIX_DATA_DIR'] = str(perfil)
        entorno['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        for numero in (1, 2):
            informe = informes / f'instalacion-{numero}.json'
            proceso = subprocess.run([str(exe), '--prueba-instalar', str(destino), '--informe', str(informe)],
                                     env=entorno, cwd=carpeta, timeout=600)
            resultado = json.loads(informe.read_text(encoding='utf-8')) if informe.exists() else {}
            print(json.dumps(resultado, ensure_ascii=False), flush=True)
            assert proceso.returncode == 0 and resultado.get('correcto'), resultado
            assert resultado['sistema'] == sistema and destino.is_dir()
            assert marcador.read_text(encoding='utf-8') == '{"conservar": true}'
            if numero == 1:
                assert resultado['respaldo'] is None
            else:
                assert Path(resultado['respaldo']).is_dir()
        print('Instalador extraído: primera instalación, reinstalación, diagnóstico y cierre de ventana correctos.', flush=True)


if __name__ == '__main__':
    main()
