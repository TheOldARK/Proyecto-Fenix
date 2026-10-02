"""Búsqueda por materia y clasificación de todos sus grupos en una franja."""

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMenu, QPushButton, QScrollArea, QToolButton, QWidget

from aplicacion.interfaz import VentanaPrincipal, buscar_grupos_en_bloque


def grupo(numero, *horarios):
    return {"numero": numero, "horarios": [
        {"dia": dia, "hora_inicio": inicio, "hora_fin": fin}
        for dia, inicio, fin in horarios
    ]}


class BusquedaGruposBloqueTests(unittest.TestCase):
    def test_selector_de_origen_usa_nombres_claros_y_abre_cada_categoria(self):
        app = QApplication.instance() or QApplication([])

        class VentanaFalsa(QWidget):
            def __init__(self):
                super().__init__()
                self.codigo_plan = "1102:3068:3534"
                self.materias_para_mostrar = {"principal": [], "libre": []}
                self.abierto = None

            def grupos_elegibles_en_bloque(self, *_args):
                return []

            def grupos_actuales(self):
                return []

            def catalogo_buscable_en_bloque(self, _origen):
                return [{"codigo": "1"}]

            def mostrar_grupos_por_origen_en_bloque(self, origen, *_args):
                self.abierto = origen

        ventana = VentanaFalsa()

        def comprobar_menu():
            menu = app.activePopupWidget()
            self.assertIsInstance(menu, QMenu)
            self.assertEqual(menu.objectName(), "menuOrigenGruposBloque")
            obligatorias = menu.findChild(QPushButton, "elegirOrigenGrupos_principal")
            libres = menu.findChild(QPushButton, "elegirOrigenGrupos_libre")
            self.assertIn("Obligatorias y optativas", obligatorias.text())
            self.assertIn("Libre elección", libres.text())
            self.assertNotIn("normales", obligatorias.text().lower())
            obligatorias.click()
            self.assertEqual(ventana.abierto, "principal")

        QTimer.singleShot(0, comprobar_menu)
        VentanaPrincipal.mostrar_grupos_del_bloque(ventana, "LUNES", 8, 2)

        def comprobar_libre():
            menu = app.activePopupWidget()
            menu.findChild(QPushButton, "elegirOrigenGrupos_libre").click()
            self.assertEqual(ventana.abierto, "libre")

        QTimer.singleShot(0, comprobar_libre)
        VentanaPrincipal.mostrar_grupos_del_bloque(ventana, "LUNES", 8, 2)
        ventana.close()
        app.processEvents()

    def setUp(self):
        self.grupo_apto = grupo("1", ("LUNES", "08:00", "10:00"))
        self.grupo_otra_hora = grupo("2", ("MARTES", "10:00", "12:00"))
        self.grupo_conflicto = grupo(
            "3", ("LUNES", "08:00", "10:00"), ("MARTES", "12:00", "14:00")
        )
        self.materia = {
            "codigo": "1000001-M", "nombre": "Álgebra Lineal",
            "grupos": [self.grupo_apto, self.grupo_otra_hora, self.grupo_conflicto],
        }
        self.actuales = [
            ({"codigo": "999", "nombre": "Materia actual"},
             grupo("1", ("MARTES", "12:00", "14:00")))
        ]

    def test_una_materia_puede_estar_en_ambas_categorias(self):
        resultados = buscar_grupos_en_bloque(
            [self.materia], "algebra", "LUNES", 8, 2, set(), set(), self.actuales
        )
        self.assertEqual(len(resultados), 1)
        self.assertEqual([g["numero"] for g in resultados[0]["disponibles"]], ["1"])
        no_disponibles = resultados[0]["no_disponibles"]
        self.assertEqual([r["grupo"]["numero"] for r in no_disponibles], ["2", "3"])
        self.assertIn("franja", no_disponibles[0]["motivo"])
        self.assertIn("Conflicto de horario", no_disponibles[1]["motivo"])

    def test_aprobada_y_sin_grupos_explican_su_motivo(self):
        aprobada = buscar_grupos_en_bloque(
            [self.materia], "1000001", "LUNES", 8, 2,
            {"1000001"}, set(), self.actuales,
        )[0]
        self.assertFalse(aprobada["disponibles"])
        self.assertEqual(len(aprobada["no_disponibles"]), 3)
        self.assertTrue(all("aprobada" in r["motivo"] for r in aprobada["no_disponibles"]))
        sin_grupos = buscar_grupos_en_bloque(
            [{"codigo": "2", "nombre": "Sin oferta", "grupos": []}],
            "sin oferta", "LUNES", 8, 2, set(), set(), [],
        )[0]
        self.assertIsNone(sin_grupos["no_disponibles"][0]["grupo"])
        self.assertIn("No tiene grupos publicados", sin_grupos["no_disponibles"][0]["motivo"])

    def test_previsualizacion_parpadea_aunque_no_haya_conflicto_con_otro_grupo(self):
        class VentanaFalsa:
            def __init__(self):
                self.temporizador_previsualizacion = Mock()
                self.resumen = Mock()
                self.grupo_previsualizado = None
                self._actualizar_cuadricula_previsualizada = Mock()

        ventana = VentanaFalsa()
        dialogo = Mock()
        VentanaPrincipal.previsualizar_grupo_no_disponible(
            ventana, self.materia, self.grupo_otra_hora,
            "No tiene clase en la franja seleccionada", dialogo,
        )
        self.assertEqual(ventana.parpadeos_previsualizacion_restantes, 6)
        self.assertEqual(ventana.grupo_previsualizado, (self.materia, self.grupo_otra_hora))
        ventana.temporizador_previsualizacion.start.assert_called_once()
        dialogo.accept.assert_called_once()

    def test_dialogo_muestra_todos_los_grupos_y_previsualiza_el_elegido(self):
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        prueba = self

        class VentanaFalsa(QWidget):
            crear_area_desplazable = staticmethod(VentanaPrincipal.crear_area_desplazable)

            def __init__(self):
                super().__init__()
                self.materias_aprobadas = set()
                self.referencias = []
                self.previsualizado = None

            def catalogo_buscable_en_bloque(self, _origen):
                return [prueba.materia]

            def grupos_actuales(self):
                return prueba.actuales

            def detalles_conflicto_grupo(self, grupo_actual):
                return ["Conflicto con Materia actual el martes 12:00–14:00"] if grupo_actual is prueba.grupo_conflicto else []

            def crear_boton_grupo(self, _origen, _materia, grupo_actual, _dialogo, _solo_informacion):
                return QPushButton(f"Grupo {grupo_actual['numero']}")

            def previsualizar_grupo_no_disponible(self, materia, grupo_actual, motivo, dialogo):
                self.previsualizado = (materia, grupo_actual, motivo)
                dialogo.accept()

        ventana = VentanaFalsa()

        def comprobar_dialogo(dialogo):
            self.assertEqual(dialogo.objectName(), "dialogoGruposBloque")
            self.assertEqual(dialogo.minimumWidth(), 320)
            dialogo.resize(320, 520)
            dialogo.show()
            app.processEvents()
            self.assertEqual(dialogo.width(), 320)
            dialogo.findChild(QLineEdit, "buscarMateriaBloque").setText("algebra")
            app.processEvents()
            area = dialogo.findChild(QScrollArea)
            self.assertEqual(
                area.horizontalScrollBar().maximum(), 0,
                f"viewport={area.viewport().width()} contenido={area.widget().width()} "
                + str([
                    (type(widget).__name__, widget.minimumSizeHint().width(), widget.sizeHint().width(),
                     widget.text() if isinstance(widget, QToolButton) else "")
                    for widget in area.widget().findChildren(QWidget)
                    if widget.parent() is area.widget()
                ]),
            )
            disponibles = dialogo.findChild(QWidget, "gruposDisponiblesBloque").layout()
            self.assertEqual(disponibles.count(), 1)
            self.assertTrue(disponibles.itemAt(0).widget().findChild(QPushButton).text().startswith("Grupo 1"))
            no_disponibles = dialogo.findChild(QWidget, "gruposNoDisponiblesBloque").layout()
            self.assertEqual(no_disponibles.count(), 2)
            tarjetas = [no_disponibles.itemAt(i).widget() for i in range(2)]
            self.assertIn("Grupo 2", tarjetas[0].text())
            self.assertIn("franja", tarjetas[0].text())
            self.assertIn("Grupo 3", tarjetas[1].text())
            self.assertIn("Conflicto con Materia actual", " ".join(tarjetas[1].text().split()))
            self.assertTrue(dialogo.findChild(QToolButton, "seccionNoDisponiblesBloque").isChecked())
            tarjetas[1].click()
            dialogo.hide()
            return QDialog.DialogCode.Accepted

        with patch.object(QDialog, "exec", comprobar_dialogo):
            VentanaPrincipal.mostrar_grupos_por_origen_en_bloque(
                ventana, "principal", "LUNES", 8, 2,
                [(self.materia, self.grupo_apto)], [(self.materia, self.grupo_conflicto)],
            )
        self.assertIs(ventana.previsualizado[1], self.grupo_conflicto)
        ventana.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
