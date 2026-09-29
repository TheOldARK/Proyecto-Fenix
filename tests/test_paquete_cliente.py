"""Evita volver a distribuir herramientas de publicación por accidente."""

import unittest
from pathlib import Path

from servicios.paquete_cliente import validar_archivos_cliente


class PaqueteClienteTests(unittest.TestCase):
    def test_las_tres_construcciones_usan_el_cliente(self):
        raiz = Path(__file__).resolve().parents[1]
        for nombre in ("Fenix.spec", "FenixMac.spec", "FenixLinux.spec"):
            with self.subTest(nombre=nombre):
                contenido = (raiz / nombre).read_text(encoding="utf-8")
                self.assertIn('"cliente_main.py"' if nombre == "Fenix.spec" else "'cliente_main.py'", contenido)
                self.assertNotIn('collect_all(', contenido)

    def test_windows_no_copia_lanzadores_privados(self):
        raiz = Path(__file__).resolve().parents[1]
        contenido = (raiz / "construir_windows.ps1").read_text(encoding="utf-8")
        self.assertNotIn("Publicador.spec", contenido)
        self.assertNotIn("Gestor.spec", contenido)

    def test_acepta_archivos_del_horario(self):
        validar_archivos_cliente([
            "Fenix/Fenix.exe",
            "Fenix/_internal/servicios/datos_cloudflare.pyc",
            "Fenix.app/Contents/Resources/recursos/logo.png",
        ])

    def test_rechaza_publicadores_y_dependencias_privadas(self):
        for nombre in (
            "Fenix/FenixGestor.exe",
            "Fenix/FenixPublicador.exe",
            "Fenix/_internal/herramientas/publicador_worker.pyc",
            "Fenix/_internal/boto3/session.pyc",
            "Fenix/_internal/botocore-1.0.dist-info/METADATA",
        ):
            with self.subTest(nombre=nombre), self.assertRaises(ValueError):
                validar_archivos_cliente([nombre])


if __name__ == "__main__":
    unittest.main()
