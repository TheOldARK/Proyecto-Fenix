import unittest

from servicios.elegibilidad import (
    advertencias_materia,
    buscar_materias_no_disponibles,
    motivo_materia_no_mostrable,
)


class ElegibilidadPorTipoTests(unittest.TestCase):
    def materia(self, tipo):
        return {
            "codigo": "9999999",
            "nombre": "Avanzada",
            "prerrequisitos": [{
                "codigo": "1000007",
                "nombre": "Ecuaciones Diferenciales",
                "tipo": tipo,
            }],
        }

    def test_m_exige_aprobacion_aunque_el_requisito_este_en_el_horario(self):
        motivo = motivo_materia_no_mostrable(self.materia("M"), [], {"1000007"})
        self.assertIn("Falta aprobar", motivo)

    def test_o_deja_inscribir_y_avisa_que_no_se_puede_calificar(self):
        materia = self.materia("O")
        self.assertEqual(motivo_materia_no_mostrable(materia, []), "")
        self.assertIn("no podrás calificarla", advertencias_materia(materia, [])[0])

    def test_e_permite_aprobada_o_cursada_simultaneamente(self):
        materia = self.materia("E")
        self.assertEqual(motivo_materia_no_mostrable(materia, ["1000007"]), "")
        self.assertEqual(motivo_materia_no_mostrable(materia, [], {"1000007"}), "")
        self.assertIn("simultáneamente", motivo_materia_no_mostrable(materia, []))

    def test_a_solo_bloquea_si_se_eligen_ambas_y_falta_aprobar_la_llave(self):
        materia = self.materia("A")
        self.assertEqual(motivo_materia_no_mostrable(materia, []), "")
        self.assertIn("Incompatibilidad Tipo A", motivo_materia_no_mostrable(
            materia, [], {"1000007"}
        ))
        self.assertEqual(motivo_materia_no_mostrable(
            materia, ["1000007"], {"1000007"}
        ), "")

    def test_y_requiere_aprobacion_o_seleccion_conjunta_y_es_provisional(self):
        materia = self.materia("Y")
        self.assertIn("simultáneamente", motivo_materia_no_mostrable(materia, []))
        self.assertIn("mismo semestre", advertencias_materia(materia, [])[0])
        self.assertEqual(motivo_materia_no_mostrable(materia, [], {"1000007"}), "")
        self.assertEqual(motivo_materia_no_mostrable(materia, ["1000007"]), "")

    def test_tipo_desconocido_conserva_el_bloqueo_seguro(self):
        motivo = motivo_materia_no_mostrable(self.materia("Z"), [])
        self.assertIn("Falta aprobar", motivo)


class BusquedaNoDisponiblesTests(unittest.TestCase):
    def setUp(self):
        self.oferta = {
            "principal": [
                {"codigo": "1000001", "nombre": "Cátedra TI"},
                {
                    "codigo": "1000002",
                    "nombre": "Análisis Numérico",
                    "prerrequisitos": [{
                        "codigo": "1000003",
                        "nombre": "Ecuaciones Diferenciales",
                        "tipo": "M",
                    }],
                },
                {"codigo": "1000004", "nombre": "Otra Disponible"},
            ],
            "libre": [],
        }

    def test_busqueda_incluye_aprobadas_y_explica_la_razon(self):
        resultados = buscar_materias_no_disponibles(
            self.oferta, "catedra ti", {"1000001"}
        )
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["materia"]["codigo"], "1000001")
        self.assertIn("aprobada", resultados[0]["motivo"])

    def test_busqueda_incluye_requisitos_pendientes_sin_distinguir_tildes(self):
        resultados = buscar_materias_no_disponibles(
            self.oferta, "analisis numerico", set()
        )
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["materia"]["codigo"], "1000002")
        self.assertIn("Falta aprobar", resultados[0]["motivo"])

    def test_omite_disponibles_y_materias_ya_seleccionadas(self):
        self.assertEqual(buscar_materias_no_disponibles(
            self.oferta, "otra disponible", set()
        ), [])
        self.assertEqual(buscar_materias_no_disponibles(
            self.oferta, "catedra ti", set(), {"1000001"}
        ), [])

    def test_busca_aprobada_adicional_que_no_esta_en_la_oferta(self):
        adicionales = [{
            "origen": "principal",
            "materia": {"codigo": "1000005", "nombre": "Cátedra TI Antiguo"},
        }]
        resultados = buscar_materias_no_disponibles(
            self.oferta, "catedra ti antiguo", {"1000005"},
            materias_adicionales=adicionales,
        )
        self.assertEqual(len(resultados), 1)
        self.assertIn("aprobada", resultados[0]["motivo"])

if __name__ == "__main__":
    unittest.main()
