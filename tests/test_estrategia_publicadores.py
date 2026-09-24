import unittest
from types import SimpleNamespace

from herramientas.estrategia_publicadores import (
    medir_lote,
    limpiar_estadisticas_rendimiento,
    debe_reintentar_timeout,
    es_error_timeout,
    ordenar_por_actualizacion_mas_antigua,
    seleccionar_concurrencia,
    unidades_plan,
)


class EstrategiaPublicadoresTests(unittest.TestCase):
    def test_normaliza_lotes_de_distinto_tamano(self):
        una_carrera = medir_lote(unidades=100, duracion_segundos=10, publicadores=1)
        cuatro_carreras = medir_lote(unidades=400, duracion_segundos=40, publicadores=4)
        self.assertEqual(una_carrera["unidades_por_segundo"], cuatro_carreras["unidades_por_segundo"])
        self.assertEqual(cuatro_carreras["unidades_por_publicador_segundo"], 2.5)

    def test_cuenta_materias_unicas_del_plan(self):
        plan = SimpleNamespace(semestres=[
            SimpleNamespace(asignaturas=["101", "102"]),
            SimpleNamespace(asignaturas=["102", "103"]),
        ])
        self.assertEqual(unidades_plan(plan), 3)

    def test_explora_concurrencia_sin_muestras(self):
        elegida = seleccionar_concurrencia(4, {1: [2.0], 2: [1.0], 3: [], 4: [0.5]})
        self.assertEqual(elegida, 3)

    def test_devuelve_una_estrategia_valida_con_historial(self):
        elegida = seleccionar_concurrencia(3, {1: [5.0, 5.1], 2: [7.0], 3: [4.0, 4.2]})
        self.assertIn(elegida, {1, 2, 3})

    def test_prioriza_el_plan_mas_rezagado(self):
        historial = {
            "plan-a": {"ultima_actualizacion_exitosa": 300},
            "plan-b": {"ultima_actualizacion_exitosa": 100},
        }
        self.assertEqual(
            ordenar_por_actualizacion_mas_antigua(["plan-a", "plan-b", "plan-c"], historial),
            ["plan-c", "plan-b", "plan-a"],
        )

    def test_limpia_solo_metricas_de_velocidad(self):
        datos = {
            "concurrencias": {"2": [{"unidades_por_segundo": 4.0}]},
            "planes": {
                "plan-a": {
                    "duracion_segundos": 20,
                    "ultima_actualizacion_exitosa": 100,
                    "errores_consecutivos": 0,
                }
            },
        }
        limpiar_estadisticas_rendimiento(datos)
        self.assertEqual(datos["concurrencias"], {})
        self.assertNotIn("duracion_segundos", datos["planes"]["plan-a"])
        self.assertEqual(datos["planes"]["plan-a"]["ultima_actualizacion_exitosa"], 100)
        self.assertEqual(datos["planes"]["plan-a"]["errores_consecutivos"], 0)

    def test_detecta_timeout_y_no_reintenta_cualquier_error(self):
        self.assertTrue(es_error_timeout("Timeout 30000ms exceeded"))
        self.assertTrue(es_error_timeout("se agotó el tiempo de espera"))
        self.assertFalse(es_error_timeout("Credenciales de Cloudflare inválidas"))

    def test_reintenta_timeout_con_limite_y_respeta_detencion(self):
        self.assertTrue(debe_reintentar_timeout("Timeout 30s", 1, 3))
        self.assertTrue(debe_reintentar_timeout("Timeout 30s", 2, 3))
        self.assertFalse(debe_reintentar_timeout("Timeout 30s", 3, 3))
        self.assertFalse(debe_reintentar_timeout("Timeout 30s", 1, 3, detener=True))
        self.assertFalse(debe_reintentar_timeout("Error de conexión", 1, 3))


if __name__ == "__main__":
    unittest.main()
