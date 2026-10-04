"""Comprueba en vivo las fichas SIA de las materias de un JSON de planes.

No ejecuta los publicadores ni modifica datos del estudiante o Cloudflare.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from configuracion import CARPETA_DATOS, URL_SIA
from dominio.codigos import codigo_base
from herramientas.verificar_planes_cloudflare import _codigos_y_nombres_plan
from infraestructura.almacenamiento.json_atomico import guardar_json_atomico
from infraestructura.sia.catalogo_sia import CatalogoSIA
from infraestructura.sia.errores import MateriaNoDisponibleEnSIA
from infraestructura.sia.extractor_asignatura import extraer_materia_actual
from infraestructura.sia.parser.materias import obtener_materias_de_tabla
from playwright.async_api import async_playwright


def cargar_planes_archivo(ruta):
    documento = json.loads(Path(ruta).read_text(encoding="utf-8-sig"))
    if not isinstance(documento, dict) or not isinstance(documento.get("planes"), dict):
        raise ValueError("El JSON debe contener un objeto 'planes'.")
    planes = {}
    for clave, datos in documento["planes"].items():
        if not isinstance(datos, dict) or not isinstance(datos.get("semestres", {}), dict):
            raise ValueError(f"Estructura no válida del plan {clave}.")
        planes[str(clave)] = SimpleNamespace(**{
            **datos,
            "semestres": [SimpleNamespace(**s) for s in datos.get("semestres", {}).values()],
        })
    return planes


def tareas_desde_planes(planes, sede="1102", facultad=None, plan=None, materias=()):
    filtro = {codigo_base(c) for c in materias}
    tareas = []
    for clave, datos in sorted(planes.items(), key=lambda par: (par[1].facultad_nombre, par[1].nombre)):
        if str(datos.sede_codigo) != str(sede):
            continue
        if facultad and str(datos.facultad_codigo) != str(facultad):
            continue
        if plan and str(plan) not in {str(clave), str(datos.codigo)}:
            continue
        cursos = _codigos_y_nombres_plan(datos)
        if filtro:
            cursos = {c: n for c, n in cursos.items() if c in filtro}
            if not cursos:
                continue
        tareas.append((clave, datos, cursos))
    return tareas


def normalizar_nombre(nombre):
    return " ".join("".join(c for c in unicodedata.normalize("NFD", nombre)
                            if unicodedata.category(c) != "Mn").casefold().split())


class SesionVerificacion:
    def __init__(self, browser, clave, plan, carpeta):
        self.browser, self.clave, self.plan = browser, clave, plan
        self.contexto = None
        self.catalogo = None
        ruta = Path(carpeta)
        estudiante = ruta / "estudiante.json"
        catalogo = ruta / "catalogo_sia.json"
        guardar_json_atomico(estudiante, {"plan_estudios": clave})
        guardar_json_atomico(catalogo, {"niveles_estudio": [{
            "value": "0", "nombre": "Pregrado", "sedes": [{
                "value": str(plan.valor_sede), "codigo": str(plan.sede_codigo), "nombre": plan.sede_nombre,
                "facultades": [{"value": str(plan.valor_facultad), "codigo": str(plan.facultad_codigo),
                    "nombre": plan.facultad_nombre, "planes_estudio": [{
                        "value": str(plan.valor_plan), "codigo": str(plan.codigo),
                        "nombre": f"{plan.codigo} {plan.nombre}",
                    }]}],
            }],
        }]})
        # Rutas de una subclase privada: no se cambia FENIX_DATA_DIR ni las
        # rutas globales de otros programas abiertos por el usuario.
        self.clase_catalogo = type("CatalogoVerificacion", (CatalogoSIA,), {
            "ARCHIVO_ESTUDIANTE": estudiante, "ARCHIVO_CATALOGO": catalogo,
            "TIEMPO_MAXIMO_CARGA": 15,
        })

    async def cerrar(self):
        contexto, self.contexto = self.contexto, None
        if contexto:
            try:
                await asyncio.wait_for(contexto.close(), timeout=10)
            except Exception:
                pass

    async def cargar(self):
        await self.cerrar()
        self.contexto = await self.browser.new_context()
        self.page = await self.contexto.new_page()
        self.page.set_default_timeout(10000)
        self.catalogo = self.clase_catalogo(self.page, URL_SIA, self.clave,
                                           omitir_configuracion_libre_eleccion=True)
        await self.catalogo.abrir()
        await self.catalogo.configurar()
        await self.catalogo.mostrar_resultados()
        await self.catalogo.esperar_resultados()
        filas = await obtener_materias_de_tabla(self.page, incluir_no_programadas=True)
        return {codigo_base(fila["codigo"]): fila for fila in filas}

    async def comprobar_ficha(self, fila):
        await self.catalogo.abrir_materia(str(fila["codigo"]))
        html = await self.page.content()
        if not html.strip():
            raise ValueError("La ficha devolvió HTML vacío.")
        materia = await extraer_materia_actual(html, fila)
        return {"grupos_detectados": len(materia.grupos),
                "requisitos_detectados": len(materia.prerrequisitos)}

    async def volver(self):
        await self.catalogo.volver()


async def verificar_plan(sesion, cursos, informar=print, guardar=lambda r: None, intentos=2):
    resultados = []
    catalogo = None
    # Si ni siquiera se puede cargar el catálogo, no repetir una carga por
    # cada asignatura ni etiquetar todas como inexistentes.
    error_catalogo = ""
    for _ in range(intentos):
        try:
            catalogo = await asyncio.wait_for(sesion.cargar(), timeout=120)
            break
        except Exception as error:
            error_catalogo = f"{type(error).__name__}: {error}"
    if catalogo is None:
        resultados = [{"codigo": c, "nombre_local": n, "estado": "no_verificada",
                       "detalle": f"No se pudo cargar el catálogo del plan: {error_catalogo}",
                       "intentos": intentos} for c, n in cursos.items()]
        guardar(resultados)
        return resultados

    for indice, (codigo, nombre) in enumerate(cursos.items(), 1):
        informar(f"  {indice}/{len(cursos)} · {codigo} · {nombre}")
        registro = {"codigo": codigo, "nombre_local": nombre, "estado": "no_verificada", "intentos": 0}
        historial = []
        for intento in range(1, intentos + 1):
            registro["intentos"] = intento
            try:
                if catalogo is None or intento > 1:
                    catalogo = await asyncio.wait_for(sesion.cargar(), timeout=120)
                fila = catalogo.get(codigo)
                if fila is None:
                    registro.update(estado="no_en_catalogo", detalle="No aparece en el catálogo de esta carrera (sin Libre Elección).")
                    historial.append(registro["detalle"])
                    continue
                registro["codigo_sia"] = fila["codigo"]
                registro["nombre_sia"] = fila["nombre"]
                registro["nombre_diferente"] = bool(nombre and normalizar_nombre(nombre) != normalizar_nombre(fila["nombre"]))
                ficha = await asyncio.wait_for(sesion.comprobar_ficha(fila), timeout=45)
                registro.update(ficha, estado="funciona", detalle="La ficha abre y Fénix puede leer sus grupos y requisitos.")
                # Un error al volver no invalida una ficha ya comprobada.
                try:
                    await asyncio.wait_for(sesion.volver(), timeout=30)
                except Exception:
                    catalogo = None
                break
            except MateriaNoDisponibleEnSIA as error:
                registro.update(estado="error_ficha_sia", detalle=str(error))
                historial.append(str(error))
                catalogo = None
            except Exception as error:
                registro.update(estado="no_verificada", detalle=f"{type(error).__name__}: {error}")
                historial.append(registro["detalle"])
                catalogo = None
        registro["historial_intentos"] = historial
        resultados.append(registro)
        guardar(resultados)
        informar(f"    {registro['estado']}: {registro['detalle']}")
    return resultados


def guardar_informe(carpeta, informe):
    contadores = Counter(m["estado"] for p in informe["planes"] for m in p["materias"])
    informe["resumen"] = dict(contadores)
    guardar_json_atomico(carpeta / "informe.json", informe)
    lineas = ["# Verificación directa del SIA", "", f"Estado: {informe['estado']}",
              f"Origen: {informe['archivo_planes']}", "",
              "Se verifica el catálogo de cada carrera y la apertura/lectura de sus fichas; no cupos, vigencia ni validez oficial del plan.",
              "Un error del SIA no demuestra que el código sea incorrecto. Sin grupos no significa ficha dañada.", ""]
    for plan in informe["planes"]:
        lineas += [f"## {plan['nombre']} ({plan['clave']})", "",
                   f"{plan['estado']} · {len(plan['materias'])}/{plan['total']} materias comprobadas", ""]
        for m in plan["materias"]:
            lineas.append(f"- **{m['estado']}** · {m['codigo']} · {m['nombre_local']}: {m['detalle']}")
            if m.get("nombre_diferente"):
                lineas.append(f"  Nombre en el SIA: {m['nombre_sia']} (revisar diferencia, no se cambia automáticamente).")
            if m["estado"] == "funciona":
                lineas.append(f"  Grupos detectados: {m['grupos_detectados']}.")
        lineas.append("")
    (carpeta / "informe.md").write_text("\n".join(lineas), encoding="utf-8")


async def ejecutar(tareas, carpeta, informe, informar):
    if not any(cursos for _, _, cursos in tareas):
        informe["planes"] = [{"clave": k, "nombre": p.nombre, "estado": "sin_malla", "total": 0, "materias": []}
                             for k, p, _ in tareas]
        return
    async with async_playwright() as p:
        # La instalación de desarrollo ya contiene Chromium de Fénix.
        import playwright
        base = Path(playwright.__file__).parent / "driver/package/.local-browsers"
        candidatos = [r for r in base.rglob("*") if r.name in {"chrome-headless-shell.exe", "chrome-headless-shell", "headless_shell"} and r.is_file()]
        browser = await p.chromium.launch(headless=True, executable_path=str(candidatos[0]) if len(candidatos) == 1 else None)
        try:
            for i, (clave, plan, cursos) in enumerate(tareas, 1):
                informar(f"Plan {i}/{len(tareas)} · {plan.nombre} · {len(cursos)} materias")
                registro = {"clave": clave, "nombre": plan.nombre, "facultad": plan.facultad_nombre,
                            "estado": "en_curso" if cursos else "sin_malla", "total": len(cursos), "materias": []}
                informe["planes"].append(registro)
                guardar_informe(carpeta, informe)
                if not cursos:
                    continue
                with tempfile.TemporaryDirectory(prefix="fenix-verificacion-sia-") as temporal:
                    sesion = SesionVerificacion(browser, clave, plan, temporal)
                    def guardar(resultados):
                        registro["materias"] = list(resultados)
                        guardar_informe(carpeta, informe)
                    try:
                        await verificar_plan(sesion, cursos, informar, guardar)
                        registro["estado"] = "revisado"
                    finally:
                        await sesion.cerrar()
        finally:
            await asyncio.wait_for(browser.close(), timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planes", type=Path, default=ROOT / "datos/planes_estudio.json")
    parser.add_argument("--sede", default="1102")
    parser.add_argument("--facultad")
    parser.add_argument("--plan", help="Código del plan o clave sede:facultad:plan")
    parser.add_argument("--materia", action="append", default=[], help="Limita la prueba a este código; se puede repetir")
    parser.add_argument("--salida", type=Path, help="Carpeta para informe JSON, Markdown y registro técnico")
    args = parser.parse_args()
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="backslashreplace")
    try:
        tareas = tareas_desde_planes(cargar_planes_archivo(args.planes), args.sede, args.facultad, args.plan, args.materia)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(f"No se pudo leer el JSON de planes: {error}")
        return 2
    if not tareas:
        print("Ningún plan o materia del JSON coincide con los filtros.")
        return 2
    carpeta = args.salida or CARPETA_DATOS / "herramientas/verificacion_sia" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    carpeta.mkdir(parents=True, exist_ok=True)
    informe = {"archivo_planes": str(args.planes.resolve()), "iniciado_en": datetime.now(timezone.utc).isoformat(),
               "estado": "en_curso", "filtros": {"sede": args.sede, "facultad": args.facultad, "plan": args.plan, "materias": args.materia},
               "planes_previstos": len(tareas), "planes": []}
    consola = sys.stdout
    informar = lambda mensaje: print(mensaje, file=consola, flush=True)
    informar(f"Leyendo: {args.planes.resolve()}\nInformes: {carpeta.resolve()}\nCtrl+C detiene y conserva los resultados ya comprobados.")
    try:
        with (carpeta / "consulta.log").open("w", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
            asyncio.run(ejecutar(tareas, carpeta, informe, informar))
        informe["estado"] = "terminado"
    except KeyboardInterrupt:
        informe["estado"] = "interrumpido"
    except Exception as error:
        informe.update(estado="error", error=f"{type(error).__name__}: {error}")
        informar(informe["error"])
    finally:
        guardar_informe(carpeta, informe)
    informar(f"Resultado: {informe['estado']} · {informe['resumen']}\nInforme: {carpeta / 'informe.md'}")
    return (2 if informe["estado"] != "terminado" or informe["resumen"].get("no_verificada") else
            1 if any(k != "funciona" and v for k, v in informe["resumen"].items()) else 0)


if __name__ == "__main__":
    raise SystemExit(main())
