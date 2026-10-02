"""La tipografía de Fénix se carga desde recursos empaquetables."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from aplicacion.interfaz import FUENTE_INTERFAZ, cargar_fuente_interfaz


class FuenteInterfazTests(unittest.TestCase):
    def test_fuente_incluida_se_aplica_sin_cambiar_tamano_base(self):
        app = QApplication.instance() or QApplication([])
        tamano = app.font().pointSize()
        self.assertTrue(cargar_fuente_interfaz(app))
        self.assertEqual(app.font().family(), FUENTE_INTERFAZ)
        self.assertEqual(app.font().pointSize(), tamano)


if __name__ == "__main__":
    unittest.main()
