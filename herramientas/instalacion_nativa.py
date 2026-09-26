"""Instalación descargable para macOS/Linux, independiente del runtime de Fénix."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import ssl
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPSHandler, HTTPRedirectHandler, build_opener
import uuid
import zipfile

import certifi

API = 'https://api.github.com/repos/TheOldARK/Proyecto-Fenix/releases'
PREFIJO_DESCARGA = 'https://github.com/TheOldARK/Proyecto-Fenix/releases/download/'
MAX_EXTRAIDO = 8 * 1024**3


class Cancelado(RuntimeError):
    pass


def comprobar_cancelacion(cancelar):
    if cancelar.is_set():
        raise Cancelado('Instalación cancelada. No se modificó la instalación anterior.')


def plataforma_nativa():
    arquitectura = platform.machine().lower()
    if sys.platform == 'darwin' and arquitectura in ('arm64', 'x86_64'):
        return 'macos-arm64' if arquitectura == 'arm64' else 'macos-x64'
    if sys.platform == 'linux' and arquitectura == 'x86_64':
        return 'linux-x64'
    raise RuntimeError(f'Sistema o arquitectura no compatible: {sys.platform}/{arquitectura}')


def nombre_raiz(sistema):
    return 'Fenix.app' if sistema.startswith('macos-') else 'Fenix'


def ejecutable(destino, sistema):
    return destino / 'Contents/MacOS/Fenix' if sistema.startswith('macos-') else destino / 'Fenix'


def destino_predeterminado(sistema):
    return Path.home() / 'Applications' / nombre_raiz(sistema)


class SoloHTTPS(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise RuntimeError('Se rechazó una redirección sin HTTPS.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def abrir_url(url, timeout=25):
    if urlsplit(url).scheme != 'https':
        raise RuntimeError('La descarga debe utilizar HTTPS.')
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())), SoloHTTPS())
    return opener.open(Request(url, headers={'User-Agent': 'Fenix-Installer-Nativo',
                                           'Accept': 'application/vnd.github+json'}), timeout=timeout)


def seleccionar_release(releases, sistema):
    candidatos = []
    extension = '.zip' if sistema.startswith('macos-') else '.tar.gz'
    for release in releases:
        if release.get('draft') or release.get('prerelease'):
            continue
        version = str(release.get('tag_name', '')).removeprefix('v')
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:\.\d+)?', version):
            continue
        nombre = f'Fenix-{version}-{sistema}{extension}'
        asset = next((a for a in release.get('assets', []) if a.get('name') == nombre), None)
        if not asset:
            continue
        url = asset.get('browser_download_url', '')
        if not url.startswith(PREFIJO_DESCARGA) or not 0 < int(asset.get('size', 0)) <= 4 * 1024**3:
            raise RuntimeError('La publicación contiene una descarga no válida.')
        digest = str(asset.get('digest') or '').removeprefix('sha256:')
        checksum = next((a for a in release.get('assets', []) if a.get('name') == nombre + '.sha256'), {})
        candidatos.append({'version': version, 'nombre': nombre, 'url': url, 'tamano': int(asset['size']),
                           'sha256': digest if re.fullmatch('[0-9a-fA-F]{64}', digest) else None,
                           'checksum_url': checksum.get('browser_download_url')})
    if not candidatos:
        raise RuntimeError('GitHub no contiene una versión estable compatible con este equipo.')
    return max(candidatos, key=lambda r: tuple(map(int, r['version'].split('.'))) + (0,) * (4 - len(r['version'].split('.'))))


def consultar_release(sistema, cancelar):
    releases = []
    for pagina in range(1, 6):
        comprobar_cancelacion(cancelar)
        with abrir_url(f'{API}?per_page=100&page={pagina}') as respuesta:
            lote = json.loads(respuesta.read(10 * 1024**2))
        if not isinstance(lote, list):
            raise RuntimeError('GitHub devolvió un catálogo de versiones no válido.')
        releases.extend(lote)
        if len(lote) < 100:
            break
    release = seleccionar_release(releases, sistema)
    if not release['sha256']:
        url = release['checksum_url'] or ''
        if not url.startswith(PREFIJO_DESCARGA):
            raise RuntimeError('La versión no publica una suma SHA-256; no se instalará sin verificarla.')
        with abrir_url(url) as r:
            partes = r.read(4096).decode('utf-8').strip().split()
        if len(partes) != 2 or partes[1] != release['nombre'] or not re.fullmatch('[0-9a-fA-F]{64}', partes[0]):
            raise RuntimeError('El archivo SHA-256 publicado no es válido.')
        release['sha256'] = partes[0]
    return release


def descargar(release, ruta, cancelar, progreso):
    for intento in range(1, 4):
        comprobar_cancelacion(cancelar)
        digest, recibidos = hashlib.sha256(), 0
        limite = time.monotonic() + 20 * 60
        try:
            with abrir_url(release['url']) as origen, ruta.open('wb') as salida:
                while True:
                    comprobar_cancelacion(cancelar)
                    if time.monotonic() > limite:
                        raise TimeoutError('La descarga superó el tiempo límite.')
                    bloque = origen.read(256 * 1024)
                    if not bloque:
                        break
                    recibidos += len(bloque)
                    if recibidos > release['tamano']:
                        raise RuntimeError('La descarga supera el tamaño publicado.')
                    salida.write(bloque)
                    digest.update(bloque)
                    progreso(f"Descargando Fénix {release['version']} · {recibidos / 1024**2:.1f} / {release['tamano'] / 1024**2:.1f} MB",
                             5 + int(50 * recibidos / release['tamano']), True)
            if recibidos != release['tamano']:
                raise URLError('La descarga quedó incompleta.')
            if digest.hexdigest() != release['sha256'].lower():
                raise RuntimeError('El SHA-256 no coincide. No se instalará este archivo.')
            return
        except (URLError, TimeoutError, ConnectionError) as error:
            if isinstance(error, HTTPError) and error.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f'GitHub rechazó la descarga (HTTP {error.code}). Intenta de nuevo más tarde.') from error
            if intento == 3:
                raise RuntimeError(f'No se pudo completar la descarga tras 3 intentos: {error}') from error
            progreso(f'Descarga interrumpida; reintentando ({intento + 1}/3)…', 5, True)
            cancelar.wait(intento)


def _ruta_segura(nombre, raiz):
    if '\\' in nombre or any(ord(c) < 32 for c in nombre):
        raise RuntimeError('El paquete contiene una ruta no válida.')
    ruta = PurePosixPath(nombre)
    if ruta.is_absolute() or '..' in ruta.parts or not ruta.parts or ruta.parts[0] != raiz:
        raise RuntimeError(f'Ruta fuera de la aplicación: {nombre}')
    return ruta


def extraer(paquete, carpeta, sistema, cancelar, progreso):
    """Archivos primero, enlaces al final: nunca escribir a través de un enlace del paquete."""
    raiz = nombre_raiz(sistema)
    es_zip = sistema.startswith('macos-')
    archivo = zipfile.ZipFile(paquete) if es_zip else tarfile.open(paquete, 'r:gz')
    with archivo:
        entradas, nombres, enlaces = [], set(), set()
        for m in (archivo.infolist() if es_zip else archivo.getmembers()):
            nombre = m.filename if es_zip else m.name
            if es_zip and nombre.startswith('__MACOSX/'):
                continue  # Metadatos Finder; no forman parte del contenido firmado.
            ruta = _ruta_segura(nombre, raiz)
            modo = m.external_attr >> 16 if es_zip else m.mode
            tipo = ('dir' if m.is_dir() else 'sym' if stat.S_ISLNK(modo) else 'file') if es_zip else (
                'dir' if m.isdir() else 'sym' if m.issym() else 'hard' if m.islnk() else 'file' if m.isfile() else 'invalid')
            if tipo == 'invalid' or ruta in nombres:
                raise RuntimeError('El paquete contiene archivos especiales o rutas duplicadas.')
            nombres.add(ruta)
            if tipo in ('sym', 'hard'):
                enlaces.add(ruta)
            tamano = m.file_size if es_zip else m.size
            entradas.append((m, ruta, modo, tipo, tamano))
        total = sum(e[4] for e in entradas)
        if len(entradas) > 100000 or total > MAX_EXTRAIDO:
            raise RuntimeError('El contenido del paquete supera el límite de seguridad.')
        if shutil.disk_usage(carpeta).free < total + 128 * 1024**2:
            raise RuntimeError('No hay espacio suficiente para extraer Fénix en esta unidad.')
        for _, ruta, _, _, _ in entradas:
            if any(p in enlaces for p in ruta.parents):
                raise RuntimeError('El paquete intenta escribir dentro de un enlace simbólico.')
        procesados = 0
        for m, ruta, modo, tipo, tamano in entradas:
            comprobar_cancelacion(cancelar)
            destino = carpeta.joinpath(*ruta.parts)
            if tipo == 'dir':
                destino.mkdir(parents=True, exist_ok=True)
            elif tipo == 'file':
                destino.parent.mkdir(parents=True, exist_ok=True)
                with (archivo.open(m) if es_zip else archivo.extractfile(m)) as origen, destino.open('xb') as salida:
                    while bloque := origen.read(1024 * 1024):
                        comprobar_cancelacion(cancelar)
                        salida.write(bloque)
                        procesados += len(bloque)
                        progreso('Verificando y extrayendo los archivos…', 55 + int(25 * procesados / max(1, total)), True)
                destino.chmod((modo & 0o777) or 0o644)
        for m, ruta, _, tipo, _ in entradas:
            if tipo not in ('sym', 'hard'):
                continue
            comprobar_cancelacion(cancelar)
            destino = carpeta.joinpath(*ruta.parts)
            destino.parent.mkdir(parents=True, exist_ok=True)
            texto = archivo.read(m).decode('utf-8') if es_zip else m.linkname
            if len(texto) > 4096 or PurePosixPath(texto).is_absolute() or '\\' in texto:
                raise RuntimeError('El paquete contiene un enlace no válido.')
            objetivo = (destino.parent / texto) if tipo == 'sym' else (carpeta / texto)
            try:
                objetivo.resolve().relative_to((carpeta / raiz).resolve())
            except (ValueError, RuntimeError) as error:
                raise RuntimeError('Un enlace apunta fuera de la aplicación.') from error
            if tipo == 'sym':
                destino.symlink_to(texto)
            else:
                if not objetivo.is_file() or objetivo.is_symlink():
                    raise RuntimeError('El paquete contiene un enlace duro no válido.')
                os.link(objetivo, destino)
        for ruta in enlaces:
            destino = carpeta.joinpath(*ruta.parts)
            try:
                destino.resolve(strict=True).relative_to((carpeta / raiz).resolve())
            except (ValueError, RuntimeError, OSError) as error:
                raise RuntimeError('El paquete contiene un enlace roto o inseguro.') from error
    return carpeta / raiz


def entorno_externo():
    entorno = os.environ.copy()
    for clave in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
        original = entorno.pop(clave + '_ORIG', None)
        if original:
            entorno[clave] = original
        else:
            entorno.pop(clave, None)
    for clave in ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH'):
        entorno.pop(clave, None)
    entorno['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return entorno


def validar_estructura(carpeta, sistema):
    exe = ejecutable(carpeta, sistema)
    if not exe.is_file() or not os.access(exe, os.X_OK):
        raise RuntimeError('El paquete no contiene el ejecutable Fenix con permiso de ejecución.')
    with exe.open('rb') as f:
        cabecera = f.read(20)
    if sistema == 'linux-x64':
        correcto = len(cabecera) >= 20 and cabecera[:6] == b'\x7fELF\x02\x01' and struct.unpack('<H', cabecera[18:20])[0] == 62
    else:
        correcto = len(cabecera) >= 8 and cabecera[:4] == b'\xcf\xfa\xed\xfe' and struct.unpack('<I', cabecera[4:8])[0] == (
            0x100000c if sistema == 'macos-arm64' else 0x1000007)
    if not correcto:
        raise RuntimeError('El ejecutable no corresponde a la arquitectura de este equipo.')
    if sistema.startswith('macos-'):
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(carpeta)],
                       env=entorno_externo(), check=True, capture_output=True, timeout=90)


def comprobar_cerrado(destino, sistema):
    if not destino.exists():
        return
    if sistema == 'linux-x64':
        for ruta in Path('/proc').glob('[0-9]*/exe'):
            try:
                ruta.resolve(strict=True).relative_to(destino.resolve())
            except (OSError, ValueError, RuntimeError):
                continue
            raise RuntimeError('Fénix sigue abierto en esa carpeta. Ciérralo antes de instalar.')
    else:
        resultado = subprocess.run(['/usr/sbin/lsof', '-t', '--', str(ejecutable(destino, sistema))],
                                   capture_output=True, timeout=15, env=entorno_externo())
        if resultado.returncode == 0 and resultado.stdout.strip():
            raise RuntimeError('Fénix sigue abierto en esa carpeta. Ciérralo antes de instalar.')
        if resultado.returncode not in (0, 1):
            raise RuntimeError('No se pudo comprobar si Fénix está abierto.')


@contextmanager
def bloqueo(destino):
    import fcntl
    ruta = destino.parent / ('.' + destino.name + '.installer.lock')
    descriptor = os.open(ruta, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'w') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Otro instalador está trabajando en esa carpeta.') from error
        yield


def diagnosticar(destino, sistema, version, temporal):
    datos = temporal / 'perfil-diagnostico'
    entorno = entorno_externo()
    entorno.update(FENIX_DATA_DIR=str(datos), QT_QPA_PLATFORM='offscreen')
    resultado = subprocess.run([str(ejecutable(destino, sistema)), '--diagnostico'],
                               cwd=destino.parent, env=entorno, capture_output=True, timeout=120)
    informe = datos / 'logs/diagnostico_instalacion.json'
    if not informe.is_file():
        detalle = (resultado.stderr or resultado.stdout).decode('utf-8', errors='replace')[-2500:]
        raise RuntimeError('Fénix no pudo iniciar su diagnóstico. Revisa las dependencias del sistema.\n' + detalle)
    info = json.loads(informe.read_text(encoding='utf-8'))
    if resultado.returncode or not info.get('correcto') or info.get('version') != version:
        raise RuntimeError('La aplicación instalada no superó la comprobación.\n' + str(info.get('error', 'Versión incorrecta.'))[-3000:])


def sustituir(nuevo, destino, verificar):
    respaldo = None
    if destino.exists():
        respaldo = destino.with_name('.' + destino.name + '-respaldo-' + uuid.uuid4().hex[:10])
        destino.rename(respaldo)
    instalado = False
    try:
        nuevo.rename(destino)
        instalado = True
        verificar()
    except Exception as error:
        try:
            if instalado:
                destino.rename(nuevo)
            if respaldo:
                respaldo.rename(destino)
        except OSError as fallo:
            raise RuntimeError(f'Falló la restauración. No borres el respaldo {respaldo}. Error: {fallo}') from error
        raise
    return respaldo


def crear_acceso_linux(destino):
    xdg = Path(os.environ.get('XDG_DATA_HOME', ''))
    base = xdg if xdg.is_absolute() else Path.home() / '.local/share'
    carpeta = base / 'applications'
    carpeta.mkdir(parents=True, exist_ok=True)
    acceso = carpeta / 'io.github.theoldark.Fenix.desktop'
    if acceso.is_symlink() or (acceso.exists() and 'X-Fenix-Installer=true' not in acceso.read_text(encoding='utf-8')):
        raise RuntimeError('Ya existe un acceso no creado por este instalador; no se reemplazó.')
    ruta = str(destino / 'Fenix')
    if any(ord(c) < 32 for c in ruta):
        raise RuntimeError('La ruta contiene caracteres no válidos para un acceso directo.')
    for anterior, siguiente in [('\\', '\\\\'), ('"', '\\"'), ('`', '\\`'), ('$', '\\$'), ('%', '%%')]:
        ruta = ruta.replace(anterior, siguiente)
    texto = ('[Desktop Entry]\nType=Application\nName=Fénix\n'
             f'Exec="{ruta}"\nIcon={destino / "_internal/recursos/logo.png"}\n'
             'Terminal=false\nCategories=Education;\nX-Fenix-Installer=true\n')
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=carpeta, delete=False) as f:
        f.write(texto)
        temporal = Path(f.name)
    try:
        temporal.chmod(0o644)
        temporal.replace(acceso)
    finally:
        temporal.unlink(missing_ok=True)
    return acceso


def instalar(destino, sistema, cancelar, progreso, acceso=True):
    destino = Path(destino).expanduser().absolute()
    if destino.name != nombre_raiz(sistema) or destino.is_symlink():
        raise RuntimeError('Elige una carpeta de instalación Fenix válida, no un enlace.')
    destino = destino.parent.resolve() / destino.name
    if destino.exists() and (not destino.is_dir() or not ejecutable(destino, sistema).is_file()):
        raise RuntimeError('La carpeta existente no parece una instalación de Fénix; no se modificará.')
    destino.parent.mkdir(parents=True, exist_ok=True)
    with bloqueo(destino):
        comprobar_cerrado(destino, sistema)
        progreso('Comprobando la última versión compatible en GitHub…', 0, True)
        release = consultar_release(sistema, cancelar)
        if shutil.disk_usage(destino.parent).free < release['tamano'] + 128 * 1024**2:
            raise RuntimeError('No hay espacio suficiente para descargar Fénix en esta unidad.')
        with tempfile.TemporaryDirectory(prefix='.fenix-install-', dir=destino.parent) as trabajo:
            temporal = Path(trabajo)
            paquete = temporal / release['nombre']
            descargar(release, paquete, cancelar, progreso)
            extraido = temporal / 'extraido'
            extraido.mkdir()
            nuevo = extraer(paquete, extraido, sistema, cancelar, progreso)
            progreso('Comprobando arquitectura y archivos de la aplicación…', 82, True)
            validar_estructura(nuevo, sistema)
            comprobar_cancelacion(cancelar)
            comprobar_cerrado(destino, sistema)
            progreso('Instalando y comprobando Fénix; no cierres esta ventana…', 88, False)
            respaldo = sustituir(nuevo, destino, lambda: diagnosticar(destino, sistema, release['version'], temporal))
            advertencias = []
            if acceso and sistema == 'linux-x64':
                progreso('Creando el acceso en el menú de aplicaciones…', 97, False)
                try:
                    crear_acceso_linux(destino)
                except Exception as error:
                    advertencias.append(f'Fénix quedó instalado, pero no se pudo crear el acceso: {error}')
        progreso('Instalación terminada.', 100, False)
        return {'destino': str(destino), 'version': release['version'], 'sistema': sistema,
                'respaldo': str(respaldo) if respaldo else None, 'advertencias': advertencias}


def abrir_fenix(destino, sistema):
    destino = Path(destino)
    entorno = entorno_externo()
    if sistema.startswith('macos-'):
        subprocess.run(['/usr/bin/open', '-a', str(destino)], env=entorno, check=True, capture_output=True, timeout=15)
    else:
        proceso = subprocess.Popen([str(ejecutable(destino, sistema))], cwd=destino.parent,
                                   env=entorno, start_new_session=True,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            codigo = proceso.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            return
        if codigo:
            raise RuntimeError(f'Fénix terminó con código {codigo}. Puedes abrirlo desde {destino}.')
