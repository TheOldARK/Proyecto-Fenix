"""El detalle de una materia debe seguir legible con el horario a la vista."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget

from aplicacion.interfaz import (
    BarraDialogo, BotonGrupoHorario, VentanaPrincipal,
    centrar_contenido_si_no_hay_barra, preparar_dialogo_sin_barra,
)


class AnchoSelectorGruposTests(unittest.TestCase):
    def test_bordes_del_dialogo_permiten_cambiar_ancho_y_alto(self):
        app = QApplication.instance() or QApplication([])
        dialogo = QDialog()
        dialogo.setMinimumSize(320, 220)
        dialogo.resize(400, 300)
        preparar_dialogo_sin_barra(dialogo, QVBoxLayout(dialogo))
        dialogo.show()
        app.processEvents()
        inicio = dialogo.mapToGlobal(QPoint(dialogo.width() - 2, dialogo.height() - 2))
        destino = inicio + QPoint(40, 30)
        pulsar = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(dialogo.width() - 2, dialogo.height() - 2),
            QPointF(inicio), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        mover = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(dialogo.width() + 38, dialogo.height() + 28),
            QPointF(destino), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(dialogo, pulsar)
        QApplication.sendEvent(dialogo, mover)
        self.assertEqual(dialogo.size().width(), 440)
        self.assertEqual(dialogo.size().height(), 330)
        soltar = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(dialogo.width() - 2, dialogo.height() - 2),
            QPointF(destino), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(dialogo, soltar)
        inicio = dialogo.mapToGlobal(QPoint(2, 2))
        destino = inicio + QPoint(300, 300)
        pulsar = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(2, 2), QPointF(inicio),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        mover = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(302, 302), QPointF(destino),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        barra = dialogo.findChild(BarraDialogo, "barraDialogoFenix")
        QApplication.sendEvent(barra, pulsar)
        QApplication.sendEvent(barra, mover)
        self.assertEqual(dialogo.size().width(), 320)
        self.assertEqual(dialogo.size().height(), 220)
        dialogo.close()

    def test_contenido_recupera_el_espacio_si_desaparece_la_barra(self):
        app = QApplication.instance() or QApplication([])
        dialogo = QDialog()
        dialogo.resize(400, 180)
        disposicion = QVBoxLayout(dialogo)
        disposicion.setContentsMargins(20, 18, 8, 18)
        area = VentanaPrincipal.crear_area_desplazable()
        disposicion.addWidget(area)
        centrar_contenido_si_no_hay_barra(area, disposicion, 8, 12)
        area.widget().layout().addWidget(QLabel("Una materia"))
        dialogo.show()
        app.processEvents()
        app.processEvents()
        self.assertEqual(area.verticalScrollBar().maximum(), 0)
        self.assertEqual(disposicion.contentsMargins().right(), 20)
        self.assertEqual(area.widget().layout().contentsMargins().right(), 0)
        for indice in range(30):
            area.widget().layout().addWidget(QLabel(f"Materia {indice}"))
        app.processEvents()
        app.processEvents()
        self.assertGreater(area.verticalScrollBar().maximum(), 0)
        self.assertEqual(disposicion.contentsMargins().right(), 8)
        self.assertEqual(area.widget().layout().contentsMargins().right(), 12)
        dialogo.close()

    def test_dialogo_sin_barra_tiene_cierre_visible(self):
        app = QApplication.instance() or QApplication([])
        dialogo = QDialog()
        preparar_dialogo_sin_barra(dialogo, QVBoxLayout(dialogo))
        self.assertTrue(dialogo.windowFlags() & Qt.WindowType.FramelessWindowHint)
        dialogo.show()
        app.processEvents()
        barra = dialogo.findChild(BarraDialogo, "barraDialogoFenix")
        self.assertEqual(barra.geometry().left(), 0)
        self.assertEqual(barra.width(), dialogo.width())
        dialogo.resize(450, 300)
        app.processEvents()
        self.assertEqual(barra.width(), dialogo.width())
        cierre = dialogo.findChild(QPushButton, "cerrarDialogoFenix")
        self.assertIsNotNone(cierre)
        self.assertTrue(cierre.isVisible())
        cierre.click()
        app.processEvents()
        self.assertFalse(dialogo.isVisible())

    def test_cuatro_sesiones_se_distribuyen_segun_el_ancho(self):
        app = QApplication.instance() or QApplication([])
        sesiones = [f"Día {indice} 08:00–10:00" for indice in range(1, 5)]
        boton = BotonGrupoHorario("Grupo 1\n" + "  |  ".join(sesiones), {})
        metricas = boton.fontMetrics()
        ancho_sesion = max(metricas.horizontalAdvance(sesion) for sesion in sesiones)
        ancho_dos = max(
            metricas.horizontalAdvance("  |  ".join(sesiones[:2])),
            metricas.horizontalAdvance("  |  ".join(sesiones[2:])),
        )
        boton._ajustar_texto(1000)
        self.assertEqual(len(boton.text().splitlines()), 2)
        boton._ajustar_texto(ancho_dos + 1)
        self.assertEqual(boton.text().splitlines()[1:], [
            "  |  ".join(sesiones[:2]), "  |  ".join(sesiones[2:]),
        ])
        boton._ajustar_texto(ancho_sesion + 1)
        self.assertEqual(boton.text().splitlines()[1:], sesiones)
        boton.close()
        app.processEvents()

    def test_horarios_conservan_formato_amplio_y_se_compactan_al_estrechar(self):
        app = QApplication.instance() or QApplication([])
        texto = "Grupo 2 · 15 cupos\nLun 08:00–10:00 · M8  |  Mié 10:00–12:00 · M9"
        boton = BotonGrupoHorario(texto, {"numero": "2"})
        boton.resize(700, 80)
        boton.show()
        app.processEvents()
        self.assertIn("  |  ", boton.text())
        boton.resize(230, 80)
        app.processEvents()
        self.assertNotIn("  |  ", boton.text())
        self.assertIn("Mié 10:00–12:00", boton.text())
        boton.resize(700, 80)
        app.processEvents()
        self.assertIn("  |  ", boton.text())
        boton.close()

    def test_dialogo_puede_reducirse_a_320_sin_desplazamiento_horizontal(self):
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        grupo = {"numero": "12", "horarios": [
            {"dia": "LUNES", "hora_inicio": "08:00", "hora_fin": "10:00", "aula": "Bloque M8 - 101"},
            {"dia": "MIÉRCOLES", "hora_inicio": "10:00", "hora_fin": "12:00", "aula": "Bloque M8 - 102"},
        ]}
        materia = {"codigo": "3000001", "nombre": "Introducción a la Ingeniería de Sistemas e Informática",
                   "creditos": 4, "tipologia": "Fundamentación obligatoria",
                   "descripcion": "Descripción completa de la asignatura.",
                   "prerrequisitos": [{"tipo": "M", "codigo": "1000004", "nombre": "Cálculo"}],
                   "grupos": [grupo]}

        class VentanaFalsa(QWidget):
            crear_area_desplazable = staticmethod(VentanaPrincipal.crear_area_desplazable)

            def crear_boton_grupo(self, _origen, _materia, grupo_actual, _dialogo, _informacion, _cambio):
                return BotonGrupoHorario(
                    "Grupo 12 · 15 cupos disponibles\n"
                    "LUNES 08:00–10:00 · Bloque M8 - 101  |  "
                    "MIÉRCOLES 10:00–12:00 · Bloque M8 - 102\n"
                    "Docente: Nombre Apellido Apellido",
                    grupo_actual,
                )

        ventana = VentanaFalsa()

        def comprobar(dialogo):
            self.assertEqual(dialogo.minimumWidth(), 320)
            dialogo.resize(320, 520)
            dialogo.show()
            app.processEvents()
            self.assertEqual(dialogo.width(), 320)
            area = dialogo.findChild(QScrollArea)
            self.assertIsNotNone(area)
            self.assertEqual(
                area.horizontalScrollBar().maximum(), 0,
                f"viewport={area.viewport().width()} contenido={area.widget().width()} "
                f"boton={dialogo.findChild(BotonGrupoHorario).minimumSizeHint().width()}"
            )
            boton = dialogo.findChild(BotonGrupoHorario)
            self.assertIsNotNone(boton)
            self.assertGreaterEqual(boton.height(), boton.minimumHeight())
            self.assertLessEqual(
                max(boton.fontMetrics().horizontalAdvance(linea) for linea in boton.text().splitlines()),
                boton.width() - 20,
            )
            lineas_estrecho = len(boton.text().splitlines())
            dialogo.resize(500, 520)
            app.processEvents()
            self.assertLessEqual(len(boton.text().splitlines()), lineas_estrecho)
            dialogo.resize(320, 520)
            app.processEvents()
            self.assertEqual(area.horizontalScrollBar().maximum(), 0)
            desplegable = dialogo.findChild(QToolButton, "desplegableDescripcionMateria")
            cuerpo = dialogo.findChild(QWidget, "contenidoDescripcionMateria")
            self.assertIsNotNone(desplegable)
            self.assertFalse(cuerpo.isVisible())
            desplegable.click()
            app.processEvents()
            self.assertTrue(cuerpo.isVisible())
            self.assertEqual(area.horizontalScrollBar().maximum(), 0)
            desplegable.click()
            self.assertFalse(cuerpo.isVisible())
            requisitos = dialogo.findChild(QToolButton, "desplegablePrerrequisitosMateria")
            cuerpo_requisitos = dialogo.findChild(QWidget, "contenidoPrerrequisitosMateria")
            self.assertIsNotNone(requisitos)
            self.assertFalse(cuerpo_requisitos.isVisible())
            requisitos.click()
            app.processEvents()
            self.assertTrue(cuerpo_requisitos.isVisible())
            self.assertIn("Cálculo", cuerpo_requisitos.findChild(QWidget).text())
            self.assertEqual(area.horizontalScrollBar().maximum(), 0)
            requisitos.click()
            self.assertFalse(cuerpo_requisitos.isVisible())
            dialogo.hide()
            return QDialog.DialogCode.Rejected

        with patch.object(QDialog, "exec", comprobar):
            VentanaPrincipal.mostrar_detalle_asignatura(
                ventana, materia, "principal"
            )
        ventana.close()
        app.processEvents()

    def test_editor_de_grupos_tambien_cabe_en_320(self):
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        grupo = {"numero": "12", "horarios": [
            {"dia": "MIÉRCOLES", "hora_inicio": "10:00", "hora_fin": "12:00", "aula": "Bloque M8 - 102"}
        ]}
        materia = {"codigo": "3000001", "nombre": "Introducción a la Ingeniería de Sistemas e Informática",
                   "grupos": [grupo]}

        class VentanaFalsa(QWidget):
            crear_area_desplazable = staticmethod(VentanaPrincipal.crear_area_desplazable)

            def __init__(self):
                super().__init__()
                self.materias_por_origen = {"principal": [materia], "libre": []}
                self.referencias = [{"origen": "principal", "codigo": "3000001", "numero": "12"}]

        ventana = VentanaFalsa()

        def comprobar(dialogo):
            self.assertEqual(dialogo.minimumWidth(), 320)
            dialogo.resize(320, 520)
            dialogo.show()
            app.processEvents()
            self.assertEqual(dialogo.width(), 320)
            area = dialogo.findChild(QScrollArea)
            self.assertEqual(area.horizontalScrollBar().maximum(), 0)
            self.assertIsNotNone(dialogo.findChild(QComboBox))
            dialogo.hide()
            return QDialog.DialogCode.Rejected

        with patch.object(QDialog, "exec", comprobar):
            VentanaPrincipal.abrir_editor_grupos(ventana)
        ventana.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
