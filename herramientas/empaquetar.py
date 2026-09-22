"""ZIP portátil con nombres POSIX, manifiesto SHA-256 y revisión completa."""
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configuracion import VERSION
from servicios.instalador import MANIFIESTO, sha256, leer_paquete


def empaquetar(raiz):
    archivos = {}
    for ruta in sorted(raiz.rglob('*')):
        if ruta.is_file() and ruta.name != MANIFIESTO:
            archivos[ruta.relative_to(raiz).as_posix()] = {'size': ruta.stat().st_size, 'sha256': sha256(ruta)}
    manifiesto = {'schema': 1, 'version': VERSION, 'files': archivos}
    (raiz / MANIFIESTO).write_text(json.dumps(manifiesto, indent=2), encoding='utf-8')
    destino = raiz.parent / f'Fenix-{VERSION}-windows-x64.zip'
    with ZipFile(destino, 'w', ZIP_DEFLATED, compresslevel=6) as archivo:
        for nombre in [*archivos, MANIFIESTO]:
            archivo.write(raiz / nombre, 'Fenix/' + nombre)
    with ZipFile(destino) as archivo:
        leer_paquete(archivo)
        assert archivo.testzip() is None, 'ZIP dañado'
    print(f'{destino}: {len(archivos)} archivos; SHA256 {sha256(destino)}')


if __name__ == '__main__':
    empaquetar(Path(sys.argv[1]).resolve())
