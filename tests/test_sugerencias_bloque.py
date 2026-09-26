import unittest

from aplicacion.interfaz import grupos_en_conflicto_en_bloque


class SugerenciasBloqueTests(unittest.TestCase):
    def test_separa_grupos_que_cruzan_el_horario_actual_en_la_franja(self):
        actuales = [
            (
                {"codigo": "100", "nombre": "Materia actual"},
                {"numero": "1", "horarios": [
                    {"dia": "LUNES", "hora_inicio": "08:00", "hora_fin": "10:00"}
                ]},
            )
        ]
        materias = [
            {"codigo": "200", "nombre": "Cruza", "grupos": [
                {"numero": "1", "horarios": [
                    {"dia": "LUNES", "hora_inicio": "09:00", "hora_fin": "11:00"}
                ]}
            ]},
            {"codigo": "300", "nombre": "Adyacente", "grupos": [
                {"numero": "1", "horarios": [
                    {"dia": "LUNES", "hora_inicio": "10:00", "hora_fin": "12:00"}
                ]}
            ]},
            {"codigo": "400", "nombre": "Otro día", "grupos": [
                {"numero": "1", "horarios": [
                    {"dia": "MARTES", "hora_inicio": "09:00", "hora_fin": "11:00"}
                ]}
            ]},
        ]

        resultado = grupos_en_conflicto_en_bloque(
            materias, actuales, "LUNES", 8, 2
        )

        self.assertEqual(
            [(materia["codigo"], grupo["numero"]) for materia, grupo in resultado],
            [("200", "1")],
        )


if __name__ == "__main__":
    unittest.main()
