"""El historial del SIA se interpreta y muestra sin conservar la sesión."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QLineEdit, QDoubleSpinBox

from aplicacion.interfaz import VentanaAvanceAcademico, VentanaPromedioActual
from aplicacion.trabajador_avance import TrabajadorAvanceAcademico
from datetime import date

from servicios.historia_academica import (
    interpretar_detalle_calificaciones, interpretar_tablas_historia,
    periodos_visibles_avance, promedio_ponderado_periodo,
)


TABLAS_EJEMPLO = [
    [
        ["ASIGNATURAS", "CRÉDITOS", "TIPO", "PERIODO", "CALIFICACIÓN"],
        ["CÁLCULO INTEGRAL (1000005-M)", "4", "FUND. OBLIGATORIA", "2025-2S Ordinaria", "1.8\nREPROBADA"],
        ["INVESTIGACIÓN DE OPERACIONES I (3007324)", "3", "DISCIPLINAR OBLIGATORIA", "2025-2S Ordinaria", "4.0\nAPROBADA"],
        ["INGLÉS II (1000045-M)", "3", "NIVELACIÓN", "2023-1S Validación por suficiencia", "APROBADA"],
    ],
    [
        ["TIPOLOGÍAS", "EXIGIDOS", "APROBADOS", "PENDIENTES", "INSCRITOS", "CURSADOS"],
        ["FUND. OBLIGATORIA", "27", "16", "11", "4", "40"],
    ],
]


class MiAvanceTests(unittest.TestCase):
    def test_vista_de_actividad_solo_lectura_y_opcional(self):
        app = QApplication.instance() or QApplication([])
        ventana = VentanaAvanceAcademico()
        ventana.show()
        ventana.marcar_consulta(True)
        self.assertTrue(ventana.boton_actividad.isVisible())
        ventana.boton_actividad.click()
        self.assertTrue(ventana.ventana_actividad.isVisible())
        self.assertFalse(hasattr(ventana.ventana_actividad, "navegador"))
        ventana.marcar_consulta(False)
        self.assertFalse(ventana.ventana_actividad.isVisible())
        ventana.close()

    def test_captura_solo_cuando_se_activa_la_vista(self):
        trabajador = TrabajadorAvanceAcademico("3534")
        pagina = MagicMock()
        pagina.url = "https://sia.unal.edu.co/ServiciosApp/faces/inicioServicios"
        pagina.is_closed.return_value = False
        pagina.screenshot = AsyncMock(return_value=b"imagen-en-memoria")
        contexto = MagicMock()
        contexto.pages = [pagina]
        recibidas = []
        trabajador.captura.connect(recibidas.append)

        async def comprobar():
            trabajador.activar_vista(True)
            tarea = asyncio.create_task(trabajador._emitir_capturas(contexto))
            await asyncio.sleep(0.05)
            tarea.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await tarea

        asyncio.run(comprobar())
        self.assertEqual(recibidas, [b"imagen-en-memoria"])
        pagina.screenshot.assert_awaited_once()

    def test_consulta_privada_transfiere_sesion_solo_en_memoria(self):
        navegador = MagicMock()
        contexto = MagicMock()
        navegador.new_context = AsyncMock(return_value=contexto)
        navegador.close = AsyncMock()
        contexto.add_init_script = AsyncMock()
        playwright = MagicMock()
        playwright.chromium.launch = AsyncMock(return_value=navegador)
        estado = {"cookies": [{"name": "sesion", "value": "temporal"}], "origins": []}

        async def consultar():
            return await TrabajadorAvanceAcademico._abrir_contexto_privado(
                playwright, estado, {"token": "solo-memoria"}
            )

        with patch("infraestructura.sia.runtime_navegador.ejecutable_integrado", return_value="/browser/headless"):
            self.assertEqual(asyncio.run(consultar()), (navegador, contexto))
        playwright.chromium.launch.assert_awaited_once_with(
            headless=True, executable_path="/browser/headless"
        )
        navegador.new_context.assert_awaited_once_with(
            accept_downloads=False, storage_state=estado
        )
        self.assertIn("sessionStorage.setItem", contexto.add_init_script.await_args.args[0])
        self.assertIn("solo-memoria", contexto.add_init_script.await_args.args[0])

    def test_barra_de_consulta_muestra_espera_y_avance(self):
        app = QApplication.instance() or QApplication([])
        ventana = VentanaAvanceAcademico()
        ventana.show()
        ventana.marcar_consulta(True)
        ventana.actualizar_progreso(15)
        self.assertTrue(ventana.barra_consulta.isVisible())
        self.assertEqual(ventana.barra_consulta.maximum(), 0)
        ventana.actualizar_progreso(65)
        self.assertEqual(ventana.barra_consulta.value(), 65)
        ventana.marcar_consulta(False)
        self.assertFalse(ventana.barra_consulta.isVisible())
        ventana.close()

    def test_promedios_usan_creditos_del_catalogo_sin_pedirlos(self):
        app = QApplication.instance() or QApplication([])
        periodo = f"{date.today().year}-{1 if date.today().month <= 6 else 2}S"
        datos = {"plan_estudios": "3534", "asignaturas": [], "calificaciones_detalle": [
            {"periodo": periodo, "codigo": "3007847", "nombre": "Base de Datos I",
             "creditos": 3, "parciales": [{"nombre": "Corte", "nota": "4", "porcentaje": "20"}]}
        ]}
        with patch("aplicacion.interfaz.cargar_plan_materias", return_value="3534"), \
             patch("aplicacion.interfaz.cargar_materias", return_value={"3007847": {"creditos": "5"}}):
            ventana = VentanaPromedioActual(datos)
        self.assertEqual(ventana.etiqueta_creditos.text(), "Créditos de la materia: 5")
        self.assertFalse(hasattr(ventana, "creditos"))
        ventana.close()

    def test_promedios_actuales_y_papa_proyectado_con_nota_manual(self):
        app = QApplication.instance() or QApplication([])
        periodo = f"{date.today().year}-{1 if date.today().month <= 6 else 2}S"
        datos = {
            "plan_estudios": "3534",
            "asignaturas": [{"periodo": "2025-2S", "codigo": "1", "creditos": 4, "nota": "4.0"}],
            "calificaciones_detalle": [{"periodo": periodo, "codigo": "3007847",
                                        "nombre": "Base de Datos I", "creditos": 3,
                                        "parciales": [{"nombre": "Parcial 1", "porcentaje": "20",
                                                       "nota": "4.5"}]}],
        }
        ventana = VentanaPromedioActual(datos)
        self.assertIn("background-color: #141414", ventana.styleSheet())
        self.assertIn("background: transparent; border: none", ventana.styleSheet())
        self.assertEqual(ventana.papa_proyectado.text(), "4.21")
        self.assertEqual(ventana.papi_provisional.text(), "4.50")
        self.assertIn("color: #F2F2F2", ventana.papa_proyectado.styleSheet())
        clave = f"{periodo}|3007847"
        nombre_importado = ventana.findChild(QLineEdit, "nombreEvaluacion")
        nota_importada = ventana.findChild(QLineEdit, "notaEvaluacion")
        porcentaje_importado = ventana.findChild(QDoubleSpinBox, "porcentajeEvaluacion")
        nombre_importado.setText("Primer corte")
        nota_importada.setText("4.0")
        ventana._guardar_fila(clave, 0, nombre_importado, nota_importada, porcentaje_importado)
        self.assertEqual(datos["notas_editadas"][clave][0]["nombre"], "Primer corte")
        self.assertEqual(datos["notas_editadas"][clave][0]["nota"], 4.0)
        ventana.nombre_nota.setText("Quiz")
        ventana.porcentaje.setValue(10)
        ventana.nota.setText("5")
        ventana._agregar()
        self.assertEqual(ventana.papa_proyectado.text(), "4.14")
        self.assertEqual(ventana.papi_provisional.text(), "4.33")
        self.assertEqual(datos["notas_editadas"][clave][1]["nombre"], "Quiz")
        ventana._eliminar(clave, 0)
        self.assertEqual(len(datos["notas_editadas"][clave]), 1)
        self.assertTrue(ventana.windowFlags() & ventana.windowFlags().FramelessWindowHint)
        ventana.close()

    def test_detalle_calificaciones_parciales_variables_y_sin_nota(self):
        texto = """BASE DE DATOS I (3007847)
        SIN DEFINITIVA
        Datos de los parciales
        PARCIAL 01
        3
        Calificación mínima*
        0
        Fallas
        20%
        nota final
        4.5
        LABORATORIO
        3
        Calificación mínima*
        0
        Fallas
        80%
        nota final
        *Calificación mínima para superar el parcial
        Datos académicos de la asignatura"""
        detalle = interpretar_detalle_calificaciones(texto, "2026-2S", "3007847", "Base de Datos I")
        self.assertTrue(detalle["sin_definitiva"])
        self.assertEqual(detalle["parciales"], [
            {"nombre": "PARCIAL 01", "porcentaje": "20", "nota": "4.5"},
            {"nombre": "LABORATORIO", "porcentaje": "80", "nota": None},
        ])

    def test_no_confunde_minimo_del_siguiente_parcial_con_nota(self):
        filas = ["Datos de los parciales"]
        for numero in range(1, 6):
            filas += [f"PARCIAL {numero:02d}", "3", "Calificación mínima*",
                      "0", "Fallas", "20%", "nota final"]
            if numero == 1:
                filas.append("4.5")
        filas += ["*Calificación mínima para superar el parcial",
                  "Datos académicos de la asignatura"]
        detalle = interpretar_detalle_calificaciones(
            "\n".join(filas), "2026-2S", "3007847", "Base de Datos I"
        )
        self.assertEqual([p["nota"] for p in detalle["parciales"]],
                         ["4.5", None, None, None, None])

    def test_detalle_sin_actividades_no_inventa_notas(self):
        texto = "Datos de los parciales\n3\nCalificación mínima*\n0\nFallas\n100%\nnota final\n*Calificación mínima para superar el parcial\nDatos académicos de la asignatura"
        detalle = interpretar_detalle_calificaciones(texto, "2026-2S", "1000005-M", "Cálculo Integral")
        self.assertEqual(detalle["parciales"], [])

    def test_periodos_vacios_hasta_el_ultimo_terminado(self):
        periodos = periodos_visibles_avance(["2025-2S"], date(2026, 9, 30))
        self.assertEqual(periodos, ["2025-2S", "2026-1S"])
        self.assertNotIn("2026-2S", periodos)
        self.assertIn("2026-2S", periodos_visibles_avance(["2025-2S", "2026-2S"], date(2026, 9, 30)))

    def test_promedio_ponderado_ignora_materias_sin_nota(self):
        materias = [
            {"creditos": "4", "nota": "2.5", "estado": "reprobada"},
            {"creditos": "3", "nota": "4.0", "estado": "aprobada"},
            {"creditos": "3", "nota": None, "estado": "aprobada"},
        ]
        self.assertEqual(str(promedio_ponderado_periodo(materias)), "3.14")
        self.assertIsNone(promedio_ponderado_periodo(materias[2:]))

    def test_parser_conserva_intentos_notas_y_validaciones(self):
        datos = interpretar_tablas_historia(TABLAS_EJEMPLO, "1102:3068:3534")
        self.assertEqual(datos["plan_estudios"], "1102:3068:3534")
        self.assertEqual(len(datos["asignaturas"]), 3)
        reprobada, aprobada, validacion = datos["asignaturas"]
        self.assertEqual((reprobada["codigo"], reprobada["periodo"], reprobada["nota"], reprobada["estado"]),
                         ("1000005-M", "2025-2S", "1.8", "reprobada"))
        self.assertEqual((aprobada["nota"], aprobada["estado"]), ("4.0", "aprobada"))
        self.assertEqual((validacion["nota"], validacion["estado"]), (None, "aprobada"))
        self.assertEqual(datos["resumen_creditos"][0]["aprobados"], "16")
        self.assertNotIn("contrasena", datos)
        self.assertNotIn("cookies", datos)

    def test_no_guarda_tabla_vacia_o_equivocada(self):
        with self.assertRaisesRegex(ValueError, "No se encontró la tabla"):
            interpretar_tablas_historia([[['TIPOLOGÍAS', 'EXIGIDOS']]], "3534")

    def test_encuentra_cabecera_despues_de_fila_de_titulo(self):
        tabla = [["Historia Académica"], *TABLAS_EJEMPLO[0]]
        datos = interpretar_tablas_historia([tabla], "3534")
        self.assertEqual(len(datos["asignaturas"]), 3)

    def test_encuentra_asignaturas_sin_cabecera_en_la_tabla(self):
        datos = interpretar_tablas_historia([TABLAS_EJEMPLO[0][1:]], "3534")
        self.assertEqual(len(datos["asignaturas"]), 3)
        self.assertEqual(datos["asignaturas"][0]["estado"], "reprobada")

    def test_reprobadas_se_muestran_rojas_por_periodo(self):
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        ventana = VentanaAvanceAcademico()
        ventana.mostrar_datos(interpretar_tablas_historia(TABLAS_EJEMPLO, "1102:3068:3534"))
        ventana.show()
        app.processEvents()
        self.assertEqual(ventana.papa.text(), "P.A.P.A.  2.74")
        columnas = ventana.findChildren(QFrame, "columnaPeriodoAvance")
        self.assertGreaterEqual(len(columnas), 1)
        tarjetas = ventana.findChildren(QFrame, "tarjetaMateriaAvance")
        self.assertEqual(len(tarjetas), 3)
        reprobada = next(t for t in tarjetas if t.property("estado_academico") == "reprobada")
        self.assertIn("#EF6670", reprobada.styleSheet())
        self.assertTrue(any("Nota: 1.8" in etiqueta.text() for etiqueta in reprobada.findChildren(QLabel)))
        self.assertTrue(any("4 créditos" in etiqueta.text() for etiqueta in reprobada.findChildren(QLabel)))
        self.assertTrue(all("background: transparent" in etiqueta.styleSheet()
                            for tarjeta in tarjetas for etiqueta in tarjeta.findChildren(QLabel)))
        self.assertTrue(ventana.nivelacion.isVisible())
        ventana.close()

    def test_nivelacion_se_muestra_separada_de_los_periodos(self):
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        ventana = VentanaAvanceAcademico()
        datos = interpretar_tablas_historia(TABLAS_EJEMPLO, "1102:3068:3534")
        datos["asignaturas"][2]["tipologia"] = "NIVELACIÓN"
        ventana.mostrar_datos(datos)
        ventana.show()
        app.processEvents()
        self.assertGreaterEqual(len(ventana.findChildren(QFrame, "columnaPeriodoAvance")), 1)
        self.assertTrue(ventana.nivelacion.isVisible())
        self.assertEqual(len(ventana.nivelacion.findChildren(QFrame, "tarjetaMateriaAvance")), 1)
        ventana.close()

    def test_calificaciones_detalladas_se_abren_sin_alterar_notas_finales(self):
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        ventana = VentanaAvanceAcademico()
        datos = interpretar_tablas_historia(TABLAS_EJEMPLO, "1102:3068:3534")
        datos["calificaciones_detalle"] = [{
            "periodo": "2025-2S", "codigo": "1000005-M", "nombre": "Cálculo Integral",
            "parciales": [{"nombre": "PARCIAL 01", "porcentaje": "20", "nota": "4.5"}],
        }]
        consultas = []
        ventana._mostrar_notas_materia = lambda materia, detalles: consultas.append((materia, detalles))
        ventana.mostrar_datos(datos)
        ventana.show()
        app.processEvents()
        tarjetas = ventana.findChildren(QFrame, "tarjetaMateriaAvance")
        calculo = next(t for t in tarjetas if "CÁLCULO INTEGRAL" in
                       " ".join(etiqueta.text() for etiqueta in t.findChildren(QLabel)))
        calculo.pulsada.emit()
        app.processEvents()
        self.assertEqual(len(consultas), 1)
        self.assertEqual(consultas[0][1][0]["parciales"][0]["nota"], "4.5")
        self.assertFalse(hasattr(ventana, "detalles_calificaciones"))
        self.assertEqual(ventana.papa.text(), "P.A.P.A.  2.74")
        ventana.close()


if __name__ == "__main__":
    unittest.main()
