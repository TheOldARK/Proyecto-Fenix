"""Publica snapshots académicos de Fénix en Cloudflare R2.

Las credenciales se leen exclusivamente desde:
  CLOUDFLARE_R2_ENDPOINT, CLOUDFLARE_R2_ACCESS_KEY,
  CLOUDFLARE_R2_SECRET_KEY y CLOUDFLARE_R2_BUCKET.

No publica estudiante.json ni ningún archivo personal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import certifi

from configuracion import URL_DATOS_CLOUDFLARE


ARCHIVOS_PUBLICOS = {
    "materias": "materias.json",
    "oferta": "oferta.json",
    "libres_eleccion": "libres_eleccion.json",
}


@contextmanager
def _bloquear_manifiesto_compartido():
    """Evita que publicadores simultáneos pierdan entradas del manifiesto."""
    personalizada = os.environ.get("FENIX_PUBLICADOR_MANIFEST_LOCK", "").strip()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Fenix"
    ruta = Path(personalizada).expanduser() if personalizada else base / "manifest-publicacion.lock"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a+b") as archivo:
        archivo.seek(0, os.SEEK_END)
        if archivo.tell() == 0:
            archivo.write(b" ")
            archivo.flush()
        inicio = time.monotonic()
        while True:
            try:
                archivo.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() - inicio >= 300:
                    raise TimeoutError("Otro publicador mantiene ocupado el manifiesto de Cloudflare.")
                time.sleep(0.25)
        try:
            yield
        finally:
            archivo.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)


def sha256(ruta: Path) -> str:
    resumen = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


class _ProgresoSubida:
    """Actualiza el estado aislado del publicador mientras boto3 transfiere."""
    def __init__(self, ruta: Path, clave: str, indice: int, total: int):
        self.ruta = ruta
        self.clave = clave
        self.indice = indice
        self.total = max(1, total)
        self.tamano = max(1, ruta.stat().st_size)
        self.transferido = 0
        self.ultimo_reporte = 0.0
        self.lock = threading.Lock()

    def __call__(self, cantidad: int):
        with self.lock:
            self.transferido += cantidad
            ahora = time.monotonic()
            if ahora - self.ultimo_reporte < 0.4 and self.transferido < self.tamano:
                return
            self.ultimo_reporte = ahora
            fraccion = min(1.0, self.transferido / self.tamano)
            avance = 90 + round(9 * ((self.indice - 1 + fraccion) / self.total))
            try:
                from infraestructura.almacenamiento.estado_actualizacion import guardar_estado

                guardar_estado(
                    "actualizando",
                    f"Subiendo archivo {self.indice}/{self.total} a Cloudflare: {Path(self.clave).name} "
                    f"({fraccion:.0%})…",
                    avance,
                    fase="publicacion_cloudflare",
                )
            except OSError:
                # Un problema al escribir el indicador no debe detener la subida.
                pass


def _manifiesto_publicado_existente() -> dict | None:
    """Lee el índice actual para que una publicación manual sea incremental."""
    solicitud = Request(
        f"{URL_DATOS_CLOUDFLARE.rstrip('/')}/manifest.json",
        headers={"User-Agent": "Proyecto-Fenix-Publicador", "Accept": "application/json"},
    )
    try:
        contexto_tls = ssl.create_default_context(cafile=certifi.where())
        with urlopen(solicitud, timeout=15, context=contexto_tls) as respuesta:
            manifiesto = json.loads(respuesta.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError(f"No se pudo leer el manifiesto actual de Cloudflare: HTTP {error.code}.") from error
    except Exception as error:
        raise RuntimeError(f"No se pudo conservar el catálogo actual de Cloudflare: {error}") from error
    if not isinstance(manifiesto, dict) or not isinstance(manifiesto.get("planes"), dict):
        raise RuntimeError("El manifiesto existente de Cloudflare tiene un formato no válido; se cancela la publicación manual para no perder carreras.")
    return manifiesto


def fusionar_manifiesto_publicacion(
    anterior: dict | None,
    sedes_nuevas: dict,
    planes_nuevos: dict,
    sede: str = "1102",
    datos_compartidos_nuevos: dict | None = None,
) -> dict:
    """Mezcla planes sin eliminar entradas publicadas por otros procesos."""
    base = json.loads(json.dumps(anterior or {}, ensure_ascii=False))
    sedes = base.get("sedes") if isinstance(base.get("sedes"), dict) else {}
    planes = base.get("planes") if isinstance(base.get("planes"), dict) else {}
    for sede_codigo, sede_nueva in sedes_nuevas.items():
        sede_destino = sedes.setdefault(
            str(sede_codigo),
            {
                "codigo": str(sede_codigo),
                "nombre": sede_nueva.get("nombre", ""),
                "facultades": {},
            },
        )
        if not isinstance(sede_destino.get("facultades"), dict):
            sede_destino["facultades"] = {}
        for facultad_codigo, facultad_nueva in sede_nueva.get("facultades", {}).items():
            facultad_destino = sede_destino["facultades"].setdefault(
                str(facultad_codigo),
                {
                    "codigo": str(facultad_codigo),
                    "nombre": facultad_nueva.get("nombre", ""),
                    "planes": [],
                },
            )
            if not isinstance(facultad_destino, dict):
                facultad_destino = {"codigo": str(facultad_codigo), "planes": []}
                sede_destino["facultades"][str(facultad_codigo)] = facultad_destino
            codigos = list(map(str, facultad_destino.get("planes", [])))
            for codigo_plan in facultad_nueva.get("planes", []):
                if str(codigo_plan) not in codigos:
                    codigos.append(str(codigo_plan))
            facultad_destino["planes"] = codigos
    for codigo_plan, registro_nuevo in planes_nuevos.items():
        registro_anterior = planes.get(str(codigo_plan), {})
        if not isinstance(registro_anterior, dict):
            registro_anterior = {}
        nuevo = dict(registro_anterior)
        nuevo.update(registro_nuevo)
        archivos = dict(registro_anterior.get("archivos", {}))
        archivos.update(registro_nuevo.get("archivos", {}))
        if archivos:
            nuevo["archivos"] = archivos
        if "plan" not in registro_nuevo and "plan" in registro_anterior:
            nuevo["plan"] = registro_anterior["plan"]
        planes[str(codigo_plan)] = nuevo
    datos_compartidos = base.get("datos_compartidos")
    if not isinstance(datos_compartidos, dict):
        datos_compartidos = {}
    datos_compartidos.update(datos_compartidos_nuevos or {})
    base.update({
        "esquema": 3,
        "version_datos": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sede": str(sede),
        "sedes": sedes,
        "planes": planes,
        "datos_compartidos": datos_compartidos,
    })
    return base


def publicar_libres_eleccion_sede(
    ruta_local: Path,
    sede: str = "1102",
    simulacion: bool = False,
) -> dict:
    """Publica el catálogo de Libre Elección compartido por toda una sede."""
    ruta_local = Path(ruta_local)
    validar_json(ruta_local)
    ruta_remota = f"sedes/{sede}/compartido/libres_eleccion_sede.json"
    info = {
        "ruta": ruta_remota,
        "sha256": sha256(ruta_local),
        "tamano": ruta_local.stat().st_size,
    }
    if simulacion:
        return fusionar_manifiesto_publicacion(
            None, {}, {}, sede,
            {"libres_eleccion_sede": info},
        )

    endpoint = os.environ.get("CLOUDFLARE_R2_ENDPOINT", "").strip()
    access_key = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("CLOUDFLARE_R2_SECRET_KEY", "").strip()
    bucket = os.environ.get("CLOUDFLARE_R2_BUCKET", "fenix-datos").strip()
    if not all((endpoint, access_key, secret_key, bucket)):
        raise RuntimeError("Faltan credenciales R2 en variables de entorno.")

    import boto3

    cliente = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    cliente.upload_file(
        str(ruta_local), bucket, ruta_remota,
        ExtraArgs={
            "ContentType": "application/json",
            "CacheControl": "public, max-age=60",
        },
        Callback=_ProgresoSubida(ruta_local, ruta_remota, 1, 1),
    )
    print(f"Publicado: {ruta_remota}")

    with _bloquear_manifiesto_compartido():
        anterior = _manifiesto_publicado_existente()
        manifest = fusionar_manifiesto_publicacion(
            anterior,
            {},
            {},
            sede,
            {"libres_eleccion_sede": info},
        )
        with tempfile.TemporaryDirectory(prefix="fenix-manifest-") as temporal:
            ruta_manifest = Path(temporal) / "manifest.json"
            ruta_manifest.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            cliente.upload_file(
                str(ruta_manifest), bucket, "manifest.json",
                ExtraArgs={"ContentType": "application/json", "CacheControl": "no-cache"},
            )
    print("Publicado: manifest.json (catálogo compartido de sede)")
    return manifest


def validar_json(ruta: Path) -> None:
    with ruta.open("r", encoding="utf-8") as archivo:
        json.load(archivo)


def construir_snapshot(origen: Path, sede: str) -> tuple[Path, dict]:
    temporal = Path(tempfile.mkdtemp(prefix="fenix-snapshot-"))
    archivos = {}
    for clave, nombre in ARCHIVOS_PUBLICOS.items():
        ruta = origen / nombre
        if not ruta.is_file():
            if clave in {"materias", "oferta", "libres_eleccion"}:
                raise FileNotFoundError(f"Falta el archivo académico requerido: {ruta}")
            continue
        validar_json(ruta)
        destino = temporal / nombre
        destino.write_bytes(ruta.read_bytes())
        archivos[clave] = {
            "ruta": f"sedes/{sede}/compartido/{nombre}",
            "sha256": sha256(destino),
            "tamano": destino.stat().st_size,
        }
    manifest = {
        "esquema": 3,
        "version_datos": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sede": sede,
        "archivos": archivos,
    }
    manifiesto = temporal / "manifest.json"
    manifiesto.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return temporal, manifest


def publicar(origen: Path, sede: str = "1102", simulacion: bool = False) -> None:
    endpoint = os.environ.get("CLOUDFLARE_R2_ENDPOINT", "").strip()
    access_key = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("CLOUDFLARE_R2_SECRET_KEY", "").strip()
    bucket = os.environ.get("CLOUDFLARE_R2_BUCKET", "fenix-datos").strip()
    if not simulacion and not all((endpoint, access_key, secret_key, bucket)):
        raise RuntimeError("Faltan credenciales R2 en variables de entorno.")

    temporal, manifest = construir_snapshot(origen, sede)
    try:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        if simulacion:
            print(f"Simulación completada. Archivos preparados en: {temporal}")
            return
        import boto3

        cliente = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        # Primero subimos datos versionados; el manifiesto se publica al final
        # para que los clientes nunca vean una referencia a archivos ausentes.
        for clave, info in manifest["archivos"].items():
            nombre = Path(info["ruta"]).name
            cliente.upload_file(str(temporal / nombre), bucket, info["ruta"], ExtraArgs={"ContentType": "application/json", "CacheControl": "public, max-age=60"})
            print(f"Publicado: {info['ruta']}")
        cliente.upload_file(str(temporal / "manifest.json"), bucket, "manifest.json", ExtraArgs={"ContentType": "application/json", "CacheControl": "no-cache"})
        print("Publicado: manifest.json")
    finally:
        for archivo in temporal.glob("*"):
            archivo.unlink(missing_ok=True)
        temporal.rmdir()


def _publicar_planes_impl(
    snapshots: dict[str, Path],
    sede: str = "1102",
    simulacion: bool = False,
    metadatos_planes: dict[str, dict] | None = None,
    preservar_existentes: bool = False,
) -> dict:
    """Publica datos por sede/facultad/plan en rutas estables, sin periodo."""
    endpoint = os.environ.get("CLOUDFLARE_R2_ENDPOINT", "").strip()
    access_key = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("CLOUDFLARE_R2_SECRET_KEY", "").strip()
    bucket = os.environ.get("CLOUDFLARE_R2_BUCKET", "fenix-datos").strip()
    if not simulacion and not all((endpoint, access_key, secret_key, bucket)):
        raise RuntimeError("Faltan credenciales R2 en variables de entorno.")
    if not snapshots:
        raise RuntimeError("No hay planes preparados para publicar.")
    sedes_nuevas = {}
    planes_nuevos = {}
    subidas: list[tuple[Path, str]] = []
    for codigo_plan, origen in sorted(snapshots.items()):
        slug = str(codigo_plan).replace(":", "-").replace("/", "-")
        metadatos = (metadatos_planes or {}).get(str(codigo_plan))
        metadatos = metadatos if isinstance(metadatos, dict) else {}
        sede_plan = str(metadatos.get("sede_codigo") or sede)
        facultad_plan = str(metadatos.get("facultad_codigo") or "sin-facultad")
        archivos = {}
        for clave, nombre in ARCHIVOS_PUBLICOS.items():
            ruta = Path(origen) / nombre
            if not ruta.is_file():
                continue
            validar_json(ruta)
            ruta_remota = (
                f"sedes/{sede_plan}/facultades/{facultad_plan}/"
                f"planes/{slug}/{nombre}"
            )
            archivos[clave] = {
                "ruta": ruta_remota,
                "sha256": sha256(ruta),
                "tamano": ruta.stat().st_size,
            }
            subidas.append((ruta, ruta_remota))
        if not archivos:
            raise FileNotFoundError(
                f"No hay archivos académicos para publicar en el plan {codigo_plan}."
            )
        registro_plan = {"archivos": archivos}
        if metadatos:
            registro_plan["plan"] = metadatos
        sede_indice = sedes_nuevas.setdefault(
            sede_plan,
            {
                "codigo": sede_plan,
                "nombre": str(metadatos.get("sede_nombre") or ""),
                "facultades": {},
            },
        )
        facultad_indice = sede_indice["facultades"].setdefault(
            facultad_plan,
            {
                "codigo": facultad_plan,
                "nombre": str(metadatos.get("facultad_nombre") or ""),
                "planes": [],
            },
        )
        if str(codigo_plan) not in facultad_indice["planes"]:
            facultad_indice["planes"].append(str(codigo_plan))
        planes_nuevos[str(codigo_plan)] = registro_plan

    if simulacion:
        return {
            "esquema": 3,
            "version_datos": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "sede": sede,
            "sedes": sedes_nuevas,
            "planes": planes_nuevos,
        }

    import boto3

    cliente = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    for indice, (ruta_local, ruta_remota) in enumerate(subidas, start=1):
        cliente.upload_file(
            str(ruta_local),
            bucket,
            ruta_remota,
            ExtraArgs={
                "ContentType": "application/json",
                "CacheControl": "public, max-age=60",
            },
            Callback=_ProgresoSubida(ruta_local, ruta_remota, indice, len(subidas)),
        )
        print(f"Publicado: {ruta_remota}")

    # Las subidas de archivos académicos pueden ocurrir a la vez desde varios
    # publicadores. Solo se serializa la mezcla y escritura del manifiesto.
    with _bloquear_manifiesto_compartido():
        anterior = _manifiesto_publicado_existente()
        manifest = fusionar_manifiesto_publicacion(
            anterior, sedes_nuevas, planes_nuevos, sede
        )
        total_facultades = sum(
            len(sede_info.get("facultades", {}))
            for sede_info in manifest["sedes"].values()
        )
        print(
            f"Manifiesto con {len(manifest['planes'])} planes en "
            f"{total_facultades} facultad(es)."
        )
        with tempfile.TemporaryDirectory(prefix="fenix-manifest-") as temporal:
            ruta_manifest = Path(temporal) / "manifest.json"
            ruta_manifest.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            cliente.upload_file(
                str(ruta_manifest),
                bucket,
                "manifest.json",
                ExtraArgs={"ContentType": "application/json", "CacheControl": "no-cache"},
            )
    print("Publicado: manifest.json")
    return manifest


def publicar_planes(
    snapshots: dict[str, Path],
    sede: str = "1102",
    simulacion: bool = False,
    metadatos_planes: dict[str, dict] | None = None,
    preservar_existentes: bool = False,
) -> dict:
    """Sube archivos sin serializarlos y mezcla el manifiesto bajo un lock breve."""
    if simulacion:
        return _publicar_planes_impl(
            snapshots, sede, simulacion, metadatos_planes, preservar_existentes
        )
    return _publicar_planes_impl(
        snapshots, sede, simulacion, metadatos_planes, preservar_existentes
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Publica datos académicos de Fénix en Cloudflare R2")
    parser.add_argument("--datos", type=Path, default=Path(os.environ.get("FENIX_DATA_DIR", "datos")))
    parser.add_argument("--sede", default="1102", help="Código de sede; por defecto Medellín")
    parser.add_argument("--simular", action="store_true", help="Valida y genera el manifiesto sin subir")
    args = parser.parse_args()
    publicar(args.datos.expanduser().resolve(), args.sede, args.simular)


if __name__ == "__main__":
    main()
