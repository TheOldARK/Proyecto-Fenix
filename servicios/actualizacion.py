# =============================================================
# ACTUALIZACIÓN DE DATOS DESDE EL SIA
# =============================================================
#
# Este módulo coordina la actualización de los datos académicos
# de Fénix utilizando el Sistema de Información Académica (SIA).
#
# La carrera que se consulta se obtiene desde:
#
#     datos/estudiante.json
#
# específicamente desde:
#
#     "plan_estudios"
#
# Por ejemplo:
#
#     {
#         "plan_estudios": "3534",
#         ...
#     }
#
# Ese código académico se utiliza junto con catalogo_sia.json
# para determinar automáticamente:
#
#     Nivel de estudio
#          ↓
#     Sede
#          ↓
#     Facultad
#          ↓
#     Plan de estudios
#
# De esta manera Fénix ya no necesita tener codificados
# directamente los values HTML internos del SIA.
#
# =============================================================

import asyncio
import json
from copy import deepcopy

from configuracion import (
    URL_SIA,
    ANCHO_VENTANA,
    ALTO_VENTANA,
    HEADLESS,
    MAX_REINTENTOS,
    ESPERA_REINTENTO,
    FACTOR_BACKOFF,
    MAX_ESPERA_REINTENTO,
    CANTIDAD_WORKERS,
    ESPERA_ENTRE_WORKERS,
    ARCHIVO_ESTUDIANTE,
    ARCHIVO_LOG_ERRORES_ACTUALIZACION,
)

from infraestructura.sia.navegador import (
    NavegadorSIA
)

from infraestructura.sia.catalogo_sia import (
    CatalogoSIA
)

from infraestructura.sia.parser.materias import (
    obtener_materias_de_tabla
)

from infraestructura.sia.extractor_asignatura import (
    extraer_materia_actual,
    extraer_libre_eleccion_actual
)

from infraestructura.almacenamiento.materias import (
    guardar_materias
)

from infraestructura.almacenamiento.oferta_academica import (
    guardar_oferta
)

from infraestructura.almacenamiento.materias_libre_eleccion import (
    guardar_libres_eleccion
)

from infraestructura.almacenamiento.estado_actualizacion import (
    cargar_estado,
    guardar_estado
)
from infraestructura.almacenamiento.cancelacion_actualizacion import (
    actualizacion_cancelada,
    token_cancelacion,
)


TOKEN_ACTUALIZACION = None
CONTEXTO_PUBLICADOR = None


def configurar_contexto_publicador(indice, total, nombre, modo="automatico"):
    """Asocia el progreso local de actualización con el avance entre carreras."""
    global CONTEXTO_PUBLICADOR
    CONTEXTO_PUBLICADOR = {
        "indice": max(1, int(indice)),
        "total": max(1, int(total)),
        "nombre": str(nombre or "Carrera"),
        "modo": str(modo or "automatico"),
    }


def _detalles_progreso_publicador(progreso):
    contexto = CONTEXTO_PUBLICADOR
    if not contexto:
        return {}
    total = contexto["total"]
    indice = contexto["indice"]
    try:
        local = max(0.0, min(100.0, float(progreso or 0)))
    except (TypeError, ValueError):
        local = 0.0
    global_pct = ((indice - 1) + local / 100) * 100 / total
    return {
        "progreso_global": round(global_pct),
        "carrera_actual": contexto["nombre"],
        "carrera_indice": indice,
        "carreras_total": total,
        "carreras_restantes": max(0, total - indice),
        "modo_publicador": contexto["modo"],
    }


def _codigo_materia(materia):
    """Obtiene un código estable de un objeto o registro básico del SIA."""
    if isinstance(materia, dict):
        return str(materia.get("codigo", ""))
    return str(getattr(materia, "codigo", ""))


def _reutilizar_desde_cache(materia_basica, cache):
    """Copia detalles compartidos conservando la tipología del plan actual."""
    codigo = _codigo_materia(materia_basica)
    guardada = cache.get(codigo) if cache is not None else None
    if guardada is None:
        return None
    materia = deepcopy(guardada)
    for atributo in ("nombre", "creditos", "tipologia"):
        valor = (
            materia_basica.get(atributo)
            if isinstance(materia_basica, dict)
            else getattr(materia_basica, atributo, None)
        )
        if valor not in (None, ""):
            if isinstance(materia, dict):
                materia[atributo] = valor
            else:
                setattr(materia, atributo, valor)
    return materia


class ActualizacionCancelada(asyncio.CancelledError):
    """Señala que el usuario cambió de perfil durante una actualización."""


def comprobar_cancelacion(token_inicial=None):
    token_inicial = TOKEN_ACTUALIZACION if token_inicial is None else token_inicial
    if token_inicial is None:
        return
    if actualizacion_cancelada(token_inicial):
        raise ActualizacionCancelada(
            "Actualización cancelada para cambiar de usuario."
        )


# =============================================================
# CONFIGURACIÓN INTERNA DE LIBRE ELECCIÓN
# =============================================================

# Esta clave solamente existe mientras las materias básicas de
# Libre Elección son procesadas.
#
# NO se guarda dentro de las materias finales.
#
# 0 → 3 SEDE MEDELLÍN
# 1 → 3068 FACULTAD DE MINAS

CLAVE_INDICE_FACULTAD_LIBRE_ELECCION = (
    "_indice_facultad_libre_eleccion"
)


# =============================================================
# UTILIDADES
# =============================================================

def imprimir(
    mensaje=""
):
    # flush=True obliga a Python a enviar inmediatamente el
    # mensaje a la terminal en lugar de dejarlo en el buffer.
    #
    # Esto es especialmente útil porque la actualización se
    # ejecuta en un hilo independiente del proceso principal.

    print(
        mensaje,
        flush=True
    )

    # La interfaz comparte el último mensaje de trabajo mediante
    # JSON. Así el usuario ve exactamente la misma línea útil
    # que aparece en consola.

    if mensaje and mensaje_visible_para_usuario(mensaje):
        estado = cargar_estado()

        guardar_estado(
            "actualizando",
            mensaje,
            estado.get("progreso"),
            **_detalles_progreso_publicador(estado.get("progreso")),
        )


def mensaje_visible_para_usuario(mensaje):
    """Oculta detalles de protocolo que no ayudan a seguir el progreso.

    Se mantienen en la consola, pero no reemplazan en la interfaz mensajes
    útiles como la materia actual, un avance o un error recuperable.
    """
    texto = str(mensaje).strip()
    if not texto:
        return False
    if texto and set(texto) <= {"=", "-", "_"}:
        return False
    ruido = (
        "Cerrando sesión",
        "Regresando al catálogo",
        "Sesión lista.",
        "Detalle abierto.",
        "HTML obtenido",
        "Intento ",
        "Worker iniciado con",
        "Todos los workers",
        "Lanzando ",
        "INICIANDO WORKERS",
        "LE Worker ",
        "Worker ",
    )
    if any(fragmento in texto for fragmento in ruido):
        return (
            "] [" in texto
            or any(marca in texto for marca in ("⚠", "✗", "✓ Materia", "✓ TERMINADO"))
        )
    return True


def publicar_progreso(
    mensaje,
    progreso
):
    # Comunica a la interfaz la fase general de la actualización.

    guardar_estado(
        "actualizando",
        mensaje,
        progreso,
        **_detalles_progreso_publicador(progreso),
    )


def datos_para_reintento(materias_basicas, fallidas):
    """Recupera datos originales, incluida la tabla de procedencia LE."""
    codigos = {str(item.get("codigo", "")).strip() for item in fallidas}
    return [
        datos for datos in materias_basicas
        if str(datos.get("codigo", "")).strip() in codigos
    ]


