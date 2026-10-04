import unittest
from types import SimpleNamespace

from herramientas.verificar_planes_cloudflare import _codigos_documento, verificar_cobertura


def crear_plan():
    return SimpleNamespace(
        sede_codigo="1102",
        facultad_nombre="Facultad de prueba",
        nombre="Plan de prueba",
        nombres_asignaturas={"1001": "Materia uno", "1002": "Materia dos"},
        semestres=[SimpleNamespace(numero=1, asignaturas=["1001"], creditos={})],
    )


class VerificadorPlanesCloudflareTests(unittest.TestCase):
    def test_normaliza_sufijo_de_sede_en_los_codigos_publicados(self):
        self.assertEqual(
            _codigos_documento({"materias": {"1000003-M": {"codigo": "1000003-M"}}}),
            {"1000003"},
        )

    def test_informa_completo_si_materias_y_oferta_cubren_el_plan(self):
        manifiesto = {
            "planes": {
                "1102:1:1": {
                    "archivos": {
                        "materias": {"ruta": "materias.json"},
                        "oferta": {"ruta": "oferta.json"},
                    }
                }
            }
        }
        documentos = {
            "materias.json": {"materias": {"1001": {}, "1002": {}}},
            "oferta.json": {"materias": {"1001": {}, "1002": {}}},
        }

        informe = verificar_cobertura(
            {"1102:1:1": crear_plan()}, manifiesto,
            lambda info: documentos[info["ruta"]],
        )

        self.assertEqual(informe[0]["faltan_materias"], [])
        self.assertEqual(informe[0]["faltan_oferta"], [])
        self.assertEqual(informe[0]["total"], 2)

    def test_detalla_codigos_que_faltan_en_cada_archivo(self):
        manifiesto = {
            "planes": {
                "1102:1:1": {
                    "archivos": {
                        "materias": {"ruta": "materias.json"},
                        "oferta": {"ruta": "oferta.json"},
                    }
                }
            }
        }
        documentos = {
            "materias.json": {"materias": {"1001": {}}},
            "oferta.json": {"materias": {"1002": {}}},
        }

        informe = verificar_cobertura(
            {"1102:1:1": crear_plan()}, manifiesto,
            lambda info: documentos[info["ruta"]],
        )

        self.assertEqual(informe[0]["faltan_materias"], ["1002"])
        self.assertEqual(informe[0]["faltan_oferta"], ["1001"])
        self.assertEqual(informe[0]["materias_faltantes_detalle"][0]["nombre"], "Materia dos")
        self.assertTrue(informe[0]["materias_faltantes_detalle"][0]["sin_semestre"])

    def test_plan_no_publicado_marca_todas_sus_materias(self):
        informe = verificar_cobertura(
            {"1102:1:1": crear_plan()}, {"planes": {}}, lambda _info: self.fail("No debe descargar")
        )

        self.assertEqual(informe[0]["faltan_materias"], ["1001", "1002"])
        self.assertEqual(informe[0]["faltan_oferta"], ["1001", "1002"])
        self.assertTrue(informe[0]["errores"])

    def test_omite_otros_campus_pero_identifica_planes_sin_malla(self):
        plan_fuera_sede = crear_plan()
        plan_fuera_sede.sede_codigo = "9999"
        plan_vacio = crear_plan()
        plan_vacio.nombres_asignaturas = {}
        plan_vacio.semestres = []
        informe = verificar_cobertura(
            {"9999:1:1": plan_fuera_sede, "1102:1:2": plan_vacio},
            {"planes": {}}, lambda _info: self.fail("No debe descargar"),
        )
        self.assertEqual(len(informe), 1)
        self.assertEqual(informe[0]["estado"], "sin_malla")
        self.assertEqual(informe[0]["codigo_plan"], "1102:1:2")
        self.assertEqual(informe[0]["errores"], [])

    def test_error_de_red_no_se_confunde_con_materias_faltantes(self):
        def fallar(info):
            raise OSError("Red no disponible")
        informe = verificar_cobertura({"1102:1:1": crear_plan()}, {
            "planes": {"1102:1:1": {"archivos": {
                "materias": {"ruta": "materias.json"}, "oferta": {"ruta": "oferta.json"}
            }}}
        }, fallar)
        self.assertEqual(informe[0]["estado"], "no_verificado")
        self.assertEqual(informe[0]["faltan_materias"], [])
        self.assertEqual(informe[0]["faltan_oferta"], [])
        self.assertEqual(informe[0]["no_verificados"], ["materias", "oferta"])

    def test_filtra_por_facultad_y_codigo_o_clave_de_carrera(self):
        primero, segundo = crear_plan(), crear_plan()
        primero.facultad_codigo, primero.codigo = "3064", "3501"
        segundo.facultad_codigo, segundo.codigo = "3516", "3706"
        planes = {"1102:3064:3501": primero, "1102:3516:3706": segundo}
        for filtro in ("3501", "1102:3064:3501"):
            informe = verificar_cobertura(planes, {"planes": {}}, lambda info: {},
                                         facultad="3064", plan_elegido=filtro)
            self.assertEqual([i["codigo_plan"] for i in informe], ["1102:3064:3501"])

    def test_no_acepta_datos_publicados_de_otra_carrera(self):
        informe = verificar_cobertura({"1102:1:1": crear_plan()}, {
            "planes": {"1102:1:1": {"archivos": {"materias": {}, "oferta": {}}}}
        }, lambda info: {"plan_estudios": "1102:2:2", "materias": {"1001": {}, "1002": {}}})
        self.assertEqual(informe[0]["estado"], "no_verificado")
        self.assertIn("pertenece al plan", informe[0]["errores"][0])


if __name__ == "__main__":
    unittest.main()
