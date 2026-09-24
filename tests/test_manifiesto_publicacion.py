import unittest
import json
import tempfile
from pathlib import Path

from herramientas.publicar_datos_cloudflare import (
    fusionar_manifiesto_publicacion,
    publicar_planes,
)
from main import seleccionar_planes_referencia_libres
from infraestructura.almacenamiento.materias_libre_eleccion import (
    sincronizar_libres_eleccion_sede,
)


class ManifiestoPublicacionTests(unittest.TestCase):
    def test_publicadores_independientes_conservan_los_planes_del_otro(self):
        ciencias = {
            "sedes": {
                "1102": {
                    "codigo": "1102",
                    "nombre": "Medellín",
                    "facultades": {
                        "3065": {
                            "codigo": "3065",
                            "nombre": "Ciencias",
                            "planes": ["1102:3065:3505"],
                        }
                    },
                }
            },
            "planes": {"1102:3065:3505": {"origen": "biológica"}},
        }
        minas_nueva = {
            "1102": {
                "codigo": "1102",
                "nombre": "Medellín",
                "facultades": {
                    "3068": {
                        "codigo": "3068",
                        "nombre": "Minas",
                        "planes": ["1102:3068:3534"],
                    }
                },
            }
        }

        resultado = fusionar_manifiesto_publicacion(
            ciencias,
            minas_nueva,
            {"1102:3068:3534": {"origen": "sistemas"}},
        )

        self.assertEqual(
            set(resultado["planes"]),
            {"1102:3065:3505", "1102:3068:3534"},
        )
        self.assertEqual(
            resultado["sedes"]["1102"]["facultades"]["3065"]["planes"],
            ["1102:3065:3505"],
        )
        self.assertEqual(
            resultado["sedes"]["1102"]["facultades"]["3068"]["planes"],
            ["1102:3068:3534"],
        )

    def test_republicar_un_plan_actualiza_sin_duplicar_su_indice(self):
        anterior = {
            "sedes": {
                "1102": {
                    "facultades": {
                        "3068": {"planes": ["1102:3068:3534"]}
                    }
                }
            },
            "planes": {"1102:3068:3534": {"version": 1}},
        }
        nueva_sede = {
            "1102": {
                "facultades": {
                    "3068": {"planes": ["1102:3068:3534"]}
                }
            }
        }

        resultado = fusionar_manifiesto_publicacion(
            anterior,
            nueva_sede,
            {"1102:3068:3534": {"version": 2}},
        )

        self.assertEqual(resultado["planes"]["1102:3068:3534"]["version"], 2)
        self.assertEqual(
            resultado["sedes"]["1102"]["facultades"]["3068"]["planes"],
            ["1102:3068:3534"],
        )
        self.assertEqual(anterior["planes"]["1102:3068:3534"]["version"], 1)

    def test_publicacion_parcial_conserva_la_otra_fase_del_plan(self):
        anterior = {
            "sedes": {},
            "planes": {
                "1102:3068:3534": {
                    "archivos": {
                        "materias": {"ruta": "vieja/materias.json"},
                        "oferta": {"ruta": "vieja/oferta.json"},
                    },
                    "plan": {"nombre": "Ingeniería de Sistemas"},
                }
            },
        }
        resultado = fusionar_manifiesto_publicacion(
            anterior,
            {},
            {
                "1102:3068:3534": {
                    "archivos": {
                        "libres_eleccion": {"ruta": "nueva/libres.json"}
                    }
                }
            },
        )
        archivos = resultado["planes"]["1102:3068:3534"]["archivos"]
        self.assertEqual(set(archivos), {"materias", "oferta", "libres_eleccion"})
        self.assertEqual(archivos["materias"]["ruta"], "vieja/materias.json")
        self.assertEqual(archivos["libres_eleccion"]["ruta"], "nueva/libres.json")
        self.assertEqual(
            resultado["planes"]["1102:3068:3534"]["plan"]["nombre"],
            "Ingeniería de Sistemas",
        )

    def test_el_manifiesto_conserva_el_catalogo_compartido_de_sede(self):
        anterior = {
            "sedes": {"1102": {"nombre": "Medellín"}},
            "planes": {},
            "datos_compartidos": {
                "libres_eleccion_sede": {"ruta": "anterior/libres.json"},
                "otro": {"ruta": "otro.json"},
            },
        }
        resultado = fusionar_manifiesto_publicacion(
            anterior,
            {},
            {},
            datos_compartidos_nuevos={
                "libres_eleccion_sede": {"ruta": "nuevo/libres.json"}
            },
        )
        self.assertEqual(
            resultado["datos_compartidos"]["libres_eleccion_sede"]["ruta"],
            "nuevo/libres.json",
        )
        self.assertIn("otro", resultado["datos_compartidos"])

    def test_publicar_planes_acepta_archivos_por_fase(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta)
            (ruta / "materias.json").write_text(json.dumps({"materias": []}), encoding="utf-8")
            (ruta / "oferta.json").write_text(json.dumps({"materias": []}), encoding="utf-8")
            manifiesto = publicar_planes(
                {"1102:3068:3534": ruta},
                simulacion=True,
                metadatos_planes={
                    "1102:3068:3534": {
                        "sede_codigo": "1102",
                        "facultad_codigo": "3068",
                        "nombre": "Ingeniería de Sistemas",
                    }
                },
            )
        self.assertEqual(
            set(manifiesto["planes"]["1102:3068:3534"]["archivos"]),
            {"materias", "oferta"},
        )

    def test_publicador_gestor_sincroniza_catalogo_de_sede_atomico(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            origen = raiz / "hijo" / "libres_eleccion_sede.json"
            destino = raiz / "datos" / "libres_eleccion_sede.json"
            origen.parent.mkdir()
            origen.write_text(
                json.dumps({
                    "sede": "1102",
                    "ultima_actualizacion": "2026-09-24T12:00:00",
                    "materias": [{"codigo": "1001", "nombre": "Materia de sede"}],
                }),
                encoding="utf-8",
            )

            cantidad = sincronizar_libres_eleccion_sede(origen, destino)

            self.assertEqual(cantidad, 1)
            self.assertEqual(json.loads(destino.read_text(encoding="utf-8"))["materias"][0]["codigo"], "1001")

    def test_no_sincroniza_catalogo_de_otra_sede_ni_datos_malformados(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            origen = raiz / "origen.json"
            destino = raiz / "destino.json"
            origen.write_text(
                json.dumps({"sede": "1101", "materias": []}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Medellín"):
                sincronizar_libres_eleccion_sede(origen, destino)
            self.assertFalse(destino.exists())

            origen.write_text(
                json.dumps({"sede": "1102", "materias": [{"nombre": "Sin código"}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "sin código"):
                sincronizar_libres_eleccion_sede(origen, destino)
            self.assertFalse(destino.exists())

    def test_carrera_de_referencia_debe_empezar_por_el_filtro_de_sede(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        planes = {
            "1102:3068:3534": SimpleNamespace(
                sede_codigo="1102", facultad_codigo="3068", codigo="3534"
            ),
            "1102:3068:3528": SimpleNamespace(
                sede_codigo="1102", facultad_codigo="3068", codigo="3528"
            ),
        }
        configuracion = {
            "1102": {
                "sede": "3 SEDE MEDELLÍN",
                "planes": {
                    "3068:3534": {
                        "facultades_libre_eleccion": [
                            "3 SEDE MEDELLÍN", "3068 FACULTAD DE MINAS"
                        ]
                    },
                    "3068:3528": {
                        "facultades_libre_eleccion": [
                            "3068 FACULTAD DE MINAS", "3 SEDE MEDELLÍN"
                        ]
                    },
                },
            }
        }
        with patch("main.cargar_json", return_value=configuracion):
            resultado = seleccionar_planes_referencia_libres(planes)

        self.assertEqual(set(resultado), {"1102:3068:3534"})


if __name__ == "__main__":
    unittest.main()
