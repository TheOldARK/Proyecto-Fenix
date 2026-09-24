"""Descarga y valida el snapshot público de datos de Fénix."""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import certifi

from configuracion import (
    ARCHIVO_CATALOGO_SIA,
    ARCHIVO_CONFIGURACION_LIBRE_ELECCION,
    ARCHIVO_DATOS_CLOUDFLARE,
    ARCHIVO_LIBRES_ELECCION_SEDE,
    ARCHIVO_MATERIAS,
    ARCHIVO_OFERTA,
    ARCHIVO_PLANES_ESTUDIO,
    CARPETA_DATOS,
    URL_DATOS_CLOUDFLARE,
)
from infraestructura.almacenamiento.plan_estudios import (
    cargar_datos_planes,
    guardar_datos_planes,
)


DESTINOS = {
    "materias": ARCHIVO_MATERIAS,
    "oferta": ARCHIVO_OFERTA,
    "libres_eleccion": CARPETA_DATOS / "libres_eleccion.json",
    "catalogo": ARCHIVO_CATALOGO_SIA,
    "planes_estudio": ARCHIVO_PLANES_ESTUDIO,
}


class DatosNoPublicadosError(RuntimeError):
    """El snapshot existe, pero Cloudflare aún no publica este plan."""


def _contexto_tls():
    return ssl.create_default_context(cafile=certifi.where())


