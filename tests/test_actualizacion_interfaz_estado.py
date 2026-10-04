import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from aplicacion.interfaz import VentanaPrincipal


class EstadoActualizacionInterfazTests(unittest.TestCase):
    def test_no_reemplaza_completada_si_worker_termina_entre_lectura_y_poll(self):
        estado_en_progreso = {
            "estado": "actualizando",
            "mensaje": "Consultando el SIA…",
            "progreso": 100,
        }
        estado_completado = {
            "estado": "completada",
            "mensaje": "Datos actualizados correctamente.",
            "progreso": 100,
            "actualizado_en": "2026-10-03T12:00:00",
        }
        proceso = Mock()
        proceso.poll.return_value = 0
        ventana = SimpleNamespace(
            cambiando_estudiante=False,
            proceso_actualizacion=proceso,
            dialogo_espera=None,
            codigo_plan=None,
            datos_disponibles=False,
            ultima_actualizacion_vista=None,
            actualizar_indicador_actualizacion=Mock(),
            hay_datos_disponibles=Mock(return_value=False),
        )

        with (
            patch(
                "aplicacion.interfaz.cargar_estado",
                side_effect=[estado_en_progreso, estado_completado],
            ),
            patch("aplicacion.interfaz.guardar_estado") as guardar_estado,
        ):
            VentanaPrincipal.revisar_actualizacion(ventana)

        guardar_estado.assert_not_called()
        ventana.actualizar_indicador_actualizacion.assert_called_once_with(
            "completada", "Datos actualizados correctamente.", 100
        )


if __name__ == "__main__":
    unittest.main()
