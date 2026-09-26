"""Descarga validada y entrega a un instalador independiente de Fénix."""
from __future__ import annotations
import json
import os
import platform
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile
import certifi
from configuracion import VERSION
from servicios.instalador import leer_paquete, ruta_larga, sha256, guardar

API_RELEASES = "https://api.github.com/repos/TheOldARK/Proyecto-Fenix/releases"


def nombre_paquete(version):
    if sys.platform == "darwin":
        arquitectura = platform.machine().lower()
        if arquitectura not in ("arm64", "x86_64"):
            raise ValueError(f"Arquitectura de Mac no compatible: {arquitectura}")
        sufijo = "macos-arm64" if arquitectura == "arm64" else "macos-x64"
    else:
        sufijo = "windows-x64"
    return f"Fenix-{version}-{sufijo}.zip"


def _contexto_tls():
    return ssl.create_default_context(cafile=certifi.where())


def _version(valor):
    partes = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?", str(valor))
    if partes:
        return tuple(int(n or 0) for n in partes.groups())
    if valor == "1.0.7b":
        return (1, 0, 7, 1)
    return (0, 0, 0, 0)


def consultar_ultima_version(timeout=15):
    solicitud = Request(API_RELEASES, headers={"Accept": "application/vnd.github+json", "User-Agent": "Proyecto-Fenix"})
    with urlopen(solicitud, timeout=timeout, context=_contexto_tls()) as respuesta:
        datos = json.load(respuesta)
    candidatos = []
    for release in datos if isinstance(datos, list) else []:
        if release.get("draft") or release.get("prerelease"):
            continue
        version = str(release.get("tag_name", "")).removeprefix("v")
        if _version(version) == (0, 0, 0, 0):
            continue
        nombre = nombre_paquete(version)
        asset = next((a for a in release.get("assets", []) if a.get("name") == nombre), None)
        if asset and asset.get("browser_download_url"):
            digest = asset.get("digest") or ""
            candidatos.append({"version": version, "asset": nombre, "url": asset["browser_download_url"],
                               "tamano": asset.get("size"), "sha256": digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
                               "notas": release.get("body", ""),
                               "instalacion_manual": sys.platform == "darwin"})
    if not candidatos:
        if sys.platform == "darwin":
            return {"sin_paquete_compatible": True, "version": VERSION,
                    "asset": None, "instalacion_manual": True}
        raise ValueError("No hay una versión de Windows completa publicada.")
    return max(candidatos, key=lambda r: _version(r["version"]))


def hay_actualizacion(release):
    return (_version(release["version"]) > _version(VERSION) and
            release.get("asset") == nombre_paquete(release['version']))


def descargar_release(release, destino=None, timeout=120, progreso=None):
    if sys.platform == "darwin":
        raise RuntimeError("En macOS descarga Fenix.app desde el enlace de la actualización.")
    destino = Path(destino) if destino else Path(tempfile.mkdtemp(prefix="fx-download-")) / "paquete.zip"
    temporal = destino.with_suffix(".partial")
    try:
        solicitud = Request(release["url"], headers={"User-Agent": "Proyecto-Fenix"})
        with urlopen(solicitud, timeout=timeout, context=_contexto_tls()) as respuesta, temporal.open("wb") as archivo:
            total = int(respuesta.headers.get("Content-Length") or release.get("tamano") or 0)
            recibidos = 0
            while bloque := respuesta.read(1024 * 1024):
                archivo.write(bloque)
                recibidos += len(bloque)
                if progreso is not None:
                    progreso(recibidos, total)
        if release.get("tamano") and temporal.stat().st_size != release["tamano"]:
            raise ValueError("La descarga está incompleta.")
        if release.get("sha256") and sha256(temporal) != release["sha256"].lower():
            raise ValueError("La descarga no coincide con el SHA-256 publicado.")
        with ZipFile(temporal) as archivo:
            manifiesto, _ = leer_paquete(archivo)
            if manifiesto["version"] != release["version"]:
                raise ValueError("La versión del paquete no coincide con la publicada.")
            corrupto = archivo.testzip()
            if corrupto:
                raise ValueError(f"ZIP dañado: {corrupto}")
        temporal.replace(destino)
        return destino
    finally:
        temporal.unlink(missing_ok=True)


def iniciar_reemplazo(paquete, pid, instalacion=None):
    if sys.platform == "darwin":
        raise RuntimeError("Cierra Fénix y sustituye Fenix.app en Aplicaciones para actualizar macOS.")
    instalacion = Path(instalacion or Path(sys.executable).parent).resolve()
    auxiliar = Path(tempfile.mkdtemp(prefix="fx-updater-"))
    if getattr(sys, "frozen", False):
        # Solo el instalador y su pequeño runtime; nunca copiar Chromium/Qt.
        shutil.copytree(ruta_larga(instalacion / "updater"), ruta_larga(auxiliar / "bin"))
        comando = [str(auxiliar / "bin" / "FenixUpdater.exe")]
    else:
        comando = [sys.executable, str(Path(__file__).with_name("instalador.py"))]
    job = {"paquete": str(Path(paquete).resolve()), "instalacion": str(instalacion), "pid": pid,
           "ready": str(auxiliar / "ready.json"), "resultado": str(auxiliar / "resultado.json")}
    guardar(auxiliar / "job.json", job)
    entorno = os.environ.copy()
    entorno["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    opciones = {"env": entorno, "cwd": str(auxiliar)}
    if os.name == "nt":
        opciones["creationflags"] = subprocess.CREATE_NO_WINDOW
    proceso = subprocess.Popen([*comando, str(auxiliar / "job.json")], **opciones)
    limite = time.monotonic() + 15
    while time.monotonic() < limite:
        if Path(job["ready"]).exists():
            return job
        if proceso.poll() is not None:
            detalle = json.loads(Path(job["resultado"]).read_text(encoding="utf-8")) if Path(job["resultado"]).exists() else {}
            raise RuntimeError(detalle.get("error", "El instalador no pudo arrancar; Fénix continúa abierto."))
        time.sleep(0.1)
    proceso.terminate()
    proceso.wait(timeout=10)
    raise RuntimeError("El instalador no confirmó su arranque; Fénix continúa abierto.")
