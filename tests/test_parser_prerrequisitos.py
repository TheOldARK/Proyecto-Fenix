import unittest

from infraestructura.sia.parser.prerrequisitos import (
    _extraer_prerrequisitos_desde_html,
)
from servicios.prerrequisitos import interpretar_tipo


class ParserPrerrequisitosTests(unittest.TestCase):
    def test_conserva_tipo_y_condicion_de_cada_grupo_del_sia(self):
        html = """
        <table>
          <tr><th>Prerrequisitos</th></tr>
          <tr><td>Condición 1 Tipo M ¿Todas? [S] Número asignaturas []</td></tr>
          <tr><td>1000005-M CÁLCULO INTEGRAL</td></tr>
          <tr><td>Condición 2 Tipo Y ¿Todas? [S] Número asignaturas []</td></tr>
          <tr><td>1000007-M ECUACIONES DIFERENCIALES</td></tr>
        </table>
        """

        requisitos = _extraer_prerrequisitos_desde_html(html)

        self.assertEqual(
            [(r.codigo, r.tipo, r.condicion) for r in requisitos],
            [("1000005-M", "M", "1"), ("1000007-M", "Y", "2")],
        )
        self.assertEqual(requisitos[1].nombre, "ECUACIONES DIFERENCIALES")
        self.assertEqual(requisitos[1].todas, "S")

    def test_fallback_sin_filas_tambien_conserva_tipo_y(self):
        html = """
        <div>Prerrequisitos
          <p>Condición 1 Tipo Y ¿Todas? [S] Número asignaturas []</p>
          <p>1000007-M ECUACIONES DIFERENCIALES</p>
        </div>
        """

        requisitos = _extraer_prerrequisitos_desde_html(html)

        self.assertEqual(len(requisitos), 1)
        self.assertEqual(requisitos[0].tipo, "Y")
        self.assertEqual(requisitos[0].condicion, "1")

    def test_tipo_y_tiene_interpretacion_provisional_separada_de_e(self):
        self.assertEqual(interpretar_tipo("Y"), "SIMULTANEO_Y")
        self.assertEqual(interpretar_tipo("E"), "SIMULTANEO")

    def test_parser_conserva_todos_los_tipos_conocidos_del_sia(self):
        filas = []
        for numero, tipo in enumerate(("M", "O", "E", "A", "Y"), start=1):
            filas.extend([
                f"<tr><td>Condición {numero} Tipo {tipo} ¿Todas? [S] Número asignaturas []</td></tr>",
                f"<tr><td>100000{numero}-M MATERIA {tipo}</td></tr>",
            ])
        html = "<table><tr><th>Prerrequisitos</th></tr>" + "".join(filas) + "</table>"

        requisitos = _extraer_prerrequisitos_desde_html(html)

        self.assertEqual([r.tipo for r in requisitos], ["M", "O", "E", "A", "Y"])
        self.assertEqual(
            [interpretar_tipo(r.tipo) for r in requisitos],
            ["OBLIGATORIO", "CALIFICACION", "SIMULTANEO", "INCOMPATIBILIDAD", "SIMULTANEO_Y"],
        )


if __name__ == "__main__":
    unittest.main()
