import unittest

from aplicacion.interfaz import VentanaPrincipal


class ClasificacionCreditosTests(unittest.TestCase):
    def test_reconoce_abreviatura_sia_de_fundamentacion(self):
        materia = {
            "nombre": "Cálculo Integral",
            "tipologia": "FUND. OBLIGATORIA",
        }

        self.assertEqual(
            VentanaPrincipal.tipo_credito_oficial(materia),
            "Fundamentacion Obligatoria",
        )

    def test_reconoce_fundamentacion_optativa_abreviada(self):
        materia = {
            "nombre": "Curso electivo",
            "tipologia": "FUND. OPTATIVA",
        }

        self.assertEqual(
            VentanaPrincipal.tipo_credito_oficial(materia),
            "Fundamentacion Optativa",
        )

    def test_mapea_tipologia_del_resumen_sia_y_sus_creditos_pendientes(self):
        self.assertEqual(
            VentanaPrincipal._tipo_credito_resumen_sia("FUND. OBLIGATORIA"),
            "Fundamentacion Obligatoria",
        )
        self.assertEqual(
            VentanaPrincipal._tipo_credito_resumen_sia("Libre Elección"),
            "Libre Eleccion",
        )
        self.assertEqual(
            VentanaPrincipal._numero_creditos_resumen_sia("11,5"),
            11.5,
        )
        self.assertIsNone(
            VentanaPrincipal._tipo_credito_resumen_sia("Categoría desconocida")
        )

if __name__ == "__main__":
    unittest.main()
