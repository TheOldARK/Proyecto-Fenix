"""Exportación e importación de estados portables de Fénix.

Un archivo ``.fnx`` es un ZIP con un manifiesto y los JSON de ``datos/``.
Se incluye la oferta y el catálogo actual para recuperar el horario, además
 del perfil del estudiante y los planes necesarios para interpretarlo.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from configuracion import CARPETA_DATOS
from infraestructura.almacenamiento.json_atomico import guardar_json_atomico

FORMATO = "fenix-state"
VERSION_FORMATO = 1
ARCHIVOS_RESPALDO = (
    "estudiante.json",
    "materias.json",
    "oferta.json",
    "libres_eleccion.json",
    "planes_estudio.json",
    "estado_actualizacion.json",
)
ARCHIVO_MATERIAS_SELECCIONADAS = "materias_seleccionadas.json"


def _leer_json(ruta: Path):
    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"No se pudo leer {ruta.name}: {error}") from error


def _materias_seleccionadas(archivos):
    """Recopila la oferta completa de las materias elegidas por el estudiante."""
    estudiante = archivos.get("estudiante.json", {})
    plan = estudiante.get("plan_estudios") if isinstance(estudiante, dict) else None
    referencias = estudiante.get("grupos_seleccionados", []) if isinstance(estudiante, dict) else []
    oferta = archivos.get("oferta.json", {})
    libres = archivos.get("libres_eleccion.json", {})
    materias_oferta = oferta.get("materias", {}) if isinstance(oferta, dict) else {}
    materias_libres = libres.get("materias", []) if isinstance(libres, dict) else []
    if isinstance(materias_libres, dict):
        materias_libres = list(materias_libres.values())

    resultado = []
    for referencia in referencias if isinstance(referencias, list) else []:
        if not isinstance(referencia, dict):
            continue
        codigo = str(referencia.get("codigo", ""))
        origen = referencia.get("origen", "principal")
        materia = None
        if origen == "libre":
            materia = next(
                (valor for valor in materias_libres
                 if isinstance(valor, dict) and str(valor.get("codigo", "")) == codigo),
                None,
            )
        elif isinstance(materias_oferta, dict):
            materia = materias_oferta.get(codigo)
        if isinstance(materia, dict):
            resultado.append({"origen": origen, "materia": materia})

    return {
        "plan_estudios": plan,
        "materias": resultado,
    }


def _incorporar_materias_seleccionadas(archivos):
    """Mezcla el respaldo solo si pertenece al mismo plan del estudiante."""
    respaldo = archivos.get(ARCHIVO_MATERIAS_SELECCIONADAS, {})
    estudiante = archivos.get("estudiante.json", {})
    if not isinstance(respaldo, dict) or not isinstance(estudiante, dict):
        return
    plan = estudiante.get("plan_estudios")
    if plan is None or respaldo.get("plan_estudios") is None:
        return
    if str(respaldo.get("plan_estudios")) != str(plan):
        return

    oferta = archivos.get("oferta.json", {})
    libres = archivos.get("libres_eleccion.json", {})
    oferta_valida = (
        isinstance(oferta, dict)
        and str(oferta.get("plan_estudios")) == str(plan)
    )
    libres_valida = (
        isinstance(libres, dict)
        and str(libres.get("plan_estudios")) == str(plan)
    )
    materias_oferta = oferta.setdefault("materias", {}) if oferta_valida else None
    materias_libres = libres.setdefault("materias", []) if libres_valida else None
    if isinstance(materias_libres, dict):
        materias_libres = list(materias_libres.values())
        libres["materias"] = materias_libres

    for entrada in respaldo.get("materias", []):
        if not isinstance(entrada, dict) or not isinstance(entrada.get("materia"), dict):
            continue
        materia = entrada["materia"]
        codigo = str(materia.get("codigo", ""))
        if not codigo:
            continue
        if entrada.get("origen", "principal") == "libre" and libres_valida:
            materias_libres[:] = [
                existente for existente in materias_libres
                if not isinstance(existente, dict) or str(existente.get("codigo", "")) != codigo
            ]
            materias_libres.append(materia)
        elif entrada.get("origen", "principal") != "libre" and oferta_valida:
            materias_oferta[codigo] = materia


def exportar_fnx(destino, carpeta_datos=None) -> Path:
    """Empaqueta todos los JSON locales en *destino* con formato FNX."""
    destino = Path(destino)
    carpeta_datos = Path(carpeta_datos or CARPETA_DATOS)
    destino.parent.mkdir(parents=True, exist_ok=True)
    archivos = {nombre: _leer_json(carpeta_datos / nombre) for nombre in ARCHIVOS_RESPALDO}
    archivos[ARCHIVO_MATERIAS_SELECCIONADAS] = _materias_seleccionadas(archivos)
    manifiesto = {
        "formato": FORMATO,
        "version": VERSION_FORMATO,
        "creado_en": datetime.now(timezone.utc).isoformat(),
        "archivos": list(archivos),
    }
    temporal = destino.with_suffix(f"{destino.suffix}.tmp")
    try:
        with zipfile.ZipFile(temporal, "w", compression=zipfile.ZIP_DEFLATED) as paquete:
            paquete.writestr("manifest.json", json.dumps(manifiesto, ensure_ascii=False, indent=2))
            for nombre, datos in archivos.items():
                paquete.writestr(nombre, json.dumps(datos, ensure_ascii=False, indent=2))
        temporal.replace(destino)
    except OSError:
        temporal.unlink(missing_ok=True)
        raise
    return destino


def _validar_paquete(origen: Path) -> dict[str, object]:
    if not zipfile.is_zipfile(origen):
        raise ValueError("El archivo seleccionado no es un paquete FNX válido.")
    try:
        with zipfile.ZipFile(origen, "r") as paquete:
            nombres = set(paquete.namelist())
            if "manifest.json" not in nombres:
                raise ValueError("El paquete no contiene manifest.json.")
            manifiesto = json.loads(paquete.read("manifest.json"))
            if manifiesto.get("formato") != FORMATO:
                raise ValueError("El archivo no pertenece a Fénix.")
            if manifiesto.get("version") != VERSION_FORMATO:
                raise ValueError("La versión del paquete FNX no es compatible.")
            datos = {}
            for nombre in ARCHIVOS_RESPALDO:
                if nombre not in nombres:
                    raise ValueError(f"El paquete está incompleto: falta {nombre}.")
                valor = json.loads(paquete.read(nombre))
                if not isinstance(valor, (dict, list)):
                    raise ValueError(f"El contenido de {nombre} no tiene un formato válido.")
                datos[nombre] = valor
            if ARCHIVO_MATERIAS_SELECCIONADAS in nombres:
                datos[ARCHIVO_MATERIAS_SELECCIONADAS] = json.loads(
                    paquete.read(ARCHIVO_MATERIAS_SELECCIONADAS)
                )
            else:
                datos[ARCHIVO_MATERIAS_SELECCIONADAS] = {}
            return datos
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise ValueError(f"No se pudo leer el paquete FNX: {error}") from error


def importar_fnx(origen, carpeta_datos=None) -> None:
    """Valida y restaura el paquete completo antes de publicar sus archivos."""
    datos = _validar_paquete(Path(origen))
    carpeta_datos = Path(carpeta_datos or CARPETA_DATOS)
    carpeta_datos.mkdir(parents=True, exist_ok=True)
    _incorporar_materias_seleccionadas(datos)
    for nombre in ARCHIVOS_RESPALDO:
        guardar_json_atomico(carpeta_datos / nombre, datos[nombre])