def combinar_materias(materias, reintentos):
    """Reemplaza el resultado anterior por el obtenido en el segundo ciclo."""
    por_codigo = {
        str(materia.codigo if hasattr(materia, "codigo") else materia.get("codigo")): materia
        for materia in materias
    }
    for materia in reintentos:
        codigo = str(materia.codigo if hasattr(materia, "codigo") else materia.get("codigo"))
        por_codigo[codigo] = materia
    return list(por_codigo.values())


def registrar_errores_definitivos(categoria, fallidas, codigo_plan):
    """Añade fallos finales al log sin truncar diagnósticos anteriores."""
    if not fallidas:
        return
    ARCHIVO_LOG_ERRORES_ACTUALIZACION.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    with open(ARCHIVO_LOG_ERRORES_ACTUALIZACION, "a", encoding="utf-8") as archivo:
        for fallo in fallidas:
            registro = {
                "fecha": datetime.now().isoformat(timespec="seconds"),
                "plan_estudios": str(codigo_plan) if codigo_plan is not None else None,
                "categoria": categoria,
                "codigo": fallo.get("codigo", ""),
                "nombre": fallo.get("nombre", ""),
                "intentos": fallo.get("intentos", MAX_REINTENTOS),
                "error": fallo.get("error", "Error no especificado"),
            }
            archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")


class ProgresoPorMaterias:
    # Calcula el avance real de una fase procesada por varios
    # workers.
    #
    # Todos los workers se ejecutan en el mismo ciclo asíncrono,
    # por lo que un contador compartido basta para publicar el
    # progreso tras cada materia.

    def __init__(
        self,
        mensaje,
        total,
        inicio,
        fin
    ):
        self.mensaje = mensaje
        self.total = max(
            1,
            total
        )
        self.inicio = inicio
        self.fin = fin
        self.completadas = 0

        publicar_progreso(
            f"{mensaje} (0/{total})",
            inicio
        )

    def registrar_materia(
        self
    ):
        self.completadas += 1

        avance = (
            self.inicio
            +
            (
                (
                    self.fin
                    -
                    self.inicio
                )
                *
                self.completadas
                //
                self.total
            )
        )

        publicar_progreso(
            (
                f"{self.mensaje} "
                f"({self.completadas}/{self.total}; "
                f"faltan {self.total - self.completadas})"
            ),
            avance
        )


# =============================================================
# CONFIGURACIÓN DE LA CARRERA
# =============================================================

def cargar_datos_estudiante():
    # Carga estudiante.json y obtiene la información necesaria
    # para determinar qué plan académico debe consultar Fénix.

    if not ARCHIVO_ESTUDIANTE.exists():
        raise FileNotFoundError(
            "No existe el archivo "
            f"'{ARCHIVO_ESTUDIANTE}'."
        )

    try:
        with open(
            ARCHIVO_ESTUDIANTE,
            "r",
            encoding="utf-8"
        ) as archivo:
            datos = json.load(
                archivo
            )

    except json.JSONDecodeError as error:
        raise RuntimeError(
            "El archivo estudiante.json "
            "no contiene JSON válido."
        ) from error

    if not isinstance(
        datos,
        dict
    ):
        raise RuntimeError(
            "estudiante.json debe contener "
            "un objeto JSON."
        )

    return datos


def obtener_codigo_plan_estudiante():
    # El plan de estudios del estudiante es el identificador
    # académico estable que se utiliza para buscar la carrera
    # dentro de catalogo_sia.json.
    #
    # Por ejemplo:
    #
    #     "plan_estudios": "3534"
    #
    # El value HTML del <select> del SIA no se utiliza aquí,
    # porque ese value es interno y puede cambiar.

    datos_estudiante = (
        cargar_datos_estudiante()
    )

    codigo_plan = datos_estudiante.get(
        "plan_estudios"
    )

    if codigo_plan is None:
        raise RuntimeError(
            "estudiante.json no contiene "
            "el campo 'plan_estudios'."
        )

    codigo_plan = str(
        codigo_plan
    ).strip()

    if not codigo_plan:
        raise RuntimeError(
            "El campo 'plan_estudios' "
            "de estudiante.json está vacío."
        )

    return codigo_plan


# =============================================================
# UTILIDADES DE REINTENTO
# =============================================================

async def esperar_reintento(
    intento: int
):
    # Espera antes de realizar un nuevo intento.
    #
    # El tiempo aumenta de manera exponencial según el número
    # del intento.

    espera = (
        ESPERA_REINTENTO
        *
        (
            FACTOR_BACKOFF
            **
            (
                intento
                -
                1
            )
        )
    )

    espera = min(
        espera,
        MAX_ESPERA_REINTENTO
    )

    imprimir(
        f"    Esperando {espera} segundos "
        f"antes del siguiente intento..."
    )

    await asyncio.sleep(
        espera
    )


def dividir_materias(
    materias,
    cantidad_workers: int
):
    # Divide una lista de materias entre los workers.
    #
    # Se utiliza una distribución por turnos:
    #
    #   Materia 1 → Worker 1
    #   Materia 2 → Worker 2
    #   Materia 3 → Worker 1
    #   Materia 4 → Worker 2
    #   ...

    if cantidad_workers <= 0:
        raise ValueError(
            "La cantidad de workers debe ser mayor que cero."
        )

    grupos = [
        []
        for _ in range(
            cantidad_workers
        )
    ]

    for posicion, materia in enumerate(
        materias
    ):
        indice = (
            posicion
            %
            cantidad_workers
        )

        grupos[indice].append(
            materia
        )

    return grupos


# =============================================================
# CREAR SESIÓN DE WORKER
# =============================================================

async def crear_sesion_normal(
    navegador,
    numero_worker,
    codigo_plan
):
    # Crea una sesión independiente para un worker.
    #
    # El CatalogoSIA recibe el código académico del plan y utiliza
    # catalogo_sia.json para determinar automáticamente la rama
    # correcta del SIA.

    contexto = await navegador.crear_contexto()

    page = await navegador.crear_pagina(
        contexto
    )

    catalogo = CatalogoSIA(
        page=page,
        url=URL_SIA,
        codigo_plan=codigo_plan
    )

    imprimir(
        f"[Worker {numero_worker}] "
        f"Abriendo catálogo..."
    )

    await catalogo.abrir()
    await catalogo.configurar()
    await catalogo.mostrar_resultados()
    await catalogo.esperar_resultados()

    imprimir(
        f"[Worker {numero_worker}] "
        f"✓ Sesión lista."
    )

    return (
        contexto,
        page,
        catalogo
    )


async def crear_sesion_libre_eleccion(
    navegador,
    numero_worker,
    codigo_plan
):
    # Crea una sesión independiente para un worker de
    # Libre Elección.
    #
    # La sesión queda posicionada siempre en la PRIMERA consulta:
    #
    #     soc6 → 3 SEDE MEDELLÍN
    #
    # Por eso, cuando una materia pertenece a la segunda consulta,
    # el worker deberá cambiar explícitamente a la segunda tabla.

    contexto = await navegador.crear_contexto()

    page = await navegador.crear_pagina(
        contexto
    )

    catalogo = CatalogoSIA(
        page=page,
        url=URL_SIA,
        codigo_plan=codigo_plan
    )

    imprimir(
        f"[LE Worker {numero_worker}] "
        f"Abriendo catálogo..."
    )

    await catalogo.abrir()
    await catalogo.configurar_libre_eleccion()
    await catalogo.mostrar_resultados()
    await catalogo.esperar_resultados()

    imprimir(
        f"[LE Worker {numero_worker}] "
        f"✓ Primera consulta de Libre Elección lista."
    )

    return (
        contexto,
        page,
        catalogo
    )


# =============================================================
# OBTENER LAS DOS TABLAS DE LIBRE ELECCIÓN
# =============================================================

