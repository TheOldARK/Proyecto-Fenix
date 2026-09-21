# =============================================================
# GRUPO DE UNA ASIGNATURA
# =============================================================
#
# Este módulo define la clase Grupo.
#
# Una asignatura puede tener varios grupos disponibles.
# Cada grupo representa una oferta concreta de esa asignatura
# y puede tener un profesor, unos cupos y uno o varios horarios.
#
# Por ejemplo, una misma materia podría tener:
#
#   Grupo 1 → Profesor A → Lunes y miércoles → 8:00-10:00
#   Grupo 2 → Profesor B → Martes y jueves → 14:00-16:00
#
# La clase Grupo permite representar cada una de esas opciones.


from dataclasses import dataclass, field

from dominio.horario import Horario


# =============================================================
# MODELO DE DATOS
# =============================================================


@dataclass
class Grupo:

    # Número que identifica al grupo dentro de la asignatura.
    numero: str = ""

    # Nombre del grupo, cuando el SIA proporciona esta información.
    nombre: str = ""

    # Profesor encargado del grupo.
    profesor: str = ""

    # Fechas en las que comienza y termina el grupo.
    fecha_inicio: str = ""
    fecha_fin: str = ""

    # Duración y jornada reportadas por el SIA.
    duracion: str = ""
    jornada: str = ""

    # Cantidad de cupos disponibles.
    #
    # Puede ser None cuando no se dispone de esta información.
    cupos_disponibles: int | None = None

    # Lista de horarios correspondientes al grupo.
    #
    # Un grupo puede tener más de un horario. Por ejemplo,
    # puede reunirse los lunes y miércoles a diferentes horas.
    #
    # default_factory=list crea una lista independiente para
    # cada objeto Grupo. Esto evita que todos los grupos
    # compartan accidentalmente la misma lista.
    horarios: list[Horario] = field(
        default_factory=list
    )
