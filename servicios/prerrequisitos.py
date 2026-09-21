# =============================================================
# INTERPRETACIÓN DE PRERREQUISITOS
# =============================================================
#
# Este módulo contiene las reglas utilizadas para interpretar
# los códigos de tipo de prerrequisito proporcionados por el SIA.
#
# El parser ubicado en:
#
#   infraestructura/sia/parser/prerrequisitos.py
#
# se encarga únicamente de encontrar los prerrequisitos dentro
# del HTML y construir los objetos correspondientes.
#
# Este módulo pertenece a la capa de servicios porque aquí
# comienza la interpretación del significado académico de esos
# códigos.
#
# Por ejemplo:
#
#   Código del SIA → Significado utilizado por Fénix
#
#       M        → OBLIGATORIO
#       O        → CALIFICACION
#       E        → SIMULTANEO
#       A        → INCOMPATIBILIDAD
#
# Mantener esta interpretación separada del parser permite que
# el parser siga siendo independiente de las reglas académicas.
#
# Si en el futuro cambia la forma en que Fénix debe interpretar
# alguno de estos tipos, solamente será necesario modificar esta
# capa.
#

# =============================================================
# TIPOS DE PRERREQUISITO
# =============================================================

# Relación entre los códigos utilizados por el SIA y los nombres
# internos utilizados por Fénix.

TIPOS_PRERREQUISITO = {
    "M": "OBLIGATORIO",
    "O": "CALIFICACION",
    "E": "SIMULTANEO",
    "A": "INCOMPATIBILIDAD"
}


# =============================================================
# INTERPRETAR TIPO
# =============================================================

def interpretar_tipo(
    tipo: str | None
) -> str:
    # Convierte un código de prerrequisito del SIA en el nombre
    # utilizado internamente por Fénix.
    #
    # strip() elimina espacios accidentales alrededor del código.
    #
    # upper() permite aceptar códigos escritos en minúscula,
    # aunque normalmente el SIA los entregue en mayúscula.
    #
    # Si aparece un código que Fénix todavía no conoce, se
    # devuelve "DESCONOCIDO" en lugar de producir un error.
    # Esto permite que la actualización continúe aunque el SIA
    # incorpore algún tipo nuevo.

    if not isinstance(tipo, str):
        return "DESCONOCIDO"

    tipo = tipo.strip().upper()

    return TIPOS_PRERREQUISITO.get(
        tipo,
        "DESCONOCIDO"
    )
