"""Empaqueta solo el instalador; la aplicación se descarga al ejecutarlo."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


def main():
    raiz = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(raiz))
    from herramientas.instalacion_nativa import plataforma_nativa
    sistema = plataforma_nativa()
    salida, trabajo = raiz / 'dist/instalador-nativo', raiz / 'build/instalador-nativo'
    trabajo.mkdir(parents=True, exist_ok=True)
    if sistema.startswith('macos-'):
        from PIL import Image
        with Image.open(raiz / 'recursos/logo.png') as imagen:
            imagen.convert('RGBA').save(raiz / 'build/instalador.icns')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    '--distpath', str(salida), '--workpath', str(trabajo),
                    str(raiz / 'InstallerNative.spec')], cwd=raiz, check=True)
    shutil.copy2(raiz / 'LEEME_INSTALADORES.txt', salida / 'LEEME_INSTALADORES.txt')
    if sistema.startswith('macos-'):
        app = salida / 'Instalar Fenix.app'
        subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        paquete = salida / f'Fenix-Instalador-{sistema}.zip'
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(paquete)], check=True)
    else:
        paquete = salida / f'Fenix-Instalador-{sistema}.tar.gz'
        with tarfile.open(paquete, 'w:gz') as archivo:
            archivo.add(salida / 'Instalar-Fenix', arcname='Instalar-Fenix')
            archivo.add(salida / 'LEEME_INSTALADORES.txt', arcname='LEEME_INSTALADORES.txt')
    with paquete.open('rb') as archivo:
        digest = hashlib.file_digest(archivo, 'sha256').hexdigest()
    paquete.with_name(paquete.name + '.sha256').write_text(f'{digest}  {paquete.name}\n', encoding='utf-8')
    print(f'Instalador generado: {paquete}', flush=True)


if __name__ == '__main__':
    main()
