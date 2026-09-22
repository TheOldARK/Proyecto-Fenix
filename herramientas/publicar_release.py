"""Publica un ZIP verificado usando la credencial Git local, sin mostrarla."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request
from zipfile import ZipFile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from servicios.instalador import leer_paquete, sha256


def main():
    p = argparse.ArgumentParser()
    p.add_argument('version')
    p.add_argument('zip', type=Path)
    p.add_argument('commit')
    args = p.parse_args()
    with ZipFile(args.zip) as z:
        manifest, _ = leer_paquete(z)
        assert manifest['version'] == args.version
        assert z.testzip() is None
    credencial = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                                text=True, capture_output=True, check=True).stdout
    cred = dict(line.split('=', 1) for line in credencial.splitlines() if '=' in line)
    headers = {'Authorization': 'Bearer ' + cred['password'], 'User-Agent': 'Fenix-release', 'Accept': 'application/vnd.github+json'}
    api = 'https://api.github.com/repos/TheOldARK/Proyecto-Fenix/releases'
    def request(url, body=None, method=None):
        data = json.dumps(body).encode() if body is not None else None
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=60) as r:
            return json.load(r)
    try:
        release = request(api + '/tags/v' + args.version)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        notas = ('Dummy funcionalmente equivalente a 1.0.8 para comprobar la actualización automática.' if args.version.endswith('.1') else
                 'Instalador independiente, soporte de rutas largas de Windows, verificación SHA-256 de todos los archivos, recuperación compatible y rollback con diagnóstico real de Qt y Chromium. Instalar esta versión manualmente una vez para sustituir el actualizador antiguo.')
        release = request(api, {'tag_name': 'v' + args.version, 'target_commitish': args.commit,
                               'name': 'Fénix ' + args.version, 'body': notas, 'draft': True, 'prerelease': False})
    nombre = f'Fenix-{args.version}-windows-x64.zip'
    digest = sha256(args.zip)
    asset = next((a for a in release.get('assets', []) if a['name'] == nombre), None)
    if asset:
        assert asset.get('digest') == 'sha256:' + digest, 'Ya existe un asset distinto; no reemplazar automáticamente.'
    else:
        conexion = http.client.HTTPSConnection('uploads.github.com', timeout=300)
        conexion.putrequest('POST', f"/repos/TheOldARK/Proyecto-Fenix/releases/{release['id']}/assets?name={nombre}")
        for k, v in headers.items():
            conexion.putheader(k, v)
        conexion.putheader('Content-Type', 'application/zip')
        conexion.putheader('Content-Length', str(args.zip.stat().st_size))
        conexion.endheaders()
        with args.zip.open('rb') as f:
            while bloque := f.read(1024 * 1024):
                conexion.send(bloque)
        respuesta = conexion.getresponse()
        asset = json.loads(respuesta.read())
        assert respuesta.status == 201, 'GitHub no aceptó el paquete: ' + str(respuesta.status)
    assert asset['size'] == args.zip.stat().st_size
    assert asset.get('digest') == 'sha256:' + digest, 'La huella de GitHub no coincide.'
    request(api + '/' + str(release['id']), {'draft': False, 'make_latest': 'true'}, 'PATCH')
    print(json.dumps({'url': asset['browser_download_url'], 'sha256': digest, 'bytes': asset['size']}))


if __name__ == '__main__':
    main()