async def obtener_materias_libre_eleccion(
    page,
    catalogo,
    numero_worker=None
):
    # Libre Elección requiere dos consultas independientes.
    #
    # Primera consulta:
    #
    #     soc6 → "3 SEDE MEDELLÍN"
    #     Mostrar
    #     extraer tabla
    #
    # Segunda consulta:
    #
    #     soc6 → "3068 FACULTAD DE MINAS"
    #     Mostrar
    #     extraer tabla
    #
    # Además de obtener las materias, se conserva internamente
    # el índice de la tabla de la que provino cada materia.
    #
    # Esto es necesario porque posteriormente los workers tendrán
    # sesiones independientes y deberán saber en qué consulta
    # deben buscar cada código.
    #
    # La información interna se guarda en:
    #
    #     _indice_facultad_libre_eleccion
    #
    # 0 → 3 SEDE MEDELLÍN
    # 1 → 3068 FACULTAD DE MINAS

    prefijo = (
        f"[LE Worker {numero_worker}] "
        if numero_worker is not None
        else ""
    )

    imprimir(
        f"{prefijo}Extrayendo primera tabla "
        f"de Libre Elección..."
    )

    primera_tabla = await obtener_materias_de_tabla(
        page
    )

    imprimir(
        f"{prefijo}✓ Primera tabla obtenida: "
        f"{len(primera_tabla)} materias."
    )

    # ---------------------------------------------------------
    # SEGUNDA CONSULTA
    # ---------------------------------------------------------
    #
    # La sesión sigue exactamente en el catálogo de resultados.
    # Ahora se modifica solamente soc6.

    imprimir(
        f"{prefijo}Cambiando al segundo filtro "
        f"de Libre Elección..."
    )

    await catalogo.seleccionar_facultad_libre_eleccion(
        1
    )

    imprimir(
        f"{prefijo}✓ Segundo filtro seleccionado."
    )

    imprimir(
        f"{prefijo}Consultando segunda tabla..."
    )

    await catalogo.mostrar_resultados()

    segunda_tabla = await obtener_materias_de_tabla(
        page
    )

    imprimir(
        f"{prefijo}✓ Segunda tabla obtenida: "
        f"{len(segunda_tabla)} materias."
    )

    # ---------------------------------------------------------
    # COMBINAR RESULTADOS CONSERVANDO LA TABLA DE ORIGEN
    # ---------------------------------------------------------
    #
    # Una materia puede aparecer en ambas consultas.
    #
    # Si aparece en ambas, se conserva la primera aparición,
    # exactamente igual que ocurría antes con la deduplicación.
    #
    # Lo nuevo es que cada materia conserva internamente:
    #
    #     0 → primera tabla
    #     1 → segunda tabla

    materias_combinadas = []
    codigos_vistos = set()

    for materia in primera_tabla:

        codigo = str(
            materia.get(
                "codigo",
                ""
            )
        ).strip()

        if not codigo:
            continue

        if codigo in codigos_vistos:
            continue

        codigos_vistos.add(
            codigo
        )

        materia_con_origen = dict(
            materia
        )

        materia_con_origen[
            CLAVE_INDICE_FACULTAD_LIBRE_ELECCION
        ] = 0

        materias_combinadas.append(
            materia_con_origen
        )

    for materia in segunda_tabla:

        codigo = str(
            materia.get(
                "codigo",
                ""
            )
        ).strip()

        if not codigo:
            continue

        if codigo in codigos_vistos:
            continue

        codigos_vistos.add(
            codigo
        )

        materia_con_origen = dict(
            materia
        )

        materia_con_origen[
            CLAVE_INDICE_FACULTAD_LIBRE_ELECCION
        ] = 1

        materias_combinadas.append(
            materia_con_origen
        )

    imprimir(
        f"{prefijo}✓ Materias únicas de Libre Elección: "
        f"{len(materias_combinadas)}."
    )

    return materias_combinadas


# =============================================================
# ASEGURAR TABLA DE LIBRE ELECCIÓN
# =============================================================

async def asegurar_tabla_libre_eleccion(
    catalogo,
    indice_actual,
    indice_objetivo,
    numero_worker
):
    # Cada sesión de Libre Elección comienza siempre en la
    # primera tabla:
    #
    #     índice 0 → 3 SEDE MEDELLÍN
    #
    # Si la materia pertenece a otra tabla, únicamente se cambia
    # soc6 y se vuelve a pulsar Mostrar.
    #
    # NO se vuelven a ejecutar los pasos 1-7 de configuración.
    #
    # Devuelve el nuevo índice actual.

    if indice_objetivo not in (0, 1):
        raise ValueError(
            "El índice de Libre Elección debe ser 0 o 1."
        )

    if indice_actual == indice_objetivo:
        return indice_actual

    if indice_objetivo == 1:
        descripcion = (
            "3068 FACULTAD DE MINAS"
        )
    else:
        descripcion = (
            "3 SEDE MEDELLÍN"
        )

    imprimir(
        f"[LE Worker {numero_worker}] "
        f"    Cambiando a la consulta: "
        f"{descripcion}"
    )

    await catalogo.seleccionar_facultad_libre_eleccion(
        indice_objetivo
    )

    await catalogo.mostrar_resultados()

    await catalogo.esperar_resultados()

    imprimir(
        f"[LE Worker {numero_worker}] "
        f"    ✓ Consulta de {descripcion} lista."
    )

    return indice_objetivo


# =============================================================
# CERRAR SESIÓN DE WORKER
# =============================================================

async def cerrar_sesion_worker(
    navegador,
    contexto,
    numero_worker,
    prefijo=""
):
    # Cierra el contexto utilizado por un worker.

    if contexto is None:
        return

    imprimir(
        f"[{prefijo}Worker {numero_worker}] "
        f"Cerrando sesión..."
    )

    try:
        await navegador.cerrar_contexto(
            contexto
        )

    except Exception as error:
        # El contexto ya puede estar cerrado por el navegador
        # o por un error previo.

        imprimir(
            f"[{prefijo}Worker {numero_worker}] "
            f"⚠ No se pudo cerrar la sesión: "
            f"{error}"
        )


# =============================================================
# PROCESAR UNA MATERIA NORMAL
# =============================================================

async def procesar_materia_normal(
    page,
    catalogo,
    datos_basicos,
    numero_worker
):
    # Abre una asignatura del catálogo, obtiene su HTML de
    # detalle y construye el objeto Materia correspondiente.

    codigo = datos_basicos.get(
        "codigo",
        ""
    )

    imprimir(
        f"[Worker {numero_worker}] "
        f"    Abriendo detalle..."
    )

    await catalogo.abrir_materia(codigo)
    imprimir(
        f"[Worker {numero_worker}] "
        f"    ✓ Detalle abierto."
    )
    detalle = await page.content()

    if not detalle:
        raise RuntimeError(
            "La página de detalle devolvió "
            "HTML vacío."
        )

    imprimir(
        f"[Worker {numero_worker}] "
        f"    ✓ HTML obtenido "
        f"({len(detalle):,} caracteres)."
    )

    materia = await extraer_materia_actual(
        detalle,
        datos_basicos
    )

    if materia.codigo != codigo:
        raise RuntimeError(
            "El código obtenido no coincide.\n"
            f"Esperado: {codigo}\n"
            f"Obtenido: {materia.codigo}"
        )

    return materia


# =============================================================
# PROCESAR UNA LIBRE ELECCIÓN
# =============================================================

async def procesar_materia_libre_eleccion(
    page,
    catalogo,
    datos_basicos,
    numero_worker
):
    # Procesa una materia de Libre Elección utilizando la sesión
    # actual del worker.
    #
    # La selección de la tabla correspondiente se realiza antes
    # de llamar a esta función.

    codigo = datos_basicos.get(
        "codigo",
        ""
    )

    imprimir(
        f"[LE Worker {numero_worker}] "
        f"    Abriendo detalle..."
    )

    await catalogo.abrir_materia(codigo)
    imprimir(
        f"[LE Worker {numero_worker}] "
        f"    ✓ Detalle abierto."
    )
    detalle = await page.content()

    if not detalle:
        raise RuntimeError(
            "La página de detalle devolvió "
            "HTML vacío."
        )

    imprimir(
        f"[LE Worker {numero_worker}] "
        f"    ✓ HTML obtenido "
        f"({len(detalle):,} caracteres)."
    )

    materia = await extraer_libre_eleccion_actual(
        detalle,
        datos_basicos
    )

    if materia["codigo"] != codigo:
        raise RuntimeError(
            "El código obtenido no coincide.\n"
            f"Esperado: {codigo}\n"
            f"Obtenido: {materia['codigo']}"
        )

    return materia


