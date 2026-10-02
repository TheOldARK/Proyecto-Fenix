"""Punto de entrada exclusivo de la aplicación distribuida a estudiantes.

No importa herramientas de publicación ni credenciales de Cloudflare R2. El
publicador privado conserva su propio punto de entrada en ``main.py``.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import sys
import time

from aplicacion.arranque import preparar_entorno
from infraestructura.almacenamiento.estado_actualizacion import guardar_estado
from infraestructura.almacenamiento.estudiante import cargar_estudiante
from infraestructura.almacenamiento.materias import cargar_materias, preparar_materias_para_plan
from infraestructura.almacenamiento.oferta_academica import cargar_oferta, preparar_oferta_para_plan
from infraestructura.almacenamiento.materias_libre_eleccion import (
    cargar_libres_eleccion,
    cargar_libres_eleccion_sede,
    preparar_libres_para_plan,
)
from infraestructura.almacenamiento.plan_estudios import cargar_planes
from servicios.actualizacion import ActualizacionCancelada, actualizar
from servicios.datos_cloudflare import DatosNoPublicadosError, actualizar_desde_cloudflare


def formatear_hora_colombia(valor):
    """Convierte la marca UTC de Cloudflare a hora fija de Colombia (UTC−5)."""
    if not valor:
        return "hora no disponible"
    try:
        fecha = datetime.fromisoformat(str(valor).strip().replace("Z", "+00:00"))
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)
        fecha = fecha.astimezone(timezone(timedelta(hours=-5)))
    except (TypeError, ValueError):
        return str(valor)
    hora = fecha.hour % 12 or 12
    sufijo = "a. m." if fecha.hour < 12 else "p. m."
    return f"{fecha.day:02d}/{fecha.month:02d}/{fecha.year} {hora:02d}:{fecha.minute:02d} {sufijo} (hora Colombia)"


def cargar_cache_libres_sede():
    """Indexa el catálogo compartido para reutilizar detalles de sede."""
    return {
        str(materia.get("codigo", "")).strip(): materia
        for materia in cargar_libres_eleccion_sede()
        if isinstance(materia, dict) and str(materia.get("codigo", "")).strip()
    }


def ejecutar_actualizacion():
    try:
        estudiante = cargar_estudiante()
        codigo_plan = estudiante.get("plan_estudios")
        plan = cargar_planes().get(codigo_plan)
        if plan is None:
            guardar_estado("esperando_perfil", "Selecciona tu plan de estudios para comenzar.", 0)
            print(">>> No hay un plan configurado; esperando el perfil inicial.", flush=True)
            return

        nombre_plan = plan.nombre
        plan_no_publicado = False
        try:
            guardar_estado("actualizando", "Comprobando datos publicados…", 0)
            manifiesto = actualizar_desde_cloudflare(codigo_plan=codigo_plan)
            hora_publicacion = formatear_hora_colombia(manifiesto.get("version_datos"))
            entrada = (manifiesto.get("planes") or {}).get(str(codigo_plan), {})
            archivos_remotos = entrada.get("archivos", {}) if isinstance(entrada, dict) else {}
            hay_libres_publicadas = (
                isinstance(archivos_remotos, dict)
                and "libres_eleccion" in archivos_remotos
            )
            if not hay_libres_publicadas or not cargar_libres_eleccion(codigo_plan):
                print(
                    ">>> Cloudflare no tiene libres de elección para este plan; "
                    "el cliente buscará esa fase directamente en el SIA.",
                    flush=True,
                )
                preparar_libres_para_plan(codigo_plan)
                libres_sede_compartidas = cargar_libres_eleccion_sede()
                cache_libres_sede = cargar_cache_libres_sede()
                guardar_estado(
                    "actualizando",
                    "Obligatorias cargadas desde Cloudflare; consultando Libre Elección en el SIA…",
                    60,
                )
                try:
                    resultado_libres = asyncio.run(
                        actualizar(
                            solo_libres=True,
                            nombre_plan=nombre_plan,
                            codigo_plan=codigo_plan,
                            cache_libres=cache_libres_sede,
                            materias_sede_compartidas=libres_sede_compartidas or None,
                        )
                    )
                except ActualizacionCancelada:
                    raise
                except Exception as error:
                    print(f">>> No se pudo completar Libre Elección en el SIA: {error}", flush=True)
                    guardar_estado(
                        "completada",
                        f"Materias obligatorias listas desde Cloudflare ({hora_publicacion}); Libre Elección no pudo actualizarse.",
                        100,
                    )
                    return
                pendientes = len(resultado_libres.get("libres_fallidas", []))
                mensaje_libres = "Libre Elección actualizada desde el SIA."
                if pendientes:
                    mensaje_libres = f"Libre Elección consultada; {pendientes} materia(s) quedaron pendientes."
                guardar_estado(
                    "completada",
                    f"Materias obligatorias desde Cloudflare ({hora_publicacion}). {mensaje_libres}",
                    100,
                )
                return

            guardar_estado(
                "completada",
                f"Datos académicos actualizados desde Cloudflare ({hora_publicacion}).",
                100,
            )
            print(">>> Datos obtenidos desde Cloudflare; no se inician workers SIA.", flush=True)
            return
        except DatosNoPublicadosError as error:
            logging.getLogger("fenix").warning("El plan no está publicado en Cloudflare: %s", error)
            print(f">>> {error} Se consultará el SIA con los workers del cliente.", flush=True)
            plan_no_publicado = True
        except Exception as error:
            logging.getLogger("fenix").exception("Falló la actualización desde Cloudflare")
            print(f">>> Cloudflare no disponible: {error}", flush=True)
            if cargar_materias() and cargar_oferta().get("materias"):
                guardar_estado("completada", "Usando la última copia local de datos académicos.", 100)
                return
        guardar_estado("actualizando", "Preparando la actualización del catálogo…", 0)

        preparar_materias_para_plan(codigo_plan)
        preparar_oferta_para_plan(codigo_plan)
        preparar_libres_para_plan(codigo_plan)
        libres_sede_compartidas = cargar_libres_eleccion_sede()
        cache_libres_sede = cargar_cache_libres_sede()

        hay_materias_normales = bool(cargar_materias())
        hay_oferta_normal = bool(cargar_oferta().get("materias"))
        libres_guardadas = cargar_libres_eleccion(codigo_plan)
        normales_listas = hay_materias_normales and hay_oferta_normal

        if normales_listas and not libres_guardadas and not plan_no_publicado:
            guardar_estado(
                "actualizando",
                "Obligatorias y optativas disponibles; actualizando Libre Elección en segundo plano…",
                0,
            )
            try:
                asyncio.run(
                    actualizar(
                        solo_libres=True,
                        nombre_plan=nombre_plan,
                        codigo_plan=codigo_plan,
                    )
                )
            except ActualizacionCancelada:
                raise
            except Exception as error:
                print(
                    f"⚠ No se pudo priorizar Libre Elección: {error}. "
                    "Continuando con obligatorias y optativas...",
                    flush=True,
                )
            else:
                guardar_estado(
                    "completada",
                    "Obligatorias y optativas disponibles; Libre Elección continúa en segundo plano.",
                    100,
                )
                return

        resultado = None
        for intento in range(1, 4):
            try:
                resultado = asyncio.run(
                    actualizar(
                        nombre_plan=nombre_plan,
                        codigo_plan=codigo_plan,
                        cache_libres=cache_libres_sede,
                        materias_sede_compartidas=libres_sede_compartidas or None,
                    )
                )
                break
            except ActualizacionCancelada:
                raise
            except Exception as error:
                if intento >= 3:
                    raise
                espera = 2 ** intento
                print(
                    f"⚠ Falló la actualización completa (intento {intento}/3): "
                    f"{error}. Reintentando en {espera} s...",
                    flush=True,
                )
                guardar_estado(
                    "actualizando",
                    f"Reintentando la actualización ({intento + 1}/3)…",
                    0,
                )
                time.sleep(espera)
    except ActualizacionCancelada:
        guardar_estado("cancelada", "Actualización detenida para cambiar de usuario.", None)
        return
    except Exception as error:
        guardar_estado("error", f"La actualización falló: {error}", None)
        print(f"✗ La actualización falló: {error}", flush=True)
        return
    else:
        fallidas = len(resultado.get("materias_fallidas", [])) + len(resultado.get("libres_fallidas", []))
        mensaje = "Datos actualizados correctamente."
        if fallidas:
            mensaje = f"Actualización terminada con {fallidas} materia(s) pendiente(s)."
        guardar_estado("completada", mensaje, 100)


def ejecutar_interfaz():
    try:
        from servicios.datos_cloudflare import sincronizar_planes_cloudflare

        cantidad = sincronizar_planes_cloudflare()
        print(f">>> Planes disponibles desde Cloudflare: {cantidad}.", flush=True)
    except Exception as error:
        print(f">>> No se pudo actualizar la lista de planes de Cloudflare: {error}", flush=True)

    from aplicacion.interfaz import iniciar_interfaz

    iniciar_interfaz()


def configurar_salida_consola_segura():
    """Evita que símbolos Unicode incompatibles con Windows aborten workers."""
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if callable(reconfigurar):
            try:
                reconfigurar(errors="backslashreplace")
            except (OSError, ValueError):
                pass


def main():
    configurar_salida_consola_segura()
    preparar_entorno()
    print("Iniciando Fénix...", flush=True)

    if "--prueba-actualizacion" in sys.argv:
        from aplicacion.prueba_actualizacion import ejecutar
        return ejecutar(sys.argv[sys.argv.index("--prueba-actualizacion") + 1:])
    if "--diagnostico" in sys.argv:
        from aplicacion.diagnostico import comprobar_instalacion
        return comprobar_instalacion(consultar_sia="--consultar-sia" in sys.argv)
    if "--actualizar-solo" in sys.argv:
        ejecutar_actualizacion()
        return 0
    if any(argumento in sys.argv for argumento in (
        "--publicar-datos", "--publicador-plan-worker", "--gestor-publicadores", "--publicador"
    )):
        print("Esta distribución de Fénix no incluye herramientas de publicación.", flush=True)
        return 2

    ejecutar_interfaz()
    return 0


if __name__ == "__main__":
    sys.exit(main())
