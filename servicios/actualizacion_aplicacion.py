"""Actualización de la aplicación desde GitHub Releases.

El catálogo del SIA y la aplicación tienen ciclos de actualización distintos.
Este módulo solo reemplaza los archivos de la instalación; los datos del
estudiante viven en ``%LOCALAPPDATA%\\Fenix`` y no forman parte del ZIP.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.request import Request, urlopen
from zipfile import ZipFile

from configuracion import BASE_DIR, VERSION

try:
    import certifi
except ImportError:  # pragma: no cover - el ejecutable siempre lo incluye
    certifi = None

REPOSITORIO_GITHUB = "TheOldARK/Proyecto-Fenix"
API_RELEASES = f"https://api.github.com/repos/{REPOSITORIO_GITHUB}/releases"
PREFIJO_ASSET = "Fenix-"


def _contexto_tls():
    """Usa una CA empaquetada para no depender del Python del equipo."""
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def _version(valor: str) -> tuple[int, ...]:
    """Convierte versiones beta en una tupla comparable."""
    numeros = []
    for parte in str(valor).lstrip("v").replace("-", ".").split("."):
        digitos = "".join(caracter for caracter in parte if caracter.isdigit())
        numeros.append(int(digitos or 0))
    return tuple(numeros)


def consultar_ultima_version(timeout: int = 15) -> dict:
    solicitud = Request(
        API_RELEASES,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Proyecto-Fenix"},
    )
    with urlopen(solicitud, timeout=timeout, context=_contexto_tls()) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))
    if not isinstance(datos, list) or not datos:
        raise ValueError("El repositorio no tiene Releases publicadas.")
    datos = next((release for release in datos if not release.get("draft")), datos[0])
    etiqueta = str(datos.get("tag_name") or datos.get("name") or "").lstrip("v")
    assets = datos.get("assets") or []
    nombre_asset = f"{PREFIJO_ASSET}{etiqueta}-windows-x64.zip"
    asset = next(
        (item for item in assets if item.get("name") == nombre_asset),
        None,
    )
    if not etiqueta or not asset or not asset.get("browser_download_url"):
        raise ValueError("La Release no contiene un paquete de Windows válido.")
    return {
        "version": etiqueta,
        "asset": nombre_asset,
        "url": asset["browser_download_url"],
        "tamano": asset.get("size"),
        "notas": datos.get("body") or "",
    }


def hay_actualizacion(release: dict) -> bool:
    if _version(release["version"]) <= _version(VERSION):
        return False
    esperado = f"{PREFIJO_ASSET}{release['version']}-windows-x64.zip"
    return release.get("asset") == esperado


def descargar_release(release: dict, destino: Path | None = None, timeout: int = 120) -> Path:
    destino = destino or Path(tempfile.gettempdir()) / f"fenix-{release['version']}.zip"
    temporal = destino.with_suffix(destino.suffix + ".partial")
    solicitud = Request(release["url"], headers={"User-Agent": "Proyecto-Fenix"})
    with urlopen(solicitud, timeout=timeout, context=_contexto_tls()) as respuesta, temporal.open("wb") as archivo:
        shutil.copyfileobj(respuesta, archivo)
    if destino.exists():
        destino.unlink()
    temporal.replace(destino)
    if release.get("sha256"):
        digest = hashlib.sha256(destino.read_bytes()).hexdigest().lower()
        if digest != str(release["sha256"]).lower():
            destino.unlink(missing_ok=True)
            raise ValueError("La descarga no coincide con el SHA-256 publicado.")
    with ZipFile(destino) as paquete:
        nombres = set(paquete.namelist())
        if not any(nombre.endswith("/Fenix.exe") or nombre == "Fenix.exe" for nombre in nombres):
            raise ValueError("El paquete descargado no contiene Fenix.exe.")
        paquete.testzip()
    return destino


def _extraer_seguro(archivo: ZipFile, destino: Path) -> None:
    """Evita que un ZIP alterado escriba fuera del directorio temporal."""
    raiz = destino.resolve()
    for miembro in archivo.infolist():
        salida = (destino / miembro.filename).resolve()
        if salida != raiz and raiz not in salida.parents:
            raise ValueError("El paquete contiene una ruta inválida.")
    archivo.extractall(destino)


def _copiar_auxiliar(origen: Path, destino: Path) -> None:
    """Copia el runtime del auxiliar, esperando cierres tardíos de Chromium."""
    for intento in range(20):
        try:
            shutil.copytree(origen, destino)
            return
        except (FileNotFoundError, PermissionError):
            shutil.rmtree(destino, ignore_errors=True)
            if intento == 19:
                raise
            time.sleep(0.5)


def iniciar_reemplazo(paquete: Path, pid: int, instalacion: Path | None = None) -> None:
    """Inicia el auxiliar y devuelve el control para que la interfaz cierre."""
    instalacion = instalacion or Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False):
        # El ejecutable en uso no puede borrarse en Windows. Se copia junto a
        # _internal y el auxiliar se ejecuta desde esta carpeta temporal.
        auxiliar = Path(tempfile.mkdtemp(prefix="fenix-updater-"))
        shutil.copy2(Path(sys.executable), auxiliar / "Fenix.exe")
        internos = instalacion / "_internal"
        if internos.is_dir():
            _copiar_auxiliar(internos, auxiliar / "_internal")
        comando = [
            str(auxiliar / "Fenix.exe"),
            "--aplicar-actualizacion", str(paquete), str(instalacion), str(pid),
        ]
    else:
        from aplicacion.arranque import comando_fenix

        comando = comando_fenix(
            "--aplicar-actualizacion", str(paquete), str(instalacion), str(pid)
        )
    entorno = os.environ.copy()
    entorno["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    opciones = {"cwd": str(Path(comando[0]).parent), "env": entorno}
    if sys.platform == "win32":
        opciones["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(comando, **opciones)


def _esperar_cierre(pid: int) -> None:
    """Espera al proceso sin usar os.kill, que en Windows puede terminarlo."""
    if pid == os.getpid():
        raise RuntimeError("El actualizador no puede reemplazar su propia instalación.")
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if kernel.WaitForSingleObject(handle, 120000) != 0:
                raise RuntimeError("Fénix sigue abierto. Cierra sus ventanas y vuelve a intentar.")
        finally:
            kernel.CloseHandle(handle)


def _mover_con_reintentos(origen: Path, destino: Path) -> None:
    """Mueve una carpeta completa sin recorrer sus archivos internos."""
    for intento in range(180):
        try:
            origen.rename(destino)
            return
        except OSError as error:
            # Playwright puede cerrar Chromium unos segundos después de que el
            # worker terminó. Reintentar el directorio completo evita tocar
            # archivos individuales mientras Windows los libera.
            if getattr(error, "winerror", None) not in (2, 3, 5, 32, 33) or intento == 179:
                raise
            time.sleep(0.5)


def aplicar_actualizacion(paquete: str, instalacion: str, pid: str) -> int:
    """Instala con intercambio atómico de directorios y rollback seguro."""
    destino = Path(instalacion).resolve()
    if getattr(sys, "frozen", False) and destino in Path(sys.executable).resolve().parents:
        raise RuntimeError("El auxiliar debe ejecutarse fuera de la instalación.")
    bloqueo = destino.parent / f".{destino.name}.actualizacion-en-curso"
    try:
        bloqueo.mkdir()
    except FileExistsError:
        # Otro auxiliar ya está haciendo el intercambio. No iniciar un
        # segundo rollback sobre la misma carpeta.
        return 0
    try:
        _esperar_cierre(int(pid))
    except Exception:
        shutil.rmtree(bloqueo, ignore_errors=True)
        raise
    # Durante un intercambio anterior la carpeta puede estar ausente durante
    # unos milisegundos. Esperar evita convertir esa ventana en un traceback.
    for _ in range(40):
        if destino.is_dir():
            break
        time.sleep(0.5)
    if not destino.is_dir():
        shutil.rmtree(bloqueo, ignore_errors=True)
        raise RuntimeError(
            "No se encontró la carpeta de instalación de Fénix. "
            "Puede que otra actualización ya esté en curso."
        )
    trabajo = Path(tempfile.mkdtemp(prefix=".fenix-update-", dir=destino.parent))
    extraido = trabajo / "extraido"
    extraido.mkdir()
    nuevo = destino.parent / f".{destino.name}.nuevo-{uuid.uuid4().hex}"
    respaldo = destino.parent / f".{destino.name}.respaldo-{uuid.uuid4().hex}"
    intercambio_iniciado = False
    try:
        with ZipFile(paquete) as archivo:
            _extraer_seguro(archivo, extraido)
        raiz = extraido / "Fenix" if (extraido / "Fenix").is_dir() else extraido
        if not (raiz / "Fenix.exe").is_file() or not (raiz / "_internal").is_dir():
            raise ValueError("Paquete incompleto: faltan Fenix.exe o _internal.")
        _mover_con_reintentos(raiz, nuevo)
        _mover_con_reintentos(destino, respaldo)
        intercambio_iniciado = True
        _mover_con_reintentos(nuevo, destino)
        entorno = os.environ.copy()
        entorno["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen([str(destino / "Fenix.exe")], cwd=str(destino), env=entorno)
    except Exception as error:
        errores = []
        if intercambio_iniciado and respaldo.exists():
            try:
                if destino.exists():
                    _mover_con_reintentos(destino, trabajo / "instalacion-fallida")
                _mover_con_reintentos(respaldo, destino)
            except OSError as restauracion:
                errores.append(str(restauracion))
        mensaje = f"No se pudo actualizar: {error}\nRespaldo: {respaldo}\n" + "\n".join(errores)
        (trabajo / "error.txt").write_text(mensaje, encoding="utf-8")
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, mensaje, "Actualización de Fénix", 0x10)
        shutil.rmtree(bloqueo, ignore_errors=True)
        return 1
    shutil.rmtree(trabajo, ignore_errors=True)
    shutil.rmtree(respaldo, ignore_errors=True)
    shutil.rmtree(bloqueo, ignore_errors=True)
    Path(paquete).unlink(missing_ok=True)
    return 0
