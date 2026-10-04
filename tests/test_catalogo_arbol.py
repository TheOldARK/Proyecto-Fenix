import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
import configuracion
from herramientas.arbol_prerrequisitos import (
    VentanaArbol, _buscar_ruta, completar_catalogo, crear_entorno_datos_temporal,
)


class CatalogoArbolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.base = json.loads(
            (configuracion.CARPETA_DATOS_BASE / "catalogo_sia.json").read_text(encoding="utf-8")
        )

    def test_incorpora_humanas_sin_borrar_otras_sedes_ni_mutar_entradas(self):
        anterior = deepcopy(self.base)
        sede = anterior["niveles_estudio"][0]["sedes"][0]
        sede["facultades"] = [f for f in sede["facultades"] if f["codigo"] != "3067"]
        otra_sede = {"codigo": "1101", "value": "2", "nombre": "Bogotá", "facultades": []}
        anterior["niveles_estudio"][0]["sedes"].append(otra_sede)
        copia = deepcopy(anterior)
        resultado = completar_catalogo(anterior, self.base)
        self.assertEqual(anterior, copia)
        self.assertIn(otra_sede, resultado["niveles_estudio"][0]["sedes"])
        for codigo in ("3512", "3513", "3514"):
            self.assertEqual(_buscar_ruta(resultado, f"1102:3067:{codigo}")[3]["codigo"], codigo)

    def test_valores_del_sia_tienen_prioridad_y_no_duplica_rutas(self):
        vivo = deepcopy(self.base)
        _buscar_ruta(vivo, "1102:3067:3512")[3]["value"] = "actualizado"
        resultado = completar_catalogo(vivo, self.base)
        self.assertEqual(_buscar_ruta(resultado, "1102:3067:3512")[3]["value"], "actualizado")
        self.assertEqual(len(VentanaArbol._aplanar_rutas(resultado)), len(VentanaArbol._aplanar_rutas(vivo)))

    def test_selector_incluye_tres_carreras_aunque_perfil_y_cache_sean_antiguos(self):
        anterior = deepcopy(self.base)
        sede = anterior["niveles_estudio"][0]["sedes"][0]
        sede["facultades"] = [f for f in sede["facultades"] if f["codigo"] != "3067"]
        with tempfile.TemporaryDirectory() as temporal:
            cache = Path(temporal) / "catalogo.json"
            cache.write_text(json.dumps(anterior), encoding="utf-8")
            with (
                patch.object(VentanaArbol, "_ruta_cache", return_value=cache),
                patch.object(configuracion, "ARCHIVO_CATALOGO_SIA", cache),
                patch.object(VentanaArbol, "_iniciar_descubrimiento"),
            ):
                ventana = VentanaArbol()
                try:
                    ventana.sede.setCurrentIndex(ventana.sede.findData("1102"))
                    ventana.facultad.setCurrentIndex(ventana.facultad.findData("3067"))
                    self.assertEqual(ventana.facultad.currentData(), "3067")
                    self.assertEqual(ventana.plan.count(), 3)
                    self.assertEqual(
                        {ventana.plan.itemData(i)["clave"] for i in range(3)},
                        {f"1102:3067:{c}" for c in ("3512", "3513", "3514")},
                    )
                finally:
                    ventana.close()
                self.assertEqual(json.loads(cache.read_text(encoding="utf-8")), anterior)

    def test_carga_base_sin_perfil_y_con_cache_ilegible(self):
        with tempfile.TemporaryDirectory() as temporal:
            cache = Path(temporal) / "cache.json"
            cache.write_text("{invalido", encoding="utf-8")
            with (
                patch.object(VentanaArbol, "_ruta_cache", return_value=cache),
                patch.object(configuracion, "ARCHIVO_CATALOGO_SIA", Path(temporal) / "inexistente.json"),
            ):
                catalogo = VentanaArbol._cargar_catalogo_local(VentanaArbol)
            self.assertEqual(catalogo, self.base)

    def test_nuevas_carreras_generan_entorno_de_consulta_sin_necesitar_malla(self):
        for codigo in ("3512", "3513", "3514"):
            with self.subTest(codigo=codigo), tempfile.TemporaryDirectory() as temporal:
                destino = Path(temporal) / "datos"
                clave = f"1102:3067:{codigo}"
                crear_entorno_datos_temporal(destino, self.base, clave, "0")
                catalogo = json.loads((destino / "catalogo_sia.json").read_text(encoding="utf-8"))
                self.assertEqual(_buscar_ruta(catalogo, clave)[2]["codigo"], "3067")


if __name__ == "__main__":
    unittest.main()
