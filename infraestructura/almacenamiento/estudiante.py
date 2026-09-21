"""Lectura y escritura de la información académica del estudiante."""

from configuracion import (
    ARCHIVO_ESTUDIANTE,
    CARPETA_DATOS
)
from infraestructura.almacenamiento.json_atomico import cargar_json, guardar_json_atomico


def inicializar_datos():
    """Crea la carpeta de datos si todavía no existe."""
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)


def cargar_estudiante():
    """Devuelve los datos guardados o un diccionario vacío si no existen."""
    inicializar_datos()

    if not ARCHIVO_ESTUDIANTE.exists():
        return {}

    datos = cargar_json(ARCHIVO_ESTUDIANTE)
    if datos is None:
        print("⚠ No se pudo leer estudiante.json.")
        return {}

    if isinstance(datos, dict):
        return datos

    print("⚠ El formato de estudiante.json no es válido.")
    return {}


def guardar_estudiante(estudiante):
    """Guarda la información del estudiante en formato JSON."""
    if not isinstance(estudiante, dict):
        raise TypeError("La información del estudiante debe ser un diccionario.")

    inicializar_datos()

    guardar_json_atomico(ARCHIVO_ESTUDIANTE, estudiante)
