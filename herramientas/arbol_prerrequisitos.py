"""Explora las relaciones de prerrequisitos de cualquier plan del SIA.

La consulta se ejecuta en un proceso hijo con un directorio de datos temporal:
no modifica el plan, la oferta ni las materias del usuario de Fénix.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from collections import defaultdict, deque
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from dominio.codigos import codigo_base
from PySide6.QtCore import QPointF, Qt, QProcess, QProcessEnvironment
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

def nombre_materia_limpio(nombre: str, descripcion: str = "") -> str:
    """Quita una descripción duplicada al final del nombre de una materia."""
    nombre = re.sub(r"\s+", " ", str(nombre or "")).strip()
    descripcion = re.sub(r"\s+", " ", str(descripcion or "")).strip()
    if not nombre or not descripcion:
        return nombre

    coincidencia = re.search(
        rf"(?:\s*[|·—–:;-]\s*|\s+){re.escape(descripcion)}\s*$",
        nombre,
        flags=re.IGNORECASE,
    )
    if coincidencia:
        nombre_limpio = nombre[:coincidencia.start()].rstrip(" |·—–:;-")
        if nombre_limpio:
            return nombre_limpio
    return nombre


def construir_grafo(materias: list[dict]) -> dict:
    """Prepara nodos, dependencias, niveles y cursos sin prerrequisitos."""
    por_codigo = {}
    codigo_canonico = {}
    for materia in materias:
        codigo = str(materia.get("codigo", "")).strip()
        if not codigo:
            continue
        por_codigo[codigo] = materia
        codigo_canonico.setdefault(codigo_base(codigo), codigo)
    nombre_canonico = {
        nombre_materia_limpio(
            materia.get("nombre", ""), materia.get("descripcion", "")
        ).casefold(): codigo
        for codigo, materia in por_codigo.items()
        if nombre_materia_limpio(
            materia.get("nombre", ""), materia.get("descripcion", "")
        )
    }

    nodos = {
        codigo: {
            "codigo": codigo,
            "nombre": nombre_materia_limpio(
                materia.get("nombre", ""), materia.get("descripcion", "")
            ) or "Materia sin nombre",
            "tipologia": str(materia.get("tipologia", "")),
            "externo": False,
        }
        for codigo, materia in por_codigo.items()
    }
    aristas = set()
    sin_prerrequisitos = []
    prereq_por_materia = {}

    for codigo, materia in por_codigo.items():
        requisitos = materia.get("prerrequisitos") or []
        validos = []
        for requisito in requisitos:
            if not isinstance(requisito, dict):
                continue
            req_codigo = str(requisito.get("codigo", "")).strip()
            req_nombre = str(requisito.get("nombre", "")).strip()
            if not req_codigo and not req_nombre:
                continue
            req_codigo = codigo_canonico.get(codigo_base(req_codigo), req_codigo)
            if req_codigo not in nodos and req_nombre.casefold() in nombre_canonico:
                req_codigo = nombre_canonico[req_nombre.casefold()]
            if req_codigo not in nodos:
                clave = req_codigo or f"externo:{req_nombre.casefold()}"
                nodos.setdefault(clave, {
                    "codigo": req_codigo or "Fuera del plan",
                    "nombre": req_nombre or f"Requisito {req_codigo}",
                    "tipologia": "Prerrequisito externo",
                    "externo": True,
                })
                if req_codigo:
                    req_codigo = clave
            if req_codigo and req_codigo != codigo:
                aristas.add((req_codigo, codigo))
                validos.append(req_codigo)
        prereq_por_materia[codigo] = validos
        if not validos:
            sin_prerrequisitos.append(nodos[codigo])

    # Orden topológico; cualquier ciclo se conserva y se informa como tal.
    entradas = {codigo: 0 for codigo in nodos}
    siguientes = defaultdict(list)
    for origen, destino in aristas:
        siguientes[origen].append(destino)
        entradas[destino] += 1
    cola = deque(sorted(codigo for codigo, cuenta in entradas.items() if cuenta == 0))
    niveles = {codigo: 0 for codigo in cola}
    ordenados = []
    while cola:
        codigo = cola.popleft()
        ordenados.append(codigo)
        for destino in siguientes[codigo]:
            niveles[destino] = max(niveles.get(destino, 0), niveles[codigo] + 1)
            entradas[destino] -= 1
            if entradas[destino] == 0:
                cola.append(destino)
    ciclicos = sorted(set(nodos) - set(ordenados))
    for codigo in ciclicos:
        niveles[codigo] = max((niveles.get(origen, 0) + 1 for origen, destino in aristas if destino == codigo), default=0)

    return {
        "nodos": nodos,
        "aristas": sorted(aristas),
        "niveles": niveles,
        "sin_prerrequisitos": sin_prerrequisitos,
        "ciclicos": ciclicos,
        "materias": list(por_codigo.values()),
    }


def ordenar_capas_por_conexiones(grafo: dict, pasadas: int = 8) -> dict[int, list[str]]:
    """Reduce cruces reordenando cada columna según sus padres e hijos."""
    por_nivel = defaultdict(list)
    for codigo, nivel in grafo["niveles"].items():
        por_nivel[nivel].append(codigo)
    for codigos in por_nivel.values():
        codigos.sort(key=lambda c: (grafo["nodos"][c]["externo"], grafo["nodos"][c]["nombre"].casefold(), c))

    padres = defaultdict(list)
    hijos = defaultdict(list)
    for origen, destino in grafo["aristas"]:
        hijos[origen].append(destino)
        padres[destino].append(origen)

    def posiciones_actuales():
        return {
            codigo: (indice + 0.5) / len(codigos)
            for codigos in por_nivel.values()
            for indice, codigo in enumerate(codigos)
        }

    def ordenar_nivel(nivel, vecinos):
        posiciones = posiciones_actuales()
        codigos = por_nivel[nivel]

        def clave(codigo):
            relacionados = [posiciones[otro] for otro in vecinos[codigo] if otro in posiciones]
            if not relacionados:
                centro = (codigos.index(codigo) + 0.5) / len(codigos)
                return centro, grafo["nodos"][codigo]["nombre"].casefold(), codigo
            return sum(relacionados) / len(relacionados), grafo["nodos"][codigo]["nombre"].casefold(), codigo

        por_nivel[nivel] = sorted(codigos, key=clave)

    niveles = sorted(por_nivel)
    for _ in range(max(1, pasadas)):
        for nivel in niveles[1:]:
            ordenar_nivel(nivel, padres)
        for nivel in reversed(niveles[:-1]):
            ordenar_nivel(nivel, hijos)
    return dict(por_nivel)


def codigos_visibles_en_arbol(grafo: dict) -> set[str]:
    """Muestra todas las obligatorias y otros nodos con flechas salientes."""
    obligatorias = {
        codigo
        for codigo, nodo in grafo["nodos"].items()
        if not nodo.get("externo") and es_materia_obligatoria(nodo.get("tipologia", ""))
    }
    con_sucesores = {origen for origen, _destino in grafo["aristas"]}
    return obligatorias | con_sucesores


def tonos_por_origen(grafo: dict) -> dict[str, int]:
    """Asigna un tono distintivo y estable a cada materia de origen."""
    origenes = sorted({origen for origen, _destino in grafo["aristas"]})
    cantidad = max(1, len(origenes))
    return {origen: int((18 + indice * 360 / cantidad) % 360) for indice, origen in enumerate(origenes)}


def _es_libre_eleccion(materia: dict) -> bool:
    texto = str(materia.get("tipologia", "")).casefold()
    return "libre elección" in texto or "libre eleccion" in texto


def etiqueta_tipo(tipologia: str) -> str:
    texto = tipologia.casefold()
    if "optativa" in texto:
        return "OPTATIVA"
    if "obligatoria" in texto or "obligatoria" in texto:
        return "OBLIGATORIA"
    if "nivelación" in texto or "nivelacion" in texto:
        return "NIVELACIÓN"
    if "trabajo de grado" in texto:
        return "TRABAJO DE GRADO"
    return tipologia.strip().upper() or "TIPO NO INDICADO"


def es_materia_obligatoria(tipologia: str) -> bool:
    return "obligatoria" in str(tipologia).casefold()


def _buscar_ruta(catalogo: dict, clave: str):
    for nivel in catalogo.get("niveles_estudio", []):
        for sede in nivel.get("sedes", []):
            for facultad in sede.get("facultades", []):
                for plan in facultad.get("planes_estudio", []):
                    if ":".join(str(x.get("codigo", "")) for x in (sede, facultad, plan)) == str(clave):
                        return nivel, sede, facultad, plan
    raise ValueError(f"No se encontró en el catálogo SIA la ruta {clave}.")


def crear_entorno_datos_temporal(ruta_datos: Path, catalogo: dict, codigo_plan: str, valor_nivel: str) -> None:
    ruta_datos.mkdir(parents=True, exist_ok=True)
    catalogo_filtrado = {
        **catalogo,
        "niveles_estudio": [n for n in catalogo.get("niveles_estudio", []) if str(n.get("value")) == str(valor_nivel)],
    }
    (ruta_datos / "catalogo_sia.json").write_text(json.dumps(catalogo_filtrado, ensure_ascii=False), encoding="utf-8")
    _nivel, sede, facultad, plan = _buscar_ruta(catalogo_filtrado, codigo_plan)
    # Esta estructura sintética solo satisface la configuración heredada que
    # CatalogoSIA carga al iniciar; la consulta de esta herramienta omite LE.
    config_libres = {
        str(sede["codigo"]): {
            "sede": sede["nombre"],
            "planes": {
                f"{facultad['codigo']}:{plan['codigo']}": {
                    "facultades_libre_eleccion": [facultad["nombre"]],
                }
            },
        }
    }
    (ruta_datos / "configuracion_libre_eleccion.json").write_text(json.dumps(config_libres, ensure_ascii=False), encoding="utf-8")
    (ruta_datos / "estudiante.json").write_text(
        json.dumps({"plan_estudios": codigo_plan, "materias_aprobadas": [], "grupos_seleccionados": []}, ensure_ascii=False),
        encoding="utf-8",
    )


async def _descubrir_catalogo_sia() -> dict:
    """Lee en vivo el árbol sede/facultad/plan del catálogo público del SIA."""
    from playwright.async_api import async_playwright
    from configuracion import URL_SIA

    selectors = {
        "nivel": 'select[name="pt1:r1:0:soc1"]',
        "sede": 'select[name="pt1:r1:0:soc9"]',
        "facultad": 'select[name="pt1:r1:0:soc2"]',
        "plan": 'select[name="pt1:r1:0:soc3"]',
        "tipologia": 'select[name="pt1:r1:0:soc4"]',
    }

    async def opciones(page, selector):
        return await page.locator(f"{selector} option").evaluate_all(
            "items => items.map(o => ({value:o.value, nombre:o.textContent.trim(), disabled:o.disabled}))"
        )

    async def elegir(page, selector, value, selector_dependiente):
        anterior = await opciones(page, selector_dependiente)
        await page.locator(selector).select_option(value=value, timeout=45000)
        try:
            await page.wait_for_function(
                "({selector, previous}) => { const e=document.querySelector(selector); "
                "if (!e || e.disabled || !e.options.length) return false; "
                "const now=Array.from(e.options).map(o=>o.value+'|'+o.textContent.trim()).join('\\n'); "
                "const old=previous.map(o=>o.value+'|'+o.nombre).join('\\n'); return now !== old; }",
                arg={"selector": selector_dependiente, "previous": anterior},
                timeout=12000,
            )
        except Exception:
            # Algunas ramas devuelven exactamente la misma lista de opciones.
            await page.wait_for_timeout(800)
            await page.locator(selector_dependiente).wait_for(state="visible", timeout=45000)
        await page.wait_for_timeout(180)

    def codigo(nombre):
        coincidencia = re.match(r"\s*(\d+)\s+", nombre or "")
        return coincidencia.group(1) if coincidencia else ""

    resultado = {"niveles_estudio": [], "tipologias": []}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(URL_SIA, wait_until="domcontentloaded", timeout=60000)
            await page.locator(selectors["nivel"]).wait_for(state="visible", timeout=60000)
            niveles = [
                o for o in await opciones(page, selectors["nivel"])
                if o["value"] and not o["disabled"] and "pregrado" in o["nombre"].casefold()
            ]
            for opcion_nivel in niveles:
                nivel = {"value": opcion_nivel["value"], "nombre": opcion_nivel["nombre"], "sedes": []}
                await elegir(page, selectors["nivel"], opcion_nivel["value"], selectors["sede"])
                sedes = [o for o in await opciones(page, selectors["sede"]) if o["value"] and not o["disabled"]]
                for opcion_sede in sedes:
                    sede = {"value": opcion_sede["value"], "nombre": opcion_sede["nombre"], "codigo": codigo(opcion_sede["nombre"]), "facultades": []}
                    await elegir(page, selectors["sede"], opcion_sede["value"], selectors["facultad"])
                    facultades = [o for o in await opciones(page, selectors["facultad"]) if o["value"] and not o["disabled"]]
                    for opcion_facultad in facultades:
                        facultad = {"value": opcion_facultad["value"], "nombre": opcion_facultad["nombre"], "codigo": codigo(opcion_facultad["nombre"]), "planes_estudio": []}
                        await elegir(page, selectors["facultad"], opcion_facultad["value"], selectors["plan"])
                        planes = [o for o in await opciones(page, selectors["plan"]) if o["value"] and not o["disabled"]]
                        for opcion_plan in planes:
                            facultad["planes_estudio"].append({"value": opcion_plan["value"], "nombre": opcion_plan["nombre"], "codigo": codigo(opcion_plan["nombre"])})
                        if facultad["planes_estudio"]:
                            sede["facultades"].append(facultad)
                    if sede["facultades"]:
                        nivel["sedes"].append(sede)
                if nivel["sedes"]:
                    resultado["niveles_estudio"].append(nivel)
            resultado["tipologias"] = [
                {"value": o["value"], "nombre": o["nombre"]}
                for o in await opciones(page, selectors["tipologia"])
                if o["value"] and not o["disabled"]
            ]
        finally:
            await browser.close()
    if not resultado["niveles_estudio"]:
        raise RuntimeError("El SIA no devolvió sedes ni planes de estudio.")
    return resultado


def ejecutar_descubrimiento(destino: Path) -> int:
    try:
        catalogo = asyncio.run(_descubrir_catalogo_sia())
        destino.write_text(json.dumps(catalogo, ensure_ascii=False), encoding="utf-8")
        total_sedes = sum(len(nivel["sedes"]) for nivel in catalogo["niveles_estudio"])
        print(f"Catálogo listo: {total_sedes} sedes encontradas en el SIA.", flush=True)
        return 0
    except Exception as error:
        print(f"No se pudieron cargar las rutas del SIA: {type(error).__name__}: {error}", flush=True)
        return 1


def ejecutar_worker(codigo_plan: str, valor_nivel: str, destino: Path, ruta_datos: Path) -> int:
    """Entrada hija: importa Fénix solo después de aislar FENIX_DATA_DIR."""
    os.environ["FENIX_DATA_DIR"] = str(ruta_datos)
    sys.path.insert(0, str(RAIZ))
    try:
        import asyncio
        from servicios.actualizacion import actualizar

        resultado = asyncio.run(actualizar(
            codigo_plan=codigo_plan,
            priorizar_estudiante=False,
            omitir_libre_eleccion=True,
        ))
        materias = [
            materia if isinstance(materia, dict) else {
                "codigo": materia.codigo,
                "nombre": materia.nombre,
                "descripcion": materia.descripcion,
                "tipologia": materia.tipologia,
                "prerrequisitos": [vars(p) for p in materia.prerrequisitos],
            }
            for materia in resultado.get("materias", [])
        ]
        materias = [materia for materia in materias if not _es_libre_eleccion(materia)]
        destino.write_text(json.dumps({
            "materias": materias,
            "materias_fallidas": resultado.get("materias_fallidas", []),
        }, ensure_ascii=False), encoding="utf-8")
        print(f"\nAnálisis listo: {len(materias)} materias del catálogo de la carrera.", flush=True)
        return 0
    except Exception as error:
        print(f"\nNo se pudo completar la consulta: {type(error).__name__}: {error}", flush=True)
        return 1


class TarjetaMateriaItem(QGraphicsPathItem):
    """Tarjeta movible; al cambiar de posición avisa a sus conexiones."""

    def __init__(self, codigo: str, nombre: str, tipologia: str, ancho: float, alto: float, externa: bool = False):
        super().__init__()
        self.codigo = codigo
        self.ancho = ancho
        self.alto = alto
        self.conexiones: list[ConexionItem] = []
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setData(0, codigo)
        self.setToolTip("Arrastra para mover esta materia")
        self.setBrush(QBrush(QColor("#303030" if externa else "#252525")))
        self.setPen(QPen(QColor("#555555"), 1))

        titulo = QGraphicsTextItem(nombre, self)
        titulo.setDefaultTextColor(QColor("#f2f2f2"))
        titulo.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        titulo.setTextWidth(ancho - 30)
        titulo.setPos(14, 10)
        titulo.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        titulo.setZValue(1)
        self._titulo = titulo

        # Mantener todo el nombre visible, incluso si ocupa varias líneas.
        alto_titulo = titulo.boundingRect().height()
        self.alto = max(alto, alto_titulo + 50)
        forma = QPainterPath()
        forma.addRoundedRect(0, 0, ancho, self.alto, 9, 9)
        self.setPath(forma)

        tipo = "PRERREQUISITO EXTERNO" if externa else etiqueta_tipo(tipologia)
        info = QGraphicsTextItem(f"{codigo}  ·  {tipo}", self)
        info.setDefaultTextColor(QColor("#b8c7d9"))
        info.setFont(QFont("Segoe UI", 8))
        info.setTextWidth(ancho - 28)
        info.setPos(14, self.alto - info.boundingRect().height() - 10)
        info.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        info.setZValue(1)
        self._info = info

        if not externa and es_materia_obligatoria(tipologia):
            indicador = QGraphicsLineItem(4, 12, 4, self.alto - 12, self)
            indicador.setPen(QPen(QColor("#ffd54a"), 4))
            indicador.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            indicador.setToolTip("Materia obligatoria")
            indicador.setZValue(2)
            self._indicador_obligatoria = indicador

    def itemChange(self, cambio, valor):
        resultado = super().itemChange(cambio, valor)
        if cambio == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for conexion in self.conexiones:
                conexion.actualizar()
        return resultado


class ConexionItem(QGraphicsPathItem):
    """Flecha que recalcula sus anclajes al moverse cualquiera de sus tarjetas."""

    def __init__(self, origen: TarjetaMateriaItem | None, destino: TarjetaMateriaItem, inicio_fijo: QPointF | None, color: QColor, tooltip: str):
        super().__init__()
        self.origen = origen
        self.destino = destino
        self.inicio_fijo = inicio_fijo
        self.ancho_tarjeta = destino.ancho
        self.alto_tarjeta = destino.alto
        self.setPen(QPen(color, 2))
        self.setZValue(-1)
        self.setToolTip(tooltip)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.punta = QGraphicsPolygonItem(self)
        self.punta.setBrush(QBrush(color))
        self.punta.setPen(QPen(color, 1))
        self.punta.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        destino.conexiones.append(self)
        if origen is not None:
            origen.conexiones.append(self)
        self.actualizar()

    def actualizar(self):
        if self.origen is not None:
            inicio = self.origen.mapToScene(QPointF(self.origen.ancho, self.origen.alto / 2))
        else:
            inicio = self.inicio_fijo
        fin = self.destino.mapToScene(QPointF(0, self.alto_tarjeta / 2))
        direccion = 1 if fin.x() >= inicio.x() else -1
        distancia = max(35, abs(fin.x() - inicio.x()) * 0.45)
        control_inicio = QPointF(inicio.x() + direccion * distancia, inicio.y())
        control_fin = QPointF(fin.x() - direccion * distancia, fin.y())
        trazado = QPainterPath(inicio)
        trazado.cubicTo(control_inicio, control_fin, fin)
        self.setPath(trazado)
        self.punta.setVisible(abs(fin.x() - inicio.x()) > 10)
        tangente = trazado.pointAtPercent(0.99)
        dx, dy = fin.x() - tangente.x(), fin.y() - tangente.y()
        longitud = max(1, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / longitud, dy / longitud
        base = QPointF(fin.x() - ux * 9, fin.y() - uy * 9)
        perpendicular = QPointF(-uy * 5, ux * 5)
        self.punta.setPolygon(QPolygonF([
            fin,
            base + perpendicular,
            base - perpendicular,
        ]))


class VistaGrafo(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor("#121212"))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setToolTip("Rueda: zoom · Arrastra una tarjeta para moverla · Arrastra el fondo para desplazarte")
        self.zoom_factor = 1.0
        self._desplazando_fondo = False
        self._ultima_posicion = None
        self.setScene(QGraphicsScene(self))

    def mousePressEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton and self._tarjeta_en(evento.pos()) is None:
            self._desplazando_fondo = True
            self._ultima_posicion = evento.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            evento.accept()
            return
        tarjeta = self._tarjeta_en(evento.pos())
        if tarjeta is not None:
            tarjeta.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(evento)

    def _tarjeta_en(self, posicion):
        item = self.itemAt(posicion)
        while item is not None and not isinstance(item, TarjetaMateriaItem):
            item = item.parentItem()
        return item

    def mouseMoveEvent(self, evento):
        if self._desplazando_fondo and self._ultima_posicion is not None:
            delta = evento.pos() - self._ultima_posicion
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self._ultima_posicion = evento.pos()
            evento.accept()
            return
        super().mouseMoveEvent(evento)

    def mouseReleaseEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton and self._desplazando_fondo:
            self._desplazando_fondo = False
            self._ultima_posicion = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            evento.accept()
            return
        tarjeta = self._tarjeta_en(evento.pos())
        if tarjeta is not None:
            tarjeta.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(evento)
        if tarjeta is not None and self.scene() is not None:
            self.scene().setSceneRect(
                self.scene().itemsBoundingRect().adjusted(-600, -600, 600, 600)
            )

    def wheelEvent(self, evento):
        paso = 1.2 if evento.angleDelta().y() > 0 else 1 / 1.2
        nuevo_zoom = self.zoom_factor * paso
        if 0.2 <= nuevo_zoom <= 5.0:
            self.scale(paso, paso)
            self.zoom_factor = nuevo_zoom
        evento.accept()

    def mostrar(self, grafo: dict):
        escena = self.scene()
        escena.clear()
        por_nivel = ordenar_capas_por_conexiones(grafo)
        visibles = codigos_visibles_en_arbol(grafo)
        tonos = tonos_por_origen(grafo)
        ancho, alto, separacion_y, margen = 250, 112, 24, 44
        columnas_visibles = {
            nivel: [codigo for codigo in codigos if codigo in visibles]
            for nivel, codigos in por_nivel.items()
        }
        columnas_visibles = {nivel: codigos for nivel, codigos in columnas_visibles.items() if codigos}
        tarjetas = {}
        for codigos in columnas_visibles.values():
            for codigo in codigos:
                nodo = grafo["nodos"][codigo]
                tarjetas[codigo] = TarjetaMateriaItem(
                    codigo,
                    nodo["nombre"],
                    nodo["tipologia"],
                    ancho,
                    alto,
                    externa=nodo["externo"],
                )

        alturas_columnas = {
            nivel: sum(tarjetas[codigo].alto + separacion_y for codigo in codigos) - separacion_y
            for nivel, codigos in columnas_visibles.items()
        }
        alto_maximo = max(alturas_columnas.values(), default=0)
        posiciones = {}
        for nivel in sorted(columnas_visibles):
            y = margen + (alto_maximo - alturas_columnas[nivel]) / 2
            x = margen + nivel * (ancho + 110)
            for codigo in columnas_visibles[nivel]:
                posiciones[codigo] = (x, y)
                y += tarjetas[codigo].alto + separacion_y

        for codigo, (x, y) in posiciones.items():
            tarjeta = tarjetas[codigo]
            tarjeta.setPos(x, y)
            escena.addItem(tarjeta)

        for origen, destino in grafo["aristas"]:
            destino_item = tarjetas.get(destino)
            if destino_item is None:
                continue
            origen_item = tarjetas.get(origen)
            if origen_item is None:
                continue
            inicio_fijo = None
            texto_ayuda = f"Sale de {grafo['nodos'][origen]['nombre']} ({grafo['nodos'][origen]['codigo']})"
            color_linea = QColor.fromHsv(tonos[origen], 190, 245)
            conexion = ConexionItem(origen_item, destino_item, inicio_fijo, color_linea, texto_ayuda)
            escena.addItem(conexion)

        if not escena.items():
            return
        escena.setSceneRect(escena.itemsBoundingRect().adjusted(-margen, -margen, margen, margen))
        if escena.items():
            self.resetTransform()
            self.zoom_factor = 1.0
            self.horizontalScrollBar().setValue(0)
            self.verticalScrollBar().setValue(0)


class VentanaArbol(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Explorador de prerrequisitos — Fénix")
        self.resize(1280, 800)
        self.proceso = None
        self.proceso_descubrimiento = None
        self.descubrimiento_finalizado = False
        self.temporal = None
        self.ruta_salida = None
        self.catalogo = self._cargar_catalogo_local()
        self.planes = self._aplanar_rutas(self.catalogo)

        raiz = QWidget()
        layout = QVBoxLayout(raiz)
        selector = QHBoxLayout()
        self.sede = QComboBox()
        self.facultad = QComboBox()
        self.plan = QComboBox()
        for etiqueta, combo in (("Sede", self.sede), ("Facultad", self.facultad), ("Plan", self.plan)):
            selector.addWidget(QLabel(etiqueta))
            selector.addWidget(combo, 1)
        layout.addLayout(selector)

        controles = QHBoxLayout()
        self.boton_rutas = QPushButton("Actualizar sedes desde SIA")
        self.boton_rutas.clicked.connect(self._iniciar_descubrimiento)
        self.boton = QPushButton("Consultar SIA y construir árbol")
        self.boton.clicked.connect(self.consultar)
        self.estado = QLabel("El análisis no depende del semestre ni modifica los datos de Fénix.")
        self.progreso = QProgressBar()
        self.progreso.setRange(0, 0)
        self.progreso.hide()
        controles.addWidget(self.boton_rutas)
        controles.addWidget(self.boton)
        controles.addWidget(self.estado, 1)
        controles.addWidget(self.progreso)
        layout.addLayout(controles)

        dividir = QSplitter(Qt.Orientation.Horizontal)
        self.vista = VistaGrafo()
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.addWidget(QLabel("Materias sin prerrequisitos"))
        self.lista = QListWidget()
        panel_layout.addWidget(self.lista)
        self.resumen = QLabel("Aún no se ha consultado un plan.")
        self.resumen.setWordWrap(True)
        panel_layout.addWidget(self.resumen)
        dividir.addWidget(self.vista)
        dividir.addWidget(panel)
        dividir.setStretchFactor(0, 5)
        dividir.setStretchFactor(1, 1)
        layout.addWidget(dividir, 1)
        self.setCentralWidget(raiz)

        self.sede.currentIndexChanged.connect(self._actualizar_facultades)
        self.facultad.currentIndexChanged.connect(self._actualizar_planes)
        self._actualizar_sedes()
        self._iniciar_descubrimiento()

    @staticmethod
    def _ruta_cache():
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Fenix" / "herramientas" / "arbol_prerrequisitos" / "catalogo_sia.json"

    def _cargar_catalogo_local(self):
        sys.path.insert(0, str(RAIZ))
        from configuracion import ARCHIVO_CATALOGO_SIA
        for ruta in (self._ruta_cache(), ARCHIVO_CATALOGO_SIA):
            try:
                with ruta.open("r", encoding="utf-8") as archivo:
                    datos = json.load(archivo)
                if datos.get("niveles_estudio"):
                    return datos
            except (OSError, json.JSONDecodeError):
                continue
        return {"niveles_estudio": [], "tipologias": []}

    @staticmethod
    def _aplanar_rutas(datos):
        rutas = []
        for nivel in datos.get("niveles_estudio", []):
            for sede in nivel.get("sedes", []):
                for facultad in sede.get("facultades", []):
                    for plan in facultad.get("planes_estudio", []):
                        if not all(x.get("codigo") for x in (sede, facultad, plan)):
                            continue
                        rutas.append({
                            "nivel": nivel,
                            "sede": sede,
                            "facultad": facultad,
                            "plan": plan,
                        })
        return rutas

    def _iniciar_descubrimiento(self):
        if self.proceso_descubrimiento and self.proceso_descubrimiento.state() != QProcess.ProcessState.NotRunning:
            return
        self.boton_rutas.setEnabled(False)
        self.descubrimiento_finalizado = False
        self.progreso.show()
        self.estado.setText("Consultando el catálogo de sedes y carreras disponibles en el SIA…")
        carpeta_temporal = Path(tempfile.mkdtemp(prefix="fenix-rutas-sia-"))
        self.ruta_catalogo_temporal = carpeta_temporal / "catalogo.json"
        proceso = QProcess(self)
        self.proceso_descubrimiento = proceso
        proceso.setProgram(sys.executable)
        proceso.setArguments([str(Path(__file__).resolve()), "--discover", str(self.ruta_catalogo_temporal)])
        entorno = QProcessEnvironment.systemEnvironment()
        entorno.insert("PYTHONPATH", str(RAIZ))
        entorno.insert("PYTHONUNBUFFERED", "1")
        proceso.setProcessEnvironment(entorno)
        proceso.readyReadStandardOutput.connect(lambda: self._leer_salida_proceso(proceso))
        proceso.readyReadStandardError.connect(lambda: self._leer_error_proceso(proceso))
        proceso.finished.connect(self._descubrimiento_terminado)
        proceso.errorOccurred.connect(lambda _error: self._descubrimiento_terminado(1, None))
        proceso.start()

    def _leer_salida_proceso(self, proceso):
        texto = bytes(proceso.readAllStandardOutput()).decode(errors="replace")
        lineas = [linea.strip() for linea in texto.splitlines() if linea.strip()]
        if lineas:
            self.estado.setText(lineas[-1][:220])

    def _leer_error_proceso(self, proceso):
        texto = bytes(proceso.readAllStandardError()).decode(errors="replace").strip()
        if texto:
            self.estado.setText(texto.splitlines()[-1][:220])

    def _descubrimiento_terminado(self, codigo_salida, _estado):
        if self.descubrimiento_finalizado:
            return
        self.descubrimiento_finalizado = True
        self.boton_rutas.setEnabled(True)
        self.progreso.hide()
        if codigo_salida == 0 and self.ruta_catalogo_temporal.exists():
            self.catalogo = json.loads(self.ruta_catalogo_temporal.read_text(encoding="utf-8"))
            ruta_cache = self._ruta_cache()
            ruta_cache.parent.mkdir(parents=True, exist_ok=True)
            ruta_cache.write_text(json.dumps(self.catalogo, ensure_ascii=False), encoding="utf-8")
            self.planes = self._aplanar_rutas(self.catalogo)
            self._actualizar_sedes()
            self.estado.setText(f"Rutas actualizadas desde el SIA: {len(self.planes)} planes en {self.sede.count()} sedes.")
        else:
            self.estado.setText("No se pudo actualizar la lista del SIA; se mantienen las rutas guardadas disponibles.")
        try:
            self.ruta_catalogo_temporal.unlink(missing_ok=True)
            self.ruta_catalogo_temporal.parent.rmdir()
        except OSError:
            pass

    @staticmethod
    def _agregar(combo, texto, datos):
        combo.addItem(texto, datos)

    def _actualizar_sedes(self):
        self.sede.blockSignals(True)
        self.sede.clear()
        sedes = {}
        for ruta in self.planes:
            sede = ruta["sede"]
            sedes[str(sede.get("codigo", sede.get("nombre", "")))] = sede
        for clave, sede in sorted(sedes.items(), key=lambda par: par[1].get("nombre", "").casefold()):
            self._agregar(self.sede, sede.get("nombre", clave), clave)
        self.sede.blockSignals(False)
        self._actualizar_facultades()

    def _actualizar_facultades(self):
        codigo = self.sede.currentData()
        self.facultad.blockSignals(True)
        self.facultad.clear()
        facultades = {}
        for ruta in self.planes:
            facultad, sede = ruta["facultad"], ruta["sede"]
            if str(sede.get("codigo", sede.get("nombre", ""))) == str(codigo):
                facultades[str(facultad.get("codigo", facultad.get("nombre", "")))] = facultad
        for clave, facultad in sorted(facultades.items(), key=lambda par: par[1].get("nombre", "").casefold()):
            self._agregar(self.facultad, facultad.get("nombre", clave), clave)
        self.facultad.blockSignals(False)
        self._actualizar_planes()

    def _actualizar_planes(self):
        sede_codigo, fac_codigo = self.sede.currentData(), self.facultad.currentData()
        self.plan.clear()
        rutas = [r for r in self.planes if str(r["sede"].get("codigo")) == str(sede_codigo) and str(r["facultad"].get("codigo")) == str(fac_codigo)]
        for ruta in sorted(rutas, key=lambda r: r["plan"].get("nombre", "").casefold()):
            identificador = ":".join(str(x.get("codigo", "")) for x in (ruta["sede"], ruta["facultad"], ruta["plan"]))
            self._agregar(self.plan, ruta["plan"].get("nombre", "Plan sin nombre"), {"clave": identificador, "ruta": ruta})

    def consultar(self):
        seleccion = self.plan.currentData()
        if not seleccion:
            QMessageBox.warning(self, "Sin plan", "No hay un plan seleccionado.")
            return
        codigo = seleccion["clave"]
        valor_nivel = str(seleccion["ruta"]["nivel"].get("value", ""))
        self.boton.setEnabled(False)
        self.progreso.show()
        self.lista.clear()
        self.vista.scene().clear()
        self.estado.setText("Preparando una consulta aislada al SIA…")
        self.temporal = tempfile.TemporaryDirectory(prefix="fenix-arbol-")
        carpeta = Path(self.temporal.name)
        datos_dir = carpeta / "datos"
        salida = carpeta / "resultado.json"
        self.ruta_salida = salida
        crear_entorno_datos_temporal(datos_dir, self.catalogo, codigo, valor_nivel)

        proceso = QProcess(self)
        self.proceso = proceso
        proceso.setProgram(sys.executable)
        proceso.setArguments([str(Path(__file__).resolve()), "--worker", codigo, valor_nivel, str(salida), str(datos_dir)])
        entorno = QProcessEnvironment.systemEnvironment()
        entorno.insert("PYTHONPATH", str(RAIZ))
        entorno.insert("PYTHONUNBUFFERED", "1")
        proceso.setProcessEnvironment(entorno)
        proceso.readyReadStandardOutput.connect(self._leer_salida)
        proceso.readyReadStandardError.connect(self._leer_error)
        proceso.finished.connect(self._terminado)
        proceso.errorOccurred.connect(lambda _error: self._terminado(1, None))
        proceso.start()

    def _leer_salida(self):
        texto = bytes(self.proceso.readAllStandardOutput()).decode(errors="replace")
        lineas = [linea.strip() for linea in texto.splitlines() if linea.strip()]
        if lineas:
            self.estado.setText(lineas[-1][:220])

    def _leer_error(self):
        texto = bytes(self.proceso.readAllStandardError()).decode(errors="replace").strip()
        if texto:
            self.estado.setText(texto.splitlines()[-1][:220])

    def _terminado(self, codigo_salida, estado_proceso):
        if not self.temporal:
            return
        self.progreso.hide()
        self.boton.setEnabled(True)
        if codigo_salida != 0 or not self.ruta_salida.exists():
            QMessageBox.critical(self, "Falló la consulta", self.estado.text())
            self.temporal.cleanup()
            return
        datos = json.loads(self.ruta_salida.read_text(encoding="utf-8"))
        materias = datos.get("materias", [])
        fallidas = datos.get("materias_fallidas", [])
        grafo = construir_grafo(materias)
        self.vista.mostrar(grafo)
        for materia in sorted(grafo["sin_prerrequisitos"], key=lambda m: m["nombre"].casefold()):
            self.lista.addItem(f"{materia['nombre']}  ·  {materia['codigo']}  ·  {etiqueta_tipo(materia['tipologia'])}")
        mensaje = f"{len(materias)} materias; {len(grafo['aristas'])} relaciones; {len(grafo['sin_prerrequisitos'])} sin prerrequisitos."
        if fallidas:
            resumen_fallos = ", ".join(
                f"{f.get('codigo', '?')} {f.get('nombre', '')}".strip()
                for f in fallidas[:6]
            )
            mensaje += f" No se pudieron leer {len(fallidas)} materias: {resumen_fallos}"
        if grafo["ciclicos"]:
            mensaje += f" Atención: se detectaron {len(grafo['ciclicos'])} materias en ciclos o dependencias circulares."
        self.resumen.setText(mensaje)
        self.estado.setText("Árbol construido desde el catálogo del SIA.")
        self.temporal.cleanup()
        self.temporal = None

    def closeEvent(self, evento):
        for proceso in (self.proceso, self.proceso_descubrimiento):
            if proceso and proceso.state() != QProcess.ProcessState.NotRunning:
                proceso.terminate()
                if not proceso.waitForFinished(2000):
                    proceso.kill()
                    proceso.waitForFinished(2000)
        if self.temporal:
            self.temporal.cleanup()
            self.temporal = None
        super().closeEvent(evento)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--discover":
        if len(sys.argv) != 3:
            print("Uso interno inválido del proceso de descubrimiento.", flush=True)
            return 2
        return ejecutar_descubrimiento(Path(sys.argv[2]))
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        if len(sys.argv) != 6:
            print("Uso interno inválido del proceso de consulta.", flush=True)
            return 2
        return ejecutar_worker(sys.argv[2], sys.argv[3], Path(sys.argv[4]), Path(sys.argv[5]))
    app = QApplication(sys.argv)
    ventana = VentanaArbol()
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
