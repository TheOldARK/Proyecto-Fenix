import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from servicios import datos_cloudflare


class LibresEleccionCloudflareOpcionalesTests(unittest.TestCase):
    def test_404_de_libres_no_impide_instalar_materias_y_activa_fallback(self):
        codigo_plan = "1102:3068:3534"
        materias = {"materias": [{"codigo": "300100", "nombre": "Cálculo"}]}
        contenido_materias = json.dumps(materias).encode("utf-8")
        manifiesto = {
            "planes": {
                codigo_plan: {
                    "archivos": {
                        "materias": {
                            "ruta": f"planes/{codigo_plan}/materias.json",
                            "sha256": hashlib.sha256(contenido_materias).hexdigest(),
                        },
                        "libres_eleccion": {
                            "ruta": f"planes/{codigo_plan}/libres_eleccion.json",
                            "sha256": "a" * 64,
                        },
                    }
                }
            }
        }

        with tempfile.TemporaryDirectory(prefix="fenix-cf-test-") as carpeta:
            raiz = Path(carpeta)
            destino_materias = raiz / "materias.json"
            destino_libres = raiz / "libres_eleccion.json"
            ruta_manifiesto_local = raiz / "manifest_cloudflare.json"
            datos_temporales = raiz / "datos"

            def descargar(url, destino, timeout=30):
                if url.endswith("/manifest.json"):
                    destino.write_text(json.dumps(manifiesto), encoding="utf-8")
                elif url.endswith("/materias.json"):
                    destino.write_bytes(contenido_materias)
                elif url.endswith("/libres_eleccion.json"):
                    raise datos_cloudflare.DatosNoPublicadosError(
                        f"No se encontró el archivo publicado: {url}"
                    )
                else:
                    self.fail(f"Descarga inesperada: {url}")

            with (
                patch.object(datos_cloudflare, "_descargar", side_effect=descargar),
                patch.object(
                    datos_cloudflare,
                    "DESTINOS",
                    {
                        "materias": destino_materias,
                        "libres_eleccion": destino_libres,
                    },
                ),
                patch.object(datos_cloudflare, "CARPETA_DATOS", datos_temporales),
                patch.object(
                    datos_cloudflare,
                    "ARCHIVO_DATOS_CLOUDFLARE",
                    ruta_manifiesto_local,
                ),
            ):
                resultado = datos_cloudflare.actualizar_desde_cloudflare(
                    codigo_plan=codigo_plan,
                    url_base="https://fenix.test",
                )

            self.assertTrue(destino_materias.is_file())
            self.assertEqual(json.loads(destino_materias.read_text("utf-8")), materias)
            self.assertFalse(destino_libres.exists())
            self.assertNotIn(
                "libres_eleccion",
                resultado["planes"][codigo_plan]["archivos"],
            )
            self.assertTrue(ruta_manifiesto_local.is_file())


if __name__ == "__main__":
    unittest.main()
