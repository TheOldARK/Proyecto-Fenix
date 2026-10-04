import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFrame, QWidget

from aplicacion.interfaz import (
    COLOR_VERDE, CapaConexionesPlan, VentanaPlanEstudios,
    _base_punta_flecha, _crear_ruta_punta_flecha,
    conexiones_entre_semestres_adyacentes,
)


class ConexionesMiPlanTests(unittest.TestCase):
    def test_semestres_tienen_once_pixeles_entre_columnas(self):
        app = QApplication.instance() or QApplication([])
        seccion = VentanaPlanEstudios._crear_seccion(
            object(), "MALLA CURRICULAR", "", {1: [], 2: []}, 2, set(), set()
        )
        seccion.show()
        app.processEvents()
        columnas = seccion.findChildren(QFrame, "columnaSemestre")
        self.assertEqual(len(columnas), 2)
        self.assertEqual(
            columnas[1].x() - (columnas[0].x() + columnas[0].width()), 11
        )
        seccion.close()

    def test_conexiones_se_dibujan_en_verde(self):
        app = QApplication.instance() or QApplication([])
        raiz = QWidget()
        raiz.resize(300, 180)
        primera = QWidget(raiz)
        primera.setGeometry(10, 10, 90, 160)
        segunda = QWidget(raiz)
        segunda.setGeometry(180, 10, 90, 160)
        origen = QWidget(primera)
        origen.setGeometry(10, 20, 60, 30)
        origen.setProperty("codigoMateriaPlan", "origen-a")
        otro_origen = QWidget(primera)
        otro_origen.setGeometry(10, 100, 60, 30)
        otro_origen.setProperty("codigoMateriaPlan", "origen-b")
        destino = QWidget(segunda)
        destino.setGeometry(10, 20, 60, 30)
        otro_destino = QWidget(segunda)
        otro_destino.setGeometry(10, 100, 60, 30)
        capa = CapaConexionesPlan(raiz)
        capa.resize(300, 180)
        raiz.show()
        capa.show()
        capa.raise_()
        capa.establecer_conexiones([
            (origen, destino, "M"),
            (otro_origen, otro_destino, "M"),
        ])
        app.processEvents()
        imagen = capa.grab().toImage()
        verde = COLOR_VERDE.lower()
        self.assertTrue(any(
            imagen.pixelColor(x, y).name().lower() == verde
            for y in range(imagen.height()) for x in range(imagen.width())
        ))
        self.assertFalse(any(
            imagen.pixelColor(x, y).name().lower() == QColor.fromHsv(18, 190, 245).name().lower()
            for y in range(imagen.height()) for x in range(imagen.width())
        ))
        raiz.close()

    def test_puntas_triangulares_quedan_orientadas_hacia_el_destino(self):
        from PySide6.QtCore import QPointF

        derecha = _crear_ruta_punta_flecha(QPointF(100, 20), QPointF(1, 0))
        izquierda = _crear_ruta_punta_flecha(QPointF(100, 20), QPointF(-1, 0))

        self.assertAlmostEqual(derecha.boundingRect().right(), 100)
        self.assertAlmostEqual(derecha.boundingRect().left(), 92)
        self.assertAlmostEqual(izquierda.boundingRect().left(), 100)
        self.assertAlmostEqual(izquierda.boundingRect().right(), 108)
        self.assertTrue(derecha.elementAt(0).isMoveTo())
        self.assertTrue(izquierda.elementAt(0).isMoveTo())
        self.assertEqual(
            _base_punta_flecha(QPointF(100, 20), QPointF(1, 0)), QPointF(92, 20)
        )
        self.assertEqual(
            _base_punta_flecha(QPointF(100, 20), QPointF(-1, 0)), QPointF(108, 20)
        )

    def test_conecta_solo_con_el_semestre_inmediatamente_anterior(self):
        materias = {
            1: [{"codigo": "1"}, {"codigo": "2"}],
            2: [
                {"codigo": "3", "prerrequisitos": [{"codigo": "1", "tipo": "M"}]},
                {"codigo": "4", "prerrequisitos": [{"codigo": "2", "tipo": "Y"}]},
            ],
            3: [
                # El requisito del semestre 1 queda a dos semestres de distancia.
                {"codigo": "5", "prerrequisitos": [{"codigo": "1", "tipo": "M"}]},
                # El requisito del semestre 2 sí es inmediatamente anterior.
                {"codigo": "6", "prerrequisitos": [{"codigo": "3", "tipo": "O"}]},
                # Las conexiones dentro del mismo semestre no se dibujan.
                {"codigo": "7", "prerrequisitos": [{"codigo": "6", "tipo": "Y"}]},
            ],
        }
        tarjetas = {codigo: object() for codigo in "1234567"}

        conexiones = conexiones_entre_semestres_adyacentes(materias, tarjetas, 3)

        self.assertEqual(
            [(materias_destino, tipo) for _, materias_destino, tipo in conexiones],
            [(tarjetas["3"], "M"), (tarjetas["4"], "Y"), (tarjetas["6"], "O")],
        )
        self.assertEqual(
            {(origen, destino) for origen, destino, _ in conexiones},
            {
                (tarjetas["1"], tarjetas["3"]),
                (tarjetas["2"], tarjetas["4"]),
                (tarjetas["3"], tarjetas["6"]),
            },
        )


if __name__ == "__main__":
    unittest.main()
