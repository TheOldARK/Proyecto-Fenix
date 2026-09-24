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
import argparse
from dataclasses import asdict, fields, is_dataclass
import json
import os
import tempfile
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aplicacion.arranque import preparar_entorno

from infraestructura.almacenamiento.estado_actualizacion import guardar_estado
from infraestructura.almacenamiento.estudiante import cargar_estudiante, guardar_estudiante
from infraestructura.almacenamiento.materias import cargar_materias, preparar_materias_para_plan
from infraestructura.almacenamiento.oferta_academica import cargar_oferta, preparar_oferta_para_plan
from infraestructura.almacenamiento.materias_libre_eleccion import (
    cargar_libres_eleccion,
    cargar_libres_eleccion_sede,
    preparar_libres_para_plan,
)
from infraestructura.almacenamiento.plan_estudios import cargar_planes
from servicios.actualizacion import (
    ActualizacionCancelada,
    actualizar,
    configurar_contexto_publicador,
)
from servicios.datos_cloudflare import DatosNoPublicadosError, actualizar_desde_cloudflare
from configuracion import (
    ARCHIVO_LIBRES_ELECCION,
    ARCHIVO_LIBRES_ELECCION_SEDE,
    ARCHIVO_MATERIAS,
    ARCHIVO_OFERTA,
    ARCHIVO_ESTUDIANTE,
    ARCHIVO_CACHE_PUBLICADOR,
    ARCHIVO_CONFIGURACION_LIBRE_ELECCION,
    CARPETA_DATOS,
)
from herramientas.publicar_datos_cloudflare import (
    publicar,
    publicar_libres_eleccion_sede,
    publicar_planes,
)
from infraestructura.almacenamiento.json_atomico import cargar_json, guardar_json_atomico
from dominio.materia import Materia, Prerrequisito
from dominio.grupo import Grupo
from dominio.horario import Horario


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
            # Este plan todavía no está en el snapshot global: el cliente debe
            # consultar el SIA con sus workers y su propio perfil académico.
            print(f">>> {error} Se consultará el SIA con los workers del cliente.", flush=True)
            plan_no_publicado = True
        except Exception as error:
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

        if normales_listas and not libres_guardadas and not plan_no_publicado:
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


def seleccionar_planes_publicables(planes, sede="1102"):
    """Elige rutas SIA válidas que ya tengan una malla iniciada.

    El editor puede contener carreras futuras aún vacías. No se deben mostrar
    como disponibles en Cloudflare hasta que tengan materias asignadas y una
    ruta SIA real; las mallas parcialmente completadas sí pueden publicarse.
    """
    seleccionados = {}
    omitidos = []
    campos_sia = ("sede_codigo", "facultad_codigo", "codigo", "valor_sede", "valor_facultad", "valor_plan")
    valores_pendientes = {"PENDIENTE", "PENDIENTE_CONFIRMAR_EN_SIA", "POR_CONFIRMAR"}

    for clave, plan in planes.items():
        codigo_sede = str(plan.sede_codigo or "")
        if codigo_sede != str(sede) and not str(clave).startswith(f"{sede}:"):
            continue
        valores = {campo: str(getattr(plan, campo, "") or "").strip() for campo in campos_sia}
        ruta_sia_valida = all(
            valor and valor.upper() not in valores_pendientes
            for valor in valores.values()
        )
        tiene_malla = bool(plan.nombres_asignaturas) and any(
            semestre.asignaturas for semestre in plan.semestres
        )
        if ruta_sia_valida and tiene_malla:
            seleccionados[str(clave)] = plan
        else:
            omitidos.append(str(clave))
    return seleccionados, omitidos


