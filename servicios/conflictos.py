"""Reglas para comparar los horarios de los grupos académicos."""

DIAS_ORDENADOS = (
    "LUNES",
    "MARTES",
    "MIÉRCOLES",
    "JUEVES",
    "VIERNES",
    "SÁBADO",
    "DOMINGO"
)


def normalizar_dia(dia):
    """Devuelve el nombre del día en mayúsculas, sin espacios externos."""
    return str(dia or "").strip().upper()


def hora_a_minutos(hora):
    """Convierte una hora HH:MM en minutos desde medianoche."""
    try:
        horas, minutos = str(hora).strip().split(":", maxsplit=1)
        horas = int(horas)
        minutos = int(minutos)
    except (TypeError, ValueError):
        return None

    if not 0 <= horas <= 23 or not 0 <= minutos <= 59:
        return None

    return horas * 60 + minutos


def sesiones_validas(grupo):
    """Obtiene las sesiones con día y horas que se pueden comparar."""
    sesiones = []

    for sesion in grupo.get("horarios", []):
        if not isinstance(sesion, dict):
            continue

        inicio = hora_a_minutos(sesion.get("hora_inicio"))
        fin = hora_a_minutos(sesion.get("hora_fin"))
        dia = normalizar_dia(sesion.get("dia"))

        if dia and inicio is not None and fin is not None and inicio < fin:
            sesiones.append((dia, inicio, fin, sesion))

    return sesiones


def grupos_tienen_conflicto(grupo_a, grupo_b):
    """Indica si dos grupos se superponen en al menos una sesión."""
    for dia_a, inicio_a, fin_a, _ in sesiones_validas(grupo_a):
        for dia_b, inicio_b, fin_b, _ in sesiones_validas(grupo_b):
            if dia_a != dia_b:
                continue

            if inicio_a < fin_b and inicio_b < fin_a:
                return True

    return False


def detalles_conflicto(grupo_a, grupo_b):
    """Devuelve las franjas exactas que se superponen entre dos grupos."""
    detalles = []
    for dia_a, inicio_a, fin_a, sesion_a in sesiones_validas(grupo_a):
        for dia_b, inicio_b, fin_b, sesion_b in sesiones_validas(grupo_b):
            if dia_a != dia_b or not (inicio_a < fin_b and inicio_b < fin_a):
                continue
            inicio = max(inicio_a, inicio_b)
            fin = min(fin_a, fin_b)
            detalles.append({
                "dia": dia_a,
                "hora_inicio": f"{inicio // 60:02d}:{inicio % 60:02d}",
                "hora_fin": f"{fin // 60:02d}:{fin % 60:02d}",
                "sesion_nueva": sesion_a,
                "sesion_actual": sesion_b,
            })
    return detalles


def grupo_tiene_cupos(grupo):
    """Un grupo sin dato de cupos se considera disponible."""
    cupos = grupo.get("cupos_disponibles")
    return cupos is None or cupos > 0


def detectar_adyacencias(grupos_seleccionados):
    """Encuentra pares de clases que terminan e inician a la misma hora."""
    sesiones_por_dia = {}

    for materia, grupo in grupos_seleccionados:
        for dia, inicio, fin, sesion in sesiones_validas(grupo):
            sesiones_por_dia.setdefault(dia, []).append(
                (inicio, fin, materia, grupo, sesion)
            )

    adyacencias = []

    for dia, sesiones in sesiones_por_dia.items():
        sesiones.sort(key=lambda sesion: (sesion[0], sesion[1]))

        for anterior, siguiente in zip(sesiones, sesiones[1:]):
            if anterior[1] == siguiente[0]:
                sede_anterior = str(anterior[4].get("sede", "")).strip().casefold()
                sede_siguiente = str(siguiente[4].get("sede", "")).strip().casefold()
                adyacencias.append(
                    {
                        "dia": dia,
                        "hora": anterior[1],
                        "anterior": anterior,
                        "siguiente": siguiente,
                        "sedes_diferentes": bool(
                            sede_anterior and sede_siguiente and sede_anterior != sede_siguiente
                        ),
                    }
                )

    return adyacencias
