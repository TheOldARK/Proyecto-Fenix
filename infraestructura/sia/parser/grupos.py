# =============================================================
# PARSER DE GRUPOS DEL SIA
# =============================================================
#
# Este módulo contiene las funciones encargadas de extraer
# información de los grupos de una asignatura a partir del HTML
# generado por el SIA.
#
# La información que se obtiene incluye:
#
#   - Número y nombre del grupo.
#   - Profesor.
#   - Fechas de inicio y finalización.
#   - Duración.
#   - Jornada.
#   - Cupos disponibles.
#   - Horarios.
#   - Aula.
#   - Sede.
#
# Este módulo no se encarga de navegar por el SIA.
# La navegación se realiza en la capa de infraestructura/sia.
#
# El flujo esperado es:
#
#   Playwright
#       ↓
#   page.content()
#       ↓
#   HTML
#       ↓
#   extraer_grupos()
#       ↓
#   Grupo + Horario
#

import re

from dominio.grupo import Grupo
from dominio.horario import Horario, es_aula_presencial_valida


# =============================================================
# UTILIDADES
# =============================================================

def normalizar_texto(texto: str) -> str:
    # El HTML del SIA puede contener saltos de línea y varios
    # espacios consecutivos.
    #
    # Esta función los convierte en un único espacio y elimina
    # los espacios innecesarios al principio y al final.

    return re.sub(
        r"\s+",
        " ",
        texto
    ).strip()


def detectar_sede(aula: str) -> str:
    # Determina la sede de la universidad a partir del formato
    # utilizado por el SIA para identificar el aula.
    #
    # Ejemplos conocidos:
    #
    #   46-211  → VOLADOR
    #   12-203  → VOLADOR
    #   M7-106  → MINAS
    #   M15-203 → MINAS
    #
    # Si el formato del aula no coincide con ninguno de los
    # casos conocidos, se devuelve una cadena vacía.
    #
    # Esta función se mantiene deliberadamente sencilla porque
    # la información de la sede se deduce del formato utilizado
    # actualmente por el SIA.

    aula = aula.strip().upper()

    if not es_aula_presencial_valida(aula):
        return ""

    if aula.startswith("M"):
        return "MINAS"

    if "-" in aula:
        return "VOLADOR"

    return ""


def _es_grupo(texto: str) -> bool:
    # Los encabezados de los grupos siguen un formato similar a:
    #
    #   (1) Grupo 1
    #   (2) Grupo 2
    #
    # La expresión regular permite espacios dentro de los
    # paréntesis y no distingue entre mayúsculas y minúsculas.

    return bool(
        re.search(
            r"\(\s*\d+\s*\)\s*Grupo\s+\d+",
            texto,
            re.IGNORECASE
        )
    )


def _extraer_numero_grupo(texto: str) -> str:
    # Extrae el número que aparece dentro de los paréntesis
    # del encabezado del grupo.
    #
    # Ejemplo:
    #
    #   "(1) Grupo 1" → "1"

    coincidencia = re.search(
        r"\(\s*(\d+)\s*\)\s*Grupo",
        texto,
        re.IGNORECASE
    )

    if not coincidencia:
        return ""

    return coincidencia.group(1)


def _ignorar_grupo(texto: str) -> bool:
    # Algunos grupos que aparecen en el SIA corresponden a
    # modalidades especiales que Fénix no debe incluir en la
    # oferta académica normal.
    #
    # Actualmente se ignoran los grupos identificados como:
    #
    #   - PAET
    #   - PEAMA

    texto_mayusculas = texto.upper()

    return (
        "PAET" in texto_mayusculas
        or
        "PEAMA" in texto_mayusculas
    )


# =============================================================
# EXTRACCIÓN DE INFORMACIÓN DEL GRUPO
# =============================================================

def _extraer_profesor(contenido) -> str:
    # El nombre del profesor aparece dentro de un elemento
    # span con la clase "strong".
    #
    # Se eliminan los espacios innecesarios y el punto final
    # que puede aparecer después del nombre.

    elemento = contenido.select_one(
        "span.strong"
    )

    if elemento is None:
        return ""

    profesor = normalizar_texto(
        elemento.get_text(
            " ",
            strip=True
        )
    )

    return (
        profesor
        .rstrip(".")
        .strip()
    )


