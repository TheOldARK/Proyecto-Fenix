import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHBoxLayout, QSplitter, QWidget
from PySide6.QtGui import QHelpEvent, QMouseEvent, QPixmap
from PySide6.QtCore import QEvent, QObject, QPointF, Qt

from aplicacion.interfaz import BLOQUES_HORARIO, COLOR_AMARILLO, RUTA_BUS_INTERCAMPUS, VentanaPrincipal


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
        self.assertFalse(capa.icono_bus.isNull())
        self.assertTrue(capa.icono_bus.hasAlphaChannel())
        self.assertLess(capa.icono_bus.height(), QPixmap(str(RUTA_BUS_INTERCAMPUS)).height())
        etiquetas = dict(capa.rectangulos_etiquetas())
        self.assertEqual(set(etiquetas), {
            ("LUNES", 16 * 60), ("JUEVES", 12 * 60),
        })
        self.assertTrue(capa.isVisible())
        self.assertEqual(cuadricula.cuadricula.indexOf(capa), -1)
        self.comprobar_centrado(cuadricula)
        self.comprobar_aviso(cuadricula)
        self.comprobar_movimiento_sin_parpadeo(cuadricula)

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
        self.assertFalse(capa.aviso.isVisible())

    def comprobar_aviso(self, cuadricula):
        capa = cuadricula.capa_intercampus
        clave = ("LUNES", 16 * 60)
        rectangulo = dict(capa.rectangulos_etiquetas())[clave]
        self.assertIn("#1C1B14", capa.aviso.styleSheet())
        self.assertIn(f"1px solid {COLOR_AMARILLO}", capa.aviso.styleSheet())
        self.assertTrue(capa.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        ancla = capa.mapToGlobal(rectangulo.topRight().toPoint())
        puntos = [rectangulo.center(), rectangulo.topLeft() + QPointF(1, 1),
                  rectangulo.bottomRight() - QPointF(1, 1)]
        anterior = cuadricula.celdas_por_bloque[("LUNES", 14, 2)]
        siguiente = cuadricula.celdas_por_bloque[("LUNES", 16, 2)]
        puntos.extend([
            QPointF(anterior.x() + 8, anterior.y() + anterior.height() - 1),
            QPointF(siguiente.x() + 8, siguiente.y() + 1),
        ])
        posicion = None
        for punto in puntos:
            with self.subTest(punto=punto):
                global_pos = capa.mapToGlobal(punto.toPoint())
                ayuda = QHelpEvent(QEvent.Type.ToolTip, cuadricula.mapFromGlobal(global_pos), global_pos)
                QApplication.sendEvent(cuadricula, ayuda)
                self.app.processEvents()
                self.assertTrue(capa.aviso.isVisible())
                self.assertEqual(capa.aviso.text(), capa.limites[clave])
                disponible = QApplication.screenAt(ancla).availableGeometry()
                x = max(disponible.left(), min(ancla.x(), disponible.right() - capa.aviso.width() + 1))
                y = max(disponible.top(), min(ancla.y() - capa.aviso.height(), disponible.bottom() - capa.aviso.height() + 1))
                self.assertEqual(capa.aviso.x(), x)
                self.assertEqual(capa.aviso.y(), y)
                if posicion is not None:
                    self.assertEqual(capa.aviso.pos(), posicion)
                posicion = capa.aviso.pos()
                render = capa.aviso.grab().toImage()
                self.assertEqual(render.pixelColor(4, render.height() // 2).name().upper(), "#1C1B14")
                self.assertEqual(render.pixelColor(0, render.height() // 2).name().upper(), COLOR_AMARILLO)
        # Cambiar al otro aviso actualiza el contenido, sin fijarlo al anterior.
        otra_clave = ("JUEVES", 12 * 60)
        otro = dict(capa.rectangulos_etiquetas())[otra_clave]
        global_pos = capa.mapToGlobal(otro.center().toPoint())
        QApplication.sendEvent(cuadricula, QHelpEvent(QEvent.Type.ToolTip, cuadricula.mapFromGlobal(global_pos), global_pos))
        self.assertEqual(capa.aviso.text(), capa.limites[otra_clave])
        # Al abandonar líneas y recuadro se oculta, sin capturar los clics.
        fuera = QPointF(cuadricula.celdas_por_bloque[("MARTES", 6, 2)].geometry().center())
        movimiento = QMouseEvent(QEvent.Type.MouseMove, fuera,
            QPointF(cuadricula.mapToGlobal(fuera.toPoint())), Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(cuadricula, movimiento)
        self.assertFalse(capa.aviso.isVisible())

    def comprobar_movimiento_sin_parpadeo(self, cuadricula):
        capa = cuadricula.capa_intercampus
        rectangulo = dict(capa.rectangulos_etiquetas())[("LUNES", 16 * 60)]
        anterior = cuadricula.celdas_por_bloque[("LUNES", 14, 2)]
        siguiente = cuadricula.celdas_por_bloque[("LUNES", 16, 2)]

        class Registro(QObject):
            def __init__(self):
                super().__init__()
                self.ocultaciones = 0
            def eventFilter(self, objeto, evento):
                if evento.type() == QEvent.Type.Hide:
                    self.ocultaciones += 1
                return False

        registro = Registro()
        capa.aviso.installEventFilter(registro)
        receptores = [anterior, cuadricula, cuadricula.parentWidget(), cuadricula.window()]
        puntos = [QPointF(x, rectangulo.center().y())
                  for x in range(round(rectangulo.left() + 1), round(rectangulo.right()))]
        puntos.extend(QPointF(anterior.x() + 10, y)
                      for y in range(anterior.geometry().bottom() - 1, siguiente.y() + 3))
        try:
            # Simula el mismo MouseMove propagado de la celda a sus ancestros,
            # sin inyectar nuevos eventos ToolTip para reabrirlo.
            for punto in puntos:
                global_pos = capa.mapToGlobal(punto.toPoint())
                for receptor in receptores:
                    evento = QMouseEvent(QEvent.Type.MouseMove,
                        QPointF(receptor.mapFromGlobal(global_pos)), QPointF(global_pos),
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
                    QApplication.sendEvent(receptor, evento)
                    self.app.processEvents()
                    self.assertTrue(capa.aviso.isVisible())
            self.assertEqual(registro.ocultaciones, 0)
            # Una acción que se oculta dentro de una tarjeta tampoco es salir.
            accion = QWidget(anterior)
            accion.setGeometry(20, 20, 10, 10)
            accion.show()
            self.app.processEvents()
            accion.hide()
            self.app.processEvents()
            self.assertTrue(capa.aviso.isVisible())
            self.assertEqual(registro.ocultaciones, 0)
            fuera = cuadricula.celdas_por_bloque[("MARTES", 6, 2)].geometry().center()
            global_pos = cuadricula.mapToGlobal(fuera)
            QApplication.sendEvent(cuadricula, QMouseEvent(QEvent.Type.MouseMove,
                QPointF(fuera), QPointF(global_pos), Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
            self.assertFalse(capa.aviso.isVisible())
            self.assertEqual(registro.ocultaciones, 1)
        finally:
            capa.aviso.removeEventFilter(registro)

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
            # El símbolo ocupa solo el centro; no debe quedar el texto largo
            # a los lados ni un fondo opaco alrededor de la silueta del bus.
            centro = rectangulo.center()
            oscuros = []
            for x in range(round(rectangulo.left() + 6), round(rectangulo.right() - 6)):
                for y in range(round(rectangulo.top() + 3), round(rectangulo.bottom() - 3)):
                    color = imagen.pixelColor(round(x + capa.x()), round(y + capa.y()))
                    if color.red() < 80 and color.green() < 80 and color.blue() < 80:
                        oscuros.append((x, y))
            self.assertGreater(len(oscuros), 5)
            self.assertTrue(all(abs(x - centro.x()) < 20 for x, _ in oscuros))
            self.assertIn("Traslado", celda_anterior.toolTip())


if __name__ == "__main__":
    unittest.main()
