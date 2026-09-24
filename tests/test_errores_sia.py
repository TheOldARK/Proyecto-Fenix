import unittest

from infraestructura.sia.errores import (
    MateriaNoDisponibleEnSIA,
    es_error_transitorio_sia,
)


class ClasificacionErroresSIATest(unittest.TestCase):
    def test_materia_sin_enlace_no_es_transitoria(self):
        error = MateriaNoDisponibleEnSIA(
            "No se encontró el enlace de la materia 300123."
        )
        self.assertFalse(es_error_transitorio_sia(error))

    def test_pagina_error_sia_marca_sesion_invalidada(self):
        error = MateriaNoDisponibleEnSIA(
            "El SIA rechazó el detalle.", sesion_invalidada=True
        )
        self.assertFalse(es_error_transitorio_sia(error))
        self.assertTrue(error.sesion_invalidada)

    def test_timeout_de_navegacion_es_transitorio(self):
        self.assertTrue(
            es_error_transitorio_sia(
                TimeoutError("Timeout 15000ms exceeded")
            )
        )

    def test_error_de_datos_no_se_reintenta(self):
        self.assertFalse(
            es_error_transitorio_sia(
                RuntimeError("El código obtenido no coincide")
            )
        )


if __name__ == "__main__":
    unittest.main()
