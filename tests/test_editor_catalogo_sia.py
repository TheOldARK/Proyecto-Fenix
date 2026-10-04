import asyncio
from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_editor_editar_materias as fixtures
from herramientas import editor_catalogo_sia as catalogo
from herramientas import editor_planes_estudio as editor
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox


class CatalogoWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_solo_catalogo_sin_abrir_fichas(self):
        sesion = Mock()
        sesion.cargar = AsyncMock(return_value={"100": {"codigo": "100-M", "nombre": "Cálculo", "grupos": [1]}})
        self.assertEqual(await catalogo.leer_nombres(sesion, Mock()), {"100": "Cálculo"})
        sesion.comprobar_ficha.assert_not_called()
        sesion.abrir_materia.assert_not_called()

    async def test_reintento_y_catalogo_vacio_no_es_exito(self):
        sesion = Mock()
        sesion.cargar = AsyncMock(side_effect=[TimeoutError(), {"1": {"nombre": "Materia"}}])
        self.assertEqual(await catalogo.leer_nombres(sesion, Mock()), {"1": "Materia"})
        self.assertEqual(sesion.cargar.await_count, 2)
        sesion.cargar = AsyncMock(return_value={})
        with self.assertRaises(ValueError):
            await catalogo.leer_nombres(sesion, Mock())

    async def test_cancelar_worker_espera_limpieza(self):
        cerrado = []
        async def consulta(*args):
            try:
                await asyncio.sleep(30)
            finally:
                cerrado.append(True)
        worker = catalogo.CatalogoNombresWorker("1", {})
        with patch.object(catalogo, "consultar_nombres", side_effect=consulta), patch.object(
            worker, "isInterruptionRequested", side_effect=[False, True]
        ):
            with self.assertRaises(asyncio.CancelledError):
                await worker._ejecutar()
        self.assertEqual(cerrado, [True])


class CatalogoEditorTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EditarMateriasTests.setUpClass.__func__)
    setUp = fixtures.EditarMateriasTests.setUp
    tearDown = fixtures.EditarMateriasTests.tearDown

    def test_autocompleta_y_desconocido_permite_nombre_manual(self):
        self.window.names_cache = {"1": {"nombres": {"400": "Nombre SIA"}}}
        self.window.course_code.setText("400-M")
        self.assertEqual(self.window.course_name.text(), "Nombre SIA")
        self.window.course_code.setText("999")
        self.assertEqual(self.window.course_name.text(), "")
        self.window.course_name.setText("Manual")
        self.window.add_course_to_plan()
        self.assertEqual(self.window.plans_doc["planes"]["1"]["nombres_asignaturas"]["999"], "Manual")

    def test_respuesta_otra_carrera_no_modifica_planes_y_guarda_cache(self):
        before = deepcopy(self.window.plans_doc)
        self.window.course_code.setText("400")
        self.window.course_name.setText("Mi nombre manual")
        with tempfile.TemporaryDirectory() as tmp:
            self.window.names_cache_path = Path(tmp) / "cache.json"
            self.window.receive_course_names("2", {"400": "SIA otra carrera"})
            saved = json.loads(self.window.names_cache_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["2"]["nombres"], {"400": "SIA otra carrera"})
        self.assertEqual(self.window.plans_doc, before)
        self.assertEqual(self.window.course_name.text(), "Mi nombre manual")
        self.window.course_code.setText("400-M")
        self.assertEqual(self.window.course_name.text(), "SIA Otra Carrera")

    def test_sugerencia_formateada_sin_reescribir_cache_ni_nombres_guardados(self):
        original = "ANALISIS ESTRUCTURAL I - CNT"
        self.window.names_cache = {"1": {"nombres": {"400": original}}}
        before = deepcopy(self.window.plans_doc)
        self.window.course_code.setText("400")
        self.assertEqual(self.window.course_name.text(), "Análisis Estructural I - CNT")
        self.assertEqual(self.window.names_cache["1"]["nombres"]["400"], original)
        self.assertEqual(self.window.plans_doc, before)
        self.window.course_name.setText("Mi versión manual")
        self.window.add_course_to_plan()
        self.assertEqual(self.window.plans_doc["planes"]["1"]["nombres_asignaturas"]["400"], "Mi versión manual")

    def test_no_inicia_dos_workers_y_cerrar_espera_finished(self):
        with patch.object(editor, "CatalogoNombresWorker") as cls:
            worker = cls.return_value
            self.window.fetch_course_names()
            self.window.fetch_course_names()
            cls.assert_called_once()
            worker.start.assert_called_once()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                event = QCloseEvent()
                self.window.closeEvent(event)
                self.assertFalse(event.isAccepted())
                worker.requestInterruption.assert_called_once()
                event = QCloseEvent()
                self.window.closeEvent(event)
                self.assertFalse(event.isAccepted())
            self.window.course_names_finished()
            self.assertIsNone(self.window.names_worker)

    def test_editar_codigo_autocompleta_nombre(self):
        dialog = editor.CourseDialog("100", "Original", [], lookup=lambda code: ["SIA"] if code == "400" else [])
        dialog.code.setText("400")
        dialog.code.textEdited.emit("400")
        self.assertEqual(dialog.name.text(), "SIA")
        dialog.code.textEdited.emit("999")
        self.assertEqual(dialog.name.text(), "")
        dialog.close()
