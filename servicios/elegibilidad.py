"""Reglas de elegibilidad académica para mostrar materias en Fénix."""

from dominio.codigos import codigo_base


def _codigo_prerrequisito(prerrequisito):
    if isinstance(prerrequisito, dict):
        return codigo_base(prerrequisito.get("codigo"))
    return codigo_base(prerrequisito)


def motivo_materia_no_mostrable(materia, materias_aprobadas, codigos_excluidos=None):
    """Devuelve el motivo por el que una materia no se puede elegir."""
    codigo = codigo_base(materia.get("codigo"))
    aprobadas = {codigo_base(valor) for valor in (materias_aprobadas or [])}
    excluidos = {codigo_base(valor) for valor in (codigos_excluidos or [])}
    if codigo in aprobadas:
        return "Ya está registrada como materia aprobada"
    if codigo in excluidos:
        return "Ya elegiste un grupo de esta materia"

    prerrequisitos = materia.get("prerrequisitos", [])
    if not prerrequisitos:
        return ""
    faltantes = []
    for requisito in prerrequisitos:
        requisito_codigo = _codigo_prerrequisito(requisito)
        requisito_nombre = (
            requisito.get("nombre", "") if isinstance(requisito, dict) else ""
        )
        if not requisito_codigo:
            faltantes.append(requisito_nombre or "requisito sin código verificable")
        elif requisito_codigo not in aprobadas:
            faltantes.append(requisito_nombre or requisito_codigo)
    if faltantes:
        return "Falta aprobar: " + ", ".join(faltantes)
    return ""


def materia_puede_mostrarse(materia, materias_aprobadas):
    """Indica si la materia cumple todos sus prerrequisitos."""
    return not motivo_materia_no_mostrable(materia, materias_aprobadas)


def materias_visibles(materias, materias_aprobadas, codigos_excluidos=None):
    """Filtra materias aprobadas/seleccionadas y las no elegibles."""
    return [
        materia
        for materia in materias
        if not motivo_materia_no_mostrable(
            materia, materias_aprobadas, codigos_excluidos
        )
    ]
