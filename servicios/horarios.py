"""Operaciones de consulta para el planificador de horarios."""

from servicios.conflictos import (
    grupo_tiene_cupos,
    grupos_tienen_conflicto,
    normalizar_dia,
    sesiones_validas
)
from dominio.codigos import codigo_base


def crear_referencia(origen, materia, grupo):
    """Crea el identificador persistente mínimo de un grupo seleccionado."""
    return {
        "origen": origen,
        "codigo": str(materia.get("codigo", "")),
        "numero": str(grupo.get("numero", ""))
    }


def referencias_iguales(referencia_a, referencia_b):
    """Compara dos referencias sin depender del orden de sus claves."""
    return (
        referencia_a.get("origen") == referencia_b.get("origen")
        and str(referencia_a.get("codigo")) == str(referencia_b.get("codigo"))
        and str(referencia_a.get("numero")) == str(referencia_b.get("numero"))
    )


def materias_principales(plan, oferta):
    """Devuelve todas las materias normales ofertadas actualmente.

    El plan se usa posteriormente para priorizar las recomendadas; no debe
    ocultar las demás materias normales que el estudiante puede consultar.
    Se conserva como parámetro para mantener la interfaz del servicio estable.
    """
    del plan
    return list(oferta.values())


def buscar_grupo(materias_por_origen, referencia):
    """Resuelve una referencia guardada al par materia/grupo actual."""
    origen = referencia.get("origen")

    for materia in materias_por_origen.get(origen, []):
        if str(materia.get("codigo")) != str(referencia.get("codigo")):
            continue

        for grupo in materia.get("grupos", []):
            if str(grupo.get("numero")) == str(referencia.get("numero")):
                return materia, grupo

    return None


def grupos_seleccionados(materias_por_origen, referencias):
    """Resuelve las selecciones existentes y omite referencias ya obsoletas."""
    encontrados = []

    for referencia in referencias:
        encontrado = buscar_grupo(materias_por_origen, referencia)
        if encontrado is not None:
            encontrados.append((referencia, *encontrado))

    return encontrados


def grupo_es_elegible(grupo, grupos_actuales):
    """Comprueba solo superposiciones frente a los grupos seleccionados.

    Los cupos son informativos: se permite añadir un grupo agotado para que el
    estudiante pueda ver su horario y decidir si quiere monitorearlo.
    """

    for _, grupo_actual in grupos_actuales:
        if grupos_tienen_conflicto(grupo, grupo_actual):
            return False, "Conflicto de horario"

    if not grupo_tiene_cupos(grupo):
        return True, "Sin cupos disponibles"

    return True, ""


def grupo_ocupa_bloque(grupo, dia, hora, duracion=1):
    """Indica si una sesión intersecta un bloque de una o más horas.

    El parámetro opcional permite que la interfaz use franjas de dos horas sin
    perder las clases excepcionales que duran solo una hora.
    """
    inicio_bloque = hora * 60
    fin_bloque = inicio_bloque + (duracion * 60)
    dia = normalizar_dia(dia)

    return any(
        dia_sesion == dia
        and inicio < fin_bloque
        and inicio_bloque < fin
        for dia_sesion, inicio, fin, _ in sesiones_validas(grupo)
    )


def grupos_en_bloque(materias_por_origen, dia, hora):
    """Lista grupos con clase durante el bloque elegido del calendario."""
    coincidencias = []

    for origen, materias in materias_por_origen.items():
        for materia in materias:
            for grupo in materia.get("grupos", []):
                if grupo_ocupa_bloque(grupo, dia, hora):
                    coincidencias.append((origen, materia, grupo))

    return coincidencias