# =============================================================
# WORKER DE MATERIAS NORMALES
# =============================================================

async def worker_materias(
    navegador,
    materias_basicas,
    numero_worker,
    progreso=None,
    codigo_plan=None
):
    # Procesa todas las materias asignadas a un worker.
    #
    # El worker mantiene una sesión mientras procesa sus
    # materias y la reconstruye cuando ocurre un error.

    materias = []
    materias_fallidas = []

    contexto = None
    page = None
    catalogo = None

    imprimir(
        f"[Worker {numero_worker}] "
        f">>> Worker iniciado con "
        f"{len(materias_basicas)} materias."
    )

    try:

        # =====================================================
        # CREAR SESIÓN INICIAL
        # =====================================================

        intento_sesion = 1

        while True:

            try:

                (
                    contexto,
                    page,
                    catalogo
                ) = await crear_sesion_normal(
                    navegador,
                    numero_worker,
                    codigo_plan
                )

                break

            except Exception as error:

                imprimir(
                    f"[Worker {numero_worker}] "
                    f"⚠ No se pudo iniciar la sesión: "
                    f"{error}"
                )

                if intento_sesion >= MAX_REINTENTOS:

                    raise RuntimeError(
                        f"El Worker {numero_worker} "
                        f"no pudo iniciar el SIA después "
                        f"de {MAX_REINTENTOS} intentos."
                    ) from error

                await cerrar_sesion_worker(
                    navegador,
                    contexto,
                    numero_worker
                )

                contexto = None
                page = None
                catalogo = None

                await esperar_reintento(
                    intento_sesion
                )

                intento_sesion += 1

        # =====================================================
        # PROCESAR MATERIAS
        # =====================================================

        total = len(
            materias_basicas
        )

        for posicion, datos_basicos in enumerate(
            materias_basicas,
            start=1
        ):
            comprobar_cancelacion()

            codigo = datos_basicos.get(
                "codigo",
                ""
            )

            nombre = datos_basicos.get(
                "nombre",
                ""
            )

            imprimir()

            imprimir(
                f"[Worker {numero_worker}] "
                f"[{posicion}/{total}] "
                f"{codigo} - {nombre}"
            )

            materia_obtenida = None
            ultimo_error = None

            for intento in range(
                1,
                MAX_REINTENTOS + 1
            ):

                try:

                    imprimir(
                        f"[Worker {numero_worker}] "
                        f"    Intento "
                        f"{intento}/{MAX_REINTENTOS}"
                    )

                    materia_obtenida = (
                        await procesar_materia_normal(
                            page,
                            catalogo,
                            datos_basicos,
                            numero_worker
                        )
                    )

                    imprimir(
                        f"[Worker {numero_worker}] "
                        f"    Regresando al catálogo..."
                    )

                    await catalogo.volver()

                    imprimir(
                        f"[Worker {numero_worker}] "
                        f"    ✓ Regresó al catálogo."
                    )

                    break

                except Exception as error:

                    ultimo_error = error

                    imprimir()
                    imprimir(
                        f"[Worker {numero_worker}] "
                        f"    ⚠ Error en {codigo}: "
                        f"{error}"
                    )

                    if intento >= MAX_REINTENTOS:

                        imprimir(
                            f"[Worker {numero_worker}] "
                            f"    ✗ Materia agotó "
                            f"todos los intentos."
                        )

                        break

                    await cerrar_sesion_worker(
                        navegador,
                        contexto,
                        numero_worker
                    )

                    contexto = None
                    page = None
                    catalogo = None

                    await esperar_reintento(
                        intento
                    )

                    try:

                        (
                            contexto,
                            page,
                            catalogo
                        ) = await crear_sesion_normal(
                            navegador,
                            numero_worker,
                            codigo_plan
                        )

                    except Exception as error_sesion:

                        ultimo_error = error_sesion

                        imprimir(
                            f"[Worker {numero_worker}] "
                            f"    ⚠ Tampoco se pudo "
                            f"recrear la sesión: "
                            f"{error_sesion}"
                        )

                        continue

            # =================================================
            # RESULTADO DE LA MATERIA
            # =================================================

            if materia_obtenida is None:

                materias_fallidas.append(
                    {
                        "codigo": codigo,
                        "nombre": nombre,
                        "intentos": MAX_REINTENTOS,
                        "error": str(
                            ultimo_error
                        )
                    }
                )

                imprimir(
                    f"[Worker {numero_worker}] "
                    f"    ⚠ Se omitirá esta materia "
                    f"y se continuará."
                )

                if progreso is not None:
                    progreso.registrar_materia()

                continue

            materias.append(
                materia_obtenida
            )

            cantidad_grupos = len(
                materia_obtenida.grupos
            )

            cantidad_prerrequisitos = len(
                materia_obtenida.prerrequisitos
            )

            cantidad_horarios = sum(
                len(grupo.horarios)
                for grupo in materia_obtenida.grupos
            )

            imprimir(
                f"[Worker {numero_worker}] "
                f"    ✓ Grupos: "
                f"{cantidad_grupos}"
            )

            imprimir(
                f"[Worker {numero_worker}] "
                f"    ✓ Prerrequisitos: "
                f"{cantidad_prerrequisitos}"
            )

            imprimir(
                f"[Worker {numero_worker}] "
                f"    ✓ Horarios: "
                f"{cantidad_horarios}"
            )

            if progreso is not None:
                progreso.registrar_materia()

        imprimir()

        imprimir(
            f"[Worker {numero_worker}] "
            f"✓ TERMINADO."
        )

        return {
            "materias": materias,
            "fallidas": materias_fallidas
        }

    finally:

        await cerrar_sesion_worker(
            navegador,
            contexto,
            numero_worker
        )


# =============================================================
# WORKER NORMAL RESISTENTE
# =============================================================

async def ejecutar_worker_normal_resistente(
    navegador,
    grupo,
    numero_worker,
    progreso,
    codigo_plan=None
):
    # Aísla un fallo inesperado para que no cancele
    # los demás workers.

    max_reinicios = 2

    for reinicio in range(max_reinicios + 1):
        try:
            if reinicio == 0 and numero_worker > 1:
                comprobar_cancelacion()
                await asyncio.sleep(
                    ESPERA_ENTRE_WORKERS * (numero_worker - 1)
                )
                comprobar_cancelacion()
                imprimir(
                    f"[Worker {numero_worker}] "
                    f">>> Inicio escalonado tras "
                    f"{ESPERA_ENTRE_WORKERS * (numero_worker - 1):g} s."
                )
            elif reinicio > 0:
                comprobar_cancelacion()
                imprimir(
                    f"[Worker {numero_worker}] "
                    f">>> Reinicio inmediato "
                    f"({reinicio}/{max_reinicios})..."
                )

            return await worker_materias(
                navegador,
                grupo,
                numero_worker,
                progreso,
                codigo_plan
            )

        except ActualizacionCancelada:
            raise

        except Exception as error:
            if reinicio < max_reinicios:
                imprimir(
                    f"[Worker {numero_worker}] "
                    f"⚠ Fallo recuperable: {error}. "
                    f"La sesión se reiniciará ahora."
                )
                continue

            imprimir(
                f"[Worker {numero_worker}] "
                f"✗ Fallo del worker tras "
                f"{max_reinicios} reinicios: {error}"
            )

            fallidas = []

            for datos in grupo:
                fallidas.append(
                    {
                        "codigo": datos.get("codigo", ""),
                        "nombre": datos.get("nombre", ""),
                        "intentos": MAX_REINTENTOS,
                        "error": f"Worker detenido: {error}",
                    }
                )

                if progreso is not None:
                    progreso.registrar_materia()

            return {
                "materias": [],
                "fallidas": fallidas
            }


