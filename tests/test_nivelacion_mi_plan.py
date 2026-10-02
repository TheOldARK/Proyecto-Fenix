"""Nivelación debe mostrarse debajo de la malla con tarjetas marcables."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

import aplicacion.interfaz as interfaz
from aplicacion.interfaz import DialogoPlan, VentanaPlanEstudios
from servicios.tipos_materia import es_materia_nivelacion


def test_clasificacion_nivelacion():
    assert es_materia_nivelacion({"nombre": "INGLÉS I", "tipologia": "NIVELACIÓN (E)"})
    assert not es_materia_nivelacion({"nombre": "BASES DE DATOS", "tipologia": "DISCIPLINAR OBLIGATORIA"})


def test_tarjetas_de_nivelacion_debajo_de_la_malla():
    app = QApplication.instance() or QApplication([])
    class VentanaFalsa(QWidget):
        def __init__(self):
            super().__init__()
            self.codigo_plan = "1102:3068:3534"
            self.planes = {self.codigo_plan: SimpleNamespace(
                nombre="Sistemas", codigo="3534", nombres_asignaturas={"1000004": "Cálculo Diferencial"},
                sede_codigo="1102", facultad_codigo="3068", facultad_nombre="Minas",
                semestres=[SimpleNamespace(numero=1, asignaturas=["1000004"])],
            )}
            self.materias_aprobadas = {"1000044"}
            self.cambios_masivos = []
            self.referencias = []
            self.materias_locales = {
                "1000045-M": {"codigo": "1000045-M", "nombre": "Inglés II", "tipologia": "NIVELACIÓN (E)", "grupos": []},
            }
            self.materias_por_origen = {"principal": [
                {"codigo": "1000004-M", "nombre": "Cálculo Diferencial", "tipologia": "FUND. OBLIGATORIA", "grupos": []},
                {"codigo": "1000044-M", "nombre": "Inglés I", "tipologia": "NIVELACIÓN (E)", "grupos": []},
            ], "libre": []}

        def abrir_grupos_desde_plan(self, _codigo):
            pass

        def cambiar_materia_aprobada_desde_plan(self, _codigo, _aprobado):
            pass

        def cambiar_materias_aprobadas_desde_plan(self, codigos, aprobado):
            self.cambios_masivos.append((set(codigos), aprobado))
            if aprobado:
                self.materias_aprobadas.update(codigos)
            else:
                self.materias_aprobadas.difference_update(codigos)
            self.ventana_plan.reconstruir()

    parent = VentanaFalsa()
    window = VentanaPlanEstudios(parent)
    parent.ventana_plan = window
    sections = [window.diagrama.itemAt(i).widget() for i in range(window.diagrama.count())]
    titles = [[label.text() for label in section.findChildren(QLabel)] for section in sections if section]
    assert any("MALLA CURRICULAR" in group for group in titles)
    assert any("NIVELACIÓN" in group for group in titles)
    level_section = next(section for section in sections if section and any(label.text() == "NIVELACIÓN" for label in section.findChildren(QLabel)))
    assert any(label.text() == "Inglés I" for label in level_section.findChildren(QLabel))
    assert any(label.text() == "Inglés II" for label in level_section.findChildren(QLabel))
    assert any(button.text() == "✓" for button in level_section.findChildren(QPushButton))
    captura = os.environ.get("FENIX_CAPTURA_NIVELACION")
    if captura:
        window.show()
        app.processEvents()
        window.area.verticalScrollBar().setValue(window.area.verticalScrollBar().maximum())
        app.processEvents()
        assert window.grab().save(captura)
    def boton_actual():
        return next(
            boton for indice in range(window.diagrama.count())
            if (seccion := window.diagrama.itemAt(indice).widget()) is not None
            if (boton := seccion.findChild(QPushButton, "botonTodasNivelaciones")) is not None
        )

    boton_todas = boton_actual()
    assert boton_todas.text() == "Marcar todas"
    window.show()
    window.area.horizontalScrollBar().setValue(0)
    window.area.verticalScrollBar().setValue(window.area.verticalScrollBar().maximum())
    app.processEvents()
    boton_todas = boton_actual()
    inicio = boton_todas.mapTo(window.area.viewport(), QPoint(0, 0)).x()
    fin = boton_todas.mapTo(window.area.viewport(), QPoint(boton_todas.width(), 0)).x()
    assert inicio >= 0 and fin <= window.area.viewport().width()
    boton_todas.click()
    assert parent.materias_aprobadas == {"1000044", "1000045"}
    assert parent.cambios_masivos == [({"1000044", "1000045"}, True)]
    boton_todas = boton_actual()
    assert boton_todas.text() == "Desmarcar todas"
    boton_todas.click()
    assert not parent.materias_aprobadas
    assert parent.cambios_masivos[-1] == ({"1000044", "1000045"}, False)
    window.close()
    parent.close()
    app.processEvents()


def test_nivelacion_ganada_solo_por_defecto():
    app = QApplication.instance() or QApplication([])
    key = "1102:3068:3534"
    plan = SimpleNamespace(
        nombre="Sistemas", codigo="3534", sede_codigo="1102", facultad_codigo="3068",
        facultad_nombre="Minas", nombres_asignaturas={"1000004": "Cálculo Diferencial"},
        semestres=[SimpleNamespace(numero=1, asignaturas=["1000004"])],
    )
    oferta = {
        "1000004-M": {"codigo": "1000004-M", "nombre": "Cálculo Diferencial", "tipologia": "FUND. OBLIGATORIA"},
        "1000044-M": {"codigo": "1000044-M", "nombre": "Inglés I", "tipologia": "NIVELACIÓN (E)"},
    }
    dialog = DialogoPlan({key: plan}, oferta)
    dialog.selector_facultad.setCurrentIndex(1)
    dialog.selector.setCurrentIndex(1)
    approved_items = [dialog.materias_elegidas.item(i) for i in range(dialog.materias_elegidas.count())]
    level = next(item for item in approved_items if item.data(Qt.ItemDataRole.UserRole) == "1000044")
    dialog.mover_materias(dialog.materias_elegidas, dialog.materias_disponibles, [level])
    dialog.selector_tipo.setCurrentIndex(2)
    assert all(dialog.materias_elegidas.item(i).data(Qt.ItemDataRole.UserRole) != "1000044"
               for i in range(dialog.materias_elegidas.count()))
    dialog.close()
    app.processEvents()


def test_nivelacion_se_marca_cuando_llegan_datos_despues_del_perfil():
    class PerfilFalso:
        def __init__(self):
            self.codigo_plan = "1102:3068:3534"
            self.planes = {self.codigo_plan: SimpleNamespace(nombre="Sistemas")}
            self.estudiante = {"nivelaciones_pendientes": True, "grupos_seleccionados": []}
            self.materias_aprobadas = set()
            self.referencias = []
            self.etiqueta_plan = SimpleNamespace(setText=lambda _texto: None)
            self.guardados = 0

        def guardar_estado_estudiante(self):
            self.guardados += 1

        def actualizar_aviso_libres_eleccion(self):
            pass

        def actualizar_materias_para_mostrar(self):
            pass

    perfil = PerfilFalso()
    local = {"materias": {}}
    with patch.object(interfaz, "cargar_oferta", return_value={"materias": {}}), \
         patch.object(interfaz, "cargar_materias", side_effect=lambda: local["materias"]), \
         patch.object(interfaz, "cargar_libres_eleccion", return_value=[]), \
         patch.object(interfaz, "codigos_recomendados", return_value=set()):
        interfaz.VentanaPrincipal.recargar_datos(perfil)
        assert perfil.estudiante["nivelaciones_pendientes"]
        local["materias"] = {
            "1000044-M": {"codigo": "1000044-M", "nombre": "Inglés I", "tipologia": "NIVELACIÓN (E)"}
        }
        interfaz.VentanaPrincipal.recargar_datos(perfil)
        assert perfil.materias_aprobadas == {"1000044"}
        assert not perfil.estudiante["nivelaciones_pendientes"]
        assert perfil.guardados == 1
        perfil.materias_aprobadas.clear()
        interfaz.VentanaPrincipal.recargar_datos(perfil)
        assert not perfil.materias_aprobadas


def test_cambio_masivo_guarda_y_actualiza_una_sola_vez():
    contador = {"guardar": 0, "recargar": 0, "interfaz": 0}
    perfil = SimpleNamespace(
        materias_aprobadas=set(),
        materias_locales={
            "1000044-M": {
                "codigo": "1000044-M", "prerrequisitos": [{"codigo": "1000002-M"}]
            }
        },
        materias_por_origen={"principal": [], "libre": []},
        guardar_estado_estudiante=lambda: contador.__setitem__("guardar", contador["guardar"] + 1),
        recargar_datos=lambda: contador.__setitem__("recargar", contador["recargar"] + 1),
        actualizar_interfaz=lambda: contador.__setitem__("interfaz", contador["interfaz"] + 1),
    )
    interfaz.VentanaPrincipal.cambiar_materias_aprobadas_desde_plan(
        perfil, {"1000044", "1000045"}, True
    )
    assert {"1000044", "1000045", "1000002"}.issubset(perfil.materias_aprobadas)
    assert contador == {"guardar": 1, "recargar": 1, "interfaz": 1}
    interfaz.VentanaPrincipal.cambiar_materias_aprobadas_desde_plan(
        perfil, {"1000044", "1000045"}, False
    )
    assert perfil.materias_aprobadas == {"1000002"}
    assert contador == {"guardar": 2, "recargar": 2, "interfaz": 2}


if __name__ == "__main__":
    test_clasificacion_nivelacion()
    test_tarjetas_de_nivelacion_debajo_de_la_malla()
    test_nivelacion_ganada_solo_por_defecto()
    test_nivelacion_se_marca_cuando_llegan_datos_despues_del_perfil()
    test_cambio_masivo_guarda_y_actualiza_una_sola_vez()
    print("Nivelación en Mi Plan: OK")
