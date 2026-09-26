import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from aplicacion.interfaz import DialogoPlan
from dominio.plan_estudios import PlanEstudios, Semestre
from herramientas.gestor_publicadores import planes_con_malla_pendiente


class SelectorFacultadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def plan(codigo, nombre, facultad, materias=None):
        materias = materias or []
        return PlanEstudios(
            codigo=codigo.rsplit(":", 1)[1],
            nombre=nombre,
            sede_codigo="1102",
            sede_nombre="1102 SEDE MEDELLÍN",
            facultad_codigo=facultad,
            facultad_nombre=f"{facultad} FACULTAD",
            semestres=[Semestre(numero=1, asignaturas=materias)],
            nombres_asignaturas={codigo_materia: "Materia" for codigo_materia in materias},
        )

    def test_selector_filtra_carreras_y_restaura_facultad_del_estudiante(self):
        planes = {
            "1102:3068:3528": self.plan("1102:3068:3528", "Sistemas", "3068", ["3001"]),
            "1102:3065:3705": self.plan("1102:3065:3705", "Química", "3065"),
        }
        dialogo = DialogoPlan(
            planes, {}, estudiante={"plan_estudios": "1102:3065:3705"}
        )
        self.assertEqual(dialogo.selector_facultad.currentData(), "1102:3065")
        self.assertEqual(dialogo.selector.currentData(), "1102:3065:3705")
        self.assertEqual(dialogo.selector.count(), 2)

        dialogo.selector_facultad.setCurrentIndex(
            dialogo.selector_facultad.findData("1102:3068")
        )
        self.assertEqual(dialogo.selector.count(), 2)
        self.assertIsNone(dialogo.selector.currentData())
        dialogo.close()

    def test_gestor_marca_como_pendiente_plan_sin_malla_con_ruta_lista(self):
        planes = {
            "1102:3065:3705": self.plan("1102:3065:3705", "Química", "3065")
        }
        planes["1102:3065:3705"].valor_sede = "6"
        planes["1102:3065:3705"].valor_facultad = "1"
        planes["1102:3065:3705"].valor_plan = "6"
        pendientes = planes_con_malla_pendiente(planes, ["1102:3065:3705"])
        self.assertEqual(list(pendientes), ["1102:3065:3705"])

        planes["1102:3065:3705"].nombres_asignaturas = {"3001": "Materia"}
        planes["1102:3065:3705"].semestres[0].asignaturas = ["3001"]
        self.assertEqual(
            planes_con_malla_pendiente(planes, ["1102:3065:3705"]), {}
        )


if __name__ == "__main__":
    unittest.main()