# =============================================================
# PROCESAR MATERIAS NORMALES
# =============================================================

async def procesar_materias(
    navegador,
    materias_basicas,
    codigo_plan=None
):
    # Distribuye las materias entre los workers y espera a que
    # todos terminen.

    if not materias_basicas:
        return [], []

    grupos = dividir_materias(
        materias_basicas,
        CANTIDAD_WORKERS
    )

    imprimir()
    imprimir(
        "=" * 80
    )

    imprimir(
        "INICIANDO WORKERS DE MATERIAS NORMALES"
    )

    imprimir(
        "=" * 80
    )

    for i, grupo in enumerate(
        grupos,
        start=1
    ):

        imprimir(
            f"Worker {i}: "
            f"{len(grupo)} materias"
        )

    imprimir(
        f">>> Lanzando {len(grupos)} workers..."
    )

    progreso = ProgresoPorMaterias(
        (
            "Extrayendo grupos, cupos, docentes, "
            "horarios y prerrequisitos de materias normales"
        ),
        len(materias_basicas),
        5,
        55
    )

    resultados = await asyncio.gather(
        *[
            ejecutar_worker_normal_resistente(
                navegador,
                grupo,
                i,
                progreso,
                codigo_plan
            )
            for i, grupo in enumerate(
                grupos,
                start=1
            )
        ]
    )

    imprimir(
        ">>> Todos los workers de materias "
        "normales finalizaron."
    )

    materias = []
    materias_fallidas = []

    for resultado in resultados:

        materias.extend(
            resultado["materias"]
        )

        materias_fallidas.extend(
            resultado["fallidas"]
        )

    return (
        materias,
        materias_fallidas
    )


# =============================================================
# WORKER DE LIBRE ELECCIÓN
# =============================================================

async def worker_libres_eleccion(
    navegador,
    materias_basicas,
    numero_worker,
    progreso=None,
    codigo_plan=None
):
    # Procesa las materias de Libre Elección asignadas
    # a un worker.
    #
    # Cada materia contiene internamente el índice de la tabla
    # de la que fue obtenida:
    #
    #     0 → 3 SEDE MEDELLÍN
    #     1 → 3068 FACULTAD DE MINAS
    #
    # El worker mantiene en memoria cuál es la tabla actualmente
    # visible y solo cambia cuando la siguiente materia pertenece
    # a otra tabla.

    libres_eleccion = []
    materias_fallidas = []

    contexto = None
    page = None
    catalogo = None

    # Toda sesión nueva de Libre Elección comienza en la primera
    # tabla porque configurar_libre_eleccion() termina allí.
    indice_facultad_actual = 0

    imprimir(
        f"[LE Worker {numero_worker}] "
        f">>> Worker iniciado con "
        f"{len(materias_basicas)} materias."
    )

    try:

        # =====================================================
        # CREAR SESIÓN INICIAL
        # =====================================================

        intento_sesion = 1

        while True:

            try:

                (
                    contexto,
                    page,
                    catalogo
                ) = await crear_sesion_libre_eleccion(
                    navegador,
                    numero_worker,
                    codigo_plan
                )

                # La nueva sesión comienza siempre en la primera
                # consulta.
                indice_facultad_actual = 0

                break

            except Exception as error:

                imprimir(
                    f"[LE Worker {numero_worker}] "
                    f"⚠ No se pudo iniciar la sesión: "
                    f"{error}"
                )

                if intento_sesion >= MAX_REINTENTOS:

                    raise RuntimeError(
                        f"El LE Worker "
                        f"{numero_worker} "
                        f"no pudo iniciar el SIA "
                        f"después de "
                        f"{MAX_REINTENTOS} intentos."
                    ) from error

                await cerrar_sesion_worker(
                    navegador,
                    contexto,
                    numero_worker,
                    "LE "
                )

                contexto = None
                page = None
                catalogo = None

                await esperar_reintento(
                    intento_sesion
                )

                intento_sesion += 1

        # =====================================================
        # PROCESAR MATERIAS
        # =====================================================

        total = len(
            materias_basicas
        )

        for posicion, datos_basicos in enumerate(
            materias_basicas,
            start=1
        ):
            comprobar_cancelacion()

            codigo = datos_basicos.get(
                "codigo",
                ""
            )

            nombre = datos_basicos.get(
                "nombre",
                ""
            )

            indice_facultad_objetivo = datos_basicos.get(
                CLAVE_INDICE_FACULTAD_LIBRE_ELECCION,
                0
            )

            try:
                indice_facultad_objetivo = int(
                    indice_facultad_objetivo
                )
            except (TypeError, ValueError):
                indice_facultad_objetivo = 0

            if indice_facultad_objetivo not in (0, 1):
                indice_facultad_objetivo = 0

            imprimir()

            imprimir(
                f"[LE Worker {numero_worker}] "
                f"[{posicion}/{total}] "
                f"{codigo} - {nombre}"
            )

            materia_obtenida = None
            ultimo_error = None

            for intento in range(
                1,
                MAX_REINTENTOS + 1
            ):

                try:

                    imprimir(
                        f"[LE Worker {numero_worker}] "
                        f"    Intento "
                        f"{intento}/{MAX_REINTENTOS}"
                    )

                    # -------------------------------------------------
                    # ASEGURAR LA TABLA CORRECTA
                    # -------------------------------------------------
                    #
                    # Si la materia pertenece a la misma tabla que
                    # ya está visible, no se hace ninguna navegación.
                    #
                    # Si pertenece a la otra tabla, únicamente se
                    # cambia soc6 y se pulsa Mostrar.

                    indice_facultad_actual = (
                        await asegurar_tabla_libre_eleccion(
                            catalogo,
                            indice_facultad_actual,
                            indice_facultad_objetivo,
                            numero_worker
                        )
                    )

                    materia_obtenida = (
                        await procesar_materia_libre_eleccion(
                            page,
                            catalogo,
                            datos_basicos,
                            numero_worker
                        )
                    )

                    imprimir(
                        f"[LE Worker {numero_worker}] "
                        f"    Regresando al catálogo..."
                    )

                    await catalogo.volver()

                    imprimir(
                        f"[LE Worker {numero_worker}] "
                        f"    ✓ Regresó al catálogo."
                    )

                    break

                except Exception as error:

                    ultimo_error = error

                    imprimir()
                    imprimir(
                        f"[LE Worker {numero_worker}] "
                        f"    ⚠ Error en {codigo}: "
                        f"{error}"
                    )

                    if intento >= MAX_REINTENTOS:

                        imprimir(
                            f"[LE Worker {numero_worker}] "
                            f"    ✗ Materia agotó "
                            f"todos los intentos."
                        )

                        break

                    # -------------------------------------------------
                    # RECREAR SESIÓN
                    # -------------------------------------------------
                    #
                    # Una sesión nueva vuelve automáticamente a la
                    # primera tabla.
                    #
                    # Por eso se reinicia el índice actual a 0.
                    # En el siguiente intento, asegurar_tabla...()
                    # volverá a cambiar a la segunda si esta materia
                    # lo necesita.

                    await cerrar_sesion_worker(
                        navegador,
                        contexto,
                        numero_worker,
                        "LE "
                    )

                    contexto = None
                    page = None
                    catalogo = None

                    indice_facultad_actual = 0

                    await esperar_reintento(
                        intento
                    )

                    try:

                        (
                            contexto,
                            page,
                            catalogo
                        ) = await crear_sesion_libre_eleccion(
                            navegador,
                            numero_worker,
                            codigo_plan
                        )

                        # La nueva sesión está en la primera tabla.
                        indice_facultad_actual = 0

                    except Exception as error_sesion:

                        ultimo_error = error_sesion

                        imprimir(
                            f"[LE Worker {numero_worker}] "
                            f"    ⚠ Tampoco se pudo "
                            f"recrear la sesión: "
                            f"{error_sesion}"
                        )

                        continue

            # =================================================
            # RESULTADO
            # =================================================

            if materia_obtenida is None:

                materias_fallidas.append(
                    {
                        "codigo": codigo,
                        "nombre": nombre,
                        "intentos": MAX_REINTENTOS,
                        "error": str(
                            ultimo_error
                        )
                    }
                )

                imprimir(
                    f"[LE Worker {numero_worker}] "
                    f"    ⚠ Se omitirá esta materia "
                    f"y se continuará."
                )

                if progreso is not None:
                    progreso.registrar_materia()

                continue

            libres_eleccion.append(
                materia_obtenida
            )

            cantidad_grupos = len(
                materia_obtenida["grupos"]
            )

            cantidad_horarios = sum(
                len(grupo["horarios"])
                for grupo in materia_obtenida["grupos"]
            )

            imprimir(
                f"[LE Worker {numero_worker}] "
                f"    ✓ Grupos: "
                f"{cantidad_grupos}"
            )

            imprimir(
                f"[LE Worker {numero_worker}] "
                f"    ✓ Horarios: "
                f"{cantidad_horarios}"
            )

            if progreso is not None:
                progreso.registrar_materia()

        imprimir()

        imprimir(
            f"[LE Worker {numero_worker}] "
            f"✓ TERMINADO."
        )

        return {
            "materias": libres_eleccion,
            "fallidas": materias_fallidas
        }

    finally:

        await cerrar_sesion_worker(
            navegador,
            contexto,
            numero_worker,
            "LE "
        )


