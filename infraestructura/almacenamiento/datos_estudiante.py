"""Limpieza coordinada de los documentos que pertenecen a un estudiante."""

from configuracion import (
    ARCHIVO_CANCELACION_ACTUALIZACION,
    ARCHIVO_ESTADO_ACTUALIZACION,
    ARCHIVO_ESTUDIANTE,
    ARCHIVO_LIBRES_ELECCION,
    ARCHIVO_MATERIAS,
    ARCHIVO_OFERTA,
)


ARCHIVOS_DEL_ESTUDIANTE = (
    ARCHIVO_ESTUDIANTE,
    ARCHIVO_MATERIAS,
    ARCHIVO_OFERTA,
    ARCHIVO_LIBRES_ELECCION,
    ARCHIVO_ESTADO_ACTUALIZACION,
    ARCHIVO_CANCELACION_ACTUALIZACION,
)


def borrar_datos_estudiante():
    """Borra la sesión anterior y verifica que ningún worker la recree."""
    for ruta in ARCHIVOS_DEL_ESTUDIANTE:
        ruta.unlink(missing_ok=True)

    restantes = [ruta.name for ruta in ARCHIVOS_DEL_ESTUDIANTE if ruta.exists()]
    if restantes:
        raise OSError(
            "No fue posible borrar estos archivos: " + ", ".join(restantes)
        )
