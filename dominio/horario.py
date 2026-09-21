# =============================================================
# HORARIO DE UNA ASIGNATURA
# =============================================================
#
# Este módulo define la clase Horario.
#
# Un horario representa una sesión concreta de una asignatura.
# Contiene el día, la hora de inicio, la hora de finalización,
# el aula y la sede donde se realiza.
#
# Un Grupo puede tener uno o varios objetos Horario.
#
# Por ejemplo, un grupo podría tener:
#
#   Lunes      → 08:00 - 10:00 → Aula 301 → Medellín
#   Miércoles  → 08:00 - 10:00 → Aula 301 → Medellín
#
# Cada una de esas sesiones se representa mediante un objeto
# Horario independiente.


import re
from dataclasses import dataclass


AULA_PRESENCIAL_RE = re.compile(
    r"^(?:M\d{1,2}|\d{1,3})-\d{3,4}[A-Z]?$",
    re.IGNORECASE,
)


def es_aula_presencial_valida(aula):
    """Valida los formatos presenciales reconocidos de Minas y Volador."""
    return bool(AULA_PRESENCIAL_RE.fullmatch(str(aula or "").strip()))


def es_sesion_virtual(sesion):
    """Determina virtualidad usando la marca guardada o el formato del aula."""
    if not isinstance(sesion, dict):
        return False
    if "virtual" in sesion:
        return bool(sesion.get("virtual"))
    return not es_aula_presencial_valida(sesion.get("aula", ""))


# =============================================================
# MODELO DE DATOS
# =============================================================


@dataclass
class Horario:

    # Día de la semana en el que se realiza la sesión.
    dia: str = ""

    # Hora en la que comienza la sesión.
    hora_inicio: str = ""

    # Hora en la que termina la sesión.
    hora_fin: str = ""

    # Aula donde se realiza la sesión.
    aula: str = ""

    # Sede de la universidad donde se encuentra el aula.
    sede: str = ""

    # True cuando el aula no tiene un formato presencial reconocido.
    virtual: bool = False