def seleccionar_planes_referencia_libres(planes):
    """Filtra planes que empiezan la búsqueda LE por la sede configurada."""
    configuracion = cargar_json(ARCHIVO_CONFIGURACION_LIBRE_ELECCION, {})
    disponibles = {}
    if not isinstance(configuracion, dict):
        return disponibles
    for codigo, plan in planes.items():
        sede = configuracion.get(str(plan.sede_codigo), {})
        nombre_sede = sede.get("sede") if isinstance(sede, dict) else None
        rutas = sede.get("planes", {}) if isinstance(sede, dict) else {}
        ruta = rutas.get(f"{plan.facultad_codigo}:{plan.codigo}") if isinstance(rutas, dict) else None
        opciones = (
            ruta.get("facultades_libre_eleccion", ruta.get("facultades", []))
            if isinstance(ruta, dict) else []
        )
        opcion_inicial = opciones[0] if isinstance(opciones, list) and opciones else None
        if isinstance(nombre_sede, str) and isinstance(opcion_inicial, str):
            nombre_sede_normalizado = nombre_sede.strip().split(maxsplit=1)
            opcion_normalizada = opcion_inicial.strip().split(maxsplit=1)
            if len(nombre_sede_normalizado) == 2 and nombre_sede_normalizado[0].isdigit():
                nombre_sede_normalizado = nombre_sede_normalizado[1:]
            if len(opcion_normalizada) == 2 and opcion_normalizada[0].isdigit():
                opcion_normalizada = opcion_normalizada[1:]
            coincide_sede = (
                " ".join(nombre_sede_normalizado).casefold()
                == " ".join(opcion_normalizada).casefold()
            )
        else:
            coincide_sede = False
        if (
            isinstance(nombre_sede, str)
            and nombre_sede.strip()
            and isinstance(opciones, list)
            and opciones
            and coincide_sede
        ):
            disponibles[str(codigo)] = plan
    return disponibles


def _ttl_cache_publicador():
    try:
        return max(60, min(86400, int(os.environ.get("FENIX_PUBLICADOR_CACHE_SEGUNDOS", "1500"))))
    except ValueError:
        return 1500


def _crear_modelo_cache(modelo, datos):
    permitidos = {campo.name for campo in fields(modelo)}
    return modelo(**{clave: valor for clave, valor in datos.items() if clave in permitidos})


def _materia_desde_cache(datos):
    prerrequisitos = [
        _crear_modelo_cache(Prerrequisito, item)
        for item in datos.get("prerrequisitos", [])
        if isinstance(item, dict)
    ]
    grupos = []
    for item in datos.get("grupos", []):
        if not isinstance(item, dict):
            continue
        grupo = dict(item)
        grupo["horarios"] = [
            _crear_modelo_cache(Horario, horario)
            for horario in grupo.get("horarios", [])
            if isinstance(horario, dict)
        ]
        grupos.append(_crear_modelo_cache(Grupo, grupo))
    return _crear_modelo_cache(Materia, {**datos, "prerrequisitos": prerrequisitos, "grupos": grupos})


def cargar_cache_libres_sede():
    """Indexa el catálogo compartido para reutilizar detalles de sede."""
    return {
        str(materia.get("codigo", "")).strip(): materia
        for materia in cargar_libres_eleccion_sede()
        if isinstance(materia, dict) and str(materia.get("codigo", "")).strip()
    }


def cargar_cache_publicador():
    """Carga solo resultados recientes; cupos y grupos se vuelven a consultar al caducar."""
    documento = cargar_json(ARCHIVO_CACHE_PUBLICADOR, {})
    cache = {"normal": {}, "libre_eleccion": {}}
    marcas_tiempo = {"normal": {}, "libre_eleccion": {}}
    if not isinstance(documento, dict):
        return cache, marcas_tiempo
    ahora = time.time()
    ttl = _ttl_cache_publicador()
    for categoria in cache:
        entradas = documento.get(categoria, {})
        if not isinstance(entradas, dict):
            continue
        for codigo, entrada in entradas.items():
            if not isinstance(entrada, dict) or not isinstance(entrada.get("datos"), dict):
                continue
            try:
                guardado = float(entrada.get("guardado_en", 0))
            except (TypeError, ValueError):
                continue
            if guardado <= 0 or ahora - guardado > ttl:
                continue
            datos = entrada["datos"]
            cache[categoria][str(codigo)] = (
                _materia_desde_cache(datos) if categoria == "normal" else datos
            )
            marcas_tiempo[categoria][str(codigo)] = guardado
    return cache, marcas_tiempo


