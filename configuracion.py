# =============================================================
# CONFIGURACIÓN DE FÉNIX
# =============================================================
#
# Este módulo contiene las configuraciones generales utilizadas
# por Fénix.
#
# La idea es mantener en un único lugar los valores que pueden
# necesitar modificarse sin tener que buscar dentro de la lógica
# de los diferentes módulos.
#
# Por ejemplo:
#
#   - Rutas de los archivos de datos.
#   - Dirección del SIA.
#   - Filtros utilizados para consultar el catálogo.
#   - Tamaño de las ventanas de Playwright.
#   - Número de reintentos.
#   - Tiempo de espera entre reintentos.
#   - Cantidad de workers.
#
# Los demás módulos pueden importar estos valores desde aquí.
#
# =============================================================

import os
from pathlib import Path

VERSION = "2.0.7"
URL_DATOS_CLOUDFLARE = "https://pub-c4af9a6ed2d249a290ff6c850b8dac15.r2.dev"


# =============================================================
# RUTAS DE DATOS
# =============================================================

# Directorio raíz del proyecto.
#
# Path(__file__) representa este archivo.
# resolve() obtiene su ruta absoluta.
# parent obtiene la carpeta que contiene configuracion.py.
#
# De esta forma las rutas de los datos no dependen del directorio
# desde el cual se ejecute Python.

BASE_DIR = Path(__file__).resolve().parent


# Los recursos viajan con el programa; los datos personales sobreviven a las
# actualizaciones y no requieren permisos de escritura en la instalación.
CARPETA_DATOS_BASE = BASE_DIR / "datos"
CARPETA_RECURSOS = BASE_DIR / "recursos"
CARPETA_DATOS = Path(
    os.environ.get("FENIX_DATA_DIR")
    or Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Fenix"
).expanduser().resolve()


# Información relativamente estable de las asignaturas.

ARCHIVO_MATERIAS = (
    CARPETA_DATOS / "materias.json"
)


# Oferta académica actual, incluyendo grupos, profesores,
# cupos y horarios.

ARCHIVO_OFERTA = (
    CARPETA_DATOS / "oferta.json"
)


# Información del estudiante.

ARCHIVO_ESTUDIANTE = (
    CARPETA_DATOS / "estudiante.json"
)


# Materias disponibles para Libre Elección.

ARCHIVO_LIBRES_ELECCION = (
    CARPETA_DATOS / "libres_eleccion.json"
)

# Catálogo compartido de Libre Elección consultado por sede Medellín.
ARCHIVO_LIBRES_ELECCION_SEDE = (
    CARPETA_DATOS / "libres_eleccion_sede.json"
)


# Planes de estudio disponibles para el programa.

ARCHIVO_PLANES_ESTUDIO = (
    CARPETA_DATOS / "planes_estudio.json"
)


# Estado compartido entre el proceso de actualización y la interfaz.

ARCHIVO_ESTADO_ACTUALIZACION = (
    CARPETA_DATOS / "estado_actualizacion.json"
)
ARCHIVO_DATOS_CLOUDFLARE = CARPETA_DATOS / "manifest_cloudflare.json"

# Caché temporal del publicador. Evita repetir consultas cuando una materia
# aparece en varios planes o si el publicador se reinicia durante un ciclo.
ARCHIVO_CACHE_PUBLICADOR = CARPETA_DATOS / "cache_publicador.json"

# Registro acumulativo de materias que no pudieron procesarse después
# del reintento focalizado de una actualización.
ARCHIVO_LOG_ERRORES_ACTUALIZACION = (
    CARPETA_DATOS / "errores_actualizacion.log"
)

# Contador monotónico usado para cancelar actualizaciones en curso sin
# confundirlas con una actualización nueva que empiece inmediatamente.
ARCHIVO_CANCELACION_ACTUALIZACION = (
    CARPETA_DATOS / "cancelacion_actualizacion.json"
)

