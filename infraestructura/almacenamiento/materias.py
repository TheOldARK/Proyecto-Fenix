"""Persistencia de materias normales asociada a un plan de estudios."""

from dataclasses import asdict

from configuracion import ARCHIVO_MATERIAS, CARPETA_DATOS
from infraestructura.almacenamiento.json_atomico import cargar_json, guardar_json_atomico


def inicializar_datos():
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)


def _leer_documento():
    inicializar_datos()
    if not ARCHIVO_MATERIAS.exists():
        return {"plan_estudios": None, "materias": {}}
    datos = cargar_json(ARCHIVO_MATERIAS)
    if datos is None:
        print("⚠ No se pudo leer materias.json.")
        return {"plan_estudios": None, "materias": {}}

    # Compatibilidad con el formato antiguo: lista o diccionario directo.
    if isinstance(datos, list):
        materias = {
            materia["codigo"]: materia
            for materia in datos
            if isinstance(materia, dict) and "codigo" in materia
        }
        return {"plan_estudios": None, "materias": materias}
    if isinstance(datos, dict) and isinstance(datos.get("materias"), dict):
        return {
            "plan_estudios": datos.get("plan_estudios"),
            "materias": datos["materias"],
        }
    if isinstance(datos, dict):
        return {"plan_estudios": None, "materias": datos}
    print("⚠ El formato de materias.json no es válido.")
    return {"plan_estudios": None, "materias": {}}


def cargar_materias():
    """Devuelve las materias indexadas por código, como en versiones previas."""
    return _leer_documento()["materias"]


def cargar_plan_materias():
    """Devuelve el código del plan asociado a materias.json, si existe."""
    return _leer_documento()["plan_estudios"]


def guardar_materias(materias, codigo_plan=None):
    """Guarda materias y la identidad del plan al que pertenecen."""
    inicializar_datos()
    datos_materias = {}
    for materia in materias:
        datos = asdict(materia)
        datos["grupos"] = []
        datos_materias[materia.codigo] = datos

    documento = {
        "plan_estudios": str(codigo_plan) if codigo_plan is not None else None,
        "materias": datos_materias,
    }
    guardar_json_atomico(ARCHIVO_MATERIAS, documento)


def preparar_materias_para_plan(codigo_plan) -> bool:
    """Invalida materias de otro plan y devuelve si las actuales son válidas."""
    plan_guardado = cargar_plan_materias()
    codigo_plan = str(codigo_plan) if codigo_plan is not None else None
    if plan_guardado == codigo_plan:
        return True
    guardar_json_atomico(
        ARCHIVO_MATERIAS,
        {"plan_estudios": codigo_plan, "materias": {}},
    )
    return False
