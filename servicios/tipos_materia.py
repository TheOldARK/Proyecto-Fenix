"""Clasificación de materias para el perfil académico del estudiante."""


def es_materia_nivelacion(materia):
    """Reconoce Nivelación por su tipología, o por el nombre si esta falta."""
    tipologia = str(materia.get("tipologia", "")).casefold()
    nombre = str(materia.get("nombre", "")).casefold()
    return "nivel" in tipologia or "nivel" in nombre


def clasificar_tipo_materia(materia, codigo, codigos_plan):
    """Clasifica una materia sin confundir posgrado con nivelación."""
    nombre = str(materia.get("nombre", "")).casefold()
    tipologia = str(materia.get("tipologia", "")).casefold()
    texto = f"{nombre} {tipologia}"
    if "trabajo de grado" in texto or "posgrado" in texto or "grado (p)" in texto:
        return "Trabajo de grado (P)"
    if es_materia_nivelacion(materia):
        return "Nivelación"
    if "optativ" in texto or "electiv" in texto:
        return "Optativas"
    return "Obligatorias" if codigo in codigos_plan else "Otros"
