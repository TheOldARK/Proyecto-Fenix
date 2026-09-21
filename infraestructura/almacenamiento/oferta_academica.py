"""Persistencia de la oferta académica asociada a un plan."""

from dataclasses import asdict
from datetime import datetime

from configuracion import ARCHIVO_OFERTA, CARPETA_DATOS
from infraestructura.almacenamiento.json_atomico import cargar_json, guardar_json_atomico


def inicializar_datos():
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)


def _documento_vacio(codigo_plan=None):
    return {
        "plan_estudios": str(codigo_plan) if codigo_plan is not None else None,
        "ultima_actualizacion": None,
        "materias": {},
    }


def cargar_oferta():
    inicializar_datos()
    if not ARCHIVO_OFERTA.exists():
        return _documento_vacio()
    oferta = cargar_json(ARCHIVO_OFERTA)
    if oferta is None:
        return _documento_vacio()

    # Compatibilidad con archivos antiguos sin identidad de plan.
    if isinstance(oferta, dict) and isinstance(oferta.get("materias"), dict):
        return {
            "plan_estudios": oferta.get("plan_estudios"),
            "ultima_actualizacion": oferta.get("ultima_actualizacion"),
            "materias": oferta["materias"],
        }
    return _documento_vacio()


def cargar_plan_oferta():
    """Devuelve el código del plan asociado a oferta.json."""
    return cargar_oferta().get("plan_estudios")


def iniciar_oferta(codigo_plan=None):
    """Vacía la oferta y conserva el plan que debe poblarla."""
    inicializar_datos()
    guardar_json_atomico(ARCHIVO_OFERTA, _documento_vacio(codigo_plan))


def guardar_oferta(materias, codigo_plan=None):
    inicializar_datos()
    datos_materias = {}
    for materia in materias:
        datos = asdict(materia)
        datos_materias[materia.codigo] = datos
    guardar_json_atomico(
        ARCHIVO_OFERTA,
        {
            "plan_estudios": str(codigo_plan) if codigo_plan is not None else None,
            "ultima_actualizacion": datetime.now().isoformat(timespec="seconds"),
            "materias": datos_materias,
        },
    )


def preparar_oferta_para_plan(codigo_plan) -> bool:
    """Invalida una oferta de otro plan y devuelve si la actual es válida."""
    plan_guardado = cargar_plan_oferta()
    codigo_plan = str(codigo_plan) if codigo_plan is not None else None
    if plan_guardado == codigo_plan:
        return True
    iniciar_oferta(codigo_plan)
    return False