def _extraer_fechas(texto: str):
    # Busca el rango de fechas mostrado por el SIA.
    #
    # Ejemplo:
    #
    #   Fecha: 01/08/2026 - 15/12/2026
    #
    # La función devuelve las dos fechas por separado.
    #
    # Si no encuentra el patrón esperado, devuelve dos cadenas
    # vacías.

    coincidencia = re.search(
        r"Fecha:\s*"
        r"(\d{2}/\d{2}/\d{4})"
        r"\s*-\s*"
        r"(\d{2}/\d{2}/\d{4})",
        texto,
        re.IGNORECASE
    )

    if not coincidencia:
        return "", ""

    return (
        coincidencia.group(1),
        coincidencia.group(2)
    )


def _extraer_duracion(texto: str) -> str:
    # Extrae el texto situado entre "Duración:" y "Jornada:".
    #
    # Se utiliza "Jornada:" como límite porque ambos campos
    # aparecen consecutivamente en la información del grupo.

    coincidencia = re.search(
        r"Duración:\s*(.*?)(?=\s*Jornada:)",
        texto,
        re.IGNORECASE
    )

    if not coincidencia:
        return ""

    return normalizar_texto(
        coincidencia.group(1)
    )


def _extraer_jornada(texto: str) -> str:
    # Extrae el texto situado entre "Jornada:" y
    # "Cupos disponibles:".

    coincidencia = re.search(
        r"Jornada:\s*(.*?)(?=\s*Cupos disponibles:)",
        texto,
        re.IGNORECASE
    )

    if not coincidencia:
        return ""

    return normalizar_texto(
        coincidencia.group(1)
    )


def _extraer_cupos(texto: str):
    # Extrae la cantidad de cupos disponibles.
    #
    # El valor se convierte a int porque posteriormente puede
    # ser utilizado para realizar comparaciones o cálculos.
    #
    # Si el SIA no proporciona el dato, se devuelve None.

    coincidencia = re.search(
        r"Cupos disponibles:\s*(\d+)",
        texto,
        re.IGNORECASE
    )

    if not coincidencia:
        return None

    return int(
        coincidencia.group(1)
    )


# =============================================================
# EXTRACCIÓN DE HORARIOS
# =============================================================

def _extraer_horarios(contenido):
    # Un grupo puede tener uno o varios horarios.
    #
    # Cada bloque de horario del HTML contiene información sobre:
    #
    #   - Día.
    #   - Hora de inicio.
    #   - Hora de finalización.
    #   - Aula.
    #
    # Cada bloque encontrado se convierte en un objeto Horario.

    horarios = []

    bloques = contenido.select(
        "span[id*=':pgl10']"
    )

    for bloque in bloques:

        # -----------------------------------------------------
        # TEXTO DEL HORARIO
        # -----------------------------------------------------
        #
        # Ejemplo esperado:
        #
        #   LUNES de 08:00 a 10:00

        elemento_hora = bloque.select_one(
            "span[id*=':ot10']"
        )

        if elemento_hora is None:
            continue

        texto_hora = normalizar_texto(
            elemento_hora.get_text(
                " ",
                strip=True
            )
        )

        coincidencia = re.search(
            r"^(LUNES|MARTES|MIÉRCOLES|"
            r"MIERCOLES|JUEVES|VIERNES|"
            r"SÁBADO|SABADO|DOMINGO)"
            r"\s+de\s+"
            r"(\d{1,2}:\d{2})"
            r"\s+a\s+"
            r"(\d{1,2}:\d{2})",
            texto_hora,
            re.IGNORECASE
        )

        if not coincidencia:
            continue

        dia = normalizar_texto(
            coincidencia.group(1)
        )

        hora_inicio = coincidencia.group(2)
        hora_fin = coincidencia.group(3)

        # -----------------------------------------------------
        # AULA
        # -----------------------------------------------------

        aula = ""

        elemento_aula = bloque.select_one(
            "span[id*=':ot28']"
        )

        if elemento_aula is not None:

            aula = normalizar_texto(
                elemento_aula.get_text(
                    " ",
                    strip=True
                )
            )

            # Algunos valores del SIA terminan en punto.
            # No forma parte del identificador del aula, por lo
            # que se elimina.

            aula = (
                aula
                .rstrip(".")
                .strip()
            )

        # -----------------------------------------------------
        # SEDE
        # -----------------------------------------------------

        sede = detectar_sede(
            aula
        )

        # -----------------------------------------------------
        # CREAR HORARIO
        # -----------------------------------------------------

        horario = Horario(
            dia=dia,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            aula=aula,
            sede=sede,
            virtual=not es_aula_presencial_valida(aula),
        )

        horarios.append(
            horario
        )

    return horarios


# =============================================================
# PARSER HTML
# =============================================================

