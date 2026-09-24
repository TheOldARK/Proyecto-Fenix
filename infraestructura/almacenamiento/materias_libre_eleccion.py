# =============================================================
# ALMACENAMIENTO DE MATERIAS DE LIBRE ELECCIÓN
# =============================================================
#
# Este módulo se encarga de guardar y cargar las materias de
# Libre Elección que Fénix obtiene del SIA.
#
# Estas materias se almacenan en un archivo independiente porque
# no forman parte de la lista normal de asignaturas del catálogo.
#
# El archivo utilizado es:
#
#     datos/libres_eleccion.json
#
# Este módulo pertenece a la capa de infraestructura, por lo que
# su responsabilidad es trabajar con el sistema de archivos.
# No debe contener reglas relacionadas con la elegibilidad o
# con la generación de horarios.


import json
from datetime import datetime
from pathlib import Path

from configuracion import (
    CARPETA_DATOS,
    ARCHIVO_LIBRES_ELECCION,
    ARCHIVO_LIBRES_ELECCION_SEDE,
)
from infraestructura.almacenamiento.json_atomico import guardar_json_atomico


# =============================================================
# INICIALIZACIÓN DE LOS DATOS
# =============================================================


def inicializar_datos():
    # Crear la carpeta donde Fénix almacena sus datos si todavía
    # no existe.
    #
    # parents=True permite crear también las carpetas superiores
    # que sean necesarias.
    #
    # exist_ok=True evita producir un error si la carpeta ya
    # existe.
    CARPETA_DATOS.mkdir(
        parents=True,
        exist_ok=True
    )


# =============================================================
# CARGAR MATERIAS
# =============================================================


def cargar_libres_eleccion(codigo_plan=None):
    # Asegurarnos de que la carpeta de datos exista antes
    # de intentar acceder al archivo.
    inicializar_datos()

    # Si todavía no existe el archivo, significa que Fénix
    # aún no ha almacenado materias de Libre Elección.
    #
    # En lugar de producir un error, simplemente devolvemos
    # una lista vacía.
    if not ARCHIVO_LIBRES_ELECCION.exists():
        return []

    try:

        # Abrir el archivo utilizando UTF-8 para conservar
        # correctamente caracteres como tildes y ñ.
        with open(
            ARCHIVO_LIBRES_ELECCION,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(
                archivo
            )

        # Normalmente el archivo contiene un objeto con una
        # estructura similar a:
        #
        # {
        #     "ultima_actualizacion": "...",
        #     "materias": [...]
        # }
        #
        # Si recibimos un diccionario, obtener la lista
        # almacenada bajo la clave "materias".
        if isinstance(datos, dict):

            plan_guardado = datos.get("plan_estudios")
            if codigo_plan is not None and str(plan_guardado) != str(codigo_plan):
                return []
            materias = datos.get(
                "materias",
                []
            )

            if isinstance(materias, list):
                return materias

            # El formato actual utiliza un diccionario indexado por código.
            # Un documento recién creado puede contenerlo vacío; equivale a
            # no tener materias descargadas y no debe producir una alerta.
            if materias == {}:
                return []

            print(
                "⚠ El formato de libres_eleccion.json "
                "no es válido."
            )
            return []

        # Esta alternativa permite leer archivos que contengan
        # directamente una lista de materias.
        #
        # Es útil como compatibilidad con versiones anteriores
        # del archivo.
        if isinstance(datos, list):
            return datos

        print(
            "⚠ El formato de libres_eleccion.json "
            "no es válido."
        )
        return []

    except (
        json.JSONDecodeError,
        OSError
    ):

        # Si el archivo está dañado, no existe un permiso
        # suficiente o no puede abrirse correctamente, evitamos
        # que el error detenga toda la aplicación.
        print(
            "⚠ No se pudo leer "
            "libres_eleccion.json."
        )

        return []


# =============================================================
# GUARDAR MATERIAS
# =============================================================


def guardar_libres_eleccion(materias, codigo_plan=None):
    # Asegurarnos de que la carpeta de datos exista antes
    # de intentar guardar el archivo.
    inicializar_datos()

    # Construir la información que será almacenada.
    #
    # Además de las materias, guardamos la fecha y hora de la
    # última actualización para saber cuándo fueron obtenidos
    # los datos.
    datos = {
        "plan_estudios": str(codigo_plan) if codigo_plan is not None else None,
        "ultima_actualizacion":
            datetime.now().isoformat(
                timespec="seconds"
            ),

        "materias": materias
    }

    guardar_json_atomico(ARCHIVO_LIBRES_ELECCION, datos)


def cargar_libres_eleccion_sede():
    """Lee el catálogo compartido de Libre Elección de la sede."""
    inicializar_datos()
    try:
        datos = json.loads(ARCHIVO_LIBRES_ELECCION_SEDE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    materias = datos.get("materias", []) if isinstance(datos, dict) else []
    return materias if isinstance(materias, list) else []


def guardar_libres_eleccion_sede(materias, sede="1102"):
    """Guarda el resultado independiente del plan que consultó el catálogo."""
    inicializar_datos()
    datos = {
        "sede": str(sede),
        "ultima_actualizacion": datetime.now().isoformat(timespec="seconds"),
        "materias": materias,
    }
    guardar_json_atomico(ARCHIVO_LIBRES_ELECCION_SEDE, datos)


def sincronizar_libres_eleccion_sede(origen, destino=ARCHIVO_LIBRES_ELECCION_SEDE):
    """Valida y copia atómicamente el catálogo de sede de un publicador hijo."""
    origen = Path(origen)
    try:
        datos = json.loads(origen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"No se pudo leer el catálogo compartido '{origen}': {error}") from error

    if not isinstance(datos, dict) or str(datos.get("sede", "")).strip() != "1102":
        raise ValueError("El catálogo compartido no corresponde a la sede Medellín (1102).")
    materias = datos.get("materias")
    if not isinstance(materias, list):
        raise ValueError("El catálogo compartido no contiene una lista válida de materias.")
    if any(
        not isinstance(materia, dict) or not str(materia.get("codigo", "")).strip()
        for materia in materias
    ):
        raise ValueError("El catálogo compartido contiene materias sin código válido.")

    guardar_json_atomico(destino, datos)
    return len(materias)


def preparar_libres_para_plan(codigo_plan):
    """Vacía las libres si pertenecen a otro plan o son de formato antiguo."""
    inicializar_datos()
    if not ARCHIVO_LIBRES_ELECCION.exists():
        return False
    try:
        with open(ARCHIVO_LIBRES_ELECCION, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (json.JSONDecodeError, OSError):
        datos = {}
    plan_guardado = datos.get("plan_estudios") if isinstance(datos, dict) else None
    if str(plan_guardado) == str(codigo_plan):
        return True
    guardar_libres_eleccion([], codigo_plan=codigo_plan)
    return False
