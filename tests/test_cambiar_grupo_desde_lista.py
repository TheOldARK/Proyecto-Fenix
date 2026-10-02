"""Una materia ya inscrita sigue permitiendo abrir su selector de grupos."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from aplicacion.interfaz import VentanaPrincipal


class CambiarGrupoDesdeListaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_materia_seleccionada_no_se_bloquea_y_abre_cambio(self):
        materia = {"codigo": "100", "nombre": "Materia", "creditos": 3}
        referencia = {"codigo": "100", "grupo": "1"}
        ventana = MagicMock()
        ventana.materia_ya_seleccionada.return_value = True
        ventana.referencia_de_materia.return_value = referencia
        ventana.referencias = [referencia]
        ventana.materias_aprobadas = set()

        with patch(
            "aplicacion.interfaz.motivo_materia_no_mostrable",
            return_value="Ya elegiste un grupo de esta materia",
        ):
            tarjeta = VentanaPrincipal.crear_boton_asignatura(
                ventana, materia, "principal"
            )

        boton = tarjeta.findChildren(QPushButton)[0]
        quitar = tarjeta.findChild(QPushButton, "quitarMateriaSeleccionada")
        self.assertIsNotNone(quitar)
        self.assertEqual(len(tarjeta.findChildren(QPushButton)), 2)
        tarjeta.resize(240, 55)
        tarjeta.show()
        self.app.processEvents()
        self.assertTrue(boton.geometry().contains(quitar.geometry().center()))
        self.assertTrue(boton.isEnabled())
        boton.click()
        ventana.mostrar_detalle_asignatura.assert_called_once_with(
            materia, "principal", referencia_cambio=referencia
        )
        quitar.click()
        ventana.quitar_grupo.assert_called_once_with(referencia)
        ventana.mostrar_detalle_asignatura.assert_called_once()
        tarjeta.close()


if __name__ == "__main__":
    unittest.main()
