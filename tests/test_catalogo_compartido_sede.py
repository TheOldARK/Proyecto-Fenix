import unittest
from unittest.mock import AsyncMock, Mock, patch

from servicios.actualizacion import obtener_materias_libre_eleccion


class CatalogoCompartidoSedeTests(unittest.IsolatedAsyncioTestCase):
    async def test_reutiliza_sede_y_solo_extrae_la_tabla_de_facultad(self):
        catalogo = Mock()
        catalogo.seleccionar_facultad_libre_eleccion = AsyncMock()
        catalogo.mostrar_resultados = AsyncMock()
        sede = [{"codigo": "1001", "nombre": "Materia de sede"}]
        facultad = [{"codigo": "2002", "nombre": "Materia de facultad"}]

        with (
            patch("servicios.actualizacion.imprimir"),
            patch(
                "servicios.actualizacion.obtener_materias_de_tabla",
                new_callable=AsyncMock,
                return_value=facultad,
            ) as extraer_tabla,
        ):
            resultado = await obtener_materias_libre_eleccion(
                object(),
                catalogo,
                materias_sede_compartidas=sede,
                segunda_consulta_ya_mostrada=True,
            )

        catalogo.seleccionar_facultad_libre_eleccion.assert_not_awaited()
        catalogo.mostrar_resultados.assert_not_awaited()
        extraer_tabla.assert_awaited_once()
        self.assertEqual(
            [materia["codigo"] for materia in resultado],
            ["1001", "2002"],
        )
        self.assertEqual(
            [materia["_indice_facultad_libre_eleccion"] for materia in resultado],
            [0, 1],
        )


if __name__ == "__main__":
    unittest.main()
