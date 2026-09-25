import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from herramientas import gestor_launcher


class GestorLauncherTests(unittest.TestCase):
    def test_encuentra_fenix_junto_al_lanzador(self):
        with tempfile.TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            fenix = carpeta / "Fenix.exe"
            fenix.touch()
            self.assertEqual(gestor_launcher._buscar_fenix(carpeta), fenix)

    def test_encuentra_fenix_en_subcarpeta_del_paquete(self):
        with tempfile.TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            fenix = carpeta / "Fenix" / "Fenix.exe"
            fenix.parent.mkdir()
            fenix.touch()
            self.assertEqual(gestor_launcher._buscar_fenix(carpeta), fenix)

    def test_si_falta_fenix_muestra_error_y_termina_sin_stdin(self):
        with tempfile.TemporaryDirectory() as temporal:
            ejecutable = Path(temporal) / "FenixGestor.exe"
            with (
                patch.object(gestor_launcher.sys, "executable", str(ejecutable)),
                patch.object(gestor_launcher, "_mostrar_error") as mostrar,
            ):
                self.assertEqual(gestor_launcher.main(), 2)
            mostrar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
