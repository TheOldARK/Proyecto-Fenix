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


def sha256(ruta: Path) -> str:
    resumen = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


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


def publicar_planes(
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

    anterior = _manifiesto_publicado_existente() if preservar_existentes and not simulacion else None
    manifest = {
        "esquema": 3,
        "version_datos": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "sede": sede,
        "sedes": anterior.get("sedes", {}) if anterior else {},
        "planes": anterior.get("planes", {}) if anterior else {},
    }
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
                raise FileNotFoundError(
                    f"Falta {nombre} para el plan {codigo_plan}: {ruta}"
                )
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
        registro_plan = {"archivos": archivos}
        if metadatos:
            registro_plan["plan"] = metadatos
        sede_indice = manifest["sedes"].setdefault(
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
        manifest["planes"][str(codigo_plan)] = registro_plan

    total_facultades = sum(
        len(sede_info["facultades"]) for sede_info in manifest["sedes"].values()
    )
    print(
        f"Preparados {len(manifest['planes'])} planes en "
        f"{total_facultades} facultad(es)."
    )
    if simulacion:
        return manifest

    import boto3

    cliente = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    for ruta_local, ruta_remota in subidas:
        cliente.upload_file(
            str(ruta_local),
            bucket,
            ruta_remota,
            ExtraArgs={
                "ContentType": "application/json",
                "CacheControl": "public, max-age=60",
            },
        )
        print(f"Publicado: {ruta_remota}")

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Publica datos académicos de Fénix en Cloudflare R2")
    parser.add_argument("--datos", type=Path, default=Path(os.environ.get("FENIX_DATA_DIR", "datos")))
    parser.add_argument("--sede", default="1102", help="Código de sede; por defecto Medellín")
    parser.add_argument("--simular", action="store_true", help="Valida y genera el manifiesto sin subir")
    args = parser.parse_args()
    publicar(args.datos.expanduser().resolve(), args.sede, args.simular)


if __name__ == "__main__":
    main()
