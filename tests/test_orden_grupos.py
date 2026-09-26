import unittest

from aplicacion.interfaz import clave_orden_grupo


class OrdenGruposTests(unittest.TestCase):
    def test_ordena_grupos_por_numero_y_no_alfabeticamente(self):
        grupos = [
            {"numero": "1"},
            {"numero": "10"},
            {"numero": "11"},
            {"numero": "2"},
            {"numero": "3"},
        ]

        ordenados = sorted(grupos, key=clave_orden_grupo)

        self.assertEqual(
            [grupo["numero"] for grupo in ordenados],
            ["1", "2", "3", "10", "11"],
        )

    def test_conserva_orden_natural_para_grupos_con_sufijos(self):
        grupos = [{"numero": "1B"}, {"numero": "10"}, {"numero": "1A"}]

        ordenados = sorted(grupos, key=clave_orden_grupo)

        self.assertEqual([grupo["numero"] for grupo in ordenados], ["1A", "1B", "10"])


if __name__ == "__main__":
    unittest.main()
