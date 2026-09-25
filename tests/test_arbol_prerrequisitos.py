import unittest

from herramientas.arbol_prerrequisitos import (
    construir_grafo,
    codigos_visibles_en_arbol,
    etiqueta_tipo,
    nombre_materia_limpio,
    ordenar_capas_por_conexiones,
    tonos_por_origen,
)


class ArbolPrerrequisitosTests(unittest.TestCase):
    def test_conecta_prerrequisitos_y_normaliza_sufijo_del_codigo(self):
        grafo = construir_grafo([
            {
                "codigo": "1000003-M",
                "nombre": "Álgebra lineal",
                "tipologia": "FUND. OBLIGATORIA",
                "prerrequisitos": [],
            },
            {
                "codigo": "3007744",
                "nombre": "Estructura de datos",
                "tipologia": "DISCIPLINAR OBLIGATORIA",
                "prerrequisitos": [{"codigo": "1000003", "nombre": "Álgebra lineal"}],
            },
        ])

        self.assertEqual(grafo["aristas"], [("1000003-M", "3007744")])
        self.assertEqual([m["codigo"] for m in grafo["sin_prerrequisitos"]], ["1000003-M"])

    def test_reconoce_prerrequisito_por_nombre_si_falta_codigo(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Base", "tipologia": "OBLIGATORIA", "prerrequisitos": []},
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OPTATIVA", "prerrequisitos": [{"nombre": "Base"}]},
        ])

        self.assertEqual(grafo["aristas"], [("1", "2")])

    def test_conserva_requisitos_que_no_pertenecen_al_plan(self):
        grafo = construir_grafo([
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OPTATIVA", "prerrequisitos": [{"codigo": "1", "nombre": "Curso externo"}]},
        ])

        self.assertEqual(grafo["aristas"], [("1", "2")])
        self.assertTrue(grafo["nodos"]["1"]["externo"])
        self.assertEqual(grafo["sin_prerrequisitos"], [])

    def test_mapea_tipologia_obligatoria_y_optativa(self):
        self.assertEqual(etiqueta_tipo("FUND. OBLIGATORIA"), "OBLIGATORIA")
        self.assertEqual(etiqueta_tipo("DISCIPLINAR OPTATIVA"), "OPTATIVA")

    def test_reordena_materias_para_alinear_padres_e_hijos(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "A raíz", "tipologia": "OBLIGATORIA", "prerrequisitos": []},
            {"codigo": "2", "nombre": "B raíz", "tipologia": "OBLIGATORIA", "prerrequisitos": []},
            {"codigo": "3", "nombre": "A destino", "tipologia": "OBLIGATORIA", "prerrequisitos": [{"codigo": "2"}]},
            {"codigo": "4", "nombre": "B destino", "tipologia": "OPTATIVA", "prerrequisitos": [{"codigo": "1"}]},
        ])

        capas = ordenar_capas_por_conexiones(grafo)

        self.assertEqual(capas[1], ["4", "3"])

    def test_muestra_raices_con_sucesores_y_oculta_materias_terminales(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Base", "tipologia": "OBLIGATORIA", "prerrequisitos": []},
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OBLIGATORIA", "prerrequisitos": [{"codigo": "1"}]},
        ])

        self.assertEqual(codigos_visibles_en_arbol(grafo), {"1", "2"})

    def test_muestra_prerrequisito_externo_si_de_el_sale_una_flecha(self):
        grafo = construir_grafo([
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OPTATIVA", "prerrequisitos": [{"codigo": "1", "nombre": "Base externa"}]},
        ])

        self.assertEqual(codigos_visibles_en_arbol(grafo), {"1"})

    def test_muestra_todas_las_obligatorias_aunque_no_tengan_conexiones(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Obligatoria aislada", "tipologia": "FUND. OBLIGATORIA", "prerrequisitos": []},
            {"codigo": "2", "nombre": "Obligatoria terminal", "tipologia": "DISCIPLINAR OBLIGATORIA", "prerrequisitos": [{"codigo": "3"}]},
            {"codigo": "3", "nombre": "Optativa base", "tipologia": "OPTATIVA", "prerrequisitos": []},
            {"codigo": "4", "nombre": "Optativa terminal", "tipologia": "OPTATIVA", "prerrequisitos": [{"codigo": "3"}]},
        ])

        self.assertEqual(codigos_visibles_en_arbol(grafo), {"1", "2", "3"})

    def test_separa_descripcion_duplicada_del_nombre(self):
        nombre = "CÁLCULO I — Herramientas matemáticas para ingeniería"
        descripcion = "Herramientas matemáticas para ingeniería"

        self.assertEqual(nombre_materia_limpio(nombre, descripcion), "CÁLCULO I")
        grafo = construir_grafo([{
            "codigo": "1",
            "nombre": nombre,
            "descripcion": descripcion,
            "tipologia": "FUND. OBLIGATORIA",
            "prerrequisitos": [],
        }])
        self.assertEqual(grafo["nodos"]["1"]["nombre"], "CÁLCULO I")

    def test_todas_las_flechas_de_un_origen_comparten_color(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Base", "tipologia": "OBLIGATORIA", "prerrequisitos": []},
            {"codigo": "2", "nombre": "Avanzada A", "tipologia": "OBLIGATORIA", "prerrequisitos": [{"codigo": "1"}]},
            {"codigo": "3", "nombre": "Avanzada B", "tipologia": "OBLIGATORIA", "prerrequisitos": [{"codigo": "1"}]},
            {"codigo": "4", "nombre": "Otra base", "tipologia": "OBLIGATORIA", "prerrequisitos": []},
            {"codigo": "5", "nombre": "Otra avanzada", "tipologia": "OBLIGATORIA", "prerrequisitos": [{"codigo": "4"}]},
        ])
        tonos = tonos_por_origen(grafo)
        colores_flechas = {
            arista: tonos[arista[0]]
            for arista in grafo["aristas"]
        }

        self.assertEqual(colores_flechas[("1", "2")], colores_flechas[("1", "3")])
        self.assertNotEqual(colores_flechas[("1", "2")], colores_flechas[("4", "5")])

    def test_conserva_tipologia_y_datos_de_condicion_en_cada_relacion(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Ecuaciones", "tipologia": "FUND. OBLIGATORIA"},
            {
                "codigo": "2",
                "nombre": "Análisis numérico",
                "tipologia": "DISCIPLINAR OBLIGATORIA",
                "prerrequisitos": [{
                    "codigo": "1",
                    "nombre": "Ecuaciones",
                    "tipo": "Y",
                    "condicion": "2",
                    "todas": "S",
                    "numero_asignaturas": "",
                }],
            },
        ])

        self.assertEqual(grafo["aristas"], [("1", "2")])
        self.assertEqual(grafo["relaciones"], [{
            "origen": "1",
            "destino": "2",
            "tipo": "Y",
            "condicion": "2",
            "todas": "S",
            "numero_asignaturas": "",
        }])

    def test_y_ubica_materias_en_la_misma_columna(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Ecuaciones", "tipologia": "OBLIGATORIA"},
            {
                "codigo": "2",
                "nombre": "Análisis numérico",
                "tipologia": "OBLIGATORIA",
                "prerrequisitos": [{"codigo": "1", "tipo": "Y"}],
            },
            {
                "codigo": "3",
                "nombre": "Métodos avanzados",
                "tipologia": "OBLIGATORIA",
                "prerrequisitos": [{"codigo": "2", "tipo": "M"}],
            },
        ])

        self.assertEqual(grafo["niveles"]["1"], grafo["niveles"]["2"])
        self.assertGreater(grafo["niveles"]["3"], grafo["niveles"]["2"])

    def test_o_e_y_a_no_se_tratan_como_precedencia_estricta(self):
        for tipo in ("O", "E", "Y", "A"):
            with self.subTest(tipo=tipo):
                grafo = construir_grafo([
                    {"codigo": "1", "nombre": "Base", "tipologia": "OBLIGATORIA"},
                    {
                        "codigo": "2",
                        "nombre": "Avanzada",
                        "tipologia": "OBLIGATORIA",
                        "prerrequisitos": [{"codigo": "1", "tipo": tipo}],
                    },
                ])
                self.assertEqual(grafo["niveles"]["1"], grafo["niveles"]["2"])

    def test_tipo_desconocido_conserva_orden_estricto_y_a_no_es_prerrequisito(self):
        desconocido = construir_grafo([
            {"codigo": "1", "nombre": "Base", "tipologia": "OBLIGATORIA"},
            {
                "codigo": "2",
                "nombre": "Avanzada",
                "tipologia": "OBLIGATORIA",
                "prerrequisitos": [{"codigo": "1", "tipo": "Z"}],
            },
        ])
        incompatibilidad = construir_grafo([
            {"codigo": "1", "nombre": "Llave", "tipologia": "OPTATIVA"},
            {
                "codigo": "2",
                "nombre": "Incompatible",
                "tipologia": "OPTATIVA",
                "prerrequisitos": [{"codigo": "1", "tipo": "A"}],
            },
        ])

        self.assertGreater(desconocido["niveles"]["2"], desconocido["niveles"]["1"])
        self.assertEqual(
            [materia["codigo"] for materia in incompatibilidad["sin_prerrequisitos"]],
            ["1", "2"],
        )
        self.assertEqual(codigos_visibles_en_arbol(incompatibilidad), {"1", "2"})

    def test_m_contradictorio_dentro_de_un_grupo_y_se_reporta(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "A", "tipologia": "OBLIGATORIA"},
            {
                "codigo": "2",
                "nombre": "B",
                "tipologia": "OBLIGATORIA",
                "prerrequisitos": [{"codigo": "1", "tipo": "Y"}],
            },
            {
                "codigo": "1",
                "nombre": "A",
                "tipologia": "OBLIGATORIA",
                "prerrequisitos": [{"codigo": "2", "tipo": "M"}],
            },
        ])

        self.assertEqual(set(grafo["ciclicos"]), {"1", "2"})


if __name__ == "__main__":
    unittest.main()
