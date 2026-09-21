"""Utilidad para publicar archivos JSON sin exponer escrituras parciales."""

import json
import os
import tempfile
import threading
import time
from pathlib import Path


BLOQUEO_ESCRITURAS = threading.RLock()
INTENTOS_REEMPLAZO = 8
ESPERA_REEMPLAZO = 0.08


def cargar_json(ruta, predeterminado=None):
    """Lee JSON de forma tolerante y devuelve *predeterminado* si falla.

    La validación de la estructura pertenece a cada repositorio: aquí solo se
    centraliza la apertura segura que todos comparten.
    """
    try:
        with Path(ruta).open("r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except (OSError, json.JSONDecodeError):
        return predeterminado


def guardar_json_atomico(ruta, datos):
    """Escribe *datos* y reemplaza el destino solo cuando el JSON está completo."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = None

    with BLOQUEO_ESCRITURAS:
        try:
            # Cada proceso obtiene un nombre distinto. Esto es importante en
            # Windows, donde varios workers no pueden compartir el mismo .tmp.
            descriptor, nombre_temporal = tempfile.mkstemp(
                prefix=f".{ruta.name}.",
                suffix=".tmp",
                dir=ruta.parent,
                text=True,
            )
            temporal = Path(nombre_temporal)
            with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
                json.dump(datos, archivo, ensure_ascii=False, indent=4)
                archivo.flush()
                os.fsync(archivo.fileno())

            # La interfaz puede estar leyendo el destino o Windows puede
            # retenerlo brevemente. Reintentamos solo errores transitorios.
            ultimo_error = None
            for intento in range(INTENTOS_REEMPLAZO):
                try:
                    os.replace(temporal, ruta)
                    temporal = None
                    break
                except PermissionError as error:
                    ultimo_error = error
                    if intento + 1 == INTENTOS_REEMPLAZO:
                        raise
                    time.sleep(ESPERA_REEMPLAZO)

            if temporal is not None and ultimo_error is not None:
                raise ultimo_error
        finally:
            if temporal is not None:
                try:
                    temporal.unlink()
                except FileNotFoundError:
                    pass