# Catálogo local del SIA y rutas particulares de Libre Elección.
ARCHIVO_CATALOGO_SIA = CARPETA_DATOS / "catalogo_sia.json"
ARCHIVO_CONFIGURACION_LIBRE_ELECCION = (
    CARPETA_DATOS / "configuracion_libre_eleccion.json"
)


# =============================================================
# CONFIGURACIÓN DEL SIA
# =============================================================

# Dirección utilizada para acceder al catálogo público
# de asignaturas del Sistema de Información Académica.
#
# Se mantiene completa aquí para que los módulos encargados
# de navegar por el SIA no tengan que conocer directamente
# la dirección del servicio.

URL_SIA = (
    "https://sia.unal.edu.co/"
    "Catalogo/facespublico/public/"
    "servicioPublico.jsf"
    "?taskflowId=task-flow-AC_CatalogoAsignaturas"
)


# =============================================================
# CONFIGURACIÓN DEL CATÁLOGO NORMAL
# =============================================================
#
# Estos valores corresponden a las opciones seleccionadas
# dentro del catálogo público del SIA.
#
# Los valores HTML de sede, facultad y plan se obtienen desde
# catalogo_sia.json para cada ruta académica incluida.
#
# Los valores son los que espera directamente el SIA.
# Por eso se mantienen como strings.

NIVEL_ESTUDIO = "0"

SEDE = "6"

FACULTAD = "6"

PLAN_ESTUDIOS = "13"

TIPOLOGIA = "0"

# =============================================================
# CONFIGURACIÓN DEL NAVEGADOR
# =============================================================

# Ancho de la ventana virtual utilizada por Playwright.

ANCHO_VENTANA = 1280


# Alto de la ventana virtual utilizada por Playwright.

ALTO_VENTANA = 720


# Indica si Chromium debe ejecutarse sin mostrar
# una ventana gráfica.
#
# True es apropiado para la actualización automática,
# ya que Fénix no necesita que el usuario vea el navegador.

HEADLESS = True


# =============================================================
# CONFIGURACIÓN DE REINTENTOS DEL SIA
# =============================================================

# Cantidad máxima de veces que se intentará realizar
# una operación antes de considerarla fallida.
#
# Se aplica a problemas temporales relacionados con el SIA,
# la red o el navegador.

MAX_REINTENTOS = 5


# Tiempo inicial de espera, en segundos, antes del primer
# reintento.

ESPERA_REINTENTO = 1


# Multiplicador utilizado para calcular el backoff exponencial.
#
# Con el valor actual:
#
#   Intento 1 → 2 segundos
#   Intento 2 → 4 segundos
#   Intento 3 → 8 segundos
#   Intento 4 → 16 segundos
#
# Aumentar el tiempo progresivamente evita realizar solicitudes
# repetidas demasiado rápido cuando el SIA está temporalmente
# saturado o presenta problemas.

FACTOR_BACKOFF = 2


# Tiempo máximo de espera entre reintentos, expresado
# en segundos.
#
# Aunque el backoff exponencial siga aumentando,
# nunca se esperará más de este valor.

MAX_ESPERA_REINTENTO = 15


# =============================================================
# CONFIGURACIÓN DE WORKERS
# =============================================================

# Cantidad de workers que procesan simultáneamente las materias.
#
# Cada worker utiliza un BrowserContext independiente para
# mantener separada su sesión del SIA.
#
# El mismo número de workers se utiliza para:
#
#   - Materias normales.
#   - Materias de Libre Elección.

# Cada publicador consulta el SIA con una sola sesión. La concurrencia entre
# carreras se controla desde el gestor; abrir varias sesiones por publicador
# provoca que el SIA se ralentice y deja una larga cola de materias al final.
CANTIDAD_WORKERS = 1

# Escalonamiento inicial para no abrir varias sesiones SIA exactamente al
# mismo tiempo. El paralelismo se conserva después de este retraso.
ESPERA_ENTRE_WORKERS = 1.0
