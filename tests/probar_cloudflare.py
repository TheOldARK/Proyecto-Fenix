"""Pruebas rápidas del flujo de datos publicado."""
from __future__ import annotations

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from servicios.datos_cloudflare import actualizar_desde_cloudflare


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="fenix-prueba-cloudflare-") as carpeta:
        original = __import__("servicios.datos_cloudflare", fromlist=["DESTINOS"])
        destinos = dict(original.DESTINOS)
        datos_originales = original.CARPETA_DATOS
        manifiesto_original = original.ARCHIVO_DATOS_CLOUDFLARE
        original.DESTINOS = {clave: Path(carpeta) / ruta.name for clave, ruta in destinos.items()}
        original.CARPETA_DATOS = Path(carpeta)
        original.ARCHIVO_DATOS_CLOUDFLARE = Path(carpeta) / "manifest_cloudflare.json"
        codigo_plan = "1102:3068:3534"
        manifiesto = actualizar_desde_cloudflare(codigo_plan=codigo_plan)
        assert manifiesto.get("archivos") or manifiesto.get("planes"), "El manifiesto está vacío"
        assert (Path(carpeta) / "materias.json").is_file(), "No se descargaron materias"
        assert (Path(carpeta) / "oferta.json").is_file(), "No se descargó oferta"
        original.DESTINOS = destinos
        original.CARPETA_DATOS = datos_originales
        original.ARCHIVO_DATOS_CLOUDFLARE = manifiesto_original
        print("Cloudflare: OK")


if __name__ == "__main__":
    main()