# =============================================================
# WORKER LIBRE RESISTENTE
# =============================================================

async def ejecutar_worker_libre_resistente(
    navegador,
    grupo,
    numero_worker,
    progreso,
    codigo_plan=None
):
    # Aísla un fallo inesperado de un worker LE y conserva
    # los demás resultados.

    max_reinicios = 2

    for reinicio in range(max_reinicios + 1):
        try:
            if reinicio == 0 and numero_worker > 1:
                comprobar_cancelacion()
                await asyncio.sleep(
                    ESPERA_ENTRE_WORKERS * (numero_worker - 1)
                )
                comprobar_cancelacion()
                imprimir(
                    f"[LE Worker {numero_worker}] "
                    f">>> Inicio escalonado tras "
                    f"{ESPERA_ENTRE_WORKERS * (numero_worker - 1):g} s."
                )
            elif reinicio > 0:
                comprobar_cancelacion()
                imprimir(
                    f"[LE Worker {numero_worker}] "
                    f">>> Reinicio inmediato "
                    f"({reinicio}/{max_reinicios})..."
                )

            return await worker_libres_eleccion(
                navegador,
                grupo,
                numero_worker,
                progreso,
                codigo_plan
            )

        except ActualizacionCancelada:
            raise

        except Exception as error:
            if reinicio < max_reinicios:
                imprimir(
                    f"[LE Worker {numero_worker}] "
                    f"⚠ Fallo recuperable: {error}. "
                    f"La sesión se reiniciará ahora."
                )
                continue

            imprimir(
                f"[LE Worker {numero_worker}] "
                f"✗ Fallo del worker tras "
                f"{max_reinicios} reinicios: {error}"
            )

            fallidas = []

            for datos in grupo:
                fallidas.append(
                    {
                        "codigo": datos.get("codigo", ""),
                        "nombre": datos.get("nombre", ""),
                        "intentos": MAX_REINTENTOS,
                        "error": f"Worker detenido: {error}",
                    }
                )

                if progreso is not None:
                    progreso.registrar_materia()

            return {
                "materias": [],
                "fallidas": fallidas
            }


# =============================================================
# PROCESAR LIBRE ELECCIÓN
# =============================================================

async def procesar_libres_eleccion(
    navegador,
    materias_basicas,
    codigo_plan=None
):
    if not materias_basicas:
        return [], []

    # Distribuye las materias de Libre Elección entre los
    # workers y espera a que todos terminen.
    #
    # La información sobre la tabla de origen viaja junto con
    # cada materia, por lo que dividir_materias() no necesita
    # ningún tratamiento especial.

    if not materias_basicas:
        imprimir(
            "No hay materias de Libre Elección para procesar."
        )
        return [], []

    grupos = dividir_materias(
        materias_basicas,
        CANTIDAD_WORKERS
    )

    imprimir()
    imprimir(
        "=" * 80
    )

    imprimir(
        "INICIANDO WORKERS DE LIBRE ELECCIÓN"
    )

    imprimir(
        "=" * 80
    )

    for i, grupo in enumerate(
        grupos,
        start=1
    ):

        imprimir(
            f"LE Worker {i}: "
            f"{len(grupo)} materias"
        )

    imprimir(
        f">>> Lanzando {len(grupos)} workers..."
    )

    progreso = ProgresoPorMaterias(
        (
            "Extrayendo grupos, cupos, docentes "
            "y horarios de materias de libre elección"
        ),
        len(materias_basicas),
        65,
        95
    )

    resultados = await asyncio.gather(
        *[
            ejecutar_worker_libre_resistente(
                navegador,
                grupo,
                i,
                progreso,
                codigo_plan
            )
            for i, grupo in enumerate(
                grupos,
                start=1
            )
        ]
    )

    imprimir(
        ">>> Todos los workers de Libre Elección "
        "finalizaron."
    )

    libres_eleccion = []
    materias_fallidas = []

    for resultado in resultados:

        libres_eleccion.extend(
            resultado["materias"]
        )

        materias_fallidas.extend(
            resultado["fallidas"]
        )

    return (
        libres_eleccion,
        materias_fallidas
    )


# =============================================================
# ACTUALIZACIÓN COMPLETA
# =============================================================

