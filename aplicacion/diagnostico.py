"""Comprobación del paquete instalado, sin descargar la oferta del estudiante."""

import asyncio
import logging
import os
from pathlib import Path
import sys
import traceback

import playwright as playwright_package

from configuracion import CARPETA_DATOS, CARPETA_RECURSOS, URL_SIA, VERSION
from infraestructura.almacenamiento.json_atomico import guardar_json_atomico


async def comprobar_navegador(consultar_sia):
    from playwright.async_api import async_playwright
    from infraestructura.sia.runtime_navegador import ejecutable_integrado

    async with async_playwright() as playwright:
        carpeta_navegadores = (
            Path(playwright_package.__file__).parent
            / "driver" / "package" / ".local-browsers"
        )
        ejecutables = list(
            carpeta_navegadores.glob(
                "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"
            )
        )
        integrado = ejecutable_integrado()
        if integrado:
            ejecutables = [Path(integrado)] if Path(integrado).is_file() else []
        if len(ejecutables) != 1:
            raise FileNotFoundError("No se encontró una única copia del Chromium integrado.")
        ejecutable = ejecutables[0]
        navegador = await playwright.chromium.launch(headless=True, executable_path=integrado)
        try:
            pagina = await navegador.new_page()
            await pagina.set_content("<title>Fenix</title><h1>Navegador disponible</h1>")
            if await pagina.title() != "Fenix":
                raise RuntimeError("Chromium no pudo procesar la página de comprobación.")
            resultado = {"version": navegador.version, "ejecutable": str(ejecutable)}
            if consultar_sia:
                respuesta = await pagina.goto(URL_SIA, wait_until="domcontentloaded", timeout=90000)
                if respuesta is None or not respuesta.ok:
                    raise RuntimeError("El catálogo del SIA no respondió correctamente.")
                await pagina.locator('select[name="pt1:r1:0:soc1"]').wait_for(timeout=60000)
                resultado["sia"] = "Formulario del catálogo accesible"
            return resultado
        finally:
            await navegador.close()


def comprobar_instalacion(consultar_sia=False):
    """Devuelve un código de salida y guarda resultados legibles para soporte."""
    resultado = {"version": VERSION, "empaquetado": bool(getattr(sys, "frozen", False))}
    destino = CARPETA_DATOS / "logs" / "diagnostico_instalacion.json"
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import qInstallMessageHandler, qVersion
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication
        from aplicacion.interfaz import CuadriculaHorario, DialogoPlan
        from infraestructura.almacenamiento.plan_estudios import cargar_planes

        app = QApplication.instance() or QApplication([])
        mensajes = []
        anterior = qInstallMessageHandler(lambda tipo, contexto, mensaje: mensajes.append(mensaje))
        try:
            planes = cargar_planes()
            if not planes:
                raise RuntimeError("El paquete no contiene planes de estudio.")
            for nombre in ("logo.png", "qr_donaciones.png", "gracias2.png"):
                if QPixmap(str(CARPETA_RECURSOS / nombre)).isNull():
                    raise RuntimeError(f"No se pudo cargar el recurso {nombre}.")
            dialogo = DialogoPlan(planes, {}, {}, {}, materias_libres=[])
            horario = CuadriculaHorario()
            horario.actualizar([])
            if dialogo.grab().isNull() or horario.grab().isNull():
                raise RuntimeError("Qt no pudo dibujar la interfaz.")
            app.processEvents()
            errores = [mensaje for mensaje in mensajes if "stylesheet" in mensaje.lower()]
            if errores:
                raise RuntimeError("\n".join(errores))
            resultado["interfaz"] = {"qt": qVersion(), "planes": len(planes), "estilos": "correctos"}
            dialogo.close()
            horario.close()
        finally:
            qInstallMessageHandler(anterior)
        resultado["navegador"] = asyncio.run(comprobar_navegador(consultar_sia))
        resultado["correcto"] = True
    except Exception:
        resultado["correcto"] = False
        resultado["error"] = traceback.format_exc()
        logging.getLogger("fenix").exception("Falló el diagnóstico de instalación")
    guardar_json_atomico(destino, resultado)
    print(f"Diagnóstico guardado en {destino}", flush=True)
    return 0 if resultado["correcto"] else 1