def guardar_cache_publicador(cache, marcas_tiempo):
    """Persiste los resultados exitosos con caducidad individual por código."""
    ahora = time.time()
    ttl = _ttl_cache_publicador()
    documento = {"version": 1, "normal": {}, "libre_eleccion": {}}
    for categoria in documento.keys() - {"version"}:
        for codigo, materia in cache.get(categoria, {}).items():
            guardado = marcas_tiempo.setdefault(categoria, {}).get(str(codigo), ahora)
            if ahora - guardado > ttl:
                continue
            datos = asdict(materia) if is_dataclass(materia) else materia
            if not isinstance(datos, dict):
                continue
            documento[categoria][str(codigo)] = {
                "guardado_en": guardado,
                "datos": datos,
            }
    guardar_json_atomico(ARCHIVO_CACHE_PUBLICADOR, documento)


def metadatos_publicacion_plan(codigo_plan, plan):
    return {
        "clave": str(codigo_plan),
        "codigo": str(plan.codigo),
        "nombre": plan.nombre,
        "sede_codigo": plan.sede_codigo,
        "sede_nombre": plan.sede_nombre,
        "facultad_codigo": plan.facultad_codigo,
        "facultad_nombre": plan.facultad_nombre,
        "valor_sede": plan.valor_sede,
        "valor_facultad": plan.valor_facultad,
        "valor_plan": plan.valor_plan,
        "nombres_asignaturas": plan.nombres_asignaturas,
        "semestres": {
            str(semestre.numero): {
                "asignaturas": semestre.asignaturas,
                "creditos": semestre.creditos,
            }
            for semestre in plan.semestres
        },
    }


