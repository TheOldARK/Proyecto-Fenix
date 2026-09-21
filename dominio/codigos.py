"""Normalización de códigos académicos compartida por el dominio y servicios."""


def codigo_base(codigo):
    """Quita el sufijo de modalidad y normaliza espacios de un código SIA."""
    return str(codigo or "").split("-", maxsplit=1)[0].strip()
