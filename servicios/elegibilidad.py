"""Reglas de elegibilidad académica para mostrar materias en Fénix."""

from dominio.codigos import codigo_base


def _codigo_prerrequisito(prerrequisito):
    if isinstance(prerrequisito, dict):
        return codigo_base(prerrequisito.get("codigo"))
    return codigo_base(prerrequisito)


def _tipo_prerrequisito(prerrequisito):
    if isinstance(prerrequisito, dict):
        return str(prerrequisito.get("tipo") or "").strip().upper()
    return ""


def advertencias_materia(materia, materias_aprobadas, codigos_excluidos=None):
    """Devuelve avisos informativos que no impiden inscribir una materia."""
    aprobadas = {codigo_base(valor) for valor in (materias_aprobadas or [])}
    seleccionadas = {codigo_base(valor) for valor in (codigos_excluidos or [])}
    avisos = []
    for requisito in materia.get("prerrequisitos", []) or []:
        codigo = _codigo_prerrequisito(requisito)
        nombre = (
            str(requisito.get("nombre") or codigo)
            if isinstance(requisito, dict) else codigo
        )
        tipo = _tipo_prerrequisito(requisito)
        if codigo and codigo not in aprobadas:
            if tipo == "O":
                avisos.append(
                    f"Puedes inscribirla, pero no podrás calificarla hasta aprobar {nombre}."
                )
            elif tipo == "Y" and codigo not in seleccionadas:
                avisos.append(
                    f"Tipo Y (interpretación provisional): incluye {nombre} en el mismo semestre."
                )
    return avisos


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
    incompatibles = []
    for requisito in prerrequisitos:
        requisito_codigo = _codigo_prerrequisito(requisito)
        requisito_nombre = (
            requisito.get("nombre", "") if isinstance(requisito, dict) else ""
        )
        tipo = _tipo_prerrequisito(requisito)
        if not requisito_codigo:
            faltantes.append(requisito_nombre or "requisito sin código verificable")
        elif tipo == "O":
            # Se puede inscribir; el SIA impide calificarla hasta aprobarlo.
            continue
        elif tipo == "A":
            if requisito_codigo in excluidos and requisito_codigo not in aprobadas:
                incompatibles.append(requisito_nombre or requisito_codigo)
        elif tipo in ("E", "Y"):
            if requisito_codigo not in aprobadas and requisito_codigo not in excluidos:
                faltantes.append(requisito_nombre or requisito_codigo)
        elif requisito_codigo not in aprobadas:
            # M y tipos desconocidos conservan el criterio seguro anterior:
            # requieren aprobación registrada antes de mostrar la materia.
            faltantes.append(requisito_nombre or requisito_codigo)
    if incompatibles:
        return "Incompatibilidad Tipo A: no elijas ambas sin aprobar " + ", ".join(incompatibles)
    if faltantes:
        if any(_tipo_prerrequisito(r) in ("E", "Y") for r in prerrequisitos):
            return "Falta aprobar o incluir simultáneamente: " + ", ".join(faltantes)
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
