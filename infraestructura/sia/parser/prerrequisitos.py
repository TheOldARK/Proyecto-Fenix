"""Extracción robusta de prerrequisitos desde el detalle HTML del SIA."""

import re

from dominio.materia import Prerrequisito


CODIGO_RE = re.compile(r"(?<!\d)(\d{6,9}(?:-[A-Za-z])?)(?!\d)")
MARCADOR_RE = re.compile(r"prerrequisit(?:o|os|a|as)", re.IGNORECASE)
CONDICION_RE = re.compile(
    r"Condici[oó]n\s*(\d+).*?\bTipo\s*([A-Z])"
    r"(?:\s+¿?Todas\??\s*\[[^\]]*\])?"
    r"(?:\s+N[uú]mero\s+asignaturas?\s*\[[^\]]*\])?",
    re.IGNORECASE,
)
TODAS_RE = re.compile(r"¿?Todas\??\s*\[\s*([^\]]*)\s*\]", re.IGNORECASE)
NUMERO_ASIGNATURAS_RE = re.compile(
    r"N[uú]mero\s+asignaturas?\s*\[\s*([^\]]*)\s*\]", re.IGNORECASE
)
FIN_REQUISITOS_RE = re.compile(
    r"\bTipo\s+de\s+(?:prerrequisitos?\s+)?implica\b"
    r"|\bCorrequisitos?\s*(?::|$|Condici[oó]n|\d{6,9})",
    re.IGNORECASE,
)


def normalizar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def limpiar_nombre_prerrequisito(texto: str) -> str:
    """Excluye la leyenda SIA, incluso de nombres guardados por parsers antiguos."""
    return FIN_REQUISITOS_RE.split(normalizar_texto(texto), maxsplit=1)[0].strip(" :-–—")


def _crear_prerrequisito(
    codigo, nombre, tipo="", condicion="", todas="", numero_asignaturas=""
):
    codigo = normalizar_texto(codigo)
    nombre = limpiar_nombre_prerrequisito(nombre)
    if not codigo or not nombre:
        return None
    return Prerrequisito(
        codigo=codigo,
        nombre=nombre,
        tipo=tipo,
        condicion=condicion,
        todas=todas,
        numero_asignaturas=numero_asignaturas,
    )


def _nombre_de_fila(fila, codigo):
    """Obtiene el nombre desde celdas, enlaces o texto de una fila."""
    texto_fila = limpiar_nombre_prerrequisito(fila.get_text(" ", strip=True))
    # Delimitar cada nombre por su propio código, no tomar cualquier celda
    # del contenedor padre (que puede incluir condiciones u otras materias).
    for coincidencia in CODIGO_RE.finditer(texto_fila):
        if coincidencia.group(1) != codigo:
            continue
        resto = texto_fila[coincidencia.end():]
        limite = re.search(r"\bCondici[oó]n\s*\d+", resto, re.IGNORECASE)
        if limite:
            resto = resto[:limite.start()]
        siguiente = CODIGO_RE.search(resto)
        if siguiente:
            resto = resto[:siguiente.start()]
        if resto.strip(" :-–—"):
            return resto.strip(" :-–—")
    elementos = fila.find_all(["td", "th", "a", "span"], recursive=True)
    textos = []
    for elemento in elementos:
        texto = limpiar_nombre_prerrequisito(elemento.get_text(" ", strip=True))
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
    filas = contenedor.find_all("tr")
    # Sin filas, el fallback de texto separa las condiciones y los códigos.
    if not filas:
        return []
    condicion_actual = ""
    tipo_actual = ""
    todas_actual = ""
    numero_actual = ""
    for fila in filas:
        # Ignorar filas que solo envuelven otras tablas: sus códigos y textos
        # se procesan en las filas hoja, sin repetirlos con nombres mezclados.
        if fila.find("tr"):
            continue
        texto_original = normalizar_texto(fila.get_text(" ", strip=True))
        texto = limpiar_nombre_prerrequisito(texto_original)
        encabezado_condicion = CONDICION_RE.search(texto)
        if encabezado_condicion:
            condicion_actual = encabezado_condicion.group(1)
            tipo_actual = encabezado_condicion.group(2).upper()
            todas_match = TODAS_RE.search(texto)
            numero_match = NUMERO_ASIGNATURAS_RE.search(texto)
            todas_actual = todas_match.group(1).strip() if todas_match else ""
            numero_actual = numero_match.group(1).strip() if numero_match else ""
        codigos = CODIGO_RE.findall(texto)
        for codigo in codigos:
            nombre = _nombre_de_fila(fila, codigo)
            requisito = _crear_prerrequisito(
                codigo,
                nombre,
                tipo=tipo_actual,
                condicion=condicion_actual,
                todas=todas_actual,
                numero_asignaturas=numero_actual,
            )
            if requisito is not None:
                resultados.append(requisito)
        if FIN_REQUISITOS_RE.search(texto_original):
            break
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
            clave = (requisito.codigo, requisito.tipo, requisito.condicion)
            if clave in vistos:
                continue
            vistos.add(clave)
            resultados.append(requisito)
        if resultados:
            break

    # Fallback para HTML sin filas: conserva el tipo de cada condición y
    # asocia ese metadato a los códigos que aparecen antes de la siguiente.
    if not resultados:
        texto = limpiar_nombre_prerrequisito(soup.get_text(" ", strip=True))
        marcador = MARCADOR_RE.search(texto)
        if marcador:
            fragmento = texto[marcador.end():]
            condiciones = list(CONDICION_RE.finditer(fragmento))
            segmentos = []
            if condiciones:
                for indice, condicion in enumerate(condiciones):
                    fin = (
                        condiciones[indice + 1].start()
                        if indice + 1 < len(condiciones)
                        else len(fragmento)
                    )
                    segmentos.append((condicion.group(0), fragmento[condicion.end():fin]))
            else:
                segmentos.append(("", fragmento))

            for encabezado, segmento in segmentos:
                condicion_match = CONDICION_RE.search(encabezado)
                todas_match = TODAS_RE.search(encabezado)
                numero_match = NUMERO_ASIGNATURAS_RE.search(encabezado)
                tipo = condicion_match.group(2).upper() if condicion_match else ""
                numero_condicion = condicion_match.group(1) if condicion_match else ""
                todas = todas_match.group(1).strip() if todas_match else ""
                numero = numero_match.group(1).strip() if numero_match else ""
                coincidencias = list(CODIGO_RE.finditer(segmento))
                for indice, coincidencia in enumerate(coincidencias):
                    inicio = coincidencia.end()
                    fin = (
                        coincidencias[indice + 1].start()
                        if indice + 1 < len(coincidencias)
                        else len(segmento)
                    )
                    nombre = MARCADOR_RE.sub("", segmento[inicio:fin])
                    requisito = _crear_prerrequisito(
                        coincidencia.group(1),
                        nombre.strip(" :-–—"),
                        tipo=tipo,
                        condicion=numero_condicion,
                        todas=todas,
                        numero_asignaturas=numero,
                    )
                    clave = (
                        requisito.codigo, requisito.tipo, requisito.condicion
                    ) if requisito is not None else None
                    if requisito is not None and clave not in vistos:
                        vistos.add(clave)
                        resultados.append(requisito)

    return resultados


async def extraer_prerrequisitos(origen):
    """Interfaz asíncrona usada por el extractor de asignaturas."""
    return _extraer_prerrequisitos_desde_html(origen)
