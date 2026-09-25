"""Ejecuta una actualización de un solo plan sin mostrar ventanas.

El gestor inicia una instancia aislada por carrera, lee el estado desde su
directorio de datos y conserva la propiedad de toda la interfaz visible.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(description="Actualiza un plan para el gestor de publicadores.")
    parser.add_argument("--plan", required=True, help="Clave sede:facultad:plan")
    parser.add_argument("--tipo", choices=("carrera", "libres_sede"), default="carrera")
    parser.add_argument("--plan-contexto", help="Carrera de referencia para el catálogo compartido de sede")
    args = parser.parse_args(argumentos)

    from configuracion import CARPETA_DATOS
    from infraestructura.almacenamiento.estado_actualizacion import guardar_estado
    from main import ejecutar_publicador

    inicio = time.time()
    salida = CARPETA_DATOS / "resultado_publicador.json"
    documento = {
        "plan": str(args.plan),
        "estado": "actualizando",
        "iniciado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(documento, ensure_ascii=False), encoding="utf-8")
    guardar_estado("actualizando", f"Actualizando {args.plan}…", 0, codigo_plan=str(args.plan))
    resumen = {}
    try:
        resumen = ejecutar_publicador(
            codigo_plan=str(args.plan),
            modo="manual",
            tipo=args.tipo,
            plan_contexto=args.plan_contexto,
        ) or {}
    except BaseException as error:
        documento.update(
            estado="error",
            terminado_en=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duracion_segundos=round(time.time() - inicio, 2),
            unidades_trabajo=int(resumen.get("unidades_actualizadas", 0)),
            error=f"{type(error).__name__}: {error}",
        )
        traceback.print_exc()
        guardar_estado("error", f"Falló la actualización de {args.plan}: {error}", None, codigo_plan=str(args.plan))
        codigo_salida = 1
    else:
        pendientes = int(resumen.get("materias_pendientes", 0) or 0)
        documento.update(
            estado="completado",
            terminado_en=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            duracion_segundos=round(time.time() - inicio, 2),
            unidades_trabajo=int(resumen.get("unidades_actualizadas", 0)),
            materias_pendientes=pendientes,
        )
        mensaje = f"Actualización de {args.plan} completada."
        if pendientes:
            mensaje += (
                f" {pendientes} materia(s) no se encontraron; "
                "se publicó el resto y se conservaron los datos anteriores para las fases vacías."
            )
            documento["advertencia"] = mensaje
        guardar_estado("completada", mensaje, 100, codigo_plan=str(args.plan))
        codigo_salida = 0
    salida.write_text(json.dumps(documento, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return codigo_salida


if __name__ == "__main__":
    raise SystemExit(main())
