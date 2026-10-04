import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from herramientas import gestor_publicadores as gestor


class GestorRecuperacionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reintenta_timeout_y_conserva_historial(self):
        plan = SimpleNamespace(semestres=[SimpleNamespace(asignaturas=["1"])])
        with tempfile.TemporaryDirectory() as carpeta, \
                patch.object(gestor, "CARPETA_GESTOR", Path(carpeta)), \
                patch.object(gestor, "leer_estadisticas", return_value={"planes": {}, "concurrencias": {}}), \
                patch.object(gestor.shutil, "copy2"), \
                patch("aplicacion.arranque.comando_fenix", return_value=["fenix"]), \
                patch.object(gestor.subprocess, "Popen") as lanzar, \
                patch.object(gestor, "supervisar", side_effect=[
                    ({"estado": "error", "error": "Timeout: sin avance"}, ""),
                    ({"estado": "completado", "unidades_trabajo": 1}, ""),
                ]), patch.object(gestor, "guardar_estadisticas"):
            lanzar.return_value.poll.return_value = 0
            ciclo = gestor.CicloPublicadores({"plan": plan}, ["plan"], 1, False, False, 1)
            ciclo.detener = Mock()
            ciclo.detener.is_set.return_value = False
            ciclo.detener.wait.return_value = False
            resultado = ciclo._ejecutar_plan("plan")
            self.assertTrue(resultado["exito"])
            self.assertEqual(lanzar.call_count, 2)
            self.assertEqual(len(resultado["intentos"]), 2)
            ciclo._guardar_resultado_plan(resultado)
            self.assertEqual(len(ciclo.estadisticas["intentos"]), 2)

    def test_ventana_organiza_estadisticas_sin_parrafo_interminable(self):
        datos = {"planes": {}, "concurrencias": {
            "2": [{"unidades_por_segundo": 1, "unidades_por_publicador_segundo": 0.5}],
            "1": [{"unidades_por_segundo": 0.7, "unidades_por_publicador_segundo": 0.7}],
        }, "intentos": [{"codigo": "plan", "intento": 1, "fecha": 1,
                         "duracion": 8, "exito": False, "detalle": "Timeout de prueba"}]}
        with patch.object(gestor, "leer_estadisticas", return_value=datos), \
                patch.object(gestor, "cargar_planes", return_value={}), \
                patch.object(gestor, "seleccionar_planes_publicables", return_value=({}, [])), \
                patch.object(gestor, "seleccionar_planes_referencia_libres", return_value={}):
            ventana = gestor.VentanaGestor(self.app)
            try:
                ventana.mostrar_intentos()
                self.app.processEvents()
                self.assertEqual(ventana.tabla_mediciones.rowCount(), 2)
                self.assertEqual(ventana.tabla_intentos.rowCount(), 1)
                self.assertLess(len(ventana.resumen_rendimiento.text()), 180)
                ventana.tabla_intentos.selectRow(0)
                self.assertIn("Timeout", ventana.detalle_intento.toPlainText())
                self.assertFalse(ventana.dialogo_intentos.isModal())
                self.assertEqual(ventana.actividad.maximumBlockCount(), 3000)
            finally:
                ventana.close()
                ventana.deleteLater()


if __name__ == "__main__":
    unittest.main()
