# =============================================================
# ESTADO DE LA APLICACIÓN
# =============================================================
#
# Este módulo contiene la clase que almacena el estado actual
# de Fénix.
#
# El estado contiene información que puede cambiar mientras
# la aplicación está funcionando, como:
#
#   - El estudiante actual.
#   - Las materias disponibles.
#   - La oferta académica.
#   - Las materias elegibles.
#   - Los horarios generados.
#   - El horario seleccionado.
#
# Este módulo solamente almacena información.
# Las reglas para modificar o utilizar estos datos pertenecen
# a los servicios y componentes correspondientes.


class EstadoAplicacion:

    def __init__(self):
        # -----------------------------------------------------
        # ESTUDIANTE
        # -----------------------------------------------------
        #
        # Aquí se almacenará la información del estudiante que
        # está utilizando Fénix.
        #
        # Inicialmente no existe ningún estudiante cargado.

        self.estudiante = None

        # -----------------------------------------------------
        # MATERIAS Y OFERTA ACADÉMICA
        # -----------------------------------------------------
        #
        # "materias" contiene las materias conocidas por Fénix.
        #
        # "oferta" contiene la información de los grupos que
        # actualmente se encuentran disponibles.

        self.materias = []
        self.oferta = {}

        # -----------------------------------------------------
        # MATERIAS ELEGIBLES
        # -----------------------------------------------------
        #
        # Aquí se almacenarán las materias que el estudiante
        # puede cursar según su situación académica.
        #
        # Por ejemplo, una materia puede no ser elegible porque
        # todavía no se han aprobado sus prerrequisitos.

        self.materias_elegibles = []

        # -----------------------------------------------------
        # HORARIOS GENERADOS
        # -----------------------------------------------------
        #
        # Aquí se almacenarán las diferentes combinaciones de
        # grupos que Fénix encuentre sin conflictos de horario.

        self.horarios_generados = []

        # -----------------------------------------------------
        # HORARIO SELECCIONADO
        # -----------------------------------------------------
        #
        # Cuando el estudiante elija uno de los horarios
        # generados, se almacenará aquí.
        #
        # Mientras no haya seleccionado ninguno, el valor será
        # None.

        self.horario_seleccionado = None