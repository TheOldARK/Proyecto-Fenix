import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
from herramientas.arbol_prerrequisitos import (
    ConexionItem, TarjetaMateriaItem, VentanaArbol, VistaGrafo, construir_grafo,
)


class VistaArbolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_modos_conservan_posiciones_zoom_y_desplazamiento_independientes(self):
        materias = [
            {"codigo": "1", "nombre": "Base", "tipologia": "OBLIGATORIA"},
            {"codigo": "2", "nombre": "Avanzada", "tipologia": "OBLIGATORIA",
             "prerrequisitos": [{"codigo": "1", "tipo": "M"}]},
            {"codigo": "3", "nombre": "Aislada", "tipologia": "OPTATIVA"},
        ]
        with (
            patch.object(VentanaArbol, "_iniciar_descubrimiento"),
            patch.object(VentanaArbol, "_cargar_catalogo_local", return_value={"niveles_estudio": []}),
        ):
            ventana = VentanaArbol()
        estados = {}
        try:
            ventana.show()
            ventana._mostrar_resultado(materias)
            self.app.processEvents()
            for indice, modo in enumerate(("normal", "todas", "obligatorias")):
                ventana.modo.setCurrentIndex(ventana.modo.findData(modo))
                self.app.processEvents()
                vista = ventana.vista
                tarjeta = next(i for i in vista.scene().items() if isinstance(i, TarjetaMateriaItem) and i.codigo == "1")
                self.assertNotIn(tarjeta.pos(), [e['posicion'] for e in estados.values()])
                flecha = next(i for i in vista.scene().items() if isinstance(i, ConexionItem))
                camino_inicial = flecha.path()
                tarjeta.setPos(QPointF(900 + indice * 250, 1100 + indice * 200))
                self.assertNotEqual(flecha.path(), camino_inicial)
                vista.scene().setSceneRect(-2000, -2000, 7000, 7000)
                factor = 1.4 + indice * 0.4
                vista.scale(factor, factor)
                vista.zoom_factor = factor
                vista.horizontalScrollBar().setValue(200 + indice * 75)
                vista.verticalScrollBar().setValue(400 + indice * 65)
                self.app.processEvents()
                estados[modo] = {
                    'vista': vista, 'tarjeta': tarjeta, 'posicion': tarjeta.pos(),
                    'transformacion': vista.transform(), 'zoom': vista.zoom_factor,
                    'horizontal': vista.horizontalScrollBar().value(),
                    'vertical': vista.verticalScrollBar().value(), 'camino': flecha.path(),
                }
            for modo in ("normal", "todas", "obligatorias", "todas", "normal"):
                with self.subTest(modo=modo):
                    ventana.modo.setCurrentIndex(ventana.modo.findData(modo))
                    self.app.processEvents()
                    esperado = estados[modo]
                    vista = ventana.vista
                    self.assertIs(vista, esperado['vista'])
                    self.assertEqual(esperado['tarjeta'].pos(), esperado['posicion'])
                    self.assertEqual(vista.transform(), esperado['transformacion'])
                    self.assertEqual(vista.zoom_factor, esperado['zoom'])
                    self.assertEqual(vista.horizontalScrollBar().value(), esperado['horizontal'])
                    self.assertEqual(vista.verticalScrollBar().value(), esperado['vertical'])
                    flecha = next(i for i in vista.scene().items() if isinstance(i, ConexionItem))
                    self.assertEqual(flecha.path(), esperado['camino'])
            # Una consulta nueva invalida las tres páginas, aunque repita códigos.
            ventana._mostrar_resultado(materias)
            for modo, esperado in estados.items():
                ventana.modo.setCurrentIndex(ventana.modo.findData(modo))
                self.app.processEvents()
                vista = ventana.vista
                tarjeta = next(i for i in vista.scene().items() if isinstance(i, TarjetaMateriaItem) and i.codigo == "1")
                self.assertNotEqual(tarjeta.pos(), esperado['posicion'])
                self.assertEqual(vista.zoom_factor, 1.0)
        finally:
            ventana.close()

    def test_tres_modos_cambian_vista_sin_consultar_ni_perder_datos(self):
        materias = [
            {"codigo": "1", "nombre": "Base", "tipologia": "FUND. OBLIGATORIA"},
            {"codigo": "2", "nombre": "Intermedia", "tipologia": "OPTATIVA",
             "prerrequisitos": [{"codigo": "1", "tipo": "M"}]},
            {"codigo": "3", "nombre": "Final", "tipologia": "DISCIPLINAR OBLIGATORIA",
             "prerrequisitos": [{"codigo": "2", "tipo": "M"}]},
            {"codigo": "4", "nombre": "Obligatoria aislada", "tipologia": "OBLIGATORIA"},
            {"codigo": "5", "nombre": "Optativa aislada", "tipologia": "OPTATIVA"},
        ]
        with (
            patch.object(VentanaArbol, "_iniciar_descubrimiento"),
            patch.object(VentanaArbol, "_cargar_catalogo_local", return_value={"niveles_estudio": []}),
            patch.object(VentanaArbol, "consultar") as consultar,
        ):
            ventana = VentanaArbol()
            try:
                self.assertEqual(ventana.modo.count(), 3)
                # También es válido elegir el modo antes de consultar.
                ventana.modo.setCurrentIndex(ventana.modo.findData("todas"))
                ventana._mostrar_resultado(materias, [{"codigo": "9", "nombre": "Pendiente"}])
                grafo = ventana.grafo_actual
                for modo, esperadas, flechas, laterales in (
                    ("todas", {"1", "2", "3", "4", "5"}, 2, 0),
                    ("obligatorias", {"1", "2", "3", "4"}, 2, 0),
                    ("normal", {"1", "2", "3"}, 2, 2),
                    ("todas", {"1", "2", "3", "4", "5"}, 2, 0),
                ):
                    with self.subTest(modo=modo):
                        ventana.modo.setCurrentIndex(ventana.modo.findData(modo))
                        tarjetas = {i.codigo for i in ventana.vista.scene().items() if isinstance(i, TarjetaMateriaItem)}
                        self.assertEqual(tarjetas, esperadas)
                        self.assertEqual(sum(isinstance(i, ConexionItem) for i in ventana.vista.scene().items()), flechas)
                        self.assertEqual(ventana.lista.count(), laterales)
                        self.assertEqual(ventana.lista.isHidden(), modo != "normal")
                        self.assertIn("Pendiente", ventana.resumen.text())
                        self.assertIs(ventana.grafo_actual, grafo)
                consultar.assert_not_called()
                # El filtro sin coincidencias deja un grafo vacío, sin tarjetas viejas.
                ventana.modo.setCurrentIndex(ventana.modo.findData("obligatorias"))
                ventana._mostrar_resultado([materias[-1]])
                self.assertFalse(ventana.vista.scene().items())
                ventana.modo.setCurrentIndex(ventana.modo.findData("todas"))
                self.assertEqual({i.codigo for i in ventana.vista.scene().items() if isinstance(i, TarjetaMateriaItem)}, {"5"})
            finally:
                ventana.close()

    def test_panel_solo_aisladas_y_grafo_conserva_paleografia_y_sucesoras(self):
        materias = [
            {"codigo": "3007262", "nombre": "Paleografía y diplomática", "tipologia": "OBLIGATORIA"},
            {"codigo": "2", "nombre": "Curso dependiente", "tipologia": "OPTATIVA",
             "prerrequisitos": [{"codigo": "3007262", "tipo": "M"}]},
            {"codigo": "3", "nombre": "Obligatoria aislada", "tipologia": "OBLIGATORIA"},
            {"codigo": "4", "nombre": "Optativa aislada", "tipologia": "OPTATIVA"},
        ]
        with (
            patch.object(VentanaArbol, "_iniciar_descubrimiento"),
            patch.object(VentanaArbol, "_cargar_catalogo_local", return_value={"niveles_estudio": []}),
        ):
            ventana = VentanaArbol()
        try:
            # Repetir el renderizado no duplica entradas en el panel.
            for _ in range(2):
                ventana._mostrar_resultado(materias)
                self.assertEqual(ventana.lista.count(), 2)
                self.assertTrue(all("aislada" in ventana.lista.item(i).text() for i in range(2)))
                tarjetas = {item.codigo for item in ventana.vista.scene().items() if isinstance(item, TarjetaMateriaItem)}
                self.assertEqual(tarjetas, {"3007262", "2"})
                self.assertEqual(sum(isinstance(item, ConexionItem) for item in ventana.vista.scene().items()), 1)
                self.assertIn("2 sin conexiones", ventana.resumen.text())
            ventana._mostrar_resultado(materias[2:])
            self.assertEqual(ventana.lista.count(), 2)
            self.assertFalse(any(isinstance(item, TarjetaMateriaItem) for item in ventana.vista.scene().items()))
            ventana._mostrar_resultado([])
            self.assertEqual(ventana.lista.count(), 0)
        finally:
            ventana.close()

    def test_dibuja_raices_sus_flechas_y_examen_sin_tarjeta_gigante(self):
        grafo = construir_grafo([
            {"codigo": "1", "nombre": "Materia base", "tipologia": "OPTATIVA"},
            {"codigo": "2", "nombre": "Historia", "tipologia": "OBLIGATORIA",
             "prerrequisitos": [
                 {"codigo": "1", "nombre": "Materia base", "tipo": "M"},
                 {"nombre": "Base externa", "tipo": "M"},
                 {"codigo": "1000095", "nombre": "Examen de clasificación en inglés "
                  "Tipo de implica. M - no se puede matricular " + "explicación " * 100},
             ]},
        ])
        vista = VistaGrafo()
        try:
            vista.mostrar(grafo)
            tarjetas = {item.codigo: item for item in vista.scene().items() if isinstance(item, TarjetaMateriaItem)}
            self.assertEqual(set(tarjetas), {"1", "2", "externo:base externa", "1000095"})
            self.assertIn("OBLIGATORIA POR DEPENDENCIA", tarjetas["1"]._info.toPlainText())
            self.assertIn("Tipología original: OPTATIVA", tarjetas["1"].toolTip())
            self.assertTrue(hasattr(tarjetas["1"], "_indicador_obligatoria"))
            self.assertIn("EXTERNA", tarjetas["1000095"]._info.toPlainText())
            self.assertEqual(sum(isinstance(item, ConexionItem) for item in vista.scene().items()), 3)
            examen = tarjetas['1000095']
            self.assertEqual(examen._titulo.toPlainText(), 'Examen de clasificación en inglés')
            self.assertLess(examen.alto, 150)
            for tarjeta in tarjetas.values():
                self.assertTrue(vista.sceneRect().contains(tarjeta.sceneBoundingRect()))
        finally:
            vista.close()


if __name__ == '__main__':
    unittest.main()
