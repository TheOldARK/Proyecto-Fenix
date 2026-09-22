"""Worker de prueba: Chromium real y cancelación cooperativa de producción."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infraestructura.almacenamiento.cancelacion_actualizacion import token_cancelacion, actualizacion_cancelada
from infraestructura.almacenamiento.estado_actualizacion import guardar_estado
from playwright.async_api import async_playwright


async def main():
    token = token_cancelacion()
    async with async_playwright() as p:
        navegador = await p.chromium.launch(executable_path=sys.argv[1], headless=True)
        pagina = await navegador.new_page()
        await pagina.set_content('<h1>Worker activo</h1>')
        Path(sys.argv[2]).write_text('Chromium abierto', encoding='utf-8')
        guardar_estado('actualizando', 'Worker de prueba activo', 10)
        while not actualizacion_cancelada(token):
            await asyncio.sleep(0.1)
        await navegador.close()
    guardar_estado('cancelada', 'Chromium cerrado', None)
    Path(sys.argv[2] + '.cerrado').write_text('Cierre cooperativo completo', encoding='utf-8')


asyncio.run(main())