def _sha256(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _descargar(url: str, destino: Path, timeout: int = 30) -> None:
    solicitud = Request(url, headers={"User-Agent": "Proyecto-Fenix", "Accept": "application/json"})
    try:
        with urlopen(solicitud, timeout=timeout, context=_contexto_tls()) as respuesta, destino.open("wb") as archivo:
            archivo.write(respuesta.read())
    except HTTPError as error:
        if error.code == 404:
            raise DatosNoPublicadosError(f"No se encontró el archivo publicado: {url}") from error
        raise


def sincronizar_planes_cloudflare(url_base: str | None = None) -> int:
    """Añade al catálogo local los planes publicados en el manifiesto R2."""
    base = (url_base or os.environ.get("FENIX_DATOS_CLOUDFLARE") or URL_DATOS_CLOUDFLARE).rstrip("/")
    temporal = Path(tempfile.mkdtemp(prefix="fenix-planes-cloudflare-"))
    try:
        manifiesto_ruta = temporal / "manifest.json"
        _descargar(f"{base}/manifest.json", manifiesto_ruta, timeout=8)
        manifiesto = json.loads(manifiesto_ruta.read_text(encoding="utf-8"))
        entradas = manifiesto.get("planes")
        if not isinstance(entradas, dict):
            return 0

        documento = cargar_datos_planes()
        planes_locales = documento.setdefault("planes", {})
        actualizados = 0
        for codigo, entrada in entradas.items():
            plan = entrada.get("plan") if isinstance(entrada, dict) else None
            if not isinstance(plan, dict):
                continue
            semestres = plan.get("semestres")
            if not isinstance(semestres, dict):
                continue
            codigo = str(codigo)
            plan_local = dict(plan)
            plan_local["clave"] = codigo
            plan_local.setdefault("codigo", codigo.split(":")[-1])
            planes_locales[codigo] = plan_local
            actualizados += 1
        if actualizados:
            guardar_datos_planes(documento)
        return actualizados
    finally:
        for archivo in temporal.glob("*"):
            archivo.unlink(missing_ok=True)
        temporal.rmdir()


def actualizar_desde_cloudflare(
    codigo_plan: str | None = None,
    url_base: str | None = None,
) -> dict:
    """Descarga un snapshot completo y lo instala atómicamente.

    Devuelve el manifiesto instalado. Cualquier fallo se propaga para que el
    arranque pueda conservar los datos locales y decidir si necesita SIA.
    """
    base = (url_base or os.environ.get("FENIX_DATOS_CLOUDFLARE") or URL_DATOS_CLOUDFLARE).rstrip("/")
    temporal = Path(tempfile.mkdtemp(prefix="fenix-cloudflare-"))
    try:
        manifiesto_ruta = temporal / "manifest.json"
        _descargar(f"{base}/manifest.json", manifiesto_ruta)
        manifiesto = json.loads(manifiesto_ruta.read_text(encoding="utf-8"))
        planes = manifiesto.get("planes")
        plan_no_publicado = False
        if isinstance(planes, dict):
            if not codigo_plan:
                raise ValueError("El manifiesto requiere identificar el plan de estudios.")
            entrada_plan = planes.get(str(codigo_plan))
            if not isinstance(entrada_plan, dict):
                plan_no_publicado = True
                archivos = {}
            else:
                archivos = entrada_plan.get("archivos")
        else:
            # Compatibilidad temporal con los manifiestos de esquema 1.
            archivos = manifiesto.get("archivos")
        if not isinstance(archivos, dict) and not plan_no_publicado:
            raise ValueError("El manifiesto de Cloudflare no contiene archivos válidos.")
        if not isinstance(archivos, dict):
            archivos = {}
        pendientes = []
        archivos_disponibles = dict(archivos)
        for clave, info in archivos.items():
            destino = DESTINOS.get(clave)
            if destino is None or not isinstance(info, dict):
                continue
            ruta = str(info.get("ruta", ""))
            esperado = str(info.get("sha256", "")).lower()
            if not ruta or len(esperado) != 64:
                raise ValueError(f"Entrada inválida en el manifiesto: {clave}")
            descarga = temporal / f"{clave}.json"
            try:
                _descargar(f"{base}/{ruta}", descarga)
            except DatosNoPublicadosError as error:
                if clave != "libres_eleccion":
                    raise
                # Las libres son opcionales en Cloudflare: pueden faltar
                # durante la publicación y el cliente las consulta al SIA.
                # No abortar aquí permite instalar materias/oferta válidas.
                print(
                    ">>> Cloudflare no contiene el archivo de Libre Elección; "
                    f"se consultará en el SIA. ({error})"
                )
                archivos_disponibles.pop(clave, None)
                continue
            if _sha256(descarga).lower() != esperado:
                raise ValueError(f"Hash inválido para {clave}.")
            json.loads(descarga.read_text(encoding="utf-8"))
            pendientes.append((descarga, destino))

        # El arranque usa este manifiesto para distinguir una publicación
        # válida de las libres de una que requiere fallback al SIA.
        if isinstance(planes, dict) and not plan_no_publicado:
            entrada_plan["archivos"] = archivos_disponibles
        elif "archivos" in manifiesto:
            manifiesto["archivos"] = archivos_disponibles

        # El catálogo de libres de sede es compartido y opcional. Si esa
        # publicación falta o está temporalmente dañada, se conserva el resto
        # del plan y el cliente podrá consultar lo faltante en el SIA.
        compartidos = manifiesto.get("datos_compartidos", {})
        libre_sede = (
            compartidos.get("libres_eleccion_sede")
            if isinstance(compartidos, dict) else None
        )
        if isinstance(libre_sede, dict):
            ruta_compartida = str(libre_sede.get("ruta", ""))
            hash_compartido = str(libre_sede.get("sha256", "")).lower()
            if (
                ruta_compartida.startswith("sedes/")
                and ruta_compartida.endswith("/libres_eleccion_sede.json")
                and len(hash_compartido) == 64
            ):
                try:
                    descarga_compartida = temporal / "libres_eleccion_sede.json"
                    _descargar(f"{base}/{ruta_compartida}", descarga_compartida)
                    if _sha256(descarga_compartida).lower() != hash_compartido:
                        raise ValueError("Hash inválido para libres_eleccion_sede.")
                    json.loads(descarga_compartida.read_text(encoding="utf-8"))
                    pendientes.append((descarga_compartida, ARCHIVO_LIBRES_ELECCION_SEDE))
                except Exception as error:
                    print(f">>> No se pudo descargar el catálogo compartido de sede: {error}")
        if not plan_no_publicado and "materias" not in archivos:
            raise ValueError("El manifiesto no contiene materias.")
        CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
        for origen, destino in pendientes:
            destino.parent.mkdir(parents=True, exist_ok=True)
            origen.replace(destino)
        if plan_no_publicado:
            raise DatosNoPublicadosError(
                f"Cloudflare todavía no contiene datos para el plan {codigo_plan}."
            )
        manifiesto_ruta.replace(ARCHIVO_DATOS_CLOUDFLARE)
        return manifiesto
    finally:
        for archivo in temporal.glob("*"):
            archivo.unlink(missing_ok=True)
        temporal.rmdir()
