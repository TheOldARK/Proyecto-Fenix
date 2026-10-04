import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox
from herramientas import editor_planes_estudio as editor


class EditorSemestresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        base, profile = root / "base", root / "perfil"
        base.mkdir()
        for name, value in {
            "DATA_DIR": base, "PROFILE_DIR": profile,
            "PLANS_FILE": base / "planes_estudio.json",
            "SIA_FILE": base / "catalogo_sia.json",
            "ELECTIVES_FILE": base / "configuracion_libre_eleccion.json",
        }.items():
            self.stack.enter_context(patch.object(editor, name, value))
        plans = {}
        for code, count in (("1", 8), ("2", 12)):
            plans[code] = {
                "clave": code, "codigo": code, "nombre": f"Carrera {code}",
                "sede_codigo": "1102", "sede_nombre": "Medellín", "valor_sede": "6",
                "facultad_codigo": "3067", "facultad_nombre": "Humanas", "valor_facultad": "5",
                "valor_plan": code, "nombres_asignaturas": {},
                "semestres": {str(n): {"asignaturas": [], "creditos": {}} for n in range(1, count + 1)},
            }
        editor.PLANS_FILE.write_text(json.dumps({"planes": plans}), encoding="utf-8")
        self.stack.enter_context(patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard))
        self.stack.enter_context(patch.object(QMessageBox, "information"))
        self.warning = self.stack.enter_context(patch.object(QMessageBox, "warning"))
        self.window = editor.EditorPlanes()
        self.addCleanup(self.window.close)

    def select(self, code):
        self.window.plan_selector.setCurrentIndex(self.window.plan_selector.findData(code))

    def resize(self, count):
        self.window.semester_count_spin.setValue(count)
        self.window.apply_semester_count_button.click()

    def test_cada_carrera_muestra_su_cantidad_y_permite_mas_de_diez(self):
        self.select("1")
        self.assertEqual(self.window.semester_list.count(), 8)
        self.select("2")
        self.assertEqual(self.window.semester_list.count(), 12)
        self.window.semester_list.setCurrentRow(11)
        self.assertEqual(self.window.current_semester, 12)
        self.select("1")
        self.assertEqual(self.window.semester_count_spin.value(), 8)

    def test_ampliar_conserva_otras_carreras_y_guarda_al_reabrir(self):
        self.select("1")
        other = deepcopy(self.window.plans_doc["planes"]["2"])
        self.resize(14)
        self.assertEqual(self.window.semester_list.count(), 14)
        self.assertEqual(self.window.plans_doc["planes"]["1"]["semestres"]["14"], {"asignaturas": [], "creditos": {}})
        self.assertEqual(self.window.plans_doc["planes"]["2"], other)
        self.assertTrue(self.window.save_all())
        reopened = editor.EditorPlanes()
        try:
            reopened.plan_selector.setCurrentIndex(reopened.plan_selector.findData("1"))
            self.assertEqual(reopened.semester_list.count(), 14)
        finally:
            reopened.close()

    def test_reducir_vacios_no_recrea_el_semestre_seleccionado_eliminado(self):
        self.select("2")
        self.window.semester_list.setCurrentRow(11)
        self.resize(6)
        self.assertEqual(self.window.current_semester, 6)
        self.window.save_all()
        for directory in (editor.DATA_DIR, editor.PROFILE_DIR):
            doc = json.loads((directory / "planes_estudio.json").read_text(encoding="utf-8"))
            self.assertEqual(set(doc["planes"]["2"]["semestres"]), {str(n) for n in range(1, 7)})
        reopened = editor.EditorPlanes()
        try:
            reopened.plan_selector.setCurrentIndex(reopened.plan_selector.findData("2"))
            self.assertEqual(reopened.semester_list.count(), 6)
        finally:
            reopened.close()

    def test_bloquea_reduccion_con_materias_y_con_creditos(self):
        self.select("2")
        plan = self.window.plans_doc["planes"]["2"]
        plan["semestres"]["12"]["asignaturas"] = ["3000001"]
        before = deepcopy(plan["semestres"])
        self.resize(8)
        self.warning.assert_called_once()
        self.assertEqual(plan["semestres"], before)
        self.assertEqual(self.window.semester_count_spin.value(), 12)
        plan["semestres"]["12"]["asignaturas"] = []
        self.window.semester_list.setCurrentRow(11)
        self.window.creditos_libres.setValue(3)
        self.resize(8)
        self.assertEqual(self.warning.call_count, 2)
        self.assertEqual(plan["semestres"]["12"]["creditos"], {"libre_eleccion": 3})
        self.assertEqual(self.window.semester_list.count(), 12)

    def test_materias_despues_del_decimo_sin_nombre_tambien_aparecen(self):
        self.select("2")
        plan = self.window.plans_doc["planes"]["2"]
        plan["semestres"]["12"]["asignaturas"] = ["3000001"]
        self.window.populate_plan_courses()
        self.assertEqual(self.window.plan_courses.count(), 1)
        self.assertIn("12", self.window.plan_courses.item(0).text())

    def test_un_semestre_y_sin_plan_no_producen_errores(self):
        self.select("1")
        self.resize(1)
        self.assertEqual(self.window.semester_list.count(), 1)
        self.window.load_semester(5)
        self.assertEqual(self.window.current_semester, 1)
        self.window.populate_empty()
        self.assertFalse(self.window.apply_semester_count_button.isEnabled())
        self.assertEqual(self.window.semester_list.count(), 0)


if __name__ == "__main__":
    unittest.main()
