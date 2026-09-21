# =============================================================
# EXTRACTOR DE INFORMACIÓN DE UNA ASIGNATURA
# =============================================================
#
# Este módulo coordina la extracción de información de una
# asignatura a partir de los datos obtenidos del catálogo del SIA.
#
# A diferencia de los módulos ubicados en parser/, este archivo
# no interpreta directamente el HTML.
#
# Su función es combinar:
#
#   - Los datos básicos obtenidos de la tabla del catálogo.
#   - Los prerrequisitos obtenidos por el parser correspondiente.
#   - Los grupos y horarios obtenidos por el parser de grupos.
#
# De esta forma, los diferentes parsers pueden concentrarse en
# interpretar una parte específica del HTML, mientras este módulo
# se encarga de construir el resultado completo.
#
# El flujo para una materia normal es:
#
#   Tabla del catálogo
#       ↓
#   datos_basicos
#       +
#   HTML del detalle
#       ↓
#   extraer_prerrequisitos()
#   extraer_grupos()
#       ↓
#   Materia
#
# Para Libre Elección se utiliza un flujo ligeramente diferente,
# ya que actualmente no se extraen prerrequisitos y el resultado
# se devuelve como diccionario.
#

from dominio.materia import Materia

from infraestructura.sia.parser.grupos import (
    extraer_grupos
)

from infraestructura.sia.parser.prerrequisitos import (
    extraer_prerrequisitos
)


# =============================================================
# EXTRAER MATERIA NORMAL
# =============================================================

async def extraer_materia_actual(
    detalle,
    datos_basicos: dict
) -> Materia:
    # Construye un objeto Materia utilizando la información
    # básica de la tabla del catálogo y el HTML de su página
    # de detalle.
    #
    # datos_basicos contiene la información que ya fue obtenida
    # de la tabla de resultados:
    #
    #   - código
    #   - nombre
    #   - créditos
    #   - tipología
    #   - descripción
    #
    # detalle contiene el HTML de la página de información de
    # la asignatura, obtenido mediante la navegación real de
    # Playwright.
    #
    # Del detalle se extraen:
    #
    #   - Prerrequisitos.
    #   - Grupos.
    #   - Horarios.
    #
    # La función combina toda esta información en un único
    # objeto Materia.

    materia = Materia()

    # =========================================================
    # INFORMACIÓN BÁSICA
    # =========================================================
    #
    # Esta información ya fue obtenida de la tabla del catálogo.
    # Se utiliza get() para evitar errores si alguno de los campos
    # no está presente en el diccionario.

    materia.codigo = datos_basicos.get(
        "codigo",
        ""
    )

    materia.nombre = datos_basicos.get(
        "nombre",
        ""
    )

    materia.creditos = datos_basicos.get(
        "creditos",
        ""
    )

    materia.tipologia = datos_basicos.get(
        "tipologia",
        ""
    )

    materia.descripcion = datos_basicos.get(
        "descripcion",
        ""
    )

    # =========================================================
    # PRERREQUISITOS
    # =========================================================
    #
    # El parser de prerrequisitos se encarga exclusivamente de
    # interpretar esa sección del HTML.
    #
    # La función devuelve objetos Prerrequisito que pasan a
    # formar parte de la materia.

    materia.prerrequisitos = (
        await extraer_prerrequisitos(
            detalle
        )
    )

    # =========================================================
    # GRUPOS Y HORARIOS
    # =========================================================
    #
    # Los horarios pertenecen a los grupos, por lo que el parser
    # de grupos devuelve directamente los objetos Grupo completos,
    # incluyendo sus objetos Horario.

    materia.grupos = (
        await extraer_grupos(
            detalle
        )
    )

    return materia


# =============================================================
# EXTRAER LIBRE ELECCIÓN
# =============================================================

async def extraer_libre_eleccion_actual(
    detalle,
    datos_basicos: dict
) -> dict:
    # Construye la información de una materia de Libre Elección.
    #
    # Actualmente las materias de Libre Elección se manejan
    # separadamente de las materias normales porque Fénix no
    # necesita extraer sus prerrequisitos.
    #
    # Se reutiliza el parser de grupos para obtener:
    #
    #   - Grupos.
    #   - Profesores.
    #   - Cupos.
    #   - Horarios.
    #
    # Los datos básicos continúan procediendo de la tabla
    # de resultados del catálogo.
    #
    # El resultado se devuelve como diccionario porque esta
    # información tiene actualmente una estructura diferente
    # a la utilizada por el objeto Materia.

    # =========================================================
    # GRUPOS
    # =========================================================

    grupos = await extraer_grupos(
        detalle
    )

    # =========================================================
    # CONSTRUIR RESULTADO
    # =========================================================
    #
    # Los objetos Grupo y Horario se convierten aquí en
    # diccionarios para producir una estructura que pueda
    # almacenarse directamente en los datos de Libre Elección.

    return {
        "codigo": datos_basicos.get(
            "codigo",
            ""
        ),

        "nombre": datos_basicos.get(
            "nombre",
            ""
        ),

        "creditos": datos_basicos.get(
            "creditos",
            ""
        ),

        "tipologia": datos_basicos.get(
            "tipologia",
            ""
        ),

        "descripcion": datos_basicos.get(
            "descripcion",
            ""
        ),

        "grupos": [
            {
                "numero": grupo.numero,

                "nombre": grupo.nombre,

                "profesor": grupo.profesor,

                "fecha_inicio": grupo.fecha_inicio,

                "fecha_fin": grupo.fecha_fin,

                "duracion": grupo.duracion,

                "jornada": grupo.jornada,

                "cupos_disponibles": (
                    grupo.cupos_disponibles
                ),

                "virtual": bool(grupo.horarios) and all(
                    horario.virtual for horario in grupo.horarios
                ),

                "horarios": [
                    {
                        "dia": horario.dia,

                        "hora_inicio": (
                            horario.hora_inicio
                        ),

                        "hora_fin": horario.hora_fin,

                        "aula": horario.aula,

                        "sede": horario.sede,

                        "virtual": horario.virtual
                    }

                    for horario in grupo.horarios
                ]
            }

            for grupo in grupos
        ]
    }