def _extraer_grupos_desde_html(
    html: str
):
    # Convierte el HTML completo de la página de detalle de una
    # asignatura en objetos Grupo.
    #
    # El HTML debe corresponder a una página que ya haya sido
    # abierta mediante la navegación real de Playwright.
    #
    # El método page.content() de Playwright proporciona
    # precisamente este HTML.
    #
    # Aquí no se realiza ninguna navegación ni petición al SIA.
    # Esta función solamente interpreta el HTML recibido.

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    grupos = []

    # =========================================================
    # BUSCAR ENCABEZADOS DE GRUPO
    # =========================================================
    #
    # El SIA utiliza tablas con esta clase para los encabezados
    # de las diferentes secciones de detalle.

    encabezados = soup.select(
        "table.af_showDetailHeader_title-table"
    )

    for encabezado in encabezados:

        texto_encabezado = normalizar_texto(
            encabezado.get_text(
                " ",
                strip=True
            )
        )

        # -----------------------------------------------------
        # COMPROBAR QUE SEA UN GRUPO
        # -----------------------------------------------------

        if not _es_grupo(
            texto_encabezado
        ):
            continue

        # -----------------------------------------------------
        # OBTENER CONTENEDOR DEL GRUPO
        # -----------------------------------------------------
        #
        # El encabezado y su contenido se encuentran dentro de
        # un mismo contenedor en la estructura generada por el
        # SIA.

        contenedor = encabezado.parent

        if contenedor is None:
            continue

        texto_grupo = normalizar_texto(
            contenedor.get_text(
                " ",
                strip=True
            )
        )

        # -----------------------------------------------------
        # IGNORAR PAET Y PEAMA
        # -----------------------------------------------------

        if _ignorar_grupo(
            texto_grupo
        ):
            continue

        grupo = Grupo()

        # -----------------------------------------------------
        # NOMBRE DEL GRUPO
        # -----------------------------------------------------

        grupo.nombre = texto_encabezado

        # -----------------------------------------------------
        # NÚMERO DEL GRUPO
        # -----------------------------------------------------

        grupo.numero = _extraer_numero_grupo(
            texto_encabezado
        )

        # -----------------------------------------------------
        # CONTENIDO DEL GRUPO
        # -----------------------------------------------------

        contenido = contenedor.select_one(
            "div.af_showDetailHeader_content0"
        )

        if contenido is None:
            continue

        texto_contenido = normalizar_texto(
            contenido.get_text(
                " ",
                strip=True
            )
        )

        # -----------------------------------------------------
        # PROFESOR
        # -----------------------------------------------------

        grupo.profesor = _extraer_profesor(
            contenido
        )

        # -----------------------------------------------------
        # FECHAS
        # -----------------------------------------------------

        (
            grupo.fecha_inicio,
            grupo.fecha_fin
        ) = _extraer_fechas(
            texto_contenido
        )

        # -----------------------------------------------------
        # DURACIÓN
        # -----------------------------------------------------

        grupo.duracion = _extraer_duracion(
            texto_contenido
        )

        # -----------------------------------------------------
        # JORNADA
        # -----------------------------------------------------

        grupo.jornada = _extraer_jornada(
            texto_contenido
        )

        # -----------------------------------------------------
        # CUPOS
        # -----------------------------------------------------

        grupo.cupos_disponibles = _extraer_cupos(
            texto_contenido
        )

        # -----------------------------------------------------
        # HORARIOS
        # -----------------------------------------------------

        grupo.horarios = _extraer_horarios(
            contenido
        )

        # -----------------------------------------------------
        # GUARDAR GRUPO
        # -----------------------------------------------------

        grupos.append(
            grupo
        )

    return grupos


# =============================================================
# FUNCIÓN PÚBLICA
# =============================================================

async def extraer_grupos(
    origen
):
    # Extrae los grupos de una asignatura a partir del HTML
    # de su página de detalle en el SIA.
    #
    # Actualmente esta función recibe directamente el HTML
    # obtenido mediante Playwright.
    #
    # Ejemplo:
    #
    #   detalle = await page.content()
    #
    #   grupos = await extraer_grupos(
    #       detalle
    #   )
    #
    # La función es asíncrona para mantener una interfaz
    # compatible con el resto del proceso de extracción,
    # aunque el procesamiento del HTML en sí mismo es síncrono.

    if not isinstance(
        origen,
        str
    ):

        raise TypeError(
            "extraer_grupos() espera el HTML "
            "de la página como str."
        )

    return _extraer_grupos_desde_html(
        origen
    )
