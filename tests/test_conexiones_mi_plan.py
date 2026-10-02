import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QWidget

from aplicacion.interfaz import (
    COLOR_NARANJA_FENIX, CapaConexionesPlan, VentanaPlanEstudios,
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

    def test_conexiones_se_dibujan_con_el_naranja_de_fenix(self):
        app = QApplication.instance() or QApplication([])
        raiz = QWidget()
        raiz.resize(300, 100)
        primera = QWidget(raiz)
        primera.setGeometry(10, 10, 90, 80)
        segunda = QWidget(raiz)
        segunda.setGeometry(180, 10, 90, 80)
        origen = QWidget(primera)
        origen.setGeometry(10, 20, 60, 30)
        destino = QWidget(segunda)
        destino.setGeometry(10, 20, 60, 30)
        capa = CapaConexionesPlan(raiz)
        capa.resize(300, 100)
        raiz.show()
        capa.show()
        capa.raise_()
        capa.establecer_conexiones([(origen, destino, "M")])
        app.processEvents()
        imagen = capa.grab().toImage()
        naranja = COLOR_NARANJA_FENIX.lower()
        self.assertTrue(any(
            imagen.pixelColor(x, y).name().lower() == naranja
            for y in range(imagen.height()) for x in range(imagen.width())
        ))
        raiz.close()

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
