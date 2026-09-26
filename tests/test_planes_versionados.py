import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from infraestructura.almacenamiento import plan_estudios


class PlanesVersionadosTests(unittest.TestCase):
    def test_incorpora_carreras_nuevas_sin_sobrescribir_el_perfil_existente(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            perfil = raiz / "perfil" / "planes_estudio.json"
            base = raiz / "paquete" / "datos" / "planes_estudio.json"
            perfil.parent.mkdir()
            base.parent.mkdir(parents=True)
            perfil.write_text(
                json.dumps({
                    "planes": {
                        "plan-existente": {
                            "nombre": "Nombre local conservado",
                            "nombres_asignaturas": {"1001": "Materia local"},
                        }
                    }
                }),
                encoding="utf-8",
            )
            base.write_text(
                json.dumps({
                    "planes": {
                        "plan-existente": {
                            "nombre": "Nombre del paquete",
                            "nombres_asignaturas": {"1002": "Materia nueva"},
                        },
                        "plan-nuevo": {"nombre": "Carrera nueva"},
                    }
                }),
                encoding="utf-8",
            )

            with (
                patch.object(plan_estudios, "ARCHIVO_PLANES_ESTUDIO", perfil),
                patch.object(plan_estudios, "CARPETA_DATOS_BASE", base.parent),
            ):
                datos = plan_estudios.cargar_datos_planes()

            self.assertEqual(datos["planes"]["plan-nuevo"]["nombre"], "Carrera nueva")
            self.assertEqual(
                datos["planes"]["plan-existente"]["nombre"], "Nombre local conservado"
            )
            self.assertEqual(
                datos["planes"]["plan-existente"]["nombres_asignaturas"],
                {"1001": "Materia local", "1002": "Materia nueva"},
            )
            # La combinación de lectura no modifica el archivo del perfil.
            guardado = json.loads(perfil.read_text(encoding="utf-8"))
            self.assertNotIn("plan-nuevo", guardado["planes"])


if __name__ == "__main__":
    unittest.main()
