"""Utilidad para publicar archivos JSON sin exponer escrituras parciales."""

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path


BLOQUEO_ESCRITURAS = threading.RLock()
INTENTOS_REEMPLAZO = 50
ESPERA_REEMPLAZO = 0.08


@contextmanager
def bloquear_json(ruta, timeout=15):
    """Exclusión entre procesos por destino; el SO libera el lock al salir.

    El archivo de bloqueo permanece: borrarlo abriría una carrera entre dos
    procesos con handles a archivos distintos. No contiene datos académicos.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.with_name(f".{ruta.name}.lock").open("a+b") as archivo:
        archivo.seek(0, os.SEEK_END)
        if archivo.tell() == 0:
            archivo.write(b" ")
            archivo.flush()
        inicio = time.monotonic()
        while True:
            try:
                archivo.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - inicio >= timeout:
                    raise TimeoutError(f"Timeout esperando escritura de {ruta.name}")
                time.sleep(ESPERA_REEMPLAZO)
        try:
            yield
        finally:
            archivo.seek(0)
            if os.name == "nt":
                msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)


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

    with BLOQUEO_ESCRITURAS, bloquear_json(ruta):
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
                except OSError:
                    pass
