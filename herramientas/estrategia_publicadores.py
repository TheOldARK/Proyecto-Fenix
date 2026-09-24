"""Selección adaptativa de concurrencia y medidas comparables de rendimiento."""
from __future__ import annotations

import math
import random


def unidades_plan(plan) -> int:
    """Usa materias únicas como aproximación estable del trabajo por carrera."""
    return max(1, len({str(codigo) for semestre in plan.semestres for codigo in semestre.asignaturas}))


def medir_lote(unidades: int, duracion_segundos: float, publicadores: int) -> dict:
    """Devuelve velocidad total y eficiencia normalizada por publicador."""
    segundos = max(0.001, float(duracion_segundos))
    cantidad = max(1, int(publicadores))
    velocidad = max(0, int(unidades)) / segundos
    return {
        "unidades": max(0, int(unidades)),
        "duracion_segundos": round(segundos, 2),
        "publicadores": cantidad,
        "unidades_por_segundo": velocidad,
        "unidades_por_publicador_segundo": velocidad / cantidad,
    }


def ordenar_por_actualizacion_mas_antigua(codigos, historial: dict) -> list[str]:
    """Prioriza primero el plan sin registro y luego el de éxito más antiguo."""
    return sorted(
        (str(codigo) for codigo in codigos),
        key=lambda codigo: (
            float(historial.get(codigo, {}).get("ultima_actualizacion_exitosa", 0) or 0),
            codigo,
        ),
    )


def limpiar_estadisticas_rendimiento(historial: dict) -> dict:
    """Borra métricas de velocidad y conserva el historial operativo por plan."""
    historial["concurrencias"] = {}
    for registro in historial.get("planes", {}).values():
        if not isinstance(registro, dict):
            continue
        for campo in (
            "duracion_segundos",
            "unidades_por_segundo",
            "unidades_por_publicador_segundo",
        ):
            registro.pop(campo, None)
    return historial


def es_error_timeout(detalle) -> bool:
    """Reconoce timeouts explícitos sin reintentar fallos permanentes ajenos."""
    texto = str(detalle or "").casefold()
    indicadores = (
        "timeout",
        "timed out",
        "time out",
        "tiempo de espera",
        "tiempo agotado",
        "se agotó el tiempo",
        "exceeded its timeout",
    )
    return any(indicador in texto for indicador in indicadores)


def debe_reintentar_timeout(detalle, intento: int, max_intentos: int, detener=False) -> bool:
    """Reintenta solo timeouts explícitos y mientras quede margen de intentos."""
    return not detener and int(intento) < int(max_intentos) and es_error_timeout(detalle)


def seleccionar_concurrencia(maximo: int, resultados: dict[int, list[float]]) -> int:
    """UCB: explora estrategias poco medidas y favorece la mejor tasa observada.

    Ante igual evidencia se sortea entre las candidatas empatadas para evitar
    que el orden numérico sesgue el experimento.
    """
    maximo = max(1, int(maximo))
    brazos = {n: [float(x) for x in resultados.get(n, []) if x is not None] for n in range(1, maximo + 1)}
    menos_probado = min(len(muestras) for muestras in brazos.values())
    if menos_probado == 0:
        return random.choice([n for n, muestras in brazos.items() if len(muestras) == 0])

    total = sum(map(len, brazos.values()))
    medias = {n: sum(muestras) / len(muestras) for n, muestras in brazos.items()}
    escala = max(1e-9, max(medias.values()))
    puntuaciones = {
        n: medias[n] + escala * math.sqrt(2 * math.log(total + 1) / len(brazos[n]))
        for n in brazos
    }
    mejor = max(puntuaciones.values())
    candidatas = [n for n, puntuacion in puntuaciones.items() if math.isclose(puntuacion, mejor, rel_tol=1e-9)]
    return random.choice(candidatas)
