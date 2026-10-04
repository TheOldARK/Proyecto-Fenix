"""Verifica que las materias de las mallas estén publicadas en Cloudflare.

Uso desde la raíz del proyecto:
    python herramientas/verificar_planes_cloudflare.py

No modifica planes ni Cloudflare. --informe guarda opcionalmente un reporte JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import certifi

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from configuracion import URL_DATOS_CLOUDFLARE
from infraestructura.almacenamiento.plan_estudios import cargar_planes
from dominio.codigos import codigo_base
from infraestructura.almacenamiento.json_atomico import guardar_json_atomico


def _codigos_y_nombres_plan(plan) -> dict[str, str]:
    nombres = getattr(plan, "nombres_asignaturas", {}) or {}
    resultado = {
        codigo_base(codigo): str(nombre).strip()
        for codigo, nombre in nombres.items()
        if str(codigo).strip()
    }
    for semestre in getattr(plan, "semestres", []) or []:
        for codigo in getattr(semestre, "asignaturas", []) or []:
            resultado.setdefault(codigo_base(codigo), "")
    resultado.pop("", None)
    return resultado


def _codigos_asignados(plan) -> set[str]:
    return {
        codigo_base(codigo)
        for semestre in getattr(plan, "semestres", []) or []
        for codigo in getattr(semestre, "asignaturas", []) or []
        if codigo_base(codigo)
    }


def _codigos_documento(documento) -> set[str]:
    """Obtiene los códigos tanto del formato Fénix actual como de formatos viejos."""
    if isinstance(documento, dict) and "materias" in documento:
        materias = documento["materias"]
    else:
        materias = documento
    if isinstance(materias, dict):
        codigos = set()
        for codigo, materia in materias.items():
            codigo = str(codigo).strip()
            if codigo and codigo not in {"ultima_actualizacion", "plan_estudios"}:
                codigos.add(codigo_base(codigo))
            if isinstance(materia, dict) and materia.get("codigo"):
                codigos.add(codigo_base(materia["codigo"]))
        return codigos
    if isinstance(materias, list):
        return {
            codigo_base(materia["codigo"])
            for materia in materias
            if isinstance(materia, dict) and str(materia.get("codigo", "")).strip()
        }
    raise ValueError("El JSON no contiene una lista o diccionario de materias válido.")


def _descargar_json(base: str, info: dict) -> object:
    ruta = str(info.get("ruta", "")).strip()
    esperado = str(info.get("sha256", "")).strip().lower()
    if not ruta or ruta.startswith("/") or "\\" in ruta or ".." in PurePosixPath(ruta).parts:
        raise ValueError("La ruta remota del manifiesto no es válida.")
    if len(esperado) != 64 or any(c not in "0123456789abcdef" for c in esperado):
        raise ValueError("El manifiesto no contiene un SHA-256 válido.")
    url = f"{base.rstrip('/')}/{quote(ruta, safe='/-_.')}"
    solicitud = Request(
        url,
        headers={"User-Agent": "Proyecto-Fenix-Verificador", "Accept": "application/json"},
    )
    with urlopen(
        solicitud,
        timeout=25,
        context=ssl.create_default_context(cafile=certifi.where()),
    ) as respuesta:
        contenido = respuesta.read()
    obtenido = hashlib.sha256(contenido).hexdigest()
    if obtenido != esperado:
        raise ValueError(f"SHA-256 incorrecto (manifiesto {esperado[:12]}, archivo {obtenido[:12]}).")
    return json.loads(contenido.decode("utf-8"))


def verificar_cobertura(planes, manifiesto, cargar_json_remoto, sede="1102",
                       facultad=None, plan_elegido=None, progreso=None):
    """Compara todas las materias declaradas en cada plan con materias.json y oferta.json."""
    entradas = manifiesto.get("planes") if isinstance(manifiesto, dict) else None
    if not isinstance(entradas, dict):
        raise ValueError("El manifiesto de Cloudflare no contiene el mapa 'planes'.")

    informe = []
    seleccion = []
    for codigo, plan in sorted(planes.items(), key=lambda par: (par[1].facultad_nombre.casefold(), par[1].nombre.casefold(), str(par[0]))):
        if str(getattr(plan, "sede_codigo", "")) != str(sede):
            continue
        if facultad and str(getattr(plan, "facultad_codigo", "")) != str(facultad):
            continue
        if plan_elegido and str(plan_elegido) not in {str(codigo), str(getattr(plan, "codigo", ""))}:
            continue
        seleccion.append((codigo, plan))
    for indice, (codigo, plan) in enumerate(seleccion, 1):
        if progreso:
            progreso(indice, len(seleccion), plan.nombre)
        cursos = _codigos_y_nombres_plan(plan)

        registro = {
            "codigo_plan": str(codigo),
            "facultad_codigo": str(getattr(plan, "facultad_codigo", "")),
            "facultad": str(getattr(plan, "facultad_nombre", "")),
            "plan": str(getattr(plan, "nombre", "")),
            "total": len(cursos),
            "sin_semestre": sorted(set(cursos) - _codigos_asignados(plan)),
            "faltan_materias": [],
            "faltan_oferta": [],
            "errores": [],
            "no_verificados": [],
            "materias_faltantes_detalle": [],
            "oferta_faltante_detalle": [],
        }
        if not cursos:
            registro["estado"] = "sin_malla"
            informe.append(registro)
            continue
        entrada = entradas.get(str(codigo))
        archivos = entrada.get("archivos") if isinstance(entrada, dict) else None
        if not isinstance(archivos, dict):
            registro["errores"].append("El plan no está publicado en el manifiesto.")
            registro["faltan_materias"] = list(cursos)
            registro["faltan_oferta"] = list(cursos)
        else:
            for clave, campo in (("materias", "faltan_materias"), ("oferta", "faltan_oferta")):
                info = archivos.get(clave)
                if not isinstance(info, dict):
                    registro["errores"].append(f"El manifiesto no incluye el archivo {clave}.json.")
                    registro[campo] = list(cursos)
                    continue
                try:
                    documento = cargar_json_remoto(info)
                    identidad = documento.get("plan_estudios") if isinstance(documento, dict) else None
                    if identidad and str(identidad) != str(codigo):
                        raise ValueError(f"El archivo pertenece al plan {identidad}, no a {codigo}.")
                    codigos_publicados = _codigos_documento(documento)
                except (OSError, ValueError, HTTPError, json.JSONDecodeError) as error:
                    registro["errores"].append(f"No se pudo verificar {clave}.json: {error}")
                    registro["no_verificados"].append(clave)
                    continue
                registro[campo] = sorted(set(cursos) - codigos_publicados, key=str)

        registro["materias_faltantes_detalle"] = [
            {
                "codigo": c,
                "nombre": cursos.get(c) or "(sin nombre en planes_estudio.json)",
                "sin_semestre": c in registro["sin_semestre"],
            }
            for c in registro["faltan_materias"]
        ]
        registro["oferta_faltante_detalle"] = [
            {
                "codigo": c,
                "nombre": cursos.get(c) or "(sin nombre en planes_estudio.json)",
                "sin_semestre": c in registro["sin_semestre"],
            }
            for c in registro["faltan_oferta"]
        ]
        registro["estado"] = (
            "no_verificado" if registro["no_verificados"] else
            "no_publicado" if not isinstance(archivos, dict) else
            "incompleto" if registro["faltan_materias"] or registro["faltan_oferta"] or registro["errores"] else
            "completo"
        )
        informe.append(registro)
    return informe


def ejecutar(base: str, sede: str, facultad=None, plan_elegido=None, ruta_informe=None) -> int:
    solicitud = Request(
        f"{base.rstrip('/')}/manifest.json",
        headers={"User-Agent": "Proyecto-Fenix-Verificador", "Accept": "application/json"},
    )
    contexto = ssl.create_default_context(cafile=certifi.where())
    try:
        with urlopen(solicitud, timeout=25, context=contexto) as respuesta:
            manifiesto = json.loads(respuesta.read().decode("utf-8"))
    except Exception as error:
        print(f"ERROR: no se pudo leer el manifiesto de Cloudflare: {error}")
        return 2

    try:
        planes = cargar_planes()
        informe = verificar_cobertura(
            planes,
            manifiesto,
            lambda info: _descargar_json(base, info),
            sede=sede,
            facultad=facultad,
            plan_elegido=plan_elegido,
            progreso=lambda i, total, nombre: print(f"Consultando {i}/{total}: {nombre}", flush=True),
        )
    except Exception as error:
        print(f"ERROR: no se pudo completar la verificación: {error}")
        return 2

    if not informe:
        print(f"No hay planes que coincidan con los filtros para la sede {sede}.")
        return 1

    sin_malla = sum(item["estado"] == "sin_malla" for item in informe)
    no_verificados = sum(item["estado"] == "no_verificado" for item in informe)

    print(f"VERIFICACIÓN DE MALLAS EN CLOUDFLARE · SEDE {sede}\n")
    print("Falta = está definida en el plan local, pero no aparece en el archivo remoto verificado.")
    print("SIN MALLA = carrera vacía pendiente de edición; NO VERIFICADO = no se pudo comprobar la descarga.")
    print("Solo se comprueba presencia: no garantiza cupos ni grupos disponibles. No se exige Libre Elección.\n")
    cursos_total = 0
    faltan_materias_total = 0
    faltan_oferta_total = 0
    con_problemas = 0
    for item in informe:
        if item["estado"] == "sin_malla":
            print(f"[SIN MALLA] {item['facultad']} · {item['plan']} ({item['codigo_plan']}) — pendiente de completar en el editor")
            continue
        cursos_total += item["total"]
        faltan_materias_total += len(item["faltan_materias"])
        faltan_oferta_total += len(item["faltan_oferta"])
        completo = not item["faltan_materias"] and not item["faltan_oferta"] and not item["errores"]
        if not completo:
            con_problemas += 1
        marca = "NO VERIFICADO" if item["no_verificados"] else "OK" if completo else "REVISAR"
        print(f"[{marca}] {item['facultad']} · {item['plan']} ({item['codigo_plan']}) — {item['total']} materias")
        if item["errores"]:
            for error in item["errores"]:
                print(f"    ERROR: {error}")
        for campo, etiqueta in (("materias_faltantes_detalle", "materias.json"), ("oferta_faltante_detalle", "oferta.json")):
            for materia in item[campo]:
                nota = " [sin asignar a semestre]" if materia["sin_semestre"] else ""
                print(f"    Falta en {etiqueta}: {materia['codigo']} — {materia['nombre']}{nota}")

    print(
        f"\nResumen: {len(informe) - sin_malla} planes con materias, {sin_malla} sin malla; {cursos_total} materias de malla; "
        f"{faltan_materias_total} faltan en materias.json, "
        f"{faltan_oferta_total} faltan en oferta.json; {con_problemas} planes requieren revisión."
    )
    if ruta_informe:
        guardar_json_atomico(Path(ruta_informe), {
            "generado_en": datetime.now(timezone.utc).isoformat(),
            "url_base": base, "sede": sede, "facultad": facultad, "plan": plan_elegido,
            "direccion_comparacion": "planes locales -> Cloudflare",
            "resumen": {"planes": len(informe), "sin_malla": sin_malla,
                        "no_verificados": no_verificados, "requieren_revision": con_problemas,
                        "faltan_materias": faltan_materias_total, "faltan_oferta": faltan_oferta_total},
            "planes": informe,
        })
        print(f"Informe guardado en: {Path(ruta_informe).resolve()}")
    return 2 if no_verificados else 1 if con_problemas else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Comprueba que las materias obligatorias de planes_estudio.json estén publicadas en Cloudflare."
    )
    parser.add_argument("--sede", default="1102", help="Código de sede; por defecto Medellín (1102).")
    parser.add_argument("--url-base", default=URL_DATOS_CLOUDFLARE, help="URL base del catálogo publicado.")
    parser.add_argument("--facultad", help="Código de facultad; sin este filtro revisa todas.")
    parser.add_argument("--plan", help="Código del plan (p. ej. 3501) o clave completa (1102:3064:3501).")
    parser.add_argument("--informe", type=Path, help="Guarda los resultados detallados en este archivo JSON.")
    args = parser.parse_args()
    return ejecutar(args.url_base, args.sede, args.facultad, args.plan, args.informe)


if __name__ == "__main__":
    raise SystemExit(main())
