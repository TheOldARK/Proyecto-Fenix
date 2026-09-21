"""Extracción robusta de prerrequisitos desde el detalle HTML del SIA."""

import re

from dominio.materia import Prerrequisito


CODIGO_RE = re.compile(r"(?<!\d)(\d{6,9}(?:-[A-Za-z])?)(?!\d)")
MARCADOR_RE = re.compile(r"prerrequisit(?:o|os|a|as)", re.IGNORECASE)


def normalizar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def _crear_prerrequisito(codigo, nombre):
    codigo = normalizar_texto(codigo)
    nombre = normalizar_texto(nombre)
    if not codigo or not nombre:
        return None
    return Prerrequisito(codigo=codigo, nombre=nombre)


def _nombre_de_fila(fila, codigo):
    """Obtiene el nombre desde celdas, enlaces o texto de una fila."""
    elementos = fila.find_all(["td", "th", "a", "span"], recursive=True)
    textos = []
    for elemento in elementos:
        texto = normalizar_texto(elemento.get_text(" ", strip=True))
        if texto and texto not in textos:
            textos.append(texto)

    for texto in textos:
        if codigo not in texto and not MARCADOR_RE.fullmatch(texto):
            limpio = CODIGO_RE.sub("", texto)
            limpio = MARCADOR_RE.sub("", limpio)
            limpio = normalizar_texto(limpio).strip(" :-–—")
            if limpio:
                return limpio

    texto = normalizar_texto(fila.get_text(" ", strip=True))
    texto = texto.replace(codigo, "")
    texto = MARCADOR_RE.sub("", texto)
    return normalizar_texto(texto).strip(" :-–—")


def _extraer_de_contenedor(contenedor):
    resultados = []
    filas = contenedor.find_all("tr") or [contenedor]
    for fila in filas:
        texto = normalizar_texto(fila.get_text(" ", strip=True))
        codigos = CODIGO_RE.findall(texto)
        for codigo in codigos:
            nombre = _nombre_de_fila(fila, codigo)
            requisito = _crear_prerrequisito(codigo, nombre)
            if requisito is not None:
                resultados.append(requisito)
    return resultados


def _extraer_prerrequisitos_desde_html(html: str):
    """Extrae códigos y nombres sin depender de una estructura exacta."""
    if not isinstance(html, str):
        raise TypeError("El HTML debe ser una cadena de texto.")

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    contenedores = []

    # El SIA ha usado tablas, fieldsets y paneles DIV en distintas versiones.
    for elemento in soup.find_all(["table", "fieldset", "section", "div", "tr"]):
        texto = normalizar_texto(elemento.get_text(" ", strip=True))
        if MARCADOR_RE.search(texto):
            contenedores.append(elemento)

    # Procesar primero el contenedor más pequeño para evitar duplicados y ruido
    # de paneles padres que repiten todo el contenido de sus hijos.
    contenedores.sort(key=lambda elemento: len(elemento.get_text(" ", strip=True)))
    resultados = []
    vistos = set()
    for contenedor in contenedores:
        for requisito in _extraer_de_contenedor(contenedor):
            if requisito.codigo in vistos:
                continue
            vistos.add(requisito.codigo)
            resultados.append(requisito)
        if resultados:
            break

    # Fallback para HTML sin filas: toma el texto inmediatamente posterior al
    # marcador y lo divide por códigos consecutivos.
    if not resultados:
        texto = normalizar_texto(soup.get_text(" ", strip=True))
        marcador = MARCADOR_RE.search(texto)
        if marcador:
            fragmento = texto[marcador.end():]
            coincidencias = list(CODIGO_RE.finditer(fragmento))
            for indice, coincidencia in enumerate(coincidencias):
                inicio = coincidencia.end()
                fin = coincidencias[indice + 1].start() if indice + 1 < len(coincidencias) else len(fragmento)
                nombre = MARCADOR_RE.sub("", fragmento[inicio:fin])
                requisito = _crear_prerrequisito(coincidencia.group(1), nombre.strip(" :-–—"))
                if requisito is not None and requisito.codigo not in vistos:
                    vistos.add(requisito.codigo)
                    resultados.append(requisito)

    return resultados


async def extraer_prerrequisitos(origen):
    """Interfaz asíncrona usada por el extractor de asignaturas."""
    return _extraer_prerrequisitos_desde_html(origen)
