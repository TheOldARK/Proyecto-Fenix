import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from infraestructura.almacenamiento.json_atomico import guardar_json_atomico, bloquear_json


def escritor(ruta, numero):
    for i in range(20):
        guardar_json_atomico(ruta, {"worker": numero, "paso": i, "texto": "á" * 4000})


class JsonConcurrenteTests(unittest.TestCase):
    def test_varios_procesos_no_corrompen_el_documento(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "estado.json"
            guardar_json_atomico(ruta, {})
            contexto = multiprocessing.get_context("spawn")
            procesos = [contexto.Process(target=escritor, args=(ruta, n)) for n in range(4)]
            try:
                for p in procesos:
                    p.start()
                for p in procesos:
                    p.join(timeout=30)
                    self.assertEqual(p.exitcode, 0)
                datos = json.loads(ruta.read_text(encoding="utf-8"))
                self.assertEqual(datos["paso"], 19)
                self.assertEqual(datos["texto"], "á" * 4000)
                self.assertFalse(list(Path(carpeta).glob("*.tmp")))
            finally:
                for p in procesos:
                    if p.is_alive():
                        p.terminate()
                        p.join(5)

    def test_reintenta_acceso_denegado_transitorio(self):
        import os
        reemplazar = os.replace
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "estado.json"
            with patch("infraestructura.almacenamiento.json_atomico.os.replace",
                       side_effect=[PermissionError("ocupado"), PermissionError("ocupado"), None]) as mock:
                guardar_json_atomico(ruta, {})
                self.assertEqual(mock.call_count, 3)

    def test_no_espera_para_siempre_por_otro_escritor(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "estado.json"
            with bloquear_json(ruta):
                with self.assertRaises(TimeoutError):
                    with bloquear_json(ruta, timeout=0.05):
                        self.fail("No debe obtener el bloqueo")


if __name__ == "__main__":
    unittest.main()
