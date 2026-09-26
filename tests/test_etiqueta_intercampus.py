import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHBoxLayout, QSplitter, QWidget

from aplicacion.interfaz import BLOQUES_HORARIO, COLOR_AMARILLO, VentanaPrincipal


class EtiquetaIntercampusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_capa_pinta_etiquetas_en_limites_reales_y_admite_varias(self):
        materia_a = {"codigo": "100", "nombre": "Materia A"}
        materia_b = {"codigo": "200", "nombre": "Materia B"}
        grupo_a = {"numero": "1", "horarios": [{
            "dia": "LUNES", "hora_inicio": "14:00", "hora_fin": "16:00",
            "sede": "Minas",
        }]}
        grupo_b = {"numero": "2", "horarios": [{
            "dia": "LUNES", "hora_inicio": "16:00", "hora_fin": "18:00",
            "sede": "Volador",
        }]}
        materia_c = {"codigo": "300", "nombre": "Materia C"}
        materia_d = {"codigo": "400", "nombre": "Materia D"}
        grupo_c = {"numero": "3", "horarios": [{
            "dia": "JUEVES", "hora_inicio": "10:00", "hora_fin": "12:00",
            "sede": "Minas",
        }]}
        grupo_d = {"numero": "4", "horarios": [{
            "dia": "JUEVES", "hora_inicio": "12:00", "hora_fin": "14:00",
            "sede": "Volador",
        }]}
        # Usa el contenedor real del horario, con cabecera, márgenes y scroll,
        # situado a la derecha de una barra lateral como en Fénix.
        ventana = QWidget()
        self.addCleanup(ventana.close)
        propietario = SimpleNamespace(
            mostrar_desglose_creditos=lambda: None,
            mostrar_materias_fuera_horario=lambda: None,
            mostrar_grupos_del_bloque=lambda *args: None,
            ejecutar_accion_materia=lambda *args: None,
            crear_area_desplazable=VentanaPrincipal.crear_area_desplazable,
        )
        layout = QHBoxLayout(ventana)
        divisor = QSplitter()
        divisor.setHandleWidth(1)
        layout.addWidget(divisor)
        lateral = QWidget()
        lateral.setMinimumWidth(245)
        lateral.setMaximumWidth(390)
        divisor.addWidget(lateral)
        desplazamiento = VentanaPrincipal.crear_contenido_horario(propietario)
        divisor.addWidget(desplazamiento)
        divisor.setSizes([300, 980])
        cuadricula = propietario.cuadricula
        ventana.resize(1400, 800)
        cuadricula.actualizar([
            (materia_a, grupo_a), (materia_b, grupo_b),
            (materia_c, grupo_c), (materia_d, grupo_d),
        ])
        ventana.show()
        self.app.processEvents()

        capa = cuadricula.capa_intercampus
        etiquetas = dict(capa.rectangulos_etiquetas())
        self.assertEqual(set(etiquetas), {
            ("LUNES", 16 * 60), ("JUEVES", 12 * 60),
        })
        self.assertTrue(capa.isVisible())
        self.assertEqual(cuadricula.cuadricula.indexOf(capa), -1)
        self.comprobar_centrado(cuadricula)

        # Arrastrar el divisor cambia el ancho de las columnas en tiempo real.
        anchos = []
        for ancho_lateral in (245, 390, 300, 245):
            with self.subTest(ancho_lateral=ancho_lateral):
                divisor.setSizes([ancho_lateral, divisor.width() - ancho_lateral - 1])
                self.app.processEvents()
                self.comprobar_centrado(cuadricula)
                anchos.append(cuadricula.width())
        self.assertGreater(anchos[0], anchos[1])
        self.assertEqual(anchos[0], anchos[-1])

        # Comprueba también cambios de altura y desplazamiento vertical.
        for ancho, alto in ((1500, 1000), (1200, 450)):
            ventana.resize(ancho, alto)
            self.app.processEvents()
            self.comprobar_centrado(cuadricula)
        barra = desplazamiento.verticalScrollBar()
        self.assertGreater(barra.maximum(), 0)
        barra.setValue(barra.maximum())
        self.app.processEvents()
        self.comprobar_centrado(cuadricula)

        cuadricula.actualizar([])
        self.app.processEvents()
        self.assertFalse(capa.rectangulos_etiquetas())

    def comprobar_centrado(self, cuadricula):
        capa = cuadricula.capa_intercampus
        etiquetas = dict(capa.rectangulos_etiquetas())
        imagen = cuadricula.grab().toImage()
        for (dia, hora), rectangulo in etiquetas.items():
            anterior = next((a, b) for a, b in BLOQUES_HORARIO if b * 60 == hora)
            siguiente = next((a, b) for a, b in BLOQUES_HORARIO if a * 60 == hora)
            celda_anterior = cuadricula.celdas_por_bloque[
                (dia, anterior[0], anterior[1] - anterior[0])
            ]
            celda_siguiente = cuadricula.celdas_por_bloque[
                (dia, siguiente[0], siguiente[1] - siguiente[0])
            ]
            # Ambos widgets son hijos de la cuadrícula: sus geometrías ya
            # comparten coordenadas. No reutilizar la conversión bajo prueba.
            self.assertIs(celda_anterior.parentWidget(), cuadricula)
            self.assertIs(celda_siguiente.parentWidget(), cuadricula)
            self.assertIs(capa.parentWidget(), cuadricula)
            inferior = celda_anterior.geometry()
            superior = celda_siguiente.geometry()
            x_esperado = (
                inferior.center().x() + superior.center().x()
            ) / 2 - capa.x()
            y_esperado = (inferior.bottom() + superior.top()) / 2 - capa.y()
            self.assertLessEqual(abs(rectangulo.center().x() - x_esperado), 1)
            self.assertLessEqual(abs(rectangulo.center().y() - y_esperado), 1)
            # La etiqueta realmente se pinta en el límite entre las celdas.
            self.assertEqual(
                imagen.pixelColor(
                    round(rectangulo.left() + capa.x() + 3),
                    round(y_esperado + capa.y()),
                ).name().upper(),
                COLOR_AMARILLO,
            )


if __name__ == "__main__":
    unittest.main()
