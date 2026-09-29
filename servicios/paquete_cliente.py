"""Reglas comunes para paquetes destinados a estudiantes."""

from pathlib import PurePosixPath


MODULOS_PRIVADOS = ("herramientas", "boto3", "botocore", "s3transfer", "jmespath")
EJECUTABLES_PRIVADOS = ("fenixgestor.exe", "fenixpublicador.exe")


def validar_archivos_cliente(nombres):
    """Impide distribuir el gestor, publicadores o su SDK de escritura R2."""
    prohibidos = []
    for nombre in nombres:
        partes = tuple(parte.casefold() for parte in PurePosixPath(str(nombre).replace("\\", "/")).parts)
        if any(parte in MODULOS_PRIVADOS for parte in partes) or any(
            parte.startswith(modulo + "-") and parte.endswith(".dist-info")
            for parte in partes for modulo in MODULOS_PRIVADOS
        ) or any(parte in EJECUTABLES_PRIVADOS for parte in partes):
            prohibidos.append(str(nombre))
    if prohibidos:
        raise ValueError(f"El paquete público contiene componentes del publicador: {prohibidos[:10]}")