async def actualizar_datos(
    playwright,
    nombre_plan=None,
    codigo_plan=None,
    priorizar_estudiante=True,
    cache_materias=None,
    cache_libres=None,
):
    # Ejecuta la actualización completa del catálogo del SIA.
    #
    # La prioridad para determinar el plan es:
    #
    #   1. codigo_plan de estudiante.json
    #   2. codigo_plan recibido explícitamente
    #
    # nombre_plan queda únicamente por compatibilidad con código
    # anterior y ya no es necesario para determinar la carrera.

    comprobar_cancelacion()
    codigo_plan_estudiante = (
        obtener_codigo_plan_estudiante()
    )

    if priorizar_estudiante and codigo_plan_estudiante:
        codigo_plan = (
            codigo_plan_estudiante
        )

    imprimir(
        f">>> Plan académico del estudiante: "
        f"{codigo_plan}"
    )

    publicar_progreso(
        (
            "Abriendo el navegador y conectando "
            "con el catálogo académico del SIA…"
        ),
        0
    )

    imprimir(
        ">>> Iniciando actualización de datos..."
    )

    navegador = NavegadorSIA(
        playwright=playwright,
        ancho=ANCHO_VENTANA,
        alto=ALTO_VENTANA,
        headless=HEADLESS
    )

    await navegador.iniciar()

    publicar_progreso(
        (
            "Consultando el catálogo principal "
            "para obtener códigos y nombres de materias…"
        ),
        5
    )

    imprimir(
        ">>> Navegador SIA iniciado."
    )

    try:

        # =====================================================
        # OBTENER LISTA DE MATERIAS NORMALES
        # =====================================================

        imprimir()
        imprimir(
            "=" * 80
        )

        imprimir(
            "OBTENIENDO MATERIAS NORMALES"
        )

        imprimir(
            "=" * 80
        )

        contexto_inicial = navegador.context
        page_inicial = navegador.page

        catalogo_inicial = CatalogoSIA(
            page=page_inicial,
            url=URL_SIA,
            codigo_plan=codigo_plan
        )

        await catalogo_inicial.abrir()

        await catalogo_inicial.configurar()

        await catalogo_inicial.mostrar_resultados()

        await catalogo_inicial.esperar_resultados()

        imprimir()
        imprimir(
            "Extrayendo materias..."
        )

        materias_basicas = (
            await obtener_materias_de_tabla(
                page_inicial
            )
        )

        publicar_progreso(
            (
                "Catálogo principal obtenido; "
                "preparando la extracción detallada "
                "de cada materia…"
            ),
            5
        )

        imprimir(
            f"✓ Materias encontradas: "
            f"{len(materias_basicas)}"
        )

        if not materias_basicas:
            raise RuntimeError(
                "El catálogo normal no devolvió "
                "materias."
            )

        await navegador.cerrar_contexto(
            contexto_inicial
        )

        navegador.context = None
        navegador.page = None

        # =====================================================
        # PROCESAR MATERIAS NORMALES
        # =====================================================

        materias_reutilizadas = [
            reutilizada
            for materia_basica in materias_basicas
            if (reutilizada := _reutilizar_desde_cache(
                materia_basica,
                cache_materias,
            )) is not None
        ]
        materias_pendientes = [
            materia_basica
            for materia_basica in materias_basicas
            if _codigo_materia(materia_basica) not in (cache_materias or {})
        ]
        imprimir(
            f">>> Caché normal: {len(materias_reutilizadas)} reutilizada(s), "
            f"{len(materias_pendientes)} por consultar."
        )
        (
            materias_nuevas,
            materias_normales_fallidas
        ) = await procesar_materias(
            navegador,
            materias_pendientes,
            codigo_plan
        )
        materias = combinar_materias(materias_reutilizadas, materias_nuevas)

        if materias_normales_fallidas:
            imprimir(
                f">>> Reintentando {len(materias_normales_fallidas)} materia(s) normal(es) fallida(s)..."
            )
            segunda_basicas = datos_para_reintento(
                materias_pendientes,
                materias_normales_fallidas,
            )
            materias_segundo_intento, materias_normales_fallidas = await procesar_materias(
                navegador,
                segunda_basicas,
                codigo_plan,
            )
            materias = combinar_materias(materias, materias_segundo_intento)
            registrar_errores_definitivos(
                "normal",
                materias_normales_fallidas,
                codigo_plan,
            )

        if cache_materias is not None:
            for materia in materias:
                cache_materias[_codigo_materia(materia)] = deepcopy(materia)

        publicar_progreso(
            (
                "Guardando materias normales, grupos, "
                "cupos, docentes, horarios y "
                "prerrequisitos…"
            ),
            55
        )

        # =====================================================
        # GUARDAR MATERIAS NORMALES
        # =====================================================

        comprobar_cancelacion()
        guardar_materias(
            materias,
            codigo_plan=codigo_plan,
        )

        guardar_oferta(
            materias,
            codigo_plan=codigo_plan,
        )

        imprimir()
        imprimir(
            "✓ Catálogo normal actualizado."
        )

        imprimir(
            f"✓ Materias procesadas: "
            f"{len(materias)}"
        )

        # Punto de disponibilidad temprana: desde aquí la interfaz ya puede
        # mostrar y permitir editar el horario. Libre Elección se consulta
        # después porque su extracción es mucho más lenta.
        publicar_progreso(
            (
                "Materias normales listas; puedes comenzar a organizar "
                "tu horario. Libre Elección continúa en segundo plano…"
            ),
            60
        )

        if materias_normales_fallidas:

            imprimir()
            imprimir(
                "⚠ Materias normales con errores:"
            )

            for materia in (
                materias_normales_fallidas
            ):

                imprimir(
                    f"    {materia['codigo']} - "
                    f"{materia['nombre']}"
                )

                imprimir(
                    f"        Error: "
                    f"{materia['error']}"
                )

        # =====================================================
        # OBTENER LISTA DE LIBRE ELECCIÓN
        # =====================================================

        imprimir()
        imprimir(
            "=" * 80
        )

        imprimir(
            "OBTENIENDO LIBRE ELECCIÓN"
        )

        imprimir(
            "=" * 80
        )

        contexto_le = (
            await navegador.crear_contexto()
        )

        publicar_progreso(
            (
                "Consultando el catálogo de libre "
                "elección para obtener sus códigos "
                "y nombres…"
            ),
            62
        )

        page_le = (
            await navegador.crear_pagina(
                contexto_le
            )
        )

        catalogo_le = CatalogoSIA(
            page=page_le,
            url=URL_SIA,
            codigo_plan=codigo_plan
        )

        try:

            # -------------------------------------------------
            # PRIMERA TABLA
            # -------------------------------------------------
            #
            # configurar_libre_eleccion() selecciona:
            #
            #   1. Pregrado
            #   2. Sede
            #   3. Facultad
            #   4. Plan
            #   5. Libre Elección
            #   6. Por Facultad y Plan
            #   7. 1102 SEDE MEDELLÍN
            #   8. 3 SEDE MEDELLÍN
            #
            # En los pasos 1-4 se utiliza la rama normal,
            # incluyendo soc2 para la facultad de la carrera.
            #
            # Después de reconstruir la rama de Libre Elección,
            # el paso 8 utiliza soc6, que corresponde al campo
            # "¿Por qué facultad?".

            await catalogo_le.abrir()

            await catalogo_le.configurar_libre_eleccion()

            await catalogo_le.mostrar_resultados()

            await catalogo_le.esperar_resultados()

            # -------------------------------------------------
            # PRIMERA TABLA → SEGUNDA TABLA
            # -------------------------------------------------
            #
            # Aquí ocurre explícitamente la secuencia:
            #
            #   Mostrar
            #   ↓
            #   procesar primera tabla
            #   ↓
            #   seleccionar 3068 FACULTAD DE MINAS
            #   ↓
            #   Mostrar
            #   ↓
            #   procesar segunda tabla
            #
            # La selección de 3068 ocurre sobre soc6.

            imprimir(
                "Procesando las dos consultas "
                "de Libre Elección..."
            )

            libres_basicas = (
                await obtener_materias_libre_eleccion(
                    page_le,
                    catalogo_le
                )
            )

        except Exception as error:

            libres_basicas = []

            imprimir(
                "⚠ No se pudieron obtener materias de Libre Elección: "
                f"{error}"
            )

        publicar_progreso(
            (
                "Catálogo de libre elección obtenido; "
                "preparando la extracción detallada…"
            ),
            65
        )

        imprimir(
            f"✓ Materias de Libre Elección "
            f"encontradas: "
            f"{len(libres_basicas)}"
        )

        await navegador.cerrar_contexto(
            contexto_le
        )

        if not libres_basicas:
            imprimir(
                "⚠ El catálogo de Libre Elección no devolvió materias; "
                "las materias normales siguen disponibles y se conservará "
                "el resultado vacío de esta fase."
            )

        # =====================================================
        # PROCESAR LIBRE ELECCIÓN
        # =====================================================

        libres_reutilizadas = [
            reutilizada
            for materia_basica in libres_basicas
            if (reutilizada := _reutilizar_desde_cache(
                materia_basica,
                cache_libres,
            )) is not None
        ]
        libres_pendientes = [
            materia_basica
            for materia_basica in libres_basicas
            if _codigo_materia(materia_basica) not in (cache_libres or {})
        ]
        imprimir(
            f">>> Caché libre: {len(libres_reutilizadas)} reutilizada(s), "
            f"{len(libres_pendientes)} por consultar."
        )
        (
            libres_nuevas,
            libres_fallidas
        ) = await procesar_libres_eleccion(
            navegador,
            libres_pendientes,
            codigo_plan
        )
        libres_eleccion = combinar_materias(
            libres_reutilizadas,
            libres_nuevas,
        )

        if libres_fallidas:
            imprimir(
                f">>> Reintentando {len(libres_fallidas)} materia(s) de Libre Elección fallida(s)..."
            )
            segunda_libres_basicas = datos_para_reintento(
                libres_pendientes,
                libres_fallidas,
            )
            libres_segundo_intento, libres_fallidas = await procesar_libres_eleccion(
                navegador,
                segunda_libres_basicas,
                codigo_plan,
            )
            libres_eleccion = combinar_materias(
                libres_eleccion,
                libres_segundo_intento,
            )
            registrar_errores_definitivos(
                "libre_eleccion",
                libres_fallidas,
                codigo_plan,
            )

        if cache_libres is not None:
            for materia in libres_eleccion:
                cache_libres[_codigo_materia(materia)] = deepcopy(materia)

        publicar_progreso(
            (
                "Guardando materias libres, grupos, "
                "cupos, docentes y horarios…"
            ),
            95
        )

        # =====================================================
        # GUARDAR LIBRE ELECCIÓN
        # =====================================================

        comprobar_cancelacion()
        guardar_libres_eleccion(
            libres_eleccion,
            codigo_plan=codigo_plan,
        )

        imprimir()
        imprimir(
            "✓ Libre Elección actualizada."
        )

        imprimir(
            f"✓ Materias procesadas: "
            f"{len(libres_eleccion)}"
        )

        if libres_fallidas:

            imprimir()
            imprimir(
                "⚠ Materias de Libre Elección "
                "con errores:"
            )

            for materia in libres_fallidas:

                imprimir(
                    f"    {materia['codigo']} - "
                    f"{materia['nombre']}"
                )

                imprimir(
                    f"        Error: "
                    f"{materia['error']}"
                )

        # =====================================================
        # RESUMEN FINAL
        # =====================================================

        total_fallidas = (
            len(
                materias_normales_fallidas
            )
            +
            len(
                libres_fallidas
            )
        )

        imprimir()
        imprimir(
            "=" * 80
        )

        imprimir(
            "ACTUALIZACIÓN COMPLETADA"
        )

        imprimir(
            "=" * 80
        )

        imprimir(
            f"Plan de estudios: "
            f"{codigo_plan}"
        )

        imprimir(
            f"Materias normales: "
            f"{len(materias)}"
        )

        imprimir(
            f"Libre Elección: "
            f"{len(libres_eleccion)}"
        )

        imprimir(
            f"Materias con errores: "
            f"{total_fallidas}"
        )

        if total_fallidas > 0:

            imprimir()
            imprimir(
                "⚠ La actualización terminó, "
                "pero quedaron materias sin procesar."
            )

        else:

            imprimir()
            imprimir(
                "✓ Todas las materias fueron procesadas."
            )

        imprimir(
            "=" * 80
        )

        publicar_progreso(
            (
                "Actualización terminada; "
                "verificando resultados y "
                "materias con errores…"
            ),
            100
        )

        return {
            "materias": materias,
            "libres_eleccion": libres_eleccion,
            "materias_fallidas": (
                materias_normales_fallidas
            ),
            "libres_fallidas": (
                libres_fallidas
            )
        }

    finally:

        await navegador.cerrar()


