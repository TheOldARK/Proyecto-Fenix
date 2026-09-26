import unittest
from unittest.mock import Mock

from aplicacion.interfaz import VentanaPrincipal


class PrevisualizacionConflictosTests(unittest.TestCase):
    def test_parpadea_tres_veces_y_luego_restaura_el_horario(self):
        class VentanaSimulada:
            limpiar_previsualizacion = VentanaPrincipal.limpiar_previsualizacion

            def __init__(self):
                self.grupo_previsualizado = (object(), object())
                self.temporizador_previsualizacion = Mock()
                self.parpadeos_previsualizacion_restantes = 6
                self.previsualizacion_resaltada = True
                self.estados_resaltados = [True]
                self.horario_restaurado = False

            def _actualizar_cuadricula_previsualizada(self):
                self.estados_resaltados.append(self.previsualizacion_resaltada)

            def actualizar_horario(self):
                self.horario_restaurado = True

        ventana = VentanaSimulada()

        for _ in range(6):
            VentanaPrincipal._alternar_parpadeo_previsualizacion(ventana)

        self.assertEqual(ventana.estados_resaltados, [True, False, True, False, True, False])
        self.assertEqual(sum(ventana.estados_resaltados), 3)
        self.assertIsNone(ventana.grupo_previsualizado)
        self.assertTrue(ventana.horario_restaurado)
        ventana.temporizador_previsualizacion.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
