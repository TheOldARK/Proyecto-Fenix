import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from infraestructura.sia.errores import MateriaNoDisponibleEnSIA
from herramientas.verificar_planes_sia import (
    verificar_plan, tareas_desde_planes, guardar_informe,
)


class VerificadorSIATests(unittest.IsolatedAsyncioTestCase):
    def sesion(self):
        return SimpleNamespace(
            cargar=AsyncMock(return_value={"1001": {"codigo": "1001-M", "nombre": "Cálculo"}}),
            comprobar_ficha=AsyncMock(return_value={"grupos_detectados": 0, "requisitos_detectados": 1}),
            volver=AsyncMock(),
        )

    async def test_abre_ficha_y_cero_grupos_no_es_codigo_invalido(self):
        sesion = self.sesion()
        resultado = await verificar_plan(sesion, {"1001": "Calculo"}, Mock())
        self.assertEqual(resultado[0]["estado"], "funciona")
        self.assertEqual(resultado[0]["grupos_detectados"], 0)
        self.assertFalse(resultado[0]["nombre_diferente"])
        self.assertEqual(sesion.comprobar_ficha.await_args.args[0]["codigo"], "1001-M")

    async def test_ausencia_se_revisa_en_catalogo_nuevo(self):
        sesion = self.sesion()
        resultado = await verificar_plan(sesion, {"9999": "No encontrada"}, Mock())
        self.assertEqual(resultado[0]["estado"], "no_en_catalogo")
        self.assertEqual(sesion.cargar.await_count, 2)
        sesion.comprobar_ficha.assert_not_awaited()

    async def test_catalogo_caido_no_declara_todos_los_codigos_inexistentes(self):
        sesion = self.sesion()
        sesion.cargar.side_effect = TimeoutError("SIA caído")
        resultado = await verificar_plan(sesion, {"1001": "Uno", "1002": "Dos"}, Mock())
        self.assertTrue(all(r["estado"] == "no_verificada" for r in resultado))
        self.assertEqual(sesion.cargar.await_count, 2)

    async def test_error_navegacion_reintenta_y_se_distingue_de_ausencia(self):
        sesion = self.sesion()
        sesion.comprobar_ficha.side_effect = MateriaNoDisponibleEnSIA("errorNavegacion.jsf", sesion_invalidada=True)
        resultado = await verificar_plan(sesion, {"1001": "Calculo"}, Mock())
        self.assertEqual(resultado[0]["estado"], "error_ficha_sia")
        self.assertEqual(sesion.comprobar_ficha.await_count, 2)

    async def test_recuperacion_de_timeout_y_diferencia_de_nombre(self):
        sesion = self.sesion()
        sesion.comprobar_ficha.side_effect = [TimeoutError("red"), {"grupos_detectados": 2, "requisitos_detectados": 0}]
        resultado = await verificar_plan(sesion, {"1001": "Nombre viejo"}, Mock())
        self.assertEqual(resultado[0]["estado"], "funciona")
        self.assertTrue(resultado[0]["nombre_diferente"])
        self.assertEqual(resultado[0]["intentos"], 2)

    async def test_fallo_al_volver_no_invalida_la_ficha_comprobada(self):
        sesion = self.sesion()
        sesion.volver.side_effect = TimeoutError("volver")
        resultado = await verificar_plan(sesion, {"1001": "Calculo"}, Mock())
        self.assertEqual(resultado[0]["estado"], "funciona")

    async def test_guarda_avances_antes_de_pasar_a_la_siguiente(self):
        sesion = self.sesion()
        capturas = []
        await verificar_plan(sesion, {"1001": "Uno", "9999": "Dos"}, Mock(),
                             lambda filas: capturas.append(list(filas)))
        self.assertEqual([len(c) for c in capturas], [1, 2])

    def test_deduplica_sufijos_dentro_del_plan_pero_no_entre_carreras(self):
        plan = SimpleNamespace(codigo="1", sede_codigo="1102", facultad_codigo="3064",
                               facultad_nombre="Arquitectura", nombre="Carrera",
                               nombres_asignaturas={"1001-M": "Uno"},
                               semestres=[SimpleNamespace(asignaturas=["1001", "1001-M"])])
        tareas = tareas_desde_planes({"1102:3064:1": plan, "1102:3064:2": plan})
        self.assertEqual(len(tareas), 2)
        self.assertEqual(tareas[0][2], {"1001": "Uno"})
        self.assertEqual(len(tareas_desde_planes({"1102:3064:1": plan}, facultad="3065")), 0)

    def test_informe_vacio_se_identifica_sin_malla(self):
        informe = {"estado": "terminado", "archivo_planes": "planes.json", "planes": [
            {"clave": "1102:3064:3501", "nombre": "Arquitectura", "estado": "sin_malla", "total": 0, "materias": []}
        ]}
        with tempfile.TemporaryDirectory() as temporal:
            guardar_informe(Path(temporal), informe)
            self.assertIn("sin_malla", (Path(temporal) / "informe.md").read_text(encoding="utf-8"))
            self.assertTrue((Path(temporal) / "informe.json").is_file())


if __name__ == "__main__":
    unittest.main()
