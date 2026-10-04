"""Enter en el código registra y asigna sin duplicar ni mover por accidente."""
import unittest
from unittest.mock import patch

import test_editor_editar_materias as fixtures
from PySide6.QtWidgets import QMessageBox


class EnterSemestreTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EditarMateriasTests.setUpClass.__func__)
    setUp = fixtures.EditarMateriasTests.setUp
    tearDown = fixtures.EditarMateriasTests.tearDown

    def enter(self, code, name=None):
        self.window.course_code.setText(code)
        if name is not None:
            self.window.course_name.setText(name)
        self.window.course_code.returnPressed.emit()

    def test_nuevo_con_nombre_sia_va_al_semestre_seleccionado(self):
        self.window.names_cache = {"1": {"nombres": {"400": "Cálculo de Estructuras"}}}
        self.window.semester_list.setCurrentRow(1)
        self.enter("400")
        plan = self.window.plans_doc["planes"]["1"]
        self.assertEqual(plan["nombres_asignaturas"]["400"], "Cálculo de Estructuras")
        self.assertEqual(plan["semestres"]["2"]["asignaturas"], ["100", "400"])
        self.assertIn("400  ·  Cálculo de Estructuras", self.window.semester_courses.item(1).text())

    def test_nuevo_manual_y_boton_solo_plan(self):
        self.enter("401", "Nombre manual")
        plan = self.window.plans_doc["planes"]["1"]
        self.assertEqual(plan["semestres"]["1"]["asignaturas"], ["100", "200", "401"])
        self.window.course_code.setText("402")
        self.window.course_name.setText("Sin semestre")
        self.window.add_course_to_plan()
        self.assertIn("402", plan["nombres_asignaturas"])
        self.assertNotIn("402", plan["semestres"]["1"]["asignaturas"])

    def test_codigo_ya_asignado_no_se_duplica(self):
        self.enter("100")
        self.enter("100")
        self.assertEqual(self.window.plans_doc["planes"]["1"]["semestres"]["1"]["asignaturas"], ["100", "200"])
        self.assertEqual(self.window.semester_courses.count(), 2)

    def test_otro_semestre_requiere_confirmacion(self):
        plan = self.window.plans_doc["planes"]["1"]
        self.window.semester_list.setCurrentRow(1)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.enter("200")
        self.assertEqual(plan["semestres"]["1"]["asignaturas"], ["100", "200"])
        self.assertEqual(plan["semestres"]["2"]["asignaturas"], ["100"])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.enter("200")
        self.assertEqual(plan["semestres"]["1"]["asignaturas"], ["100"])
        self.assertEqual(plan["semestres"]["2"]["asignaturas"], ["100", "200"])

    def test_cancelar_nombre_desconocido_no_asigna(self):
        before = list(self.window.plans_doc["planes"]["1"]["semestres"]["1"]["asignaturas"])
        with patch.object(self.window, "known_course_names", return_value=[]), patch(
            "herramientas.editor_planes_estudio.QInputDialog.getText", return_value=("", False)
        ):
            self.enter("999")
        self.assertEqual(self.window.plans_doc["planes"]["1"]["semestres"]["1"]["asignaturas"], before)
        self.assertNotIn("999", self.window.plans_doc["planes"]["1"]["nombres_asignaturas"])


if __name__ == "__main__":
    unittest.main()
