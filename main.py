# =============================================================
# PUNTO DE ENTRADA DE FÉNIX
# =============================================================
#
# Este archivo es el punto de entrada de la aplicación.
#
# Su responsabilidad es coordinar:
#
#   1. La actualización de los datos del SIA.
#   2. La ejecución de la interfaz gráfica.
#
# El proceso principal ejecuta Qt. La interfaz inicia otro proceso del mismo
# programa con --actualizar-solo para consultar el SIA sin bloquear la ventana.
# Este mecanismo funciona tanto con Python como con Fenix.exe.
#
# =============================================================

import asyncio
import sys
import time

from aplicacion.arranque import preparar_entorno

from infraestructura.almacenamiento.estado_actualizacion import guardar_estado
from infraestructura.almacenamiento.estudiante import cargar_estudiante
from infraestructura.almacenamiento.materias import cargar_materias, preparar_materias_para_plan
from infraestructura.almacenamiento.oferta_academica import cargar_oferta, preparar_oferta_para_plan
from infraestructura.almacenamiento.materias_libre_eleccion import (
    cargar_libres_eleccion,
    preparar_libres_para_plan,
)
from infraestructura.almacenamiento.plan_estudios import cargar_planes
from servicios.actualizacion import ActualizacionCancelada, actualizar


def ejecutar_actualizacion():
    try:
        estudiante = cargar_estudiante()
        codigo_plan = estudiante.get("plan_estudios")
        plan = cargar_planes().get(codigo_plan)

        # En una instalación nueva la interfaz debe solicitar el perfil
        # antes de iniciar Playwright. No se debe arrancar una actualización
        # con codigo_plan=None ni convertir ese estado normal en un error.
        if plan is None:
            guardar_estado(
                "esperando_perfil",
                "Selecciona tu plan de estudios para comenzar.",
                0,
            )
            print(
                ">>> No hay un plan configurado; esperando el perfil inicial.",
                flush=True,
            )
            return

        nombre_plan = plan.nombre
        guardar_estado("actualizando", "Preparando la actualización del catálogo…", 0)

        preparar_materias_para_plan(codigo_plan)
        preparar_oferta_para_plan(codigo_plan)
        preparar_libres_para_plan(codigo_plan)

        # Prioridad de documentos durante el arranque:
        #   1. materias normales
        #   2. oferta académica normal
        #   3. Libre Elección
        #
        # Materias y oferta son necesarias para habilitar el horario. Si
        # ambas existen, la ausencia de Libre Elección no debe bloquear al
        # usuario: esa fase puede ejecutarse por separado en segundo plano.
        hay_materias_normales = bool(cargar_materias())
        hay_oferta_normal = bool(cargar_oferta().get("materias"))
        libres_guardadas = cargar_libres_eleccion(codigo_plan)
        normales_listas = hay_materias_normales and hay_oferta_normal

        if normales_listas and not libres_guardadas:
            guardar_estado(
                "actualizando",
                "Materias normales disponibles; actualizando Libre Elección en segundo plano…",
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
                # La actualización completa todavía puede recuperar las
                # materias normales aunque Libre Elección falle primero.
                print(
                    f"⚠ No se pudo priorizar Libre Elección: {error}. "
                    "Continuando con materias normales...",
                    flush=True,
                )
            else:
                guardar_estado(
                    "completada",
                    "Materias normales disponibles; Libre Elección continúa en segundo plano.",
                    100,
                )
                return

        # Si algún documento normal está vacío, se prioriza la actualización
        # completa y la interfaz permanece bloqueada hasta guardar la oferta.
        # Si ningún documento está vacío, también se actualiza todo, pero la
        # interfaz conserva el horario que ya estaba disponible.
        resultado = None
        for intento in range(1, 4):
            try:
                resultado = asyncio.run(
                    actualizar(nombre_plan=nombre_plan, codigo_plan=codigo_plan)
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
        guardar_estado(
            "cancelada",
            "Actualización detenida para cambiar de usuario.",
            None,
        )
        return
    except Exception as error:
        guardar_estado("error", f"La actualización falló: {error}", None)
        print(f"✗ La actualización falló: {error}", flush=True)
        # La interfaz continúa abierta para permitir reintentar manualmente;
        # no propagar la excepción al hilo evita un traceback engañoso.
        return
    else:
        fallidas = len(resultado.get("materias_fallidas", [])) + len(
            resultado.get("libres_fallidas", [])
        )
        mensaje = "Datos actualizados correctamente."
        if fallidas:
            mensaje = f"Actualización terminada con {fallidas} materia(s) pendiente(s)."
        guardar_estado("completada", mensaje, 100)


def ejecutar_interfaz():
    from aplicacion.interfaz import iniciar_interfaz

    iniciar_interfaz()


def main():
    preparar_entorno()
    print("Iniciando Fénix...", flush=True)

    if "--diagnostico" in sys.argv:
        from aplicacion.diagnostico import comprobar_instalacion

        return comprobar_instalacion(consultar_sia="--consultar-sia" in sys.argv)

    if "--actualizar-solo" in sys.argv:
        ejecutar_actualizacion()
        return 0

    ejecutar_interfaz()
    return 0


if __name__ == "__main__":
    sys.exit(main())
