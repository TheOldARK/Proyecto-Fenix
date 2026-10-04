"""Las carreras vacías deben ser editables y consultables en el árbol."""
import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox
import configuracion
from herramientas import editor_planes_estudio as editor
from herramientas.arbol_prerrequisitos import VentanaArbol, _buscar_ruta


FACULTADES = {
    "3064": ("0", {"3501": "Arquitectura", "3502": "Artes Plásticas", "3503": "Construcción"}),
    "3442": ("2", {"3508": "Ingeniería Agrícola", "3509": "Ingeniería Agronómica", "3510": "Ingeniería Forestal", "3511": "Zootecnia"}),
    "3516": ("4", {"3706": "Farmacia"}),
}


class FacultadesMedellinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.catalogo = json.loads(editor.SIA_FILE.read_text(encoding="utf-8"))

    def test_planes_catalogo_y_libres_coinciden(self):
        planes = json.loads(editor.PLANS_FILE.read_text(encoding="utf-8"))["planes"]
        libres = json.loads(editor.ELECTIVES_FILE.read_text(encoding="utf-8"))["1102"]["planes"]
        for facultad, (valor, carreras) in FACULTADES.items():
            for indice, (codigo, nombre) in enumerate(carreras.items()):
                clave = f"1102:{facultad}:{codigo}"
                with self.subTest(clave=clave):
                    plan = planes[clave]
                    self.assertEqual(plan["nombre"], nombre)
                    self.assertEqual(plan["facultad_codigo"], facultad)
                    self.assertEqual(plan["valor_facultad"], valor)
                    self.assertEqual(plan["valor_plan"], str(indice))
                    ruta = _buscar_ruta(self.catalogo, clave)
                    self.assertEqual(ruta[2]["value"], valor)
                    self.assertEqual(ruta[3]["value"], str(indice))
                    self.assertEqual(libres[f"{facultad}:{codigo}"]["plan"], f"{codigo} {nombre}")
                    # No exigir que permanezcan vacíos: el usuario los editará.
                    self.assertIsInstance(plan["nombres_asignaturas"], dict)
                    self.assertTrue(plan["semestres"])

    def test_editor_muestra_las_ocho_carreras_sin_perfil_nuevo(self):
        with tempfile.TemporaryDirectory() as temporal, \
                patch.object(editor, "PROFILE_DIR", Path(temporal)), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            ventana = editor.EditorPlanes()
            try:
                for facultad, (_, carreras) in FACULTADES.items():
                    indice = next((i for i in range(ventana.faculty_selector.count())
                                   if ventana.faculty_selector.itemData(i) == ("1102", facultad)), -1)
                    self.assertGreaterEqual(indice, 0)
                    ventana.faculty_selector.setCurrentIndex(indice)
                    self.assertEqual(
                        {ventana.plan_selector.itemData(i) for i in range(ventana.plan_selector.count())},
                        {f"1102:{facultad}:{c}" for c in carreras},
                    )
                    for codigo in carreras:
                        ventana.plan_selector.setCurrentIndex(ventana.plan_selector.findData(f"1102:{facultad}:{codigo}"))
                        self.assertGreater(ventana.semester_list.count(), 0)
            finally:
                ventana.close()

    def test_arbol_incluye_nuevas_facultades_con_cache_antigua(self):
        anterior = deepcopy(self.catalogo)
        for nivel in anterior["niveles_estudio"]:
            for sede in nivel["sedes"]:
                sede["facultades"] = [f for f in sede["facultades"] if f["codigo"] not in FACULTADES]
        with tempfile.TemporaryDirectory() as temporal:
            cache = Path(temporal) / "catalogo.json"
            cache.write_text(json.dumps(anterior), encoding="utf-8")
            with patch.object(VentanaArbol, "_ruta_cache", return_value=cache), \
                    patch.object(configuracion, "ARCHIVO_CATALOGO_SIA", cache), \
                    patch.object(VentanaArbol, "_iniciar_descubrimiento"):
                ventana = VentanaArbol()
                try:
                    ventana.sede.setCurrentIndex(ventana.sede.findData("1102"))
                    for facultad, (_, carreras) in FACULTADES.items():
                        indice = ventana.facultad.findData(facultad)
                        self.assertGreaterEqual(indice, 0)
                        ventana.facultad.setCurrentIndex(indice)
                        self.assertEqual(
                            {ventana.plan.itemData(i)["clave"] for i in range(ventana.plan.count())},
                            {f"1102:{facultad}:{c}" for c in carreras},
                        )
                finally:
                    ventana.close()
            self.assertEqual(json.loads(cache.read_text(encoding="utf-8")), anterior)


if __name__ == "__main__":
    unittest.main()
