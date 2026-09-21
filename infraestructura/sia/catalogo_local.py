"""Índice local de rutas académicas disponibles en el catálogo SIA.

El código académico del plan no es único entre sedes y facultades. Por eso la
identidad de una entrada se forma como sede:facultad:plan.
"""

import json

from configuracion import ARCHIVO_CATALOGO_SIA


def clave_plan(sede_codigo, facultad_codigo, plan_codigo):
    """Devuelve la identidad estable de una ruta académica."""
    return f"{sede_codigo}:{facultad_codigo}:{plan_codigo}"


def cargar_catalogo():
    """Carga el catálogo local y devuelve sus entradas aplanadas."""
    with open(ARCHIVO_CATALOGO_SIA, "r", encoding="utf-8") as archivo:
        documento = json.load(archivo)

    entradas = []
    for nivel in documento.get("niveles_estudio", []):
        for sede in nivel.get("sedes", []):
            for facultad in sede.get("facultades", []):
                for plan in facultad.get("planes_estudio", []):
                    codigo = plan.get("codigo")
                    if not codigo:
                        continue
                    sede_codigo = str(sede.get("codigo", ""))
                    facultad_codigo = str(facultad.get("codigo", ""))
                    plan_codigo = str(codigo)
                    entradas.append({
                        "clave": clave_plan(sede_codigo, facultad_codigo, plan_codigo),
                        "nivel": nivel,
                        "sede": sede,
                        "facultad": facultad,
                        "plan": plan,
                        "sede_codigo": sede_codigo,
                        "facultad_codigo": facultad_codigo,
                        "plan_codigo": plan_codigo,
                        "valor_nivel": str(nivel.get("value", "")),
                        "valor_sede": str(sede.get("value", "")),
                        "valor_facultad": str(facultad.get("value", "")),
                        "valor_plan": str(plan.get("value", "")),
                    })
    return entradas


def indice_catalogo():
    """Indexa todas las rutas por clave compuesta."""
    return {entrada["clave"]: entrada for entrada in cargar_catalogo()}


def buscar_por_codigo(codigo):
    """Devuelve todas las rutas que comparten un código de plan."""
    codigo = str(codigo)
    return [entrada for entrada in cargar_catalogo() if entrada["plan_codigo"] == codigo]
