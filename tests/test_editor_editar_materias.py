import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from herramientas import editor_planes_estudio as editor


class EditarMateriasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        plan = {
            "codigo": "1", "nombre": "Carrera", "sede_codigo": "1102",
            "sede_nombre": "Medellín", "facultad_codigo": "3065", "facultad_nombre": "Ciencias",
            "nombres_asignaturas": {"100": "Original", "200": "Otra", "300": "Sin asignar"},
            "semestres": {
                "1": {"asignaturas": ["100", "200"], "creditos": {"libre_eleccion": 3}},
                "2": {"asignaturas": ["100"], "creditos": {}},
            },
        }
        self.doc = {"planes": {"1": plan, "2": deepcopy(plan)}}
        def load(_profile, repo, fallback):
            return deepcopy(self.doc) if repo == editor.PLANS_FILE else deepcopy(fallback)
        with patch.object(editor, "load_editor_json", side_effect=load):
            self.window = editor.EditorPlanes()
        self.window.plan_selector.setCurrentIndex(self.window.plan_selector.findData("1"))
        self.window.populate_plan_courses("100")

    def tearDown(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.window.close()

    def edit(self, code, name, accepted=True):
        with patch.object(editor, "CourseDialog") as cls:
            cls.return_value.exec.return_value = QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
            cls.return_value.values.return_value = code, name
            self.window.edit_course_button.click()

    def test_codigo_nombre_conservan_semestres_creditos_y_otro_plan(self):
        other = deepcopy(self.window.plans_doc["planes"]["2"])
        self.window.creditos_libres.setValue(5)
        self.edit("101", "Corregida")
        self.window.save_current(False)
        plan = self.window.plans_doc["planes"]["1"]
        self.assertNotIn("100", plan["nombres_asignaturas"])
        self.assertEqual(plan["nombres_asignaturas"]["101"], "Corregida")
        self.assertEqual(plan["semestres"]["1"]["asignaturas"], ["101", "200"])
        self.assertEqual(plan["semestres"]["2"]["asignaturas"], ["101"])
        self.assertEqual(plan["semestres"]["1"]["creditos"]["libre_eleccion"], 5)
        self.assertIn("101  ·  Corregida", self.window.semester_courses.item(0).text())
        self.assertEqual(self.window.plans_doc["planes"]["2"], other)

    def test_solo_nombre_y_cancelar(self):
        self.edit("100", "Nombre nuevo")
        self.assertIn("Nombre nuevo", self.window.semester_courses.item(0).text())
        before = deepcopy(self.window.plans_doc)
        self.edit("999", "No guardar", accepted=False)
        self.assertEqual(self.window.plans_doc, before)

    def test_sin_asignacion_y_sin_nombre_registrado(self):
        self.window.populate_plan_courses("300")
        self.edit("301", "Sin asignación corregida")
        plan = self.window.plans_doc["planes"]["1"]
        self.assertFalse(any("301" in sem["asignaturas"] for sem in plan["semestres"].values()))
        del plan["nombres_asignaturas"]["100"]
        self.window.populate_plan_courses("100")
        self.edit("101", "Nombre recuperado")
        self.assertEqual(plan["nombres_asignaturas"]["101"], "Nombre recuperado")

    def test_dialogo_rechaza_vacios_y_duplicados_incluso_sufijo(self):
        dialog = editor.CourseDialog("100", "Original", ["200"])
        try:
            with patch.object(QMessageBox, "warning") as warning:
                for code, name in (("", "Materia"), ("100", " "), ("200", "Otra"), ("200-M", "Otra")):
                    dialog.code.setText(code)
                    dialog.name.setText(name)
                    dialog.accept()
                    self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                self.assertEqual(warning.call_count, 4)
                dialog.code.setText(" 101 ")
                dialog.name.setText(" Corregida ")
                dialog.accept()
                self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
                self.assertEqual(dialog.values(), ("101", "Corregida"))
        finally:
            dialog.close()

    def test_guardado_en_ambos_destinos_y_reapertura(self):
        self.edit("101", "Persistente")
        with tempfile.TemporaryDirectory() as tmp:
            base, profile = Path(tmp) / "base", Path(tmp) / "perfil"
            base.mkdir()
            profile.mkdir()
            with (
                patch.object(editor, "DATA_DIR", base), patch.object(editor, "PROFILE_DIR", profile),
                patch.object(editor, "PLANS_FILE", base / "planes_estudio.json"),
                patch.object(editor, "SIA_FILE", base / "catalogo_sia.json"),
                patch.object(editor, "ELECTIVES_FILE", base / "configuracion_libre_eleccion.json"),
                patch.object(QMessageBox, "information"),
            ):
                self.assertTrue(self.window.save_all())
                for folder in (base, profile):
                    saved = json.loads((folder / "planes_estudio.json").read_text(encoding="utf-8"))
                    self.assertNotIn("100", saved["planes"]["1"]["nombres_asignaturas"])
                reopened = editor.EditorPlanes()
                try:
                    self.assertEqual(reopened.plans_doc["planes"]["1"]["nombres_asignaturas"]["101"], "Persistente")
                finally:
                    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                        reopened.close()


if __name__ == "__main__":
    unittest.main()
