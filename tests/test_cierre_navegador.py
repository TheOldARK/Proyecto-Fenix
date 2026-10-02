import asyncio
import unittest
from unittest.mock import Mock, patch

from infraestructura.sia.navegador import NavegadorSIA


class CierreTests(unittest.IsolatedAsyncioTestCase):
    async def test_cierre_bloqueado_no_impide_continuar(self):
        async def no_termina():
            await asyncio.Event().wait()
        navegador = NavegadorSIA(Mock(), 800, 600)
        contexto = Mock()
        contexto.close = no_termina
        navegador.context = contexto
        navegador.browser = Mock()
        navegador.browser.close = no_termina
        with patch("infraestructura.sia.navegador.TIEMPO_MAXIMO_CIERRE", 0.01):
            await asyncio.wait_for(navegador.cerrar(), timeout=1)
        self.assertIsNone(navegador.context)
        self.assertIsNone(navegador.browser)
