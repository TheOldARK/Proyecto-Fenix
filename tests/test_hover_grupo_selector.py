import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest

from aplicacion.interfaz import BotonGrupoHorario, CuadriculaHorario, TarjetaHorario


class HoverGrupoSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_delinea_horario_del_grupo_sin_agregarlo(self):
        actual = {"codigo": "100", "nombre": "Ya seleccionado"}
        grupo_actual = {
            "numero": "1",
            "horarios": [{
                "dia": "MARTES", "hora_inicio": "08:00", "hora_fin": "10:00"
            }],
        }
        candidato = {
            "numero": "7",
            "horarios": [
                {"dia": "LUNES", "hora_inicio": "08:00", "hora_fin": "12:00"},
                {"dia": "MIÉRCOLES", "hora_inicio": "10:00", "hora_fin": "11:00"},
            ],
        }
        cuadricula = CuadriculaHorario()
        cuadricula.actualizar([(actual, grupo_actual)])
        tarjetas_antes = len(cuadricula.findChildren(TarjetaHorario))
        boton_grupo = BotonGrupoHorario("Grupo 7", candidato)
        boton_grupo.cursor_entro.connect(cuadricula.previsualizar_grupo)
        boton_grupo.cursor_salio.connect(
            cuadricula.programar_limpieza_previsualizacion
        )
        boton_grupo.resize(250, 70)
        boton_grupo.setEnabled(False)
        boton_grupo.show()
        self.assertTrue(QTest.qWaitForWindowExposed(boton_grupo))

        QTest.mouseMove(boton_grupo, QPoint(10, 10))
        # X11 entrega el movimiento desde el servidor de ventanas de forma
        # asíncrona; processEvents por sí solo puede adelantarse al evento.
        QTest.qWait(100)

        self.assertEqual(len(cuadricula.bloques_previsualizados), 3)
        self.assertTrue(all(
            cuadricula.celdas_por_bloque[bloque].previsualizacion_grupo_activa
            for bloque in cuadricula.bloques_previsualizados
        ))
        self.assertEqual(len(cuadricula.findChildren(TarjetaHorario)), tarjetas_antes)
        self.assertTrue(all(
            "#F2F2F2" in cuadricula.celdas_por_bloque[bloque].styleSheet()
            for bloque in cuadricula.bloques_previsualizados
        ))

        cuadricula.programar_limpieza_previsualizacion()
        cuadricula.limpiar_previsualizacion_grupo()
        boton_grupo.hide()

        self.assertFalse(cuadricula.bloques_previsualizados)
        self.assertTrue(all(
            not celda.previsualizacion_grupo_activa
            for celda in cuadricula.celdas_por_bloque.values()
        ))


if __name__ == "__main__":
    unittest.main()