def ejecutar_publicador(codigo_plan=None, modo="automatico", tipo="carrera", plan_contexto=None):
    """Actualiza las mallas iniciadas de Medellín, todas o una carrera elegida."""
    if tipo == "libres_sede":
        return ejecutar_publicador_libres_sede(plan_contexto or codigo_plan)
    if tipo != "carrera":
        raise ValueError(f"Tipo de publicador desconocido: {tipo}")
    planes, planes_omitidos = seleccionar_planes_publicables(cargar_planes())
    if codigo_plan is not None:
        codigo_plan = str(codigo_plan)
        planes = {clave: plan for clave, plan in planes.items() if str(clave) == codigo_plan}
        if not planes:
            raise ValueError(f"La carrera seleccionada ya no está disponible para publicar: {codigo_plan}")
    if not planes:
        raise RuntimeError(
            "No hay planes de estudio de Medellín listos para publicar. "
            "Completa la ruta SIA y asigna materias a la malla en el editor."
        )
    if planes_omitidos:
        print(
            f">>> Se omiten {len(planes_omitidos)} planes sin malla asignada "
            "o con ruta SIA pendiente.",
            flush=True,
        )

    archivos_a_restaurar = (
        ARCHIVO_MATERIAS,
        ARCHIVO_OFERTA,
        ARCHIVO_LIBRES_ELECCION,
        ARCHIVO_ESTUDIANTE,
    )
    respaldo = {
        ruta: ruta.read_bytes() if ruta.is_file() else None
        for ruta in archivos_a_restaurar
    }
    estudiante_original = cargar_estudiante()
    cache, marcas_tiempo = cargar_cache_publicador()
    cache_materias = cache["normal"]
    cache_libres = cache["libre_eleccion"]
    libres_sede_compartidas = cargar_libres_eleccion_sede()
    unidades_actualizadas = 0
    publicadas = 0
    with tempfile.TemporaryDirectory(prefix="fenix-planes-") as temporal:
        raiz_snapshots = Path(temporal)
        try:
            total = len(planes)
            for indice, (codigo_plan, plan) in enumerate(sorted(planes.items()), start=1):
                configurar_contexto_publicador(indice, total, plan.nombre, modo)
                guardar_estado(
                    "actualizando",
                    f"Carrera {indice}/{total} · {plan.facultad_nombre or 'Facultad pendiente'} · {plan.nombre} · quedan {total - indice}",
                    int((indice - 1) * 90 / total),
                    progreso_global=round((indice - 1) * 100 / total),
                    carrera_actual=plan.nombre,
                    carrera_indice=indice,
                    carreras_total=total,
                    carreras_restantes=total - indice,
                    modo_publicador=modo,
                )
                # CatalogoSIA valida el código solicitado contra estudiante.json.
                # Cambiar solo ese campo permite publicar varios planes en serie
                # sin que quede activo el perfil del plan consultado antes.
                estudiante_temporal = dict(estudiante_original)
                estudiante_temporal["plan_estudios"] = str(codigo_plan)
                guardar_estudiante(estudiante_temporal)

                metadatos = metadatos_publicacion_plan(codigo_plan, plan)
                carpeta_plan = raiz_snapshots / str(codigo_plan).replace(":", "-")
                carpeta_obligatorias = carpeta_plan / "obligatorias"
                carpeta_libres = carpeta_plan / "libres"
                publicacion_obligatorias = {"exitosa": False}

                def publicar_obligatorias(materias, fallidas, *, _codigo=str(codigo_plan), _meta=metadatos, _destino=carpeta_obligatorias, _estado=publicacion_obligatorias):
                    if fallidas:
                        print(
                            f">>> Se omite la publicación temprana de {_codigo}: "
                            f"{len(fallidas)} materia(s) obligatoria(s) fallaron.",
                            flush=True,
                        )
                        return
                    _destino.mkdir(parents=True, exist_ok=True)
                    for ruta in (ARCHIVO_MATERIAS, ARCHIVO_OFERTA):
                        if not ruta.is_file():
                            raise FileNotFoundError(
                                f"No se generó {ruta.name} para publicar {_codigo}."
                            )
                        (_destino / ruta.name).write_bytes(ruta.read_bytes())
                    try:
                        publicar_planes(
                            {_codigo: _destino},
                            sede="1102",
                            metadatos_planes={_codigo: _meta},
                            preservar_existentes=True,
                        )
                    except Exception as error:
                        print(
                            f">>> No se pudieron publicar aún las materias obligatorias "
                            f"de {_codigo}: {error}",
                            flush=True,
                        )
                    else:
                        _estado["exitosa"] = True
                        print(
                            f">>> Materias obligatorias de {_codigo} publicadas; "
                            "ahora comienza Libre Elección.",
                            flush=True,
                        )

                resultado = asyncio.run(
                    actualizar(
                        nombre_plan=plan.nombre,
                        codigo_plan=codigo_plan,
                        priorizar_estudiante=False,
                        cache_materias=cache_materias,
                        cache_libres=cache_libres,
                        materias_sede_compartidas=libres_sede_compartidas or None,
                        al_terminar_obligatorias=publicar_obligatorias,
                    )
                )
                if resultado.get("materias_fallidas") or resultado.get("libres_fallidas"):
                    fallos = (
                        list(resultado.get("materias_fallidas", []))
                        + list(resultado.get("libres_fallidas", []))
                    )
                    detalle_fallos = "; ".join(
                        f"{fallo.get('codigo', '¿?')} ({fallo.get('nombre', 'materia')}): "
                        f"{fallo.get('error', 'error desconocido')}"
                        for fallo in fallos[:3]
                    )
                    restantes = len(fallos) - min(3, len(fallos))
                    if restantes:
                        detalle_fallos += f"; y {restantes} más"
                    raise RuntimeError(
                        f"El plan {codigo_plan} terminó con materias pendientes; "
                        f"no se publicaron datos incompletos. Fallos: {detalle_fallos}"
                    )
                unidades_actualizadas += len(resultado.get("materias", []))
                unidades_actualizadas += len(resultado.get("libres_eleccion", []))

                if resultado.get("catalogo_libres_consultado"):
                    carpeta_libres.mkdir(parents=True, exist_ok=True)
                    if not ARCHIVO_LIBRES_ELECCION.is_file():
                        raise FileNotFoundError(
                            f"La actualización del plan {codigo_plan} no generó libres_eleccion.json."
                        )
                    (carpeta_libres / ARCHIVO_LIBRES_ELECCION.name).write_bytes(
                        ARCHIVO_LIBRES_ELECCION.read_bytes()
                    )
                    carpeta_publicar = carpeta_libres
                    if not publicacion_obligatorias["exitosa"]:
                        # Si falló la primera subida, publicar el paquete
                        # completo ahora para no dejar fuera las obligatorias.
                        for ruta in (ARCHIVO_MATERIAS, ARCHIVO_OFERTA):
                            (carpeta_libres / ruta.name).write_bytes(ruta.read_bytes())
                    publicar_planes(
                        {str(codigo_plan): carpeta_publicar},
                        sede="1102",
                        metadatos_planes={str(codigo_plan): metadatos},
                        preservar_existentes=True,
                    )
                    publicadas += 1
                    print(
                        f">>> Libre Elección de {codigo_plan} publicada; "
                        "Cloudflare ya tiene ambas fases.",
                        flush=True,
                    )
                elif publicacion_obligatorias["exitosa"]:
                    publicadas += 1
                    print(
                        f">>> Solo se publicó la fase obligatoria de {codigo_plan}; "
                        "no se obtuvo un catálogo de Libre Elección válido.",
                        flush=True,
                    )

                for categoria, codigos in (("normal", cache_materias), ("libre_eleccion", cache_libres)):
                    tiempos = marcas_tiempo[categoria]
                    for codigo in codigos:
                        tiempos.setdefault(str(codigo), time.time())
                guardar_cache_publicador(cache, marcas_tiempo)

        finally:
            for ruta, contenido in respaldo.items():
                if contenido is None:
                    ruta.unlink(missing_ok=True)
                else:
                    ruta.parent.mkdir(parents=True, exist_ok=True)
                    ruta.write_bytes(contenido)

    guardar_estado(
        "completada",
        (
            f"Publicador: {publicadas} carreras enviadas a Cloudflare; "
            f"{len(cache_materias)} materias obligatorias y "
            f"{len(cache_libres)} libres en caché reciente."
        ),
        100,
    )
    return {
        "planes_actualizados": len(planes),
        "unidades_actualizadas": unidades_actualizadas,
    }


