"""Señal persistente de cancelación entre la interfaz y el actualizador."""

import time

from configuracion import ARCHIVO_CANCELACION_ACTUALIZACION, CARPETA_DATOS
from infraestructura.almacenamiento.json_atomico import cargar_json, guardar_json_atomico


def solicitar_cancelacion():
    """Invalida la actualización en curso y devuelve su nuevo token."""
    token = time.time_ns()
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    guardar_json_atomico(ARCHIVO_CANCELACION_ACTUALIZACION, {"token": token})
    return token


def token_cancelacion():
    """Lee el token más reciente; devuelve cero si aún no existe."""
    datos = cargar_json(ARCHIVO_CANCELACION_ACTUALIZACION, {})
    try:
        return int(datos.get("token", 0))
    except (AttributeError, ValueError, TypeError):
        return 0


def actualizacion_cancelada(token_inicial):
    """Indica si otra parte solicitó cancelar este ciclo de actualización."""
    return token_cancelacion() != int(token_inicial)
