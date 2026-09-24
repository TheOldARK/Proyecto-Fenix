"""Estado persistente de la actualización del catálogo del SIA."""

from datetime import datetime

from configuracion import ARCHIVO_ESTADO_ACTUALIZACION, CARPETA_DATOS
from infraestructura.almacenamiento.json_atomico import cargar_json, guardar_json_atomico


def guardar_estado(estado, mensaje, progreso=None, **detalles):
    """Publica un estado que puede ser leído por la interfaz en otro proceso."""
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    datos = {
        "estado": estado,
        "mensaje": mensaje,
        "progreso": progreso,
        "actualizado_en": datetime.now().isoformat(timespec="seconds")
    }
    datos.update({clave: valor for clave, valor in detalles.items() if valor is not None})
    guardar_json_atomico(ARCHIVO_ESTADO_ACTUALIZACION, datos)


def cargar_estado():
    """Obtiene el último estado publicado o uno neutral si todavía no existe."""
    if not ARCHIVO_ESTADO_ACTUALIZACION.exists():
        return {
            "estado": "sin_iniciar",
            "mensaje": "Los datos aún no se han actualizado.",
            "progreso": None
        }

    datos = cargar_json(ARCHIVO_ESTADO_ACTUALIZACION)
    if datos is None:
        return {
            "estado": "actualizando",
            "mensaje": "Leyendo el estado de la actualización…",
            "progreso": None
        }

    return datos if isinstance(datos, dict) else {}