def ejecutar_publicador_libres_sede(codigo_plan=None):
    """Actualiza y publica la consulta compartida de Libre Elección de sede."""
    planes, _ = seleccionar_planes_publicables(cargar_planes())
    referencias = seleccionar_planes_referencia_libres(planes)
    if not referencias:
        raise RuntimeError("No hay carreras válidas de Medellín para configurar la consulta de sede.")
    codigo_plan = str(codigo_plan or sorted(referencias)[0])
    plan = referencias.get(codigo_plan)
    if plan is None:
        raise ValueError(f"La carrera de referencia no está disponible: {codigo_plan}")

    respaldos = {
        ruta: ruta.read_bytes() if ruta.is_file() else None
        for ruta in (ARCHIVO_ESTUDIANTE, ARCHIVO_LIBRES_ELECCION_SEDE)
    }
    estudiante_original = cargar_estudiante()
    try:
        estudiante_temporal = dict(estudiante_original)
        estudiante_temporal["plan_estudios"] = codigo_plan
        guardar_estudiante(estudiante_temporal)
        print(
            f">>> Publicador compartido de sede: usando {plan.facultad_nombre} · {plan.nombre} "
            "solo para configurar la ruta SIA; se consultará la lista de sede Medellín.",
            flush=True,
        )
        resultado = asyncio.run(
            actualizar(
                solo_libres=True,
                nombre_plan=plan.nombre,
                codigo_plan=codigo_plan,
                priorizar_estudiante=False,
                solo_sede=True,
                cantidad_workers=3,
            )
        )
        if resultado.get("libres_fallidas"):
            detalle = "; ".join(
                f"{item.get('codigo')}: {item.get('error')}"
                for item in resultado["libres_fallidas"][:3]
            )
            raise RuntimeError(f"La lectura de libres de sede tuvo errores: {detalle}")
        if not resultado.get("catalogo_libres_consultado"):
            raise RuntimeError("No se pudo confirmar la consulta del catálogo de sede.")
        publicar_libres_eleccion_sede(ARCHIVO_LIBRES_ELECCION_SEDE, sede="1102")
        guardar_estado(
            "completada",
            f"Catálogo compartido de Libre Elección de Medellín publicado ({len(resultado.get('libres_eleccion', []))} materias).",
            100,
        )
        return {
            "planes_actualizados": 1,
            "unidades_actualizadas": len(resultado.get("libres_eleccion", [])),
        }
    finally:
        for ruta, contenido in respaldos.items():
            if contenido is None:
                ruta.unlink(missing_ok=True)
            else:
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_bytes(contenido)


