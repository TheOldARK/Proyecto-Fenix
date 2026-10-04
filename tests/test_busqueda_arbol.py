import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from herramientas.arbol_prerrequisitos import TarjetaMateriaItem, VentanaArbol


class BusquedaArbolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch.object(VentanaArbol, "_iniciar_descubrimiento"), patch.object(
            VentanaArbol, "_cargar_catalogo_local", return_value={"niveles_estudio": []}
        ):
            self.ventana = VentanaArbol()
        self.addCleanup(self.ventana.close)
        self.ventana._mostrar_resultado([
            {"codigo": "1000004-M", "nombre": "Cálculo", "tipologia": "OBLIGATORIA"},
            {"codigo": "1000005", "nombre": "Integral", "tipologia": "OPTATIVA",
             "prerrequisitos": [{"codigo": "1000004", "tipo": "M"}]},
            {"codigo": "3000000", "nombre": "Aislada", "tipologia": "OPTATIVA"},
        ])

    def tarjeta(self, codigo):
        return next(i for i in self.ventana.vista.scene().items()
                    if isinstance(i, TarjetaMateriaItem) and i.codigo == codigo)

    def test_codigo_con_o_sin_sufijo_y_limpieza(self):
        tarjeta = self.tarjeta("1000004-M")
        posicion, fondo = tarjeta.pos(), tarjeta.brush()
        for codigo in ("1000004", " 1000004-m "):
            self.ventana.buscador_codigo.setText(codigo)
            self.assertEqual(tarjeta.pen().color().name(), "#ffd54a")
            self.assertEqual(tarjeta.pos(), posicion)
        self.ventana.buscador_codigo.setText("1000005")
        self.assertEqual(tarjeta.brush(), fondo)
        self.assertEqual(self.tarjeta("1000005").pen().color().name(), "#ffd54a")
        self.ventana.buscador_codigo.clear()
        self.assertEqual(self.tarjeta("1000005").pen().color().name(), "#555555")
        self.assertEqual(self.ventana.resultado_busqueda.text(), "")

    def test_lista_lateral_y_materia_oculta(self):
        self.ventana.buscador_codigo.setText("3000000")
        self.assertEqual(self.ventana.lista.item(0).background().color().name(), "#ffd54a")
        self.ventana.modo.setCurrentIndex(2)
        self.assertIn("oculta", self.ventana.resultado_busqueda.text())
        self.ventana.modo.setCurrentIndex(1)
        self.assertEqual(self.tarjeta("3000000").pen().color().name(), "#ffd54a")

    def test_enter_centra_sin_mover_ni_cambiar_zoom(self):
        tarjeta = self.tarjeta("1000004-M")
        tarjeta.setPos(900, 600)
        zoom = self.ventana.vista.transform()
        self.ventana.buscador_codigo.setText("1000004")
        with patch.object(self.ventana.vista, "centerOn") as centrar:
            self.ventana.buscador_codigo.returnPressed.emit()
            centrar.assert_called_once_with(tarjeta)
        self.assertEqual(tarjeta.pos().x(), 900)
        self.assertEqual(self.ventana.vista.transform(), zoom)

    def test_inexistente_y_nuevo_resultado(self):
        self.ventana.buscador_codigo.setText("1000")
        self.assertIn("No se encontró", self.ventana.resultado_busqueda.text())
        self.ventana.buscador_codigo.setText("1000004")
        self.ventana._mostrar_resultado([])
        self.assertIn("No se encontró", self.ventana.resultado_busqueda.text())

    def test_nombre_parcial_sin_tildes_ni_mayusculas(self):
        for consulta in ("CALCULO", " cál ", "cal", "CA\u0301LCULO"):
            self.ventana.buscador_codigo.setText(consulta)
            self.assertEqual(self.tarjeta("1000004-M").pen().color().name(), "#ffd54a")
        self.ventana.buscador_codigo.setText("integral")
        self.assertEqual(self.tarjeta("1000004-M").pen().color().name(), "#555555")
        self.assertEqual(self.tarjeta("1000005").pen().color().name(), "#ffd54a")

    def test_nombre_lateral_y_oculto_por_modo(self):
        self.ventana.buscador_codigo.setText("aisl")
        self.assertEqual(self.ventana.lista.item(0).background().color().name(), "#ffd54a")
        self.ventana.modo.setCurrentIndex(2)
        self.assertIn("oculta", self.ventana.resultado_busqueda.text())
        self.ventana.modo.setCurrentIndex(1)
        self.assertEqual(self.tarjeta("3000000").pen().color().name(), "#ffd54a")

    def test_nombre_con_guion_y_multiples_coincidencias(self):
        self.ventana._mostrar_resultado([
            {"codigo": "1", "nombre": "Teoría físico-química", "tipologia": "OBLIGATORIA"},
            {"codigo": "2", "nombre": "Teoría física", "tipologia": "OBLIGATORIA"},
        ])
        self.ventana.modo.setCurrentIndex(1)
        self.ventana.buscador_codigo.setText("teoria")
        for codigo in ("1", "2"):
            self.assertEqual(self.tarjeta(codigo).pen().color().name(), "#ffd54a")
        self.assertIn("2 coincidencia", self.ventana.resultado_busqueda.text())
        self.ventana.buscador_codigo.setText("fisico-quimica")
        self.assertEqual(self.tarjeta("1").pen().color().name(), "#ffd54a")
        self.assertEqual(self.tarjeta("2").pen().color().name(), "#555555")


if __name__ == "__main__":
    unittest.main()
