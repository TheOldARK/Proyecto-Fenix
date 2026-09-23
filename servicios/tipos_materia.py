"""Clasificación de materias para el perfil académico del estudiante."""


def clasificar_tipo_materia(materia, codigo, codigos_plan):
    """Clasifica una materia sin confundir posgrado con nivelación."""
    nombre = str(materia.get("nombre", "")).casefold()
    tipologia = str(materia.get("tipologia", "")).casefold()
    texto = f"{nombre} {tipologia}"
    if "trabajo de grado" in texto or "posgrado" in texto or "grado (p)" in texto:
        return "Trabajo de grado (P)"
    if "nivel" in texto:
        return "Nivelación"
    if "optativ" in texto or "electiv" in texto:
        return "Optativas"
    return "Obligatorias" if codigo in codigos_plan else "Otros"
