import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main


class PublicacionParcialTests(unittest.TestCase):
    def test_publica_materias_validas_y_reporta_las_que_fallaron(self):
        codigo = "1102:3068:3528"
        plan = SimpleNamespace(
            codigo="3528",
            nombre="Plan de prueba",
            sede_codigo="1102",
            sede_nombre="Medellín",
            facultad_codigo="3068",
            facultad_nombre="Minas",
            valor_sede="sede",
            valor_facultad="facultad",
            valor_plan="plan",
            nombres_asignaturas=["Materia válida"],
            semestres=[SimpleNamespace(numero=1, asignaturas=["3001"], creditos=3)],
        )
        fallida_normal = {"codigo": "3991", "nombre": "Materia pendiente", "error": "No hallada"}
        fallida_libre = {"codigo": "3992", "nombre": "Libre pendiente", "error": "No hallada"}
        actualizacion = {
            "materias": [{"codigo": "3001", "nombre": "Materia válida"}],
            "libres_eleccion": [{"codigo": "3002", "nombre": "Libre válida"}],
            "catalogo_libres_consultado": True,
            "materias_fallidas": [fallida_normal],
            "libres_fallidas": [fallida_libre],
        }

        with tempfile.TemporaryDirectory(prefix="fenix-publicacion-parcial-") as temporal:
            raiz = Path(temporal)
            rutas = {
                "ARCHIVO_MATERIAS": raiz / "materias.json",
                "ARCHIVO_OFERTA": raiz / "oferta.json",
                "ARCHIVO_LIBRES_ELECCION": raiz / "libres_eleccion.json",
                "ARCHIVO_ESTUDIANTE": raiz / "estudiante.json",
            }
            for ruta in rutas.values():
                ruta.write_text("{}", encoding="utf-8")

            actualizar_falsa = Mock()
            publicar_falsa = Mock()

            def ejecutar_actualizacion(_corutina):
                for campo, ruta in rutas.items():
                    if campo != "ARCHIVO_ESTUDIANTE":
                        ruta.write_text(json.dumps({"materias": []}), encoding="utf-8")
                callback = actualizar_falsa.call_args.kwargs["al_terminar_obligatorias"]
                callback(actualizacion["materias"], actualizacion["materias_fallidas"])
                return actualizacion

            with (
                patch.object(main, "ARCHIVO_MATERIAS", rutas["ARCHIVO_MATERIAS"]),
                patch.object(main, "ARCHIVO_OFERTA", rutas["ARCHIVO_OFERTA"]),
                patch.object(main, "ARCHIVO_LIBRES_ELECCION", rutas["ARCHIVO_LIBRES_ELECCION"]),
                patch.object(main, "ARCHIVO_ESTUDIANTE", rutas["ARCHIVO_ESTUDIANTE"]),
                patch.object(main, "seleccionar_planes_publicables", return_value=({codigo: plan}, [])),
                patch.object(main, "cargar_planes", return_value={}),
                patch.object(main, "cargar_estudiante", return_value={"plan_estudios": "otro"}),
                patch.object(main, "guardar_estudiante"),
                patch.object(main, "cargar_cache_publicador", return_value=(
                    {"normal": {}, "libre_eleccion": {}},
                    {"normal": {}, "libre_eleccion": {}},
                )),
                patch.object(main, "guardar_cache_publicador"),
                patch.object(main, "cargar_libres_eleccion_sede", return_value=[]),
                patch.object(main, "configurar_contexto_publicador"),
                patch.object(main, "guardar_estado"),
                patch.object(main, "actualizar", actualizar_falsa),
                patch.object(main.asyncio, "run", side_effect=ejecutar_actualizacion),
                patch.object(main, "publicar_planes", publicar_falsa),
            ):
                resumen = main.ejecutar_publicador(codigo)

        self.assertEqual(publicar_falsa.call_count, 2)
        self.assertEqual(resumen["materias_pendientes"], 2)
        self.assertEqual(resumen["unidades_actualizadas"], 2)


if __name__ == "__main__":
    unittest.main()
