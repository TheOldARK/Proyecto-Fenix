"""Interpretación de la historia académica del SIA, sin datos de autenticación."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


EXTRAER_TABLAS_HISTORIA = """() => Array.from(document.querySelectorAll('table')).map(table =>
  Array.from(table.rows).map(row =>
    Array.from(row.cells).map(cell =>
      (cell.innerText || cell.textContent || '').trim()
    )
  )
)"""

_CODIGO_MATERIA = re.compile(r"\((\d{5,}(?:-[A-Za-z0-9]+)?)\)\s*$")
_PERIODO = re.compile(r"\b(\d{4})\s*[-/]\s*([12])([A-Za-z]?)\b")
_NOTA = re.compile(r"(?<!\d)([0-5](?:[.,]\d+)?)\b")


def _normalizar(texto):
    sin_tildes = unicodedata.normalize("NFD", str(texto or ""))
    return " ".join(
        "".join(letra for letra in sin_tildes if unicodedata.category(letra) != "Mn")
        .upper().split()
    )


def _clave_periodo(periodo):
    coincidencia = _PERIODO.search(str(periodo or ""))
    if not coincidencia:
        return str(periodo or "").split(maxsplit=1)[0]
    return f"{coincidencia.group(1)}-{coincidencia.group(2)}{coincidencia.group(3).upper()}"


def _estado_calificacion(texto):
    valor = _normalizar(texto)
    if "REPROBADA" in valor or "REPROBADO" in valor:
        return "reprobada"
    if "APROBADA" in valor or "APROBADO" in valor:
        return "aprobada"
    if "CANCELADA" in valor or "CANCELADO" in valor:
        return "cancelada"
    return "sin_estado"


def _nota_calificacion(texto):
    coincidencia = _NOTA.search(str(texto or ""))
    return coincidencia.group(1).replace(",", ".") if coincidencia else None


def _asignatura_de_fila(fila, indices):
    if not isinstance(fila, list) or len(fila) <= max(indices.values()):
        return None
    materia = str(fila[indices["ASIGNATURAS"]]).strip()
    periodo_original = str(fila[indices["PERIODO"]]).strip()
    codigo = _CODIGO_MATERIA.search(materia)
    if not codigo or not _PERIODO.search(periodo_original):
        return None
    calificacion = str(fila[indices["CALIFICACION"]]).strip()
    return {
        "codigo": codigo.group(1),
        "nombre": materia[:codigo.start()].strip(),
        "creditos": str(fila[indices["CREDITOS"]]).strip(),
        "tipologia": str(fila[indices["TIPO"]]).strip(),
        "periodo": _clave_periodo(periodo_original),
        "periodo_detalle": periodo_original,
        "nota": _nota_calificacion(calificacion),
        "estado": _estado_calificacion(calificacion),
    }


def interpretar_tablas_historia(tablas, codigo_plan):
    """Extrae intentos por periodo y el resumen de créditos de tablas visibles."""
    asignaturas = []
    resumen_creditos = []
    for tabla in tablas if isinstance(tablas, list) else []:
        if not isinstance(tabla, list) or not tabla:
            continue
        cabecera_asignaturas = None
        cabecera_creditos = None
        for posicion, fila in enumerate(tabla):
            if not isinstance(fila, list):
                continue
            cabecera = [_normalizar(celda) for celda in fila]
            if {"ASIGNATURAS", "CREDITOS", "TIPO", "PERIODO", "CALIFICACION"}.issubset(cabecera):
                cabecera_asignaturas = (posicion, cabecera)
                break
            if {"TIPOLOGIAS", "EXIGIDOS", "APROBADOS", "PENDIENTES"}.issubset(cabecera):
                cabecera_creditos = (posicion, cabecera)
                break
        if cabecera_asignaturas is not None:
            posicion, cabecera = cabecera_asignaturas
            indices = {nombre: cabecera.index(nombre) for nombre in (
                "ASIGNATURAS", "CREDITOS", "TIPO", "PERIODO", "CALIFICACION"
            )}
            for fila in tabla[posicion + 1:]:
                asignatura = _asignatura_de_fila(fila, indices)
                if asignatura:
                    asignaturas.append(asignatura)
        elif cabecera_creditos is not None:
            posicion, _ = cabecera_creditos
            for fila in tabla[posicion + 1:]:
                if isinstance(fila, list) and len(fila) >= 4 and str(fila[0]).strip():
                    resumen_creditos.append({
                        "tipologia": str(fila[0]).strip(),
                        "exigidos": str(fila[1]).strip(),
                        "aprobados": str(fila[2]).strip(),
                        "pendientes": str(fila[3]).strip(),
                    })
        else:
            # Algunas vistas JSF usan una cabecera visual fuera de la tabla.
            # Una fila de curso se reconoce por su código y su período, no por
            # el texto exacto de esos encabezados.
            indices = {
                "ASIGNATURAS": 0, "CREDITOS": 1, "TIPO": 2,
                "PERIODO": 3, "CALIFICACION": 4,
            }
            for fila in tabla:
                asignatura = _asignatura_de_fila(fila, indices)
                if asignatura:
                    asignaturas.append(asignatura)
    if not asignaturas:
        raise ValueError(
            "No se encontró la tabla de asignaturas de Mi historia académica. "
            "No se guardó ningún dato."
        )
    return {
        "formato": 1,
        "plan_estudios": str(codigo_plan),
        "consultado_en": datetime.now(timezone.utc).isoformat(),
        "asignaturas": asignaturas,
        "resumen_creditos": resumen_creditos,
    }


def clave_orden_periodo(periodo):
    coincidencia = _PERIODO.search(str(periodo or ""))
    if coincidencia:
        return (int(coincidencia.group(1)), int(coincidencia.group(2)), coincidencia.group(3))
    return (9999, 9, str(periodo or ""))


def periodos_visibles_avance(periodos, hoy=None):
    """Incluye semestres vacíos hasta el último terminado, nunca el actual vacío."""
    originales = {str(periodo) for periodo in periodos if periodo}
    reconocidos = []
    for periodo in originales:
        coincidencia = _PERIODO.search(periodo)
        if coincidencia:
            reconocidos.append((int(coincidencia.group(1)), int(coincidencia.group(2))))
    if not reconocidos:
        return sorted(originales, key=clave_orden_periodo)
    if hoy is None:
        hoy = datetime.now(timezone(timedelta(hours=-5))).date()
    if isinstance(hoy, datetime):
        hoy = hoy.date()
    if not isinstance(hoy, date):
        raise TypeError("hoy debe ser una fecha")
    actual = (hoy.year, 1 if hoy.month <= 6 else 2)
    ultimo_terminado = (actual[0] - 1, 2) if actual[1] == 1 else (actual[0], 1)
    primero = min(reconocidos)
    if primero <= ultimo_terminado:
        anio, semestre = primero
        while (anio, semestre) <= ultimo_terminado:
            originales.add(f"{anio}-{semestre}S")
            anio, semestre = (anio, 2) if semestre == 1 else (anio + 1, 1)
    return sorted(originales, key=clave_orden_periodo)


def promedio_ponderado_periodo(asignaturas):
    """Calcula el PAPI solo con las materias que tienen nota numérica."""
    total_creditos = Decimal(0)
    total_ponderado = Decimal(0)
    for materia in asignaturas:
        nota = materia.get("nota")
        if materia.get("estado") == "cancelada" or nota is None or str(nota).strip() == "":
            continue
        try:
            creditos = Decimal(str(materia.get("creditos", "")).replace(",", "."))
            if creditos <= 0:
                return None
            calificacion = Decimal(str(nota).replace(",", "."))
            if not 0 <= calificacion <= 5:
                return None
        except (InvalidOperation, TypeError, ValueError):
            return None
        total_creditos += creditos
        total_ponderado += creditos * calificacion
    if not total_creditos:
        return None
    return (total_ponderado / total_creditos).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def interpretar_detalle_calificaciones(texto, periodo, codigo, nombre):
    """Lee parciales de la vista de detalle sin confundir mínimos con notas."""
    lineas = [linea.strip() for linea in str(texto or "").splitlines() if linea.strip()]
    inicio = next((i for i, linea in enumerate(lineas)
                   if _normalizar(linea) == "DATOS DE LOS PARCIALES"), None)
    parciales = []
    if inicio is not None:
        fin = next((i for i in range(inicio + 1, len(lineas))
                    if _normalizar(lineas[i]).startswith("DATOS ACADEMICOS DE LA ASIGNATURA")),
                   len(lineas))
        seccion = lineas[inicio + 1:fin]
        nota_pie = next((i for i, linea in enumerate(seccion) if linea.startswith("*")), len(seccion))
        seccion = seccion[:nota_pie]
        marcadores = [i for i, linea in enumerate(seccion)
                     if _normalizar(linea).rstrip("*") == "CALIFICACION MINIMA"]
        anterior = 0
        for numero, posicion in enumerate(marcadores):
            antes = seccion[anterior:posicion]
            candidatos = [linea for linea in antes if not re.fullmatch(r"\d+(?:[.,]\d+)?", linea)
                          and not linea.startswith("*")
                          and not re.fullmatch(r"\d+(?:[.,]\d+)?%", linea)
                          and _normalizar(linea) not in {"FALLAS", "NOTA FINAL", "CALIFICACION MINIMA"}]
            nombre_parcial = candidatos[-1] if candidatos else None
            limite = marcadores[numero + 1] if numero + 1 < len(marcadores) else len(seccion)
            despues = seccion[posicion + 1:limite]
            porcentaje = next((coincidencia.group(1).replace(",", ".")
                               for linea in despues
                               if (coincidencia := re.search(r"(\d+(?:[.,]\d+)?)\s*%", linea))), None)
            indice_nota = next((i for i, linea in enumerate(despues)
                                if _normalizar(linea) == "NOTA FINAL"), None)
            nota = None
            # La siguiente fila puede empezar antes del próximo marcador de
            # «Calificación mínima». No buscar números más adelante: su 3
            # corresponde al mínimo del siguiente parcial, no a esta nota.
            if indice_nota is not None and indice_nota + 1 < len(despues):
                candidata = despues[indice_nota + 1]
                if re.fullmatch(r"[0-5](?:[.,]\d+)?", candidata):
                    nota = candidata.replace(",", ".")
            if nombre_parcial or nota is not None:
                parciales.append({
                    "nombre": nombre_parcial or f"Actividad {numero + 1}",
                    "porcentaje": porcentaje,
                    "nota": nota,
                })
            anterior = posicion + 1
    return {
        "periodo": periodo,
        "codigo": codigo,
        "nombre": nombre,
        "parciales": parciales,
        "creditos": int(coincidencia.group(1)) if (coincidencia := re.search(
            r"Créditos teóricos y/o prácticos:\s*(\d+)", texto, re.I)) else None,
        "sin_definitiva": "SIN DEFINITIVA" in _normalizar(texto),
    }
