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


def iniciar_reemplazo(paquete: Path, pid: int, instalacion: Path | None = None) -> None:
    """Inicia el auxiliar y devuelve el control para que la interfaz cierre."""
    instalacion = instalacion or Path(sys.executable).resolve().parent
    from aplicacion.arranque import comando_fenix

    comando = comando_fenix(
        "--aplicar-actualizacion", str(paquete), str(instalacion), str(pid)
    )
    opciones = {"cwd": str(BASE_DIR)}
    if sys.platform == "win32":
        opciones["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(comando, **opciones)


def aplicar_actualizacion(paquete: str, instalacion: str, pid: str) -> int:
    """Reemplaza la instalación con copia de seguridad y rollback automático."""
    if int(pid) != os.getpid():
        for _ in range(120):
            try:
                os.kill(int(pid), 0)
            except OSError:
                break
            time.sleep(0.5)
    destino = Path(instalacion).resolve()
    temporal = Path(tempfile.mkdtemp(prefix="fenix-update-"))
    respaldo = Path(tempfile.mkdtemp(prefix="fenix-rollback-"))
    reemplazados = []
    try:
        with ZipFile(paquete) as archivo:
            _extraer_seguro(archivo, temporal)
        raiz = temporal / "Fenix"
        if not raiz.is_dir():
            raiz = temporal
        # La copia se hace antes de tocar la instalación. Así un fallo por
        # permisos, antivirus o un archivo bloqueado no deja Fénix incompleto.
        for actual in destino.iterdir():
            copia = respaldo / actual.name
            if actual.is_dir():
                shutil.copytree(actual, copia)
            else:
                shutil.copy2(actual, copia)
        for origen in raiz.iterdir():
            destino_origen = destino / origen.name
            if origen.is_dir() and destino_origen.exists():
                shutil.rmtree(destino_origen)
            elif destino_origen.exists():
                destino_origen.unlink()
            shutil.move(str(origen), str(destino_origen))
            reemplazados.append(destino_origen)
        ejecutable = destino / "Fenix.exe"
        if ejecutable.exists():
            subprocess.Popen([str(ejecutable)], cwd=str(destino))
        return 0
    except Exception:
        # Restaurar primero los elementos que la actualización eliminó y luego
        # devolver cualquier archivo que faltara en el destino original.
        for elemento in reemplazados:
            if elemento.is_dir():
                shutil.rmtree(elemento, ignore_errors=True)
            else:
                elemento.unlink(missing_ok=True)
        for copia in respaldo.iterdir():
            destino_copia = destino / copia.name
            if copia.is_dir():
                shutil.copytree(copia, destino_copia, dirs_exist_ok=True)
            else:
                shutil.copy2(copia, destino_copia)
        raise
    finally:
        shutil.rmtree(temporal, ignore_errors=True)
        shutil.rmtree(respaldo, ignore_errors=True)
        Path(paquete).unlink(missing_ok=True)
