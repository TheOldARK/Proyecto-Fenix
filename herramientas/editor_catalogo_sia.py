"""Consulta ligera del catálogo: nunca abre fichas ni descarga grupos."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace

from PySide6.QtCore import QThread, Signal


async def leer_nombres(sesion, progreso):
    for intento in range(1, 3):
        progreso(f"Consultando códigos y nombres en SIA (intento {intento}/2)…")
        try:
            filas = await asyncio.wait_for(sesion.cargar(), 100)
            nombres = {codigo: str(fila.get("nombre", "")).strip()
                       for codigo, fila in filas.items() if codigo and str(fila.get("nombre", "")).strip()}
            if not nombres:
                raise ValueError("El catálogo no devolvió códigos y nombres; se conserva la consulta anterior.")
            return nombres
        except Exception:
            if intento == 2:
                raise


async def consultar_nombres(clave, plan, progreso):
    from playwright.async_api import async_playwright
    import playwright
    from herramientas.verificar_planes_sia import SesionVerificacion

    progreso("Abriendo el catálogo SIA…")
    async with async_playwright() as p:
        base = Path(playwright.__file__).parent / "driver/package/.local-browsers"
        candidatos = [r for r in base.rglob("*") if r.is_file() and r.name in {
            "chrome-headless-shell.exe", "chrome-headless-shell", "headless_shell"}]
        browser = await p.chromium.launch(headless=True,
            executable_path=str(candidatos[0]) if len(candidatos) == 1 else None)
        try:
            with tempfile.TemporaryDirectory(prefix="fenix-editor-sia-") as temporal:
                sesion = SesionVerificacion(browser, clave, SimpleNamespace(**plan), temporal)
                try:
                    return await leer_nombres(sesion, progreso)
                finally:
                    await sesion.cerrar()
        finally:
            await asyncio.wait_for(browser.close(), 15)


class CatalogoNombresWorker(QThread):
    progreso = Signal(str)
    resultado = Signal(str, dict)
    error = Signal(str)

    def __init__(self, clave, plan, parent=None):
        super().__init__(parent)
        self.clave, self.plan = clave, plan

    async def _ejecutar(self):
        tarea = asyncio.create_task(consultar_nombres(self.clave, self.plan, self.progreso.emit))
        try:
            while not tarea.done():
                if self.isInterruptionRequested():
                    tarea.cancel()
                    break
                await asyncio.sleep(0.2)
            return await tarea
        finally:
            if not tarea.done():
                tarea.cancel()
                try:
                    await tarea
                except asyncio.CancelledError:
                    pass

    def run(self):
        try:
            nombres = asyncio.run(asyncio.wait_for(self._ejecutar(), 240))
            if not self.isInterruptionRequested():
                self.resultado.emit(self.clave, nombres)
        except asyncio.CancelledError:
            self.progreso.emit("Consulta cancelada.")
        except Exception as error:
            self.error.emit(f"{type(error).__name__}: {error}")