def ejecutar_interfaz():
    try:
        from servicios.datos_cloudflare import sincronizar_planes_cloudflare

        cantidad = sincronizar_planes_cloudflare()
        print(f">>> Planes disponibles desde Cloudflare: {cantidad}.", flush=True)
    except Exception as error:
        # El catálogo local permite seguir usando Fénix aunque el manifiesto
        # público no esté disponible temporalmente.
        print(f">>> No se pudo actualizar la lista de planes de Cloudflare: {error}", flush=True)

    from aplicacion.interfaz import iniciar_interfaz

    iniciar_interfaz()


def main():
    # Fenix.exe es una aplicación GUI y normalmente no tiene stdout/stderr.
    # Cuando lo inicia FenixPublicador.exe (consola), conectarlos explícitamente
    # para que los errores y el avance de los workers sean visibles.
    if "--publicador" in sys.argv and os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.AttachConsole.argtypes = [ctypes.c_ulong]
            kernel32.AttachConsole.restype = ctypes.c_bool
            kernel32.AttachConsole(0xFFFFFFFF)  # ATTACH_PARENT_PROCESS
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        except OSError:
            # La ventana gráfica sigue funcionando aunque Windows no ofrezca
            # una consola adjuntable (por ejemplo, al abrir Fenix.exe directo).
            pass

    preparar_entorno()
    print("Iniciando Fénix...", flush=True)

    if "--prueba-actualizacion" in sys.argv:
        from aplicacion.prueba_actualizacion import ejecutar
        return ejecutar(sys.argv[sys.argv.index("--prueba-actualizacion") + 1])

    if "--diagnostico" in sys.argv:
        from aplicacion.diagnostico import comprobar_instalacion

        return comprobar_instalacion(consultar_sia="--consultar-sia" in sys.argv)

    if "--actualizar-solo" in sys.argv:
        ejecutar_actualizacion()
        return 0

    if "--publicar-datos" in sys.argv:
        try:
            ejecutar_publicador()
            return 0
        except Exception as error:
            guardar_estado("error", f"El publicador falló: {error}", None)
            print(f"✗ El publicador falló: {error}", flush=True)
            return 1

    if "--publicador-plan-worker" in sys.argv:
        from herramientas.publicador_worker import main as ejecutar_worker_publicador

        return ejecutar_worker_publicador(sys.argv[sys.argv.index("--publicador-plan-worker") + 1:])

    if "--gestor-publicadores" in sys.argv:
        from herramientas.gestor_publicadores import main as iniciar_gestor_publicadores

        return iniciar_gestor_publicadores()

    if "--publicador" in sys.argv:
        indice = sys.argv.index("--publicador")
        argumentos_publicador = sys.argv[indice + 1:]
        try:
            from herramientas.publicador_main import main as iniciar_publicador

            sys.argv = [sys.argv[0], *argumentos_publicador]
            return iniciar_publicador()
        except Exception:
            traceback.print_exc()
            return 1

    ejecutar_interfaz()
    return 0


if __name__ == "__main__":
    sys.exit(main())
