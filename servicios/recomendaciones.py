"""Reglas para priorizar asignaturas según el plan y el avance del estudiante."""

from dominio.codigos import codigo_base


def _creditos(materia):
    try:
        return max(0, float(str(materia.get("creditos", 0)).replace(",", ".")))
    except (TypeError, ValueError):
        return 0


def _es_optativa(materia):
    """Reconoce las optativas según la tipología entregada por el SIA."""
    tipologia = str(materia.get("tipologia", "")).casefold()
    return "optativ" in tipologia or "electiv" in tipologia


def codigos_recomendados(plan, aprobadas, materias_disponibles=None, minimo_creditos=16):
    """Selecciona materias del nivel actual hasta 16 créditos.

    La regla deliberadamente no toma materias obligatorias de semestres
    posteriores. Primero agrega las obligatorias pendientes del primer semestre
    incompleto. Si no alcanzan el mínimo de créditos, completa con optativas
    elegibles del semestre actual o de semestres anteriores, ordenadas desde el
    nivel más bajo. De esta manera una persona de sexto semestre no recibe
    accidentalmente Trabajo de grado u otra obligatoria avanzada.
    """
    aprobadas = {codigo_base(codigo) for codigo in (aprobadas or [])}
    disponibles = None
    if materias_disponibles is not None:
        disponibles = {
            codigo_base(materia.get("codigo")): materia
            for materia in materias_disponibles
        }

    semestres = sorted(plan.semestres, key=lambda item: item.numero)
    pendientes_por_semestre = {}
    semestre_por_codigo = {}
    for semestre in semestres:
        pendientes = []
        for codigo in semestre.asignaturas:
            base = codigo_base(codigo)
            if base not in aprobadas:
                pendientes.append(base)
                semestre_por_codigo.setdefault(base, semestre.numero)
        if pendientes:
            pendientes_por_semestre[semestre.numero] = pendientes

    if not pendientes_por_semestre:
        return set()

    semestre_actual = min(pendientes_por_semestre)
    seleccionadas = set()
    creditos = 0

    def disponible(codigo):
        return disponibles is None or codigo in disponibles

    def agregar(codigo):
        nonlocal creditos
        if codigo in seleccionadas or not disponible(codigo):
            return
        seleccionadas.add(codigo)
        if disponibles is not None:
            creditos += _creditos(disponibles[codigo])

    # Obligaciones del primer semestre incompleto, nunca de semestres futuros.
    for codigo in pendientes_por_semestre[semestre_actual]:
        materia = disponibles.get(codigo, {}) if disponibles is not None else {}
        if disponibles is None or not _es_optativa(materia):
            agregar(codigo)

    # Las optativas sirven para completar carga, pero no se buscan en niveles
    # posteriores al actual para evitar recomendar asignaturas avanzadas.
    if disponibles is not None and creditos < minimo_creditos:
        optativas = []
        for codigo, materia in disponibles.items():
            nivel = semestre_por_codigo.get(codigo)
            if nivel is None or nivel > semestre_actual or not _es_optativa(materia):
                continue
            if codigo in aprobadas or codigo in seleccionadas:
                continue
            optativas.append((nivel, codigo, materia))
        for _, codigo, _ in sorted(optativas, key=lambda item: (item[0], item[1])):
            agregar(codigo)
            if creditos >= minimo_creditos:
                break

    return seleccionadas


def ordenar_materias(materias, recomendadas):
    """Ordena recomendadas primero y después el resto alfabéticamente."""
    recomendadas = {codigo_base(codigo) for codigo in (recomendadas or [])}
    return sorted(
        materias,
        key=lambda materia: (
            0 if codigo_base(materia.get("codigo")) in recomendadas else 1,
            str(materia.get("nombre", "")).casefold(),
        ),
    )
