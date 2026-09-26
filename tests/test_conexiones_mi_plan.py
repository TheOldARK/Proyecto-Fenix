import unittest

from aplicacion.interfaz import conexiones_entre_semestres_adyacentes


class ConexionesMiPlanTests(unittest.TestCase):
    def test_conecta_solo_con_el_semestre_inmediatamente_anterior(self):
        materias = {
            1: [{"codigo": "1"}, {"codigo": "2"}],
            2: [
                {"codigo": "3", "prerrequisitos": [{"codigo": "1", "tipo": "M"}]},
                {"codigo": "4", "prerrequisitos": [{"codigo": "2", "tipo": "Y"}]},
            ],
            3: [
                # El requisito del semestre 1 queda a dos semestres de distancia.
                {"codigo": "5", "prerrequisitos": [{"codigo": "1", "tipo": "M"}]},
                # El requisito del semestre 2 sí es inmediatamente anterior.
                {"codigo": "6", "prerrequisitos": [{"codigo": "3", "tipo": "O"}]},
                # Las conexiones dentro del mismo semestre no se dibujan.
                {"codigo": "7", "prerrequisitos": [{"codigo": "6", "tipo": "Y"}]},
            ],
        }
        tarjetas = {codigo: object() for codigo in "1234567"}

        conexiones = conexiones_entre_semestres_adyacentes(materias, tarjetas, 3)

        self.assertEqual(
            [(materias_destino, tipo) for _, materias_destino, tipo in conexiones],
            [(tarjetas["3"], "M"), (tarjetas["4"], "Y"), (tarjetas["6"], "O")],
        )
        self.assertEqual(
            {(origen, destino) for origen, destino, _ in conexiones},
            {
                (tarjetas["1"], tarjetas["3"]),
                (tarjetas["2"], tarjetas["4"]),
                (tarjetas["3"], tarjetas["6"]),
            },
        )


if __name__ == "__main__":
    unittest.main()
