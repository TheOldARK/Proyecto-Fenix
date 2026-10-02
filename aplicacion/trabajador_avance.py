"""Consulta voluntaria del historial del SIA con inicio de sesión manual."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from urllib.parse import urlsplit

from PySide6.QtCore import QThread, Signal

from servicios.historia_academica import (
    EXTRAER_TABLAS_HISTORIA, interpretar_detalle_calificaciones,
    interpretar_tablas_historia,
)


URL_SERVICIOS_SIA = "https://sia.unal.edu.co/ServiciosApp/"


class TrabajadorAvanceAcademico(QThread):
    estado = Signal(str)
    progreso = Signal(int)
    captura = Signal(bytes)
    completado = Signal(object)
    fallo = Signal(str)
    cancelado = Signal()

    def __init__(self, codigo_plan, parent=None):
        super().__init__(parent)
        self.codigo_plan = str(codigo_plan)
        self._bucle = None
        self._tarea = None
        self._vista_activa = threading.Event()

    def activar_vista(self, activa):
        if activa:
            self._vista_activa.set()
        else:
            self._vista_activa.clear()

    def cancelar(self):
        self.requestInterruption()
        if self._bucle is not None and self._tarea is not None:
            try:
                self._bucle.call_soon_threadsafe(self._tarea.cancel)
            except RuntimeError:
                pass

    def run(self):
        try:
            resultado = asyncio.run(self._consultar())
            if self.isInterruptionRequested():
                self.cancelado.emit()
            else:
                self.completado.emit(resultado)
        except asyncio.CancelledError:
            self.cancelado.emit()
        except Exception as error:
            if self.isInterruptionRequested():
                self.cancelado.emit()
            else:
                self.fallo.emit(str(error))
        finally:
            self._bucle = None
            self._tarea = None

    async def _consultar(self):
        from playwright.async_api import async_playwright

        self._bucle = asyncio.get_running_loop()
        self._tarea = asyncio.current_task()
        self.progreso.emit(5)
        self.estado.emit("Abriendo Chrome o Edge para que inicies sesión en el SIA…")
        async with async_playwright() as playwright:
            navegador = await self._abrir_navegador(playwright)
            contexto = None
            tarea_vista = None
            try:
                # El contexto es efímero: cookies, sesión y contraseñas no se guardan.
                contexto = await navegador.new_context(accept_downloads=False)
                pagina = await contexto.new_page()
                await pagina.goto(URL_SERVICIOS_SIA, wait_until="domcontentloaded", timeout=45000)
                self.estado.emit(
                    "Inicia sesión en la ventana del SIA. Fénix esperará sin leer tu contraseña."
                )
                self.progreso.emit(15)
                portal = await self._esperar_portal(contexto, navegador)
                self.progreso.emit(25)
                self.estado.emit("Sesión iniciada. Cerrando la ventana de acceso para consultar sin interrupciones…")
                estado_sesion = await contexto.storage_state()
                sesion_pagina = await portal.evaluate(
                    "() => Object.fromEntries(Array.from({length: sessionStorage.length}, "
                    "(_, i) => [sessionStorage.key(i), sessionStorage.getItem(sessionStorage.key(i))]))"
                )
                url_portal = portal.url
                if urlsplit(url_portal).hostname != "sia.unal.edu.co":
                    raise RuntimeError("El portal autenticado no pertenece al SIA esperado.")
                await contexto.close()
                contexto = None
                await navegador.close()
                navegador = None
                # Cookies y almacenamiento permanecen solo en memoria. El usuario
                # ya no tiene una pestaña en la que alterar la navegación del worker.
                navegador, contexto = await self._abrir_contexto_privado(
                    playwright, estado_sesion, sesion_pagina
                )
                pagina = await contexto.new_page()
                await pagina.goto(url_portal, wait_until="domcontentloaded", timeout=45000)
                try:
                    portal = await asyncio.wait_for(
                        self._esperar_portal(contexto, navegador), timeout=25
                    )
                except asyncio.TimeoutError as error:
                    raise RuntimeError(
                        "El SIA no conservó la sesión al pasar al navegador privado. "
                        "No se importaron datos; vuelve a consultar SIA."
                    ) from error
                tarea_vista = asyncio.create_task(self._emitir_capturas(contexto))
                self.progreso.emit(35)
                self.estado.emit("Buscando Información académica → Mi historia académica…")
                pagina_historia = await self._abrir_historia(contexto, portal)
                await self._seleccionar_plan(pagina_historia)
                self.progreso.emit(50)
                self.estado.emit("Leyendo asignaturas, periodos, notas y resumen de créditos…")
                historia = await self._leer_historia(contexto)
                self.progreso.emit(65)
                self.estado.emit("Abriendo Mis Calificaciones para revisar las notas por materia…")
                try:
                    historia["calificaciones_detalle"] = await self._leer_calificaciones(
                        contexto, pagina_historia
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    # La historia válida no se descarta por un cambio en esta vista del SIA.
                    historia["calificaciones_detalle"] = []
                    historia["aviso_calificaciones"] = (
                        "No se pudieron revisar Mis Calificaciones: "
                        f"{str(error).splitlines()[0]}"
                    )
                self.progreso.emit(100)
                return historia
            finally:
                if tarea_vista is not None:
                    tarea_vista.cancel()
                    try:
                        await tarea_vista
                    except asyncio.CancelledError:
                        pass
                if contexto is not None:
                    try:
                        await contexto.close()
                    except Exception:
                        pass
                if navegador is not None:
                    try:
                        await navegador.close()
                    except Exception:
                        pass

    async def _emitir_capturas(self, contexto):
        """Vista de solo lectura; nunca observa la página visible de acceso."""
        while not self.isInterruptionRequested():
            if self._vista_activa.is_set():
                for pagina in reversed(self._paginas_sia(contexto)):
                    try:
                        imagen = await pagina.screenshot(
                            type="jpeg", quality=45, animations="disabled", timeout=3000
                        )
                        self.captura.emit(imagen)
                        break
                    except Exception:
                        continue
            await asyncio.sleep(1.5)

    @staticmethod
    async def _abrir_navegador(playwright):
        errores = []
        for canal in ("chrome", "msedge"):
            try:
                return await playwright.chromium.launch(channel=canal, headless=False)
            except Exception as error:
                errores.append(f"{canal}: {str(error).splitlines()[0]}")
        try:
            # En desarrollo puede existir Chromium completo; el .exe distribuido
            # incluye solo headless-shell, que no sirve para un login visible.
            return await playwright.chromium.launch(headless=False)
        except Exception as error:
            errores.append(f"Chromium: {str(error).splitlines()[0]}")
        raise RuntimeError(
            "No se pudo abrir un navegador visible. Instala Chrome o Edge y vuelve "
            "a intentarlo. " + "; ".join(errores)
        )

    @staticmethod
    async def _abrir_contexto_privado(playwright, estado_sesion, sesion_pagina):
        from infraestructura.sia.runtime_navegador import ejecutable_integrado

        ejecutable = ejecutable_integrado()
        opciones = {"headless": True}
        if ejecutable:
            opciones["executable_path"] = ejecutable
        navegador = await playwright.chromium.launch(**opciones)
        try:
            contexto = await navegador.new_context(
                accept_downloads=False, storage_state=estado_sesion
            )
            if sesion_pagina:
                valores = json.dumps(sesion_pagina, ensure_ascii=False)
                await contexto.add_init_script(
                    f"if (location.origin === {json.dumps('https://sia.unal.edu.co')}) "
                    f"for (const [k, v] of Object.entries({valores})) "
                    "sessionStorage.setItem(k, v);"
                )
            return navegador, contexto
        except Exception:
            await navegador.close()
            raise

    @staticmethod
    def _paginas_sia(contexto):
        return [
            pagina for pagina in contexto.pages
            if not pagina.is_closed() and pagina.url.startswith(URL_SERVICIOS_SIA.rstrip("/"))
        ]

    async def _esperar_portal(self, contexto, navegador):
        while not self.isInterruptionRequested():
            if not navegador.is_connected() or all(pagina.is_closed() for pagina in contexto.pages):
                raise RuntimeError("Se cerró el navegador antes de consultar la historia académica.")
            for pagina in self._paginas_sia(contexto):
                try:
                    opcion = pagina.get_by_text(
                        re.compile(r"informaci[oó]n acad[eé]mica", re.I)
                    ).first
                    if await opcion.is_visible(timeout=1000):
                        return pagina
                except Exception:
                    continue
            await asyncio.sleep(0.8)
        raise asyncio.CancelledError()

    async def _abrir_historia(self, contexto, portal):
        for intento in range(3):
            if self.isInterruptionRequested():
                raise asyncio.CancelledError()
            try:
                await portal.get_by_text(
                    re.compile(r"informaci[oó]n acad[eé]mica", re.I)
                ).first.click(timeout=8000)
                enlace = portal.get_by_text(
                    re.compile(r"mi historia acad[eé]mica", re.I)
                ).first
                await enlace.click(timeout=8000)
                for _ in range(20):
                    for pagina in self._paginas_sia(contexto):
                        if await pagina.get_by_text(
                            re.compile(r"historia acad[eé]mica", re.I)
                        ).count() and await pagina.locator("table").count():
                            return pagina
                    await asyncio.sleep(0.5)
                return portal
            except Exception:
                if intento == 2:
                    raise RuntimeError(
                        "No se pudo abrir Información académica → Mi historia académica. "
                        "Verifica que el portal haya terminado de cargar."
                    ) from None
                await asyncio.sleep(1)
        return portal

    async def _seleccionar_plan(self, pagina):
        codigo_corto = self.codigo_plan.split(":")[-1]
        selectores_con_planes = 0
        for selector in await pagina.locator("select").all():
            opciones = await selector.locator("option").evaluate_all(
                "items => items.map(item => ({value: item.value, text: item.textContent.trim()}))"
            )
            if not any(re.match(r"^\d{4}\s+\S", opcion["text"]) for opcion in opciones):
                continue
            selectores_con_planes += 1
            coincidencia = next(
                (opcion for opcion in opciones
                 if re.match(rf"^{re.escape(codigo_corto)}\b", opcion["text"])),
                None,
            )
            if coincidencia:
                if await selector.input_value() != coincidencia["value"]:
                    tablas_anteriores = await pagina.locator("table").all_text_contents()
                    await selector.select_option(coincidencia["value"])
                    for _ in range(20):
                        if await pagina.locator("table").all_text_contents() != tablas_anteriores:
                            break
                        await asyncio.sleep(0.5)
                    else:
                        raise RuntimeError(
                            "El SIA no confirmó el cambio al plan del perfil actual. "
                            "No se importaron datos para evitar mezclar planes."
                        )
                return
        if selectores_con_planes:
            raise RuntimeError(
                f"La historia académica no ofrece el plan {codigo_corto} del perfil actual. "
                "No se importaron datos de otro plan."
            )

    async def _leer_historia(self, contexto):
        diagnostico = (0, 0, 0)
        for _ in range(45):
            if self.isInterruptionRequested():
                raise asyncio.CancelledError()
            for pagina in self._paginas_sia(contexto):
                for marco in pagina.frames:
                    try:
                        tablas = await marco.evaluate(EXTRAER_TABLAS_HISTORIA)
                        diagnostico = max(
                            diagnostico,
                            (len(pagina.frames), len(tablas), sum(len(tabla) for tabla in tablas)),
                        )
                        return interpretar_tablas_historia(tablas, self.codigo_plan)
                    except ValueError:
                        continue
                    except Exception:
                        continue
            await asyncio.sleep(1)
        raise RuntimeError(
            "La página está abierta, pero Fénix no pudo interpretar sus asignaturas "
            f"({diagnostico[0]} marcos, {diagnostico[1]} tablas, {diagnostico[2]} filas detectadas). "
            "No se guardó ningún dato."
        )

    async def _leer_calificaciones(self, contexto, pagina):
        enlace = pagina.get_by_text(re.compile(r"mis calificaciones", re.I)).first
        await enlace.click(timeout=10000)
        for _ in range(20):
            if self.isInterruptionRequested():
                raise asyncio.CancelledError()
            if await pagina.get_by_text(re.compile(r"periodo acad[eé]mico", re.I)).count():
                break
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("No apareció el selector de período académico.")

        selector_periodo = None
        periodos = []
        for selector in await pagina.locator("select").all():
            opciones = await selector.locator("option").evaluate_all(
                "items => items.map(item => ({value: item.value, text: item.textContent.trim()}))"
            )
            candidatas = [
                opcion for opcion in opciones
                if re.search(r"\b\d{4}-[12]S\b", opcion["text"], re.I)
            ]
            if candidatas:
                selector_periodo = selector
                periodos = candidatas
                break
        if selector_periodo is None:
            raise RuntimeError("No se encontró un selector con períodos académicos.")

        resultados = []
        for indice, periodo in enumerate(periodos, 1):
            if self.isInterruptionRequested():
                raise asyncio.CancelledError()
            texto_periodo = re.search(r"\d{4}-[12]S", periodo["text"], re.I).group(0)
            self.estado.emit(
                f"Mis Calificaciones: período {texto_periodo} ({indice}/{len(periodos)})…"
            )
            self.progreso.emit(65 + int(30 * (indice - 1) / max(1, len(periodos))))
            await self._seleccionar_periodo_calificaciones(pagina, periodo)
            materias = await self._materias_en_calificaciones(pagina)
            for numero, materia in enumerate(materias, 1):
                if self.isInterruptionRequested():
                    raise asyncio.CancelledError()
                # Al regresar del detalle, el SIA puede restaurar otro período.
                await self._seleccionar_periodo_calificaciones(pagina, periodo)
                self.estado.emit(
                    f"Mis Calificaciones · {texto_periodo}: {materia['nombre']} "
                    f"({numero}/{len(materias)})…"
                )
                self.progreso.emit(65 + int(30 * ((indice - 1) + numero / max(1, len(materias))) / max(1, len(periodos))))
                localizador = pagina.get_by_text(
                    re.compile(rf"\({re.escape(materia['codigo'])}\)")
                ).first
                try:
                    await localizador.click(timeout=8000)
                    await pagina.get_by_text(
                        re.compile(r"datos de los parciales", re.I)
                    ).first.wait_for(state="visible", timeout=10000)
                    texto_detalle = await pagina.locator("body").inner_text()
                    resultados.append(interpretar_detalle_calificaciones(
                        texto_detalle, texto_periodo, materia["codigo"], materia["nombre"]
                    ))
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    resultados.append({
                        "periodo": texto_periodo,
                        "codigo": materia["codigo"],
                        "nombre": materia["nombre"],
                        "parciales": [],
                        "error": str(error).splitlines()[0],
                    })
                finally:
                    # El detalle no tiene selector de período. Volver primero a
                    # la lista, incluso si falló la lectura de esta materia.
                    await self._abrir_lista_calificaciones(pagina)
        return resultados

    @staticmethod
    async def _seleccionar_periodo_calificaciones(pagina, periodo):
        await TrabajadorAvanceAcademico._abrir_lista_calificaciones(pagina)
        for selector in await pagina.locator("select").all():
            opciones = await selector.locator("option").evaluate_all(
                "items => items.map(item => item.value)"
            )
            if periodo["value"] not in opciones:
                continue
            if await selector.input_value() != periodo["value"]:
                await selector.select_option(periodo["value"])
                await asyncio.sleep(0.7)
            return
        raise RuntimeError("El selector de período desapareció de Mis Calificaciones.")

    @staticmethod
    async def _abrir_lista_calificaciones(pagina):
        async def tiene_selector():
            for selector in await pagina.locator("select").all():
                opciones = await selector.locator("option").all_text_contents()
                if any(re.search(r"\b\d{4}-[12]S\b", texto, re.I) for texto in opciones):
                    return True
            return False

        if await tiene_selector():
            return
        volver = pagina.get_by_text(re.compile(r"^volver$", re.I)).first
        if await volver.count():
            try:
                await volver.click(timeout=8000)
            except Exception:
                pass
        for intento in range(30):
            if await tiene_selector():
                return
            if intento == 10:
                # En algunas respuestas del SIA «Volver» no regresa a la lista.
                await pagina.get_by_text(re.compile(r"^mis calificaciones$", re.I)).first.click(timeout=8000)
            await asyncio.sleep(0.5)
        raise RuntimeError("No se pudo volver a la lista de Mis Calificaciones.")

    @staticmethod
    async def _materias_en_calificaciones(pagina):
        textos = await pagina.get_by_text(
            re.compile(r"\(\d{5,}(?:-[A-Za-z0-9]+)?\)")
        ).all_text_contents()
        materias = {}
        for texto in textos:
            texto = " ".join(texto.split())
            if len(texto) > 180:
                continue
            codigo = re.search(r"\((\d{5,}(?:-[A-Za-z0-9]+)?)\)", texto)
            if codigo and codigo.group(1) not in materias:
                materias[codigo.group(1)] = {
                    "codigo": codigo.group(1), "nombre": texto[:codigo.start()].strip()
                }
        return list(materias.values())
