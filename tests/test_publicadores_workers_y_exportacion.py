import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import main
from servicios import actualizacion


class ExportacionCatalogoSedeTests(unittest.TestCase):
    def test_el_gestor_recibe_catalogo_nuevo_aunque_el_worker_restaure_su_copia(self):
        codigo_plan = "1102:3068:3534"
        plan = SimpleNamespace(
            nombre="Ingeniería de Sistemas e Informática",
            facultad_nombre="Facultad de Minas",
        )
        catalogo_anterior = {
            "sede": "1102",
            "materias": [{"codigo": "anterior", "nombre": "Anterior"}],
        }
        catalogo_nuevo = {
            "sede": "1102",
            "materias": [{"codigo": "nuevo", "nombre": "Nuevo"}],
        }

        with tempfile.TemporaryDirectory(prefix="fenix-export-sede-") as carpeta:
            raiz = Path(carpeta)
            archivo_estudiante = raiz / "estudiante.json"
            archivo_compartido = raiz / "libres_eleccion_sede.json"
            salida_gestor = raiz / "resultado_libres_eleccion_sede.json"
            archivo_compartido.write_text(
                json.dumps(catalogo_anterior), encoding="utf-8"
            )
            bytes_anteriores = archivo_compartido.read_bytes()

            with (
                patch.dict(
                    "os.environ",
                    {"FENIX_PUBLICADOR_LIBRES_SEDE_SALIDA": str(salida_gestor)},
                ),
                patch.object(main, "ARCHIVO_ESTUDIANTE", archivo_estudiante),
                patch.object(
                    main, "ARCHIVO_LIBRES_ELECCION_SEDE", archivo_compartido
                ),
                patch.object(main, "cargar_estudiante", return_value={}),
                patch.object(main, "guardar_estudiante"),
                patch.object(
                    main,
                    "seleccionar_planes_publicables",
                    return_value=({codigo_plan: plan}, []),
                ),
                patch.object(
                    main,
                    "seleccionar_planes_referencia_libres",
                    return_value={codigo_plan: plan},
                ),
                patch.object(
                    main.asyncio,
                    "run",
                    side_effect=lambda corutina: _simular_salida_actualizacion(
                        corutina, archivo_compartido, catalogo_nuevo
                    ),
                ),
                patch.object(main, "actualizar", return_value=object()),
                patch.object(main, "publicar_libres_eleccion_sede"),
                patch.object(main, "guardar_estado"),
            ):
                main.ejecutar_publicador_libres_sede(codigo_plan)

            self.assertEqual(
                json.loads(salida_gestor.read_text(encoding="utf-8")),
                catalogo_nuevo,
            )
            self.assertEqual(archivo_compartido.read_bytes(), bytes_anteriores)


class CantidadWorkersPublicadoresTests(unittest.TestCase):
    def test_fase_obligatorias_divide_el_trabajo_entre_dos_workers(self):
        materias = [{"codigo": "1001"}, {"codigo": "1002"}]
        dividir = Mock(return_value=[[materias[0]], [materias[1]]])
        with patch("servicios.actualizacion.dividir_materias", dividir):
            cantidad = max(1, int(2 or actualizacion.CANTIDAD_WORKERS))
            grupos = actualizacion.dividir_materias(materias, cantidad)
        dividir.assert_called_once_with(materias, 2)
        self.assertEqual(len(grupos), 2)


class CacheCatalogoSedeTests(unittest.TestCase):
    def test_indiza_la_lista_del_catalogo_compartido_por_codigo(self):
        compartidas = [
            {"codigo": "3001", "nombre": "Libre compartida"},
            {"codigo": "3002", "nombre": "Otra libre"},
        ]

        cache = actualizacion._combinar_cache_libres({}, compartidas)

        self.assertEqual(set(cache), {"3001", "3002"})
        self.assertEqual(cache["3001"]["nombre"], "Libre compartida")

    def test_la_cache_detallada_del_plan_tiene_prioridad(self):
        compartida = {"codigo": "3001", "nombre": "Nombre compartido"}
        detallada = {"codigo": "3001", "nombre": "Nombre del plan", "grupos": []}

        cache = actualizacion._combinar_cache_libres(
            {"3001": detallada}, [compartida]
        )

        self.assertIs(cache["3001"], detallada)

    def test_fase_libres_divide_el_trabajo_entre_dos_workers(self):
        dividir = Mock(return_value=[[{"codigo": "1001"}], [{"codigo": "1002"}]])
        with patch("servicios.actualizacion.dividir_materias", dividir):
            cantidad = max(1, int(2 or actualizacion.CANTIDAD_WORKERS))
            grupos = actualizacion.dividir_materias(
                [{"codigo": "1001"}, {"codigo": "1002"}], cantidad
            )
        dividir.assert_called_once_with(
            [{"codigo": "1001"}, {"codigo": "1002"}], 2
        )
        self.assertEqual(len(grupos), 2)


def _simular_salida_actualizacion(corutina, archivo_compartido, catalogo_nuevo):
    corutina.close()
    archivo_compartido.write_text(json.dumps(catalogo_nuevo), encoding="utf-8")
    return {
        "catalogo_libres_consultado": True,
        "libres_eleccion": catalogo_nuevo["materias"],
    }


if __name__ == "__main__":
    unittest.main()