# =============================================================
# ACTUALIZACIÓN EXCLUSIVA DE LIBRES
# =============================================================

async def actualizar_solo_libres(
    playwright,
    nombre_plan=None
):
    # Actualiza solamente las materias de Libre Elección.
    #
    # El plan se obtiene igualmente desde estudiante.json.

    comprobar_cancelacion()
    codigo_plan = (
        obtener_codigo_plan_estudiante()
    )

    publicar_progreso(
        "Priorizando la actualización de libres elección…",
        0
    )

    navegador = NavegadorSIA(
        playwright=playwright,
        ancho=ANCHO_VENTANA,
        alto=ALTO_VENTANA,
        headless=HEADLESS,
    )

    try:

        await navegador.iniciar()

        contexto = await navegador.crear_contexto()

        publicar_progreso(
            "Consultando las asignaturas de libre elección…",
            5
        )

        pagina = await navegador.crear_pagina(
            contexto
        )

        catalogo = CatalogoSIA(
            page=pagina,
            url=URL_SIA,
            codigo_plan=codigo_plan
        )

        await catalogo.abrir()

        # -----------------------------------------------------
        # PRIMERA CONSULTA DE LIBRE ELECCIÓN
        # -----------------------------------------------------

        # configurar_libre_eleccion() deja seleccionada la
        # primera opción de "¿Por qué facultad?" utilizando
        # soc6.

        await catalogo.configurar_libre_eleccion()

        await catalogo.mostrar_resultados()

        await catalogo.esperar_resultados()

        # -----------------------------------------------------
        # PRIMERA TABLA + SEGUNDA TABLA
        # -----------------------------------------------------
        #
        # No se vuelve a configurar la rama del SIA. La segunda
        # consulta se hace sobre el mismo formulario reconstruido,
        # cambiando soc6.
        #
        # Cada materia conserva además el índice de la tabla
        # de origen para que los workers posteriores sepan dónde
        # encontrarla.

        libres_basicas = (
            await obtener_materias_libre_eleccion(
                pagina,
                catalogo
            )
        )

        if not libres_basicas:
            raise RuntimeError(
                "El catálogo de Libre Elección "
                "no devolvió materias."
            )

        await navegador.cerrar_contexto(
            contexto
        )

        (
            libres,
            fallidas
        ) = await procesar_libres_eleccion(
            navegador,
            libres_basicas,
            codigo_plan
        )

        if fallidas:
            imprimir(
                f">>> Reintentando {len(fallidas)} materia(s) de Libre Elección fallida(s)..."
            )
            segunda_basicas = datos_para_reintento(libres_basicas, fallidas)
            libres_segundo_intento, fallidas = await procesar_libres_eleccion(
                navegador,
                segunda_basicas,
                codigo_plan,
            )
            libres = combinar_materias(libres, libres_segundo_intento)
            registrar_errores_definitivos("libre_eleccion", fallidas, codigo_plan)

        publicar_progreso(
            "Guardando las asignaturas de libre elección…",
            100
        )

        comprobar_cancelacion()
        guardar_libres_eleccion(
            libres,
            codigo_plan=codigo_plan,
        )

        return {
            "materias": [],
            "libres_eleccion": libres,
            "materias_fallidas": [],
            "libres_fallidas": fallidas,
        }

    finally:

        await navegador.cerrar()


# =============================================================
# FUNCIÓN DE ENTRADA
# =============================================================

async def actualizar(
    solo_libres=False,
    nombre_plan=None,
    codigo_plan=None,
    priorizar_estudiante=True,
    cache_materias=None,
    cache_libres=None,
):
    # Función pública utilizada por main.py.
    #
    # Aquí se crea y administra la instancia de Playwright.
    #
    # codigo_plan se mantiene como argumento por compatibilidad,
    # pero actualizar_datos() y actualizar_solo_libres() priorizan
    # el plan almacenado en estudiante.json.

    global TOKEN_ACTUALIZACION
    TOKEN_ACTUALIZACION = token_cancelacion()

    from playwright.async_api import (
        async_playwright
    )

    imprimir(
        ">>> Preparando Playwright..."
    )

    async with async_playwright() as playwright:

        imprimir(
            ">>> Playwright listo."
        )
        publicar_progreso("Abriendo SIA", 0)

        if solo_libres:

            return await actualizar_solo_libres(
                playwright,
                nombre_plan
            )

        return await actualizar_datos(
            playwright,
            nombre_plan,
            codigo_plan,
            priorizar_estudiante=priorizar_estudiante,
            cache_materias=cache_materias,
            cache_libres=cache_libres,
        )
