import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from herramientas.supervision_publicadores import supervisar


class SupervisionTests(unittest.TestCase):
    def simular(self, estado=None, resultado=None, **opciones):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            e, r = raiz / "estado.json", raiz / "resultado.json"
            e.write_text(json.dumps(estado or {}), encoding="utf-8")
            r.write_text(json.dumps(resultado or {}), encoding="utf-8")
            reloj = iter(range(100))
            proceso = Mock()
            proceso.poll.return_value = None
            evento = Mock()
            evento.is_set.return_value = opciones.pop("cancelar", False)
            informar = Mock()
            with patch("herramientas.supervision_publicadores.detener_arbol") as cerrar:
                salida = supervisar(proceso, e, r, "nuevo", evento, informar,
                                    sin_avance=4, max_duracion=20, gracia_salida=2,
                                    reloj=lambda: next(reloj), **opciones)
                cerrar.assert_called_once_with(proceso)
            return salida, informar

    def test_sin_avance_termina_en_timeout(self):
        (resultado, _), informar = self.simular(estado={"intento_id": "nuevo", "mensaje": "Worker terminado"})
        self.assertIn("Timeout", resultado["error"])
        informar.assert_called_once()

    def test_resultado_confirmado_no_se_republica_si_el_hijo_no_cierra(self):
        (resultado, aviso), _ = self.simular(resultado={"intento_id": "nuevo", "estado": "completado"})
        self.assertEqual(resultado["estado"], "completado")
        self.assertIn("no cerraba", aviso)

    def test_no_acepta_resultado_de_intento_anterior(self):
        (resultado, _), informar = self.simular(
            estado={"intento_id": "viejo", "mensaje": "100%"},
            resultado={"intento_id": "viejo", "estado": "completado"})
        self.assertEqual(resultado["estado"], "error")
        informar.assert_not_called()

    def test_cancelacion_es_inmediata(self):
        (resultado, _), _ = self.simular(cancelar=True)
        self.assertIn("Cancelado", resultado["error"])

    def test_proceso_real_bloqueado_se_cierra(self):
        with tempfile.TemporaryDirectory() as carpeta:
            proceso = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=os.name != "nt",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                resultado, _ = supervisar(
                    proceso, Path(carpeta) / "estado.json", Path(carpeta) / "resultado.json",
                    "real", threading.Event(), lambda e: None,
                    sin_avance=0.2, intervalo=0.05,
                )
                self.assertIn("Timeout", resultado["error"])
                self.assertIsNotNone(proceso.poll())
            finally:
                if proceso.poll() is None:
                    proceso.kill()
                    proceso.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
