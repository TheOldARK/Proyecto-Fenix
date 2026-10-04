import unittest
from unittest.mock import AsyncMock, Mock

from playwright.async_api import TimeoutError as TimeoutPlaywright
from infraestructura.sia.catalogo_sia import CatalogoSIA


class SeleccionPlanTests(unittest.IsolatedAsyncioTestCase):
    def crear_catalogo(self):
        sia = CatalogoSIA.__new__(CatalogoSIA)
        sia.codigo_plan = "3501"
        sia.nombre_plan = "3501 Arquitectura"
        sia.codigo_facultad = "3064"
        sia.MAXIMO_INTENTOS_PLAN = 3
        sia.page = Mock()
        sia.page.wait_for_timeout = AsyncMock()
        sia.page.wait_for_function = AsyncMock()
        sia.esperar_codigo_disponible = AsyncMock()
        sia.seleccionar_por_codigo = AsyncMock(return_value="0")
        return sia

    async def test_espera_el_codigo_y_valida_la_seleccion_incluso_value_cero(self):
        sia = self.crear_catalogo()
        await sia.seleccionar_plan()
        sia.esperar_codigo_disponible.assert_awaited_once_with(sia.SELECTOR_PLAN, "3501")
        sia.seleccionar_por_codigo.assert_awaited_once_with(sia.SELECTOR_PLAN, "3501", esperar_adf=True)
        sia.page.get_by_text.assert_not_called()
        sia.page.locator.assert_not_called()

    async def test_lista_vieja_se_recupera_desde_facultad_no_desde_mostrar(self):
        sia = self.crear_catalogo()
        sia.esperar_codigo_disponible.side_effect = [TimeoutPlaywright("solo opción vacía"), None]
        await sia.seleccionar_plan()
        self.assertEqual(sia.esperar_codigo_disponible.await_count, 2)
        self.assertEqual(sia.seleccionar_por_codigo.await_args_list[0].args, (sia.SELECTOR_FACULTAD, "3064"))
        self.assertEqual(sia.seleccionar_por_codigo.await_args_list[1].args, (sia.SELECTOR_PLAN, "3501"))
        sia.page.get_by_text.assert_not_called()
        sia.page.locator.assert_not_called()

    async def test_agota_intentos_con_error_que_identifica_la_carrera(self):
        sia = self.crear_catalogo()
        sia.esperar_codigo_disponible.side_effect = TimeoutPlaywright("no disponible")
        with self.assertRaisesRegex(ValueError, "3501.*3064.*3 intentos"):
            await sia.seleccionar_plan()
        self.assertEqual(sia.esperar_codigo_disponible.await_count, 3)
        self.assertEqual(sia.seleccionar_por_codigo.await_count, 2)
        sia.page.get_by_text.assert_not_called()

    async def test_no_sustituye_la_carrera_solicitada_por_otra(self):
        sia = self.crear_catalogo()
        with self.assertRaises(ValueError):
            await sia.seleccionar_plan("3503 Construcción")
        sia.seleccionar_por_codigo.assert_not_awaited()

    async def test_espera_codigo_academico_no_indice_html(self):
        sia = self.crear_catalogo()
        await CatalogoSIA.esperar_codigo_disponible(sia, sia.SELECTOR_PLAN, "3501")
        argumentos = sia.page.wait_for_function.await_args.kwargs
        self.assertEqual(argumentos["arg"]["codigo"], "3501")
        self.assertEqual(argumentos["timeout"], 10000)

    async def test_reasignacion_adf_del_value_repite_por_codigo_academico(self):
        sia = self.crear_catalogo()
        sia.obtener_valor_por_codigo = AsyncMock(side_effect=["3", "0"])
        sia.seleccionar_nativamente = AsyncMock()
        sia.page.wait_for_function.side_effect = [TimeoutPlaywright("ahora es Agropecuarias"), None]
        valor = await CatalogoSIA.seleccionar_por_codigo(sia, sia.SELECTOR_FACULTAD, "3064")
        self.assertEqual(valor, "0")
        self.assertEqual(sia.seleccionar_nativamente.await_count, 2)
        for llamada in sia.page.wait_for_function.await_args_list:
            self.assertEqual(llamada.kwargs["arg"]["codigo"], "3064")


if __name__ == "__main__":
    unittest.main()
