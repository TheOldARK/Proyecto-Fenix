import unittest
from copy import deepcopy

from herramientas.arbol_prerrequisitos import (
    construir_grafo,
    codigos_visibles_en_arbol,
    etiqueta_tipo,
    nombre_materia_limpio,
    ordenar_capas_por_conexiones,
    tonos_por_origen,
)


class ArbolPrerrequisitosTests(unittest.TestCase):
    def test_obligatoriedad_se_propaga_hacia_requisitos_no_hacia_dependientes(self):
        for tipo in ("M", "O", "E", "Y", ""):
            with self.subTest(tipo=tipo):
                materias = [
                    {"codigo": "1", "nombre": "Base", "tipologia": "OPTATIVA"},
                    {"codigo": "2", "nombre": "Intermedia", "tipologia": "OPTATIVA",
                     "prerrequisitos": [{"codigo": "1", "tipo": tipo}]},
                    {"codigo": "3", "nombre": "Obligatoria", "tipologia": "OBLIGATORIA",
                     "prerrequisitos": [{"codigo": "2", "tipo": tipo}]},
                    {"codigo": "4", "nombre": "Optativa posterior", "tipologia": "OPTATIVA",
                     "prerrequisitos": [{"codigo": "3", "tipo": tipo}]},
                ]
                original = deepcopy(materias)
                grafo = construir_grafo(materias)
                self.assertEqual(codigos_visibles_en_arbol(grafo, "obligatorias"), {"1", "2", "3"})
                self.assertTrue(grafo["nodos"]["1"]["obligatoria_por_dependencia"])
                self.assertTrue(grafo["nodos"]["2"]["obligatoria_por_dependencia"])
                self.assertFalse(grafo["nodos"]["3"]["obligatoria_por_dependencia"])
                self.assertFalse(grafo["nodos"]["4"]["obligatoria"])
                self.assertEqual(grafo["nodos"]["1"]["tipologia"], "OPTATIVA")
                self.assertEqual(materias, original)

    def test_incompatibilidad_no_convierte_materia_en_obligatoria(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Incompatible", "tipologia": "OPTATIVA"},
            {"codigo": "2", "nombre": "Obligatoria", "tipologia": "OBLIGATORIA",
             "prerrequisitos": [{"codigo": "1", "tipo": "A"}]},
        ])
        self.assertEqual(codigos_visibles_en_arbol(grafo, "obligatorias"), {"2"})

    def test_ciclos_no_bloquean_propagacion_y_no_crean_obligatorias_sin_semilla(self):
        materias = [
            {"codigo": "1", "nombre": "A", "tipologia": "OPTATIVA", "prerrequisitos": [{"codigo": "2", "tipo": "M"}]},
            {"codigo": "2", "nombre": "B", "tipologia": "OPTATIVA", "prerrequisitos": [{"codigo": "1", "tipo": "M"}]},
        ]
        self.assertEqual(codigos_visibles_en_arbol(construir_grafo(materias), "obligatorias"), set())
        materias[0]["tipologia"] = "OBLIGATORIA"
        self.assertEqual(codigos_visibles_en_arbol(construir_grafo(materias), "obligatorias"), {"1", "2"})

    def test_requisito_externo_hereda_obligatoriedad_sin_inventar_tipologia_sia(self):
        grafo = construir_grafo([
            {"codigo": "2", "nombre": "Obligatoria", "tipologia": "OBLIGATORIA",
             "prerrequisitos": [{"nombre": "Externa", "tipo": "Y"}]},
        ])
        self.assertEqual(codigos_visibles_en_arbol(grafo, "obligatorias"), {"2", "externo:externa"})
        self.assertTrue(grafo["nodos"]["externo:externa"]["externo"])

    def test_raiz_optativa_sin_prerrequisitos_aparece_si_otra_materia_la_requiere(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Materia base", "tipologia": "OPTATIVA"},
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OBLIGATORIA",
             "prerrequisitos": [{"nombre": "Materia base"}]},
        ])
        self.assertIn("1", {m["codigo"] for m in grafo["sin_prerrequisitos"]})
        self.assertIn("1", codigos_visibles_en_arbol(grafo))
        self.assertEqual(grafo["aristas"], [("1", "2")])

    def test_requisito_externo_sin_codigo_tambien_tiene_tarjeta_y_flecha(self):
        grafo = construir_grafo([
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OBLIGATORIA",
             "prerrequisitos": [{"nombre": "Materia base externa", "tipo": "M"}]},
        ])
        clave = "externo:materia base externa"
        self.assertEqual(grafo["aristas"], [(clave, "2")])
        self.assertIn(clave, codigos_visibles_en_arbol(grafo))
        self.assertEqual(grafo["niveles"][clave], 0)
        self.assertNotIn("2", {m["codigo"] for m in grafo["sin_prerrequisitos"]})

    def test_limpia_examen_externo_incluso_si_llega_con_leyenda_antigua(self):
        for leyenda in ("Tipo de prerrequisito implica.", "Tipo de implica."):
            with self.subTest(leyenda=leyenda):
                grafo = construir_grafo([
                    {"codigo": "3007279", "nombre": "Teorías de la historia IV", "tipologia": "OBLIGATORIA",
                     "prerrequisitos": [{"codigo": "1000095", "nombre":
                         "Examen de clasificación en inglés " + leyenda + " M - no se puede matricular. Correquisitos"}]},
                ])
                self.assertEqual(grafo["nodos"]["1000095"]["nombre"], "Examen de clasificación en inglés")
                self.assertIn("1000095", codigos_visibles_en_arbol(grafo))

    def test_nombre_con_leyenda_reconoce_la_raiz_del_plan(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Materia base", "tipologia": "OPTATIVA"},
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OBLIGATORIA",
             "prerrequisitos": [{"nombre": "Materia base Tipo de implica. M - explicación"}]},
        ])
        self.assertEqual(grafo["aristas"], [("1", "2")])
        self.assertFalse(grafo["nodos"]["1"]["externo"])

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

    def test_muestra_tanto_raices_como_materias_terminales(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Base", "tipologia": "OBLIGATORIA", "prerrequisitos": []},
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OBLIGATORIA", "prerrequisitos": [{"codigo": "1"}]},
        ])

        self.assertEqual(codigos_visibles_en_arbol(grafo), {"1", "2"})

    def test_muestra_prerrequisito_externo_si_de_el_sale_una_flecha(self):
        grafo = construir_grafo([
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OPTATIVA", "prerrequisitos": [{"codigo": "1", "nombre": "Base externa"}]},
        ])

        self.assertEqual(codigos_visibles_en_arbol(grafo), {"1", "2"})

    def test_separa_obligatorias_aisladas_y_muestra_optativas_conectadas(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Obligatoria aislada", "tipologia": "FUND. OBLIGATORIA", "prerrequisitos": []},
            {"codigo": "2", "nombre": "Obligatoria terminal", "tipologia": "DISCIPLINAR OBLIGATORIA", "prerrequisitos": [{"codigo": "3"}]},
            {"codigo": "3", "nombre": "Optativa base", "tipologia": "OPTATIVA", "prerrequisitos": []},
            {"codigo": "4", "nombre": "Optativa terminal", "tipologia": "OPTATIVA", "prerrequisitos": [{"codigo": "3"}]},
        ])

        self.assertEqual(codigos_visibles_en_arbol(grafo), {"2", "3", "4"})
        self.assertEqual([m["codigo"] for m in grafo["sin_conexiones"]], ["1"])

    def test_distingue_raiz_intermedia_terminal_y_aislada(self):
        grafo = construir_grafo([
            {"codigo": "3007262", "nombre": "Paleografía y diplomática", "tipologia": "OBLIGATORIA"},
            {"codigo": "2", "nombre": "Curso intermedio", "tipologia": "OPTATIVA",
             "prerrequisitos": [{"codigo": "3007262"}]},
            {"codigo": "3", "nombre": "Curso final", "tipologia": "OPTATIVA",
             "prerrequisitos": [{"codigo": "2"}]},
            {"codigo": "4", "nombre": "Curso aislado", "tipologia": "OPTATIVA"},
        ])
        visibles = codigos_visibles_en_arbol(grafo)
        aisladas = {m["codigo"] for m in grafo["sin_conexiones"]}
        self.assertEqual(visibles, {"3007262", "2", "3"})
        self.assertEqual(aisladas, {"4"})
        self.assertFalse(visibles & aisladas)
        self.assertEqual(visibles | aisladas, set(grafo["nodos"]))

    def test_sin_relaciones_todas_las_materias_van_al_panel(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "A", "tipologia": "OBLIGATORIA"},
            {"codigo": "2", "nombre": "B", "tipologia": "OPTATIVA"},
        ])
        self.assertEqual(codigos_visibles_en_arbol(grafo), set())
        self.assertEqual({m["codigo"] for m in grafo["sin_conexiones"]}, {"1", "2"})

    def test_relaciones_no_estrictas_tambien_permanecen_en_el_grafo(self):
        for tipo in ("O", "E", "Y", "A"):
            with self.subTest(tipo=tipo):
                grafo = construir_grafo([
                    {"codigo": "1", "nombre": "A", "tipologia": "OPTATIVA"},
                    {"codigo": "2", "nombre": "B", "tipologia": "OPTATIVA",
                     "prerrequisitos": [{"codigo": "1", "tipo": tipo}]},
                ])
                self.assertEqual(codigos_visibles_en_arbol(grafo), {"1", "2"})
                self.assertEqual(grafo["sin_conexiones"], [])

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
