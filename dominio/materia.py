# =============================================================
# MATERIA Y PRERREQUISITO
# =============================================================
#
# Este módulo define dos modelos del dominio académico de Fénix:
#
#   - Prerrequisito: representa una condición asociada a una
#     asignatura que debe tenerse en cuenta para determinar
#     si puede ser cursada.
#
#   - Materia: representa una asignatura y contiene tanto su
#     información académica como sus prerrequisitos y grupos.
#
# Estos objetos representan datos del dominio.
# Las reglas para interpretar los prerrequisitos, determinar
# la elegibilidad o generar horarios pertenecen a la capa
# de servicios.


from dataclasses import dataclass, field

from dominio.grupo import Grupo


# =============================================================
# PRERREQUISITO
# =============================================================


@dataclass
class Prerrequisito:

    # Código de la asignatura o requisito relacionado.
    codigo: str = ""

    # Nombre de la asignatura o requisito.
    nombre: str = ""

    # Tipo de prerrequisito informado por el SIA.
    #
    # El significado concreto de este campo será interpretado
    # posteriormente por los servicios de Fénix.
    tipo: str = ""

    # Condición asociada al prerrequisito.
    #
    # Este valor se conserva tal como es obtenido de los datos
    # para que la lógica correspondiente pueda interpretarlo.
    condicion: str = ""

    # Información adicional relacionada con la condición
    # de los prerrequisitos.
    todas: str = ""

    # Número de asignaturas exigidas dentro de la condición del SIA, cuando
    # la página lo informa. Se conserva para que cada consumidor interprete
    # correctamente condiciones compuestas.
    numero_asignaturas: str = ""


# =============================================================
# MATERIA
# =============================================================


@dataclass
class Materia:

    # Código oficial de la asignatura.
    codigo: str = ""

    # Nombre de la asignatura.
    nombre: str = ""

    # Cantidad de créditos académicos.
    #
    # Actualmente se conserva como texto porque este valor
    # proviene directamente de los datos obtenidos del SIA.
    creditos: str = ""

    # Tipología de la asignatura.
    #
    # Puede indicar categorías como fundamentación,
    # disciplinar, libre elección, etc.
    tipologia: str = ""

    # Descripción proporcionada para la asignatura.
    descripcion: str = ""

    # Lista de prerrequisitos asociados a la materia.
    #
    # Se utiliza default_factory para crear una lista nueva
    # para cada objeto Materia.
    #
    # De esta manera, los prerrequisitos de una materia no
    # quedan compartidos accidentalmente con los de otra.
    prerrequisitos: list[Prerrequisito] = field(
        default_factory=list
    )

    # Lista de grupos disponibles para la materia.
    #
    # Cada grupo contiene información como el profesor,
    # los cupos y sus respectivos horarios.
    #
    # Al igual que con los prerrequisitos, default_factory
    # garantiza que cada materia tenga su propia lista.
    grupos: list[Grupo] = field(
        default_factory=list
    )
