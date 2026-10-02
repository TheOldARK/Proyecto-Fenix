import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel

from aplicacion.interfaz import TarjetaHorario


class TituloTarjetaHorarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if os.path.exists("C:/Windows/Fonts/segoeui.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")

    def crear_tarjeta(self, nombre):
        tarjeta = TarjetaHorario(
            {"nombre": nombre},
            {"numero": "2", "horarios": [{
                "dia": "JUEVES", "hora_inicio": "06:00",
                "hora_fin": "08:00", "aula": "Virtual",
            }]},
            "#363030", "#F2F2F2", "JUEVES", 6, 2,
        )
        tarjeta.setFont(QFont("Segoe UI", 9))
        self.addCleanup(tarjeta.deleteLater)
        return tarjeta, tarjeta.findChild(QLabel)

    def test_conserva_titulo_completo_y_detalle(self):
        nombre = "Ingles Intensivo B2 (Intensive English B2)"
        tarjeta, etiqueta = self.crear_tarjeta(nombre)
        self.assertEqual(etiqueta.text().splitlines()[0], nombre)
        self.assertIn("G2 · 06:00–08:00", etiqueta.text())
        self.assertTrue(etiqueta.wordWrap())
        self.assertTrue(etiqueta.hasHeightForWidth())
        self.assertEqual(etiqueta.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(tarjeta.layout().contentsMargins().right(), 2)
        self.assertIn("padding: 5px 2px 5px 5px", etiqueta.styleSheet())

        # El espacio solicitado crece al reducir el ancho; no se pierde texto.
        self.assertGreater(etiqueta.heightForWidth(180), etiqueta.heightForWidth(400))
        for ancho in (240, 180, 400):
            for acciones_visibles in (False, True):
                tarjeta.acciones_widget.setVisible(acciones_visibles)
                alto = max(94, tarjeta.layout().totalHeightForWidth(ancho))
                tarjeta.resize(ancho, alto)
                tarjeta.show()
                tarjeta.layout().activate()
                self.app.processEvents()
                self.assertGreaterEqual(
                    etiqueta.height(), etiqueta.heightForWidth(etiqueta.width())
                )
                self.assertTrue(etiqueta.text().startswith(nombre + "\n"))

    def test_nombre_con_signos_no_se_interpreta_como_html(self):
        _, etiqueta = self.crear_tarjeta("Taller <B2> y comunicación")
        self.assertEqual(etiqueta.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("<B2>", etiqueta.text())


if __name__ == "__main__":
    unittest.main()
