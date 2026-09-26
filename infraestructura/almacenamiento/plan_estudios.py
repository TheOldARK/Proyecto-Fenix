"""Persistencia de los planes de estudio.

Este módulo mantiene dos niveles de acceso: datos crudos para herramientas
administrativas y objetos de dominio para el resto de la aplicación.
"""

import json

from configuracion import ARCHIVO_PLANES_ESTUDIO, CARPETA_DATOS_BASE
from dominio.plan_estudios import PlanEstudios, Semestre
from infraestructura.almacenamiento.json_atomico import guardar_json_atomico


def _fusionar_faltantes(perfil, base):
    """Incorpora datos nuevos del paquete sin reemplazar ajustes del perfil."""
    if isinstance(perfil, dict) and isinstance(base, dict):
        resultado = dict(perfil)
        for clave, valor in base.items():
            if clave in resultado:
                resultado[clave] = _fusionar_faltantes(resultado[clave], valor)
            else:
                resultado[clave] = valor
        return resultado
    if isinstance(perfil, list) and isinstance(base, list):
        if not perfil:
            return base
        if all(isinstance(item, dict) for item in perfil + base):
            resultado = list(perfil)
            posiciones = {}
            for indice, item in enumerate(resultado):
                identidad = item.get("codigo", item.get("nombre"))
                if identidad is not None:
                    posiciones[("codigo" if "codigo" in item else "nombre", str(identidad).casefold())] = indice
            for item in base:
                identidad = item.get("codigo", item.get("nombre"))
                if identidad is None:
                    resultado.append(item)
                    continue
                clave = ("codigo" if "codigo" in item else "nombre", str(identidad).casefold())
                if clave in posiciones:
                    indice = posiciones[clave]
                    resultado[indice] = _fusionar_faltantes(resultado[indice], item)
                else:
                    posiciones[clave] = len(resultado)
                    resultado.append(item)
            return resultado
        return perfil
    return base if perfil in (None, "", [], {}) else perfil


def _cargar_documento(ruta):
    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            documento = json.load(archivo)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"No se pudo leer {ruta.name}: {error}") from error
    if not isinstance(documento, dict) or not isinstance(documento.get("planes"), dict):
        raise ValueError(f"{ruta.name} debe contener un objeto dentro de 'planes'.")
    return documento


def cargar_datos_planes() -> dict:
    """Devuelve el documento JSON completo o lanza un error descriptivo."""
    perfil = _cargar_documento(ARCHIVO_PLANES_ESTUDIO) or {"planes": {}}
    ruta_base = CARPETA_DATOS_BASE / ARCHIVO_PLANES_ESTUDIO.name
    if ruta_base.resolve() == ARCHIVO_PLANES_ESTUDIO.resolve():
        return perfil
    base = _cargar_documento(ruta_base)
    if base is None:
        return perfil
    return _fusionar_faltantes(perfil, base)


def guardar_datos_planes(datos: dict) -> None:
    """Publica el documento completo reemplazando el archivo de forma atómica."""
    if not isinstance(datos, dict) or not isinstance(datos.get("planes"), dict):
        raise ValueError("Los planes deben ser un diccionario dentro de la clave 'planes'.")
    ARCHIVO_PLANES_ESTUDIO.parent.mkdir(parents=True, exist_ok=True)
    guardar_json_atomico(ARCHIVO_PLANES_ESTUDIO, datos)


def cargar_planes() -> dict[str, PlanEstudios]:
    """Convierte el JSON almacenado en objetos del dominio."""
    try:
        datos_planes = cargar_datos_planes().get("planes", {})
    except ValueError as error:
        print(f"⚠ {error}")
        return {}

    planes = {}
    for codigo, datos_plan in datos_planes.items():
        if not isinstance(datos_plan, dict):
            continue

        semestres = []
        datos_semestres = datos_plan.get("semestres", {})
        if not isinstance(datos_semestres, dict):
            continue

        for numero, datos_semestre in datos_semestres.items():
            if not isinstance(datos_semestre, dict):
                continue
            try:
                numero_semestre = int(numero)
            except (TypeError, ValueError):
                continue
            asignaturas = datos_semestre.get("asignaturas", [])
            creditos = datos_semestre.get("creditos", {})
            semestres.append(
                Semestre(
                    numero=numero_semestre,
                    asignaturas=list(asignaturas) if isinstance(asignaturas, list) else [],
                    creditos=dict(creditos) if isinstance(creditos, dict) else {},
                )
            )

        semestres.sort(key=lambda semestre: semestre.numero)
        nombres = datos_plan.get("nombres_asignaturas", {})
        if not isinstance(nombres, dict):
            nombres = {}
        clave = str(datos_plan.get("clave", codigo))
        planes[clave] = PlanEstudios(
            codigo=str(datos_plan.get("codigo", codigo)),
            nombre=str(datos_plan.get("nombre", "")),
            sede_codigo=str(datos_plan.get("sede_codigo", "")),
            sede_nombre=str(datos_plan.get("sede_nombre", "")),
            facultad_codigo=str(datos_plan.get("facultad_codigo", "")),
            facultad_nombre=str(datos_plan.get("facultad_nombre", "")),
            valor_sede=str(datos_plan.get("valor_sede", "")),
            valor_facultad=str(datos_plan.get("valor_facultad", "")),
            valor_plan=str(datos_plan.get("valor_plan", "")),
            nombres_asignaturas={
                str(codigo_materia): str(nombre_materia)
                for codigo_materia, nombre_materia in nombres.items()
                if isinstance(codigo_materia, str)
                and isinstance(nombre_materia, str)
            },
            semestres=semestres,
        )
    return planes


def obtener_plan(codigo):
    """Obtiene un plan por código sin exponer el archivo JSON al llamador."""
    return cargar_planes().get(codigo)
