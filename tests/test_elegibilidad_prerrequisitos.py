import unittest

from servicios.elegibilidad import (
    advertencias_materia,
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


if __name__ == "__main__":
    unittest.main()
