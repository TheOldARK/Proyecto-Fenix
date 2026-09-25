"""Clasificación de errores del SIA para controlar reintentos."""


class MateriaNoDisponibleEnSIA(RuntimeError):
    """El SIA no ofrece el detalle solicitado para una materia."""

    def __init__(self, mensaje, *, sesion_invalidada=False):
        super().__init__(mensaje)
        self.sesion_invalidada = sesion_invalidada


def es_error_transitorio_sia(error):
    """True solo cuando repetir una consulta puede recuperarla."""
    if isinstance(error, MateriaNoDisponibleEnSIA):
        # errorNavegacion.jsf también invalida la sesión. Al reabrirla, un
        # segundo intento permite distinguir un tropiezo de navegación de
        # una materia realmente ausente; los enlaces inexistentes siguen
        # siendo permanentes.
        return error.sesion_invalidada

    texto = str(error).casefold()
    marcas_transitorias = (
        "timeout",
        "timed out",
        "net::",
        "err_connection",
        "connection reset",
        "connection refused",
        "navigation failed",
        "navigation timeout",
        "target closed",
        "page closed",
        "browser has been closed",
        "execution context was destroyed",
    )
    return any(marca in texto for marca in marcas_transitorias)
