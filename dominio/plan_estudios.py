# =============================================================
# PLAN DE ESTUDIOS
# =============================================================
#
# Este módulo define los modelos utilizados para representar
# un plan de estudios académico.
#
# Un PlanEstudios está compuesto por varios Semestre.
# Cada semestre contiene las asignaturas que pertenecen
# directamente al plan y los créditos correspondientes a
# categorías que el estudiante debe completar.
#
# Por ejemplo, un semestre puede contener:
#
#   - Varias asignaturas obligatorias.
#   - Créditos de libre elección.
#   - Créditos de optativa disciplinar.
#   - Créditos de fundamentación optativa.
#
# Las asignaturas se almacenan mediante sus códigos.
# La información completa de cada asignatura se encuentra
# en los modelos de Materia y en los datos correspondientes.


from dataclasses import dataclass, field


# =============================================================
# SEMESTRE
# =============================================================


@dataclass
class Semestre:

    # Número del semestre dentro del plan de estudios.
    numero: int

    # Códigos de las asignaturas que pertenecen directamente
    # a este semestre.
    #
    # Se almacenan códigos y no objetos Materia porque el plan
    # de estudios solamente necesita indicar qué asignaturas
    # pertenecen al plan.
    asignaturas: list[str] = field(
        default_factory=list
    )

    # Cantidad de créditos que el estudiante debe completar
    # en diferentes categorías durante este semestre.
    #
    # Las claves indican la categoría y los valores indican
    # la cantidad de créditos.
    #
    # Por ejemplo:
    #
    # {
    #     "libre_eleccion": 6,
    #     "optativa_disciplinar": 3
    # }
    creditos: dict[str, int] = field(
        default_factory=dict
    )


# =============================================================
# PLAN DE ESTUDIOS
# =============================================================


@dataclass
class PlanEstudios:

    # Código que identifica el plan de estudios.
    codigo: str

    # Nombre del programa académico asociado al plan.
    nombre: str

    # Ubicación académica que diferencia planes con el mismo código.
    sede_codigo: str = ""
    sede_nombre: str = ""
    facultad_codigo: str = ""
    facultad_nombre: str = ""

    # Valores internos de los <select> del catálogo SIA.
    valor_sede: str = ""
    valor_facultad: str = ""
    valor_plan: str = ""

    # Lista de semestres que componen el plan de estudios.
    #
    # Cada elemento de la lista es un objeto Semestre.
    #
    # default_factory crea una lista independiente para cada
    # objeto PlanEstudios.
    semestres: list[Semestre] = field(
        default_factory=list
    )

    # Nombres de las asignaturas propias del plan, indexados por código.
    # Permiten identificar una materia antes de que la oferta del SIA haya
    # terminado de descargarse por primera vez.
    nombres_asignaturas: dict[str, str] = field(
        default_factory=dict
    )
