"""Editor privado para mantener planes de estudio locales de Fénix.

Esta herramienta modifica únicamente los datos de desarrollo indicados por el
usuario; no se importa desde el cliente ni publica información en servicios.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from configuracion import CARPETA_DATOS  # noqa: E402
from dominio.codigos import codigo_base  # noqa: E402
from herramientas.editor_catalogo_sia import CatalogoNombresWorker  # noqa: E402
from herramientas.nombres_materias import sugerir_nombre_materia  # noqa: E402

DATA_DIR = ROOT / "datos"
PROFILE_DIR = CARPETA_DATOS
PLANS_FILE = DATA_DIR / "planes_estudio.json"
SIA_FILE = DATA_DIR / "catalogo_sia.json"
ELECTIVES_FILE = DATA_DIR / "configuracion_libre_eleccion.json"
SEMESTERS = 10


def semester_count(plan):
    """La duración se obtiene de la malla; diez solo es el valor inicial."""
    numbers = [int(key) for key in plan.get("semestres", {}) if str(key).isdigit() and int(key) > 0]
    return max(numbers, default=SEMESTERS)

def read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def merge_missing(primary, reference):
    """Añade al perfil local datos del repositorio que aún no existan allí.

    Los valores existentes del perfil tienen prioridad para conservar cambios
    locales; en listas jerárquicas del catálogo SIA se incorporan elementos
    nuevos por código.
    """
    if isinstance(primary, dict) and isinstance(reference, dict):
        merged = deepcopy(primary)
        for key, value in reference.items():
            if key not in merged:
                merged[key] = deepcopy(value)
            else:
                merged[key] = merge_missing(merged[key], value)
        return merged
    if isinstance(primary, list) and isinstance(reference, list):
        if all(isinstance(item, dict) for item in primary + reference):
            merged = []
            indexes = {}

            def identity(item):
                code = item.get("codigo")
                if code is not None:
                    return ("codigo", str(code))
                name = item.get("nombre")
                if name is not None:
                    return ("nombre", str(name).casefold(), str(item.get("value", "")))
                return None

            for item in primary + reference:
                item_identity = identity(item)
                if item_identity is not None and item_identity in indexes:
                    index = indexes[item_identity]
                    merged[index] = merge_missing(merged[index], item)
                    continue
                merged.append(deepcopy(item))
                if item_identity is not None:
                    indexes[item_identity] = len(merged) - 1
            return merged
        merged = deepcopy(primary)
        return merged if merged else deepcopy(reference)
    return deepcopy(primary) if primary not in (None, "", [], {}) else deepcopy(reference)


def load_editor_json(profile_path: Path, repository_path: Path, fallback):
    repository_data = read_json(repository_path, fallback)
    profile_data = read_json(profile_path, repository_data)
    return merge_missing(profile_data, repository_data)


def write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=4)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


class CourseDialog(QDialog):
    def __init__(self, code, name, other_codes, parent=None, lookup=None):
        super().__init__(parent)
        self.setWindowTitle("Editar materia")
        self.setMinimumWidth(480)
        self.other_codes = {codigo_base(value).casefold() for value in other_codes}
        form = QFormLayout(self)
        self.code = QLineEdit(code)
        self.name = QLineEdit(name)
        form.addRow("Código", self.code)
        form.addRow("Nombre", self.name)
        if lookup:
            def completar(text):
                known = lookup(text.strip())
                self.name.setText(name if text.strip() == code else (known[0] if known else ""))
            self.code.textEdited.connect(completar)
        note = QLabel(
            "Se actualizará únicamente este plan, conservando los semestres asignados. "
            "Para guardar en los archivos, usa «Guardar planes y configuración SIA»."
        )
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return self.code.text().strip(), self.name.text().strip()

    def accept(self):
        code, name = self.values()
        if not codigo_base(code) or not name:
            QMessageBox.warning(self, "Faltan datos", "El código y el nombre no pueden quedar vacíos.")
            return
        if codigo_base(code).casefold() in self.other_codes:
            QMessageBox.warning(self, "Código duplicado", "Ese código ya pertenece a otra materia de este plan.")
            return
        super().accept()


class PlanDialog(QDialog):
    def __init__(self, existing: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datos del plan · Fénix")
        self.setMinimumWidth(520)
        existing = existing or {}
        form = QFormLayout(self)
        self.fields = {}
        labels = (
            ("codigo", "Código del plan"),
            ("nombre", "Nombre del programa"),
            ("sede_codigo", "Código de sede"),
            ("sede_nombre", "Nombre de sede"),
            ("facultad_codigo", "Código de facultad"),
            ("facultad_nombre", "Nombre de facultad"),
            ("valor_sede", "Valor del selector SIA · sede"),
            ("valor_facultad", "Valor del selector SIA · facultad"),
            ("valor_plan", "Valor del selector SIA · plan"),
        )
        for key, label in labels:
            field = QLineEdit(str(existing.get(key, "")))
            field.setPlaceholderText(label)
            form.addRow(label, field)
            self.fields[key] = field
        self.electives = QLineEdit(", ".join(existing.get("facultades_libre_eleccion", [])))
        self.electives.setPlaceholderText("p. ej. 3 SEDE MEDELLÍN, 3068 FACULTAD DE MINAS")
        form.addRow("Opciones SIA de libre elección", self.electives)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        result = {key: field.text().strip() for key, field in self.fields.items()}
        result["facultades_libre_eleccion"] = [
            value.strip() for value in self.electives.text().split(",") if value.strip()
        ]
        return result

    def accept(self):
        required = ("codigo", "nombre", "sede_codigo", "sede_nombre", "facultad_codigo", "facultad_nombre", "valor_sede", "valor_facultad", "valor_plan")
        missing = [key for key in required if not self.fields[key].text().strip()]
        if missing:
            QMessageBox.warning(self, "Faltan datos", "Completa todos los datos del plan y los valores de los selectores SIA.")
            return
        if not self.electives.text().strip():
            QMessageBox.warning(self, "Faltan opciones", "Añade las opciones de facultad para la búsqueda de libre elección, separadas por comas.")
            return
        super().accept()


class FacultyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Añadir facultad · Fénix")
        form = QFormLayout(self)
        defaults = {
            "sede_codigo": "1102",
            "sede_nombre": "1102 SEDE MEDELLÍN",
            "valor_sede": "6",
        }
        self.fields = {}
        for key, label in (
            ("sede_codigo", "Código de sede"),
            ("sede_nombre", "Nombre de sede"),
            ("valor_sede", "Valor del selector SIA · sede"),
            ("facultad_codigo", "Código de facultad"),
            ("facultad_nombre", "Nombre de facultad"),
            ("valor_facultad", "Valor del selector SIA · facultad"),
        ):
            field = QLineEdit(defaults.get(key, ""))
            form.addRow(label, field)
            self.fields[key] = field
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return {key: field.text().strip() for key, field in self.fields.items()}

    def accept(self):
        if any(not field.text().strip() for field in self.fields.values()):
            QMessageBox.warning(self, "Faltan datos", "Completa todos los campos de la facultad.")
            return
        super().accept()


class EditorPlanes(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Editor privado de planes de estudio · Fénix")
        self.resize(1120, 760)
        # El Publicador usa el perfil de datos de Fénix en LocalAppData,
        # mientras que los builds leen los JSON incluidos en el repositorio.
        # El editor carga el perfil activo y al guardar sincroniza ambos.
        self.plans_doc = load_editor_json(
            PROFILE_DIR / PLANS_FILE.name, PLANS_FILE, {"planes": {}}
        )
        self.sia_doc = load_editor_json(
            PROFILE_DIR / SIA_FILE.name,
            SIA_FILE,
            {"niveles_estudio": [], "tipologias": []},
        )
        for level in self.sia_doc.get("niveles_estudio", []):
            for seat in level.get("sedes", []):
                for faculty in seat.get("facultades", []):
                    faculty["planes_estudio"] = [
                        plan for plan in faculty.get("planes_estudio", [])
                        if str(plan.get("codigo", "")).strip().upper() not in {"PENDIENTE", "POR_CONFIRMAR"}
                    ]
        self.electives_doc = load_editor_json(
            PROFILE_DIR / ELECTIVES_FILE.name, ELECTIVES_FILE, {}
        )
        if not isinstance(self.plans_doc.get("planes"), dict):
            raise ValueError("planes_estudio.json no contiene un objeto 'planes'.")
        self.current_key = None
        self.current_semester = None
        self.names_cache_path = PROFILE_DIR / "herramientas" / "editor_planes" / "nombres_sia.json"
        self.names_cache = read_json(self.names_cache_path, {})
        if not isinstance(self.names_cache, dict):
            self.names_cache = {}
        self.names_worker = None
        self.close_after_worker = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        intro = QLabel(
            "Herramienta privada de desarrollo. Edita planes, materias por semestre "
            "y las rutas/valores del catálogo SIA. Guardar modifica únicamente los "
            "JSON locales; no publica nada."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        toolbar = QHBoxLayout()
        self.faculty_selector = QComboBox()
        self.faculty_selector.currentIndexChanged.connect(self.faculty_changed)
        toolbar.addWidget(QLabel("Facultad"))
        toolbar.addWidget(self.faculty_selector, 1)
        self.plan_selector = QComboBox()
        self.plan_selector.currentIndexChanged.connect(self.load_selected)
        toolbar.addWidget(QLabel("Carrera"))
        toolbar.addWidget(self.plan_selector, 1)
        add_faculty_button = QPushButton("Añadir facultad")
        add_faculty_button.clicked.connect(self.add_faculty)
        toolbar.addWidget(add_faculty_button)
        add_career_button = QPushButton("Añadir carrera")
        add_career_button.clicked.connect(self.add_career)
        toolbar.addWidget(add_career_button)
        edit_button = QPushButton("Editar sede/facultad y SIA")
        edit_button.clicked.connect(self.edit_metadata)
        toolbar.addWidget(edit_button)
        layout.addLayout(toolbar)

        self.metadata = QLabel("Selecciona o crea un plan.")
        self.metadata.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.metadata)
        editor = QSplitter(Qt.Orientation.Horizontal)
        semester_panel = QWidget()
        semester_layout = QVBoxLayout(semester_panel)
        semester_layout.setContentsMargins(0, 0, 4, 0)
        semester_layout.addWidget(QLabel("Cantidad de semestres"))
        self.semester_count_spin = QSpinBox()
        self.semester_count_spin.setRange(1, 99)
        self.semester_count_spin.setValue(SEMESTERS)
        semester_layout.addWidget(self.semester_count_spin)
        self.apply_semester_count_button = QPushButton("Aplicar cantidad")
        self.apply_semester_count_button.clicked.connect(self.change_semester_count)
        semester_layout.addWidget(self.apply_semester_count_button)
        self.semester_list = QListWidget()
        self.semester_list.setMinimumWidth(150)
        self.semester_list.currentRowChanged.connect(self.load_semester)
        semester_layout.addWidget(self.semester_list)
        editor.addWidget(semester_panel)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.addWidget(QLabel("Materias registradas en este plan"))
        self.plan_courses = QListWidget()
        self.plan_courses.currentItemChanged.connect(self.update_course_button)
        self.plan_courses.itemDoubleClicked.connect(lambda _item: self.add_course_to_semester())
        right_layout.addWidget(self.plan_courses, 3)

        course_actions = QHBoxLayout()
        self.course_code = QLineEdit()
        self.course_code.setPlaceholderText("Código de la materia")
        self.course_code.returnPressed.connect(self.add_course_from_code)
        course_actions.addWidget(self.course_code, 1)
        add_course_button = QPushButton("Añadir materia al plan")
        add_course_button.clicked.connect(self.add_course_to_plan)
        course_actions.addWidget(add_course_button)
        right_layout.addLayout(course_actions)
        self.course_name = QLineEdit()
        self.course_name.setPlaceholderText("Nombre: se completa por código; también puedes escribirlo")
        self.course_name.returnPressed.connect(self.add_course_to_plan)
        self.course_code.textChanged.connect(self.autocomplete_course_name)
        right_layout.addWidget(self.course_name)
        sia_actions = QHBoxLayout()
        self.fetch_names_button = QPushButton("Consultar códigos y nombres SIA")
        self.fetch_names_button.clicked.connect(self.fetch_course_names)
        self.cancel_names_button = QPushButton("Cancelar consulta")
        self.cancel_names_button.clicked.connect(self.cancel_course_names)
        self.cancel_names_button.setEnabled(False)
        self.names_progress = QProgressBar()
        self.names_progress.setRange(0, 0)
        self.names_progress.setTextVisible(False)
        self.names_progress.hide()
        sia_actions.addWidget(self.fetch_names_button)
        sia_actions.addWidget(self.cancel_names_button)
        sia_actions.addWidget(self.names_progress)
        right_layout.addLayout(sia_actions)
        self.names_status = QLabel("Consulta el SIA para reconocer códigos. No se descargan grupos ni se añaden materias al plan.")
        self.names_status.setWordWrap(True)
        right_layout.addWidget(self.names_status)

        selection_actions = QHBoxLayout()
        self.edit_course_button = QPushButton("Editar materia seleccionada")
        self.edit_course_button.clicked.connect(self.edit_course)
        selection_actions.addWidget(self.edit_course_button)
        self.add_semester_button = QPushButton("Añadir seleccionada al semestre ↓")
        self.add_semester_button.clicked.connect(self.add_course_to_semester)
        selection_actions.addWidget(self.add_semester_button)
        remove_course_button = QPushButton("Quitar del plan")
        remove_course_button.clicked.connect(self.remove_course_from_plan)
        selection_actions.addWidget(remove_course_button)
        right_layout.addLayout(selection_actions)

        right_layout.addWidget(QLabel("Materias del semestre seleccionado"))
        self.semester_courses = QListWidget()
        self.semester_courses.itemDoubleClicked.connect(lambda _item: self.remove_course_from_semester())
        right_layout.addWidget(self.semester_courses, 2)
        semester_actions = QHBoxLayout()
        remove_semester_button = QPushButton("Quitar del semestre")
        remove_semester_button.clicked.connect(self.remove_course_from_semester)
        semester_actions.addWidget(remove_semester_button)
        semester_actions.addStretch()
        right_layout.addLayout(semester_actions)

        credits = QHBoxLayout()
        credits.addWidget(QLabel("Créditos libre elección"))
        self.creditos_libres = QSpinBox()
        self.creditos_libres.setRange(0, 99)
        credits.addWidget(self.creditos_libres)
        credits.addWidget(QLabel("Fund. optativa"))
        self.creditos_fund_opt = QSpinBox()
        self.creditos_fund_opt.setRange(0, 99)
        credits.addWidget(self.creditos_fund_opt)
        credits.addWidget(QLabel("Disc. optativa"))
        self.creditos_disc_opt = QSpinBox()
        self.creditos_disc_opt.setRange(0, 99)
        credits.addWidget(self.creditos_disc_opt)
        right_layout.addLayout(credits)
        editor.addWidget(right)
        editor.setStretchFactor(0, 0)
        editor.setStretchFactor(1, 1)
        layout.addWidget(editor, 1)

        note = QLabel(
            "Escribe un código para añadir una materia al plan. Si ya aparece en "
            "otro plan, Fénix reutiliza su nombre; si no, podrás escribirlo. "
            "Selecciona una materia de la lista superior y añádela al semestre."
            " Pulsa Enter en el código para añadirla al plan y al semestre seleccionado."
            " Usa «Editar materia seleccionada» para corregir su nombre o código."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        save_button = QPushButton("Guardar planes y configuración SIA")
        save_button.clicked.connect(self.save_all)
        layout.addWidget(save_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.refresh_selector()
        self.setStyleSheet("QMainWindow, QWidget { background: #171717; color: #f2f2f2; } QLineEdit, QComboBox, QListWidget, QSpinBox { background: #242424; color: #f2f2f2; border: 1px solid #555; padding: 5px; } QListWidget::item { padding: 6px; } QListWidget::item:selected { background: #31583e; } QPushButton { background: #294a35; color: white; border: 1px solid #49c77a; padding: 7px 12px; border-radius: 5px; }")

    def faculties(self):
        result = {}
        for level in self.sia_doc.get("niveles_estudio", []):
            for seat in level.get("sedes", []):
                for faculty in seat.get("facultades", []):
                    code = str(faculty.get("codigo", "")).strip()
                    if not code:
                        continue
                    result[(str(seat.get("codigo", "")), code)] = {
                        "sede_codigo": str(seat.get("codigo", "")),
                        "sede_nombre": str(seat.get("nombre", "")),
                        "valor_sede": str(seat.get("value", "")),
                        "facultad_codigo": code,
                        "facultad_nombre": str(faculty.get("nombre", "")),
                        "valor_facultad": str(faculty.get("value", "")),
                    }
        for plan in self.plans_doc["planes"].values():
            code = str(plan.get("facultad_codigo", "")).strip()
            if not code:
                continue
            key = (str(plan.get("sede_codigo", "")), code)
            result.setdefault(key, {
                "sede_codigo": str(plan.get("sede_codigo", "")),
                "sede_nombre": str(plan.get("sede_nombre", "")),
                "valor_sede": str(plan.get("valor_sede", "")),
                "facultad_codigo": code,
                "facultad_nombre": str(plan.get("facultad_nombre", "")),
                "valor_facultad": str(plan.get("valor_facultad", "")),
            })
        return sorted(result.values(), key=lambda item: (item["sede_nombre"].casefold(), item["facultad_nombre"].casefold(), item["facultad_codigo"]))

    def refresh_selector(self, select_key=None, faculty_code=None, seat_code=None):
        selected_plan = self.plans_doc["planes"].get(str(select_key), {}) if select_key else {}
        if not faculty_code:
            faculty_code = selected_plan.get("facultad_codigo")
        if seat_code is None:
            seat_code = selected_plan.get("sede_codigo")
        if not faculty_code:
            current_faculty = self.faculty_selector.currentData()
            if isinstance(current_faculty, (tuple, list)):
                faculty_code = current_faculty[1]
        available = self.faculties()

        self.faculty_selector.blockSignals(True)
        self.faculty_selector.clear()
        for faculty in available:
            label = f'{faculty["facultad_nombre"]} · {faculty["sede_nombre"]}'
            self.faculty_selector.addItem(label, (faculty["sede_codigo"], faculty["facultad_codigo"]))
        selected_seat = str(seat_code or "")
        selected_faculty = str(faculty_code or "")
        target = next(
            (i for i in range(self.faculty_selector.count())
             if self.faculty_selector.itemData(i) == (selected_seat, selected_faculty)
             or (not selected_seat and self.faculty_selector.itemData(i)[1] == selected_faculty)),
            -1,
        )
        if target < 0 and self.faculty_selector.count():
            target = 0
        self.faculty_selector.setCurrentIndex(target)
        self.faculty_selector.blockSignals(False)
        self.populate_career_selector(select_key)

    def populate_career_selector(self, select_key=None):
        faculty_key = self.faculty_selector.currentData()
        self.plan_selector.blockSignals(True)
        self.plan_selector.clear()
        matching = []
        if faculty_key:
            seat_code, faculty_code = faculty_key
            matching = [
                (key, plan) for key, plan in self.plans_doc["planes"].items()
                if str(plan.get("sede_codigo", "")) == str(seat_code)
                and str(plan.get("facultad_codigo", "")) == str(faculty_code)
            ]
        for key, plan in sorted(matching, key=lambda pair: (str(pair[1].get("nombre", "")).casefold(), str(pair[1].get("codigo", "")))):
            self.plan_selector.addItem(f'{plan.get("nombre", "Carrera sin nombre")} · {plan.get("codigo", key)}', key)
        if select_key is not None:
            index = self.plan_selector.findData(str(select_key))
            if index >= 0:
                self.plan_selector.setCurrentIndex(index)
        elif self.plan_selector.count():
            self.plan_selector.setCurrentIndex(0)
        self.plan_selector.blockSignals(False)
        if self.plan_selector.count():
            self.load_selected()
        else:
            self.populate_empty()

    def faculty_changed(self, *_args):
        if self.current_key and not self.save_current(False):
            return
        self.populate_career_selector()

    def populate_empty(self):
        self.metadata.setText("No hay un plan seleccionado.")
        self.current_key = None
        self.current_semester = None
        self.semester_list.clear()
        self.semester_count_spin.setEnabled(False)
        self.apply_semester_count_button.setEnabled(False)
        self.plan_courses.clear()
        self.semester_courses.clear()
        self.creditos_libres.setValue(0)
        self.creditos_fund_opt.setValue(0)
        self.creditos_disc_opt.setValue(0)

    def load_selected(self):
        key = self.plan_selector.currentData()
        if key is None:
            return
        if not self.save_current(show_message=False):
            QMessageBox.warning(
                self,
                "No se pudo cambiar de plan",
                "Corrige los datos del semestre actual antes de cambiar de plan.",
            )
            self.plan_selector.blockSignals(True)
            self.plan_selector.setCurrentIndex(self.plan_selector.findData(self.current_key))
            self.plan_selector.blockSignals(False)
            return
        self.current_key = str(key)
        plan = self.plans_doc["planes"][self.current_key]
        self.current_semester = None
        self.metadata.setText(
            f'Plan {plan.get("codigo", key)} · {plan.get("sede_nombre", "")} · '
            f'{plan.get("facultad_nombre", "")} · clave {self.current_key}'
        )
        self.populate_plan_courses()
        self.refresh_semesters()
        self.autocomplete_course_name()

    def refresh_semesters(self, selected=1):
        count = semester_count(self.plans_doc["planes"][self.current_key])
        self.semester_count_spin.setEnabled(True)
        self.apply_semester_count_button.setEnabled(True)
        self.semester_count_spin.setMaximum(max(99, count))
        self.semester_count_spin.setValue(count)
        self.current_semester = None
        self.semester_list.blockSignals(True)
        self.semester_list.clear()
        for number in range(1, count + 1):
            self.semester_list.addItem(f"Semestre {number}")
        row = max(0, min(selected, count) - 1)
        self.semester_list.setCurrentRow(row)
        self.semester_list.blockSignals(False)
        self.load_semester(row, save_previous=False)

    def change_semester_count(self):
        if not self.current_key or not self.save_current(False):
            return
        plan = self.plans_doc["planes"][self.current_key]
        count = self.semester_count_spin.value()
        semesters = plan.setdefault("semestres", {})
        removed = [key for key in semesters if str(key).isdigit() and int(key) > count]
        occupied = [key for key in removed if semesters[key].get("asignaturas")
                    or any(semesters[key].get("creditos", {}).values())]
        if occupied:
            QMessageBox.warning(
                self, "Semestres con información",
                "No se puede reducir la cantidad: los semestres "
                + ", ".join(sorted(occupied, key=int))
                + " contienen materias o créditos. Reubica las materias y los "
                "créditos antes de quitar esos semestres. No se ha eliminado nada.",
            )
            self.semester_count_spin.setValue(semester_count(plan))
            return
        selected = self.current_semester or 1
        for key in removed:
            del semesters[key]
        for number in range(1, count + 1):
            semesters.setdefault(str(number), {"asignaturas": [], "creditos": {}})
        self.refresh_semesters(selected)
        self.populate_plan_courses()

    def course_codes_for_plan(self, plan):
        codes = []
        for semester in plan.get("semestres", {}).values():
            for code in semester.get("asignaturas", []):
                code = str(code)
                if code not in codes:
                    codes.append(code)
        for code in plan.get("nombres_asignaturas", {}):
            code = str(code)
            if code not in codes:
                codes.append(code)
        return codes

    def populate_plan_courses(self, select_code=None):
        self.plan_courses.clear()
        if not self.current_key:
            return
        plan = self.plans_doc["planes"][self.current_key]
        names = plan.setdefault("nombres_asignaturas", {})
        assignments = {}
        for semester_number, semester in plan.get("semestres", {}).items():
            for code in semester.get("asignaturas", []):
                assignments.setdefault(str(code), []).append(str(semester_number))
        for code in self.course_codes_for_plan(plan):
            name = str(names.get(code, "Materia sin nombre"))
            used_in = assignments.get(code, [])
            if used_in:
                semesters_text = ", ".join(sorted(used_in, key=lambda value: int(value) if value.isdigit() else 999))
                marker = f"✓  Semestre(s) {semesters_text}"
                color = QColor("#70D99A")
                detail = f"Asignada en semestre(s): {semesters_text}"
            else:
                marker = "⚠  SIN ASIGNAR"
                color = QColor("#F2C14E")
                detail = "Está registrada en el plan, pero aún no se ha asignado a ningún semestre."
            item = QListWidgetItem(f"{code}  ·  {name}     [{marker}]")
            item.setData(Qt.ItemDataRole.UserRole, code)
            item.setForeground(color)
            item.setToolTip(detail)
            self.plan_courses.addItem(item)
            if code == select_code:
                self.plan_courses.setCurrentItem(item)
        self.update_course_button()

    def load_semester(self, row, save_previous=True):
        if row < 0 or row >= self.semester_list.count():
            return
        if save_previous and self.current_key and self.current_semester is not None:
            if not self.save_semester():
                return
        self.current_semester = row + 1
        if not self.current_key:
            self.semester_courses.clear()
            return
        plan = self.plans_doc["planes"][self.current_key]
        semester = plan.setdefault("semestres", {}).setdefault(
            str(self.current_semester), {"asignaturas": [], "creditos": {}}
        )
        names = plan.get("nombres_asignaturas", {})
        self.semester_courses.clear()
        for code in semester.get("asignaturas", []):
            code = str(code)
            item = QListWidgetItem(f"{code}  ·  {names.get(code, 'Materia sin nombre')}")
            item.setData(Qt.ItemDataRole.UserRole, code)
            self.semester_courses.addItem(item)
        credits = semester.get("creditos", {})
        self.creditos_libres.setValue(int(credits.get("libre_eleccion", 0) or 0))
        self.creditos_fund_opt.setValue(int(credits.get("fundamentacion_optativa", 0) or 0))
        self.creditos_disc_opt.setValue(int(credits.get("optativa_disciplinar", 0) or 0))
        self.update_course_button()

    def save_semester(self):
        if not self.current_key or self.current_semester is None:
            return True
        plan = self.plans_doc["planes"][self.current_key]
        semester = plan.setdefault("semestres", {}).setdefault(
            str(self.current_semester), {"asignaturas": [], "creditos": {}}
        )
        semester["asignaturas"] = [
            str(self.semester_courses.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.semester_courses.count())
        ]
        credits = {
            "libre_eleccion": self.creditos_libres.value(),
            "fundamentacion_optativa": self.creditos_fund_opt.value(),
            "optativa_disciplinar": self.creditos_disc_opt.value(),
        }
        semester["creditos"] = {key: value for key, value in credits.items() if value}
        return True

    def known_course_names(self, code):
        base = codigo_base(code)
        # Primero el catálogo consultado para esta carrera, luego otros planes.
        keys = [self.current_key] + [key for key in self.names_cache if key != self.current_key]
        for key in keys:
            entry = self.names_cache.get(key, {})
            if isinstance(entry, dict) and isinstance(entry.get("nombres"), dict):
                name = entry["nombres"].get(base)
                if isinstance(name, str) and name.strip():
                    return [sugerir_nombre_materia(name)]
        names = {}
        for plan in self.plans_doc["planes"].values():
            for key, value in plan.get("nombres_asignaturas", {}).items():
                name = str(value).strip()
                if codigo_base(key) == base and name:
                    names[name] = names.get(name, 0) + 1
        return sorted(names, key=lambda name: (-names[name], name.casefold()))

    def autocomplete_course_name(self, *_args):
        known = self.known_course_names(self.course_code.text().strip())
        self.course_name.setText(known[0] if known else "")

    def fetch_course_names(self):
        if not self.current_key or self.names_worker is not None:
            return
        plan = deepcopy(self.plans_doc["planes"][self.current_key])
        self.names_status.setText(f"Consultando {plan['nombre']}… Puedes seguir editando.")
        worker = CatalogoNombresWorker(self.current_key, plan, self)
        self.names_worker = worker
        worker.progreso.connect(lambda text: self.names_status.setText(f"{plan['nombre']} · {text}"))
        worker.resultado.connect(self.receive_course_names)
        worker.error.connect(lambda text: self.names_status.setText(
            f"No se pudo consultar {plan['nombre']}: {text}. Puedes reintentar o introducir el nombre manualmente."))
        worker.finished.connect(self.course_names_finished)
        self.fetch_names_button.setEnabled(False)
        self.cancel_names_button.setEnabled(True)
        self.names_progress.show()
        worker.start()

    def cancel_course_names(self):
        if self.names_worker is not None:
            self.names_worker.requestInterruption()
            self.cancel_names_button.setEnabled(False)
            self.names_status.setText("Cancelando consulta y cerrando el navegador…")

    def receive_course_names(self, key, names):
        self.names_cache[key] = {"actualizado_en": datetime.now(timezone.utc).isoformat(), "nombres": names}
        mensaje = f"{len(names)} códigos y nombres obtenidos para {self.plans_doc['planes'].get(key, {}).get('nombre', key)}. Sin consultar grupos."
        try:
            write_json_atomic(self.names_cache_path, self.names_cache)
        except OSError as error:
            mensaje += f" No se pudo guardar el catálogo auxiliar: {error}. Se usará durante esta sesión."
        self.names_status.setText(mensaje)
        if not self.course_name.text().strip():
            self.autocomplete_course_name()

    def course_names_finished(self):
        worker, self.names_worker = self.names_worker, None
        if worker:
            worker.deleteLater()
        self.fetch_names_button.setEnabled(True)
        self.cancel_names_button.setEnabled(False)
        self.names_progress.hide()
        if self.close_after_worker:
            self.close()

    def add_course_from_code(self):
        """Enter en el código: registrar y asignar, solo si el registro terminó."""
        code = self.add_course_to_plan()
        if code and self.current_semester is not None:
            self.add_course_to_semester()

    def add_course_to_plan(self):
        if not self.current_key:
            QMessageBox.information(self, "Selecciona un plan", "Primero selecciona o crea un plan de estudios.")
            return
        if not self.save_current(False):
            return
        code = self.course_code.text().strip()
        if not code:
            QMessageBox.information(self, "Falta el código", "Escribe el código de la materia que quieres añadir.")
            return
        plan = self.plans_doc["planes"][self.current_key]
        names = plan.setdefault("nombres_asignaturas", {})
        entered_name = self.course_name.text().strip()
        if code in self.course_codes_for_plan(plan):
            if not str(names.get(code, "")).strip():
                known = self.known_course_names(code)
                if entered_name:
                    names[code] = entered_name
                elif len(known) == 1:
                    names[code] = known[0]
                elif known:
                    name, accepted = QInputDialog.getItem(
                        self, "Nombre encontrado en otros planes",
                        f"El código {code} aparece con más de un nombre. Elige el correcto:",
                        known, 0, False,
                    )
                    if accepted:
                        names[code] = name
                else:
                    name, accepted = QInputDialog.getText(
                        self, "Nombre de la materia",
                        f"No conozco el código {code}. Escribe el nombre de la materia:",
                    )
                    if accepted and name.strip():
                        names[code] = name.strip()
                if not str(names.get(code, "")).strip():
                    return
            self.populate_plan_courses(code)
            self.course_code.clear()
            return code

        known = self.known_course_names(code)
        if entered_name:
            name = entered_name
        elif len(known) == 1:
            name = known[0]
        elif known:
            name, accepted = QInputDialog.getItem(
                self,
                "Nombre encontrado en otros planes",
                f"El código {code} aparece con más de un nombre. Elige el correcto:",
                known,
                0,
                False,
            )
            if not accepted:
                return
        else:
            name, accepted = QInputDialog.getText(
                self,
                "Nueva materia",
                f"No conozco el código {code}. Escribe el nombre de la materia:",
            )
            if not accepted or not name.strip():
                return
            name = name.strip()

        names[code] = name
        self.populate_plan_courses(code)
        self.course_code.clear()
        return code

    def edit_course(self):
        item = self.plan_courses.currentItem()
        if not self.current_key or item is None:
            return
        if not self.save_current(False):
            return
        old_code = str(item.data(Qt.ItemDataRole.UserRole))
        plan = self.plans_doc["planes"][self.current_key]
        names = plan.setdefault("nombres_asignaturas", {})
        dialog = CourseDialog(
            old_code, str(names.get(old_code, "")),
            [code for code in self.course_codes_for_plan(plan) if code != old_code], self,
            lookup=self.known_course_names,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        code, name = dialog.values()
        # Reemplazar la clave en su posición, sin alterar otras materias ni planes.
        plan["nombres_asignaturas"] = {
            (code if key == old_code else key): (name if key == old_code else value)
            for key, value in names.items()
        }
        plan["nombres_asignaturas"][code] = name
        for semester in plan.get("semestres", {}).values():
            semester["asignaturas"] = [
                code if str(value) == old_code else value
                for value in semester.get("asignaturas", [])
            ]
        self.populate_plan_courses(code)
        if self.current_semester is not None:
            # No guardar la lista anterior: todavía contiene el código viejo.
            self.load_semester(self.current_semester - 1, save_previous=False)

    def update_course_button(self, *_args):
        self.edit_course_button.setEnabled(bool(self.current_key and self.plan_courses.currentItem()))
        self.add_semester_button.setEnabled(
            bool(self.current_key and self.current_semester and self.plan_courses.currentItem())
        )

    def add_course_to_semester(self):
        item = self.plan_courses.currentItem()
        if not self.current_key or self.current_semester is None or item is None:
            return
        if not self.save_current(False):
            return
        code = str(item.data(Qt.ItemDataRole.UserRole))
        plan = self.plans_doc["planes"][self.current_key]
        current_key = str(self.current_semester)
        semester = plan.setdefault("semestres", {}).setdefault(
            current_key, {"asignaturas": [], "creditos": {}}
        )
        codes = list(map(str, semester.get("asignaturas", [])))
        if code in codes:
            self.populate_plan_courses(code)
            return
        old_semester = next(
            (
                number for number, semester in plan.get("semestres", {}).items()
                if str(number) != current_key and code in map(str, semester.get("asignaturas", []))
            ),
            None,
        )
        if old_semester is not None:
            answer = QMessageBox.question(
                self,
                "Materia ya asignada",
                f"Esta materia ya está en el semestre {old_semester}. ¿Moverla al semestre {current_key}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            old = plan["semestres"][old_semester]
            old["asignaturas"] = [value for value in old.get("asignaturas", []) if str(value) != code]
        codes.append(code)
        semester["asignaturas"] = codes
        name = plan.get("nombres_asignaturas", {}).get(code, "Materia sin nombre")
        row_item = QListWidgetItem(f"{code}  ·  {name}")
        row_item.setData(Qt.ItemDataRole.UserRole, code)
        self.semester_courses.addItem(row_item)
        self.populate_plan_courses(code)

    def remove_course_from_semester(self):
        item = self.semester_courses.currentItem()
        if item is None or not self.current_key:
            return
        code = str(item.data(Qt.ItemDataRole.UserRole))
        semester = self.plans_doc["planes"][self.current_key]["semestres"][str(self.current_semester)]
        semester["asignaturas"] = [value for value in semester.get("asignaturas", []) if str(value) != code]
        self.semester_courses.takeItem(self.semester_courses.row(item))
        self.save_semester()
        self.populate_plan_courses(code)

    def remove_course_from_plan(self):
        item = self.plan_courses.currentItem()
        if item is None or not self.current_key:
            return
        code = str(item.data(Qt.ItemDataRole.UserRole))
        answer = QMessageBox.question(
            self,
            "Quitar materia del plan",
            f"¿Quitar {code} y su asignación de todos los semestres de este plan?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        plan = self.plans_doc["planes"][self.current_key]
        plan.get("nombres_asignaturas", {}).pop(code, None)
        for semester in plan.get("semestres", {}).values():
            semester["asignaturas"] = [value for value in semester.get("asignaturas", []) if str(value) != code]
        self.populate_plan_courses()
        self.load_semester(self.current_semester - 1, save_previous=False)

    def save_current(self, show_message=True):
        if not self.current_key or self.current_key not in self.plans_doc["planes"]:
            return True
        return self.save_semester()

    def save_all(self):
        if not self.save_current():
            return False
        try:
            for directory in (DATA_DIR, PROFILE_DIR):
                write_json_atomic(directory / PLANS_FILE.name, self.plans_doc)
                write_json_atomic(directory / SIA_FILE.name, self.sia_doc)
                write_json_atomic(directory / ELECTIVES_FILE.name, self.electives_doc)
        except OSError as error:
            QMessageBox.critical(
                self,
                "No se pudo guardar",
                f"No se pudieron guardar los archivos del plan.\n\n{error}",
            )
            return False
        QMessageBox.information(
            self,
            "Cambios guardados",
            "Los planes y las rutas SIA se guardaron en los datos de desarrollo "
            "y en el perfil activo de Fénix.",
        )
        return True

    def add_faculty(self):
        dialog = FacultyDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        metadata = dialog.values()
        existing = {
            (faculty["sede_codigo"], faculty["facultad_codigo"])
            for faculty in self.faculties()
        }
        key = (metadata["sede_codigo"], metadata["facultad_codigo"])
        if key in existing:
            QMessageBox.warning(self, "Facultad existente", "Esa facultad ya está registrada para la sede seleccionada.")
            return
        self.set_sia_faculty(metadata)
        self.refresh_selector(
            faculty_code=metadata["facultad_codigo"],
            seat_code=metadata["sede_codigo"],
        )

    def add_career(self):
        faculty_key = self.faculty_selector.currentData()
        if not faculty_key:
            QMessageBox.information(self, "Selecciona una facultad", "Selecciona o añade una facultad antes de agregar una carrera.")
            return
        seat_code, faculty_code = faculty_key
        faculty = next(
            (item for item in self.faculties()
             if item["sede_codigo"] == seat_code and item["facultad_codigo"] == faculty_code),
            None,
        )
        if not faculty:
            return
        existing = dict(faculty)
        existing["codigo"] = ""
        existing["nombre"] = ""
        existing["valor_plan"] = ""
        existing["facultades_libre_eleccion"] = [faculty["sede_nombre"], faculty["facultad_nombre"]]
        for plan in self.plans_doc["planes"].values():
            if str(plan.get("sede_codigo")) == seat_code and str(plan.get("facultad_codigo")) == faculty_code:
                existing["facultades_libre_eleccion"] = self.get_elective_route(plan) or existing["facultades_libre_eleccion"]
                break
        dialog = PlanDialog(existing, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        metadata = dialog.values()
        if (metadata["sede_codigo"], metadata["facultad_codigo"]) != (seat_code, faculty_code):
            QMessageBox.warning(
                self,
                "Facultad distinta",
                "La carrera debe pertenecer a la facultad seleccionada. "
                "Para usar otra facultad, selecciónala antes de añadir la carrera.",
            )
            return
        key = f'{metadata["sede_codigo"]}:{metadata["facultad_codigo"]}:{metadata["codigo"]}'
        if key in self.plans_doc["planes"]:
            QMessageBox.warning(self, "Plan existente", f"Ya existe la ruta {key}.")
            return
        plan = {
            "clave": key, "codigo": metadata["codigo"], "nombre": metadata["nombre"],
            "sede_codigo": metadata["sede_codigo"], "sede_nombre": metadata["sede_nombre"],
            "facultad_codigo": metadata["facultad_codigo"], "facultad_nombre": metadata["facultad_nombre"],
            "valor_sede": metadata["valor_sede"], "valor_facultad": metadata["valor_facultad"],
            "valor_plan": metadata["valor_plan"], "nombres_asignaturas": {},
            "semestres": {str(n): {"asignaturas": [], "creditos": {}} for n in range(1, SEMESTERS + 1)},
        }
        self.plans_doc["planes"][key] = plan
        self.set_sia_route(metadata)
        self.set_elective_route(metadata)
        self.refresh_selector(key)

    def edit_metadata(self):
        if not self.current_key or not self.save_current(True):
            return
        plan = self.plans_doc["planes"][self.current_key]
        metadata = dict(plan)
        route = self.get_elective_route(plan)
        metadata["facultades_libre_eleccion"] = route
        dialog = PlanDialog(metadata, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new = dialog.values()
        new_key = f'{new["sede_codigo"]}:{new["facultad_codigo"]}:{new["codigo"]}'
        if new_key != self.current_key and new_key in self.plans_doc["planes"]:
            QMessageBox.warning(self, "Plan existente", f"Ya existe la ruta {new_key}.")
            return
        for field in ("codigo", "nombre", "sede_codigo", "sede_nombre", "facultad_codigo", "facultad_nombre", "valor_sede", "valor_facultad", "valor_plan"):
            plan[field] = new[field]
        plan["clave"] = new_key
        self.set_sia_route(new)
        self.set_elective_route(new)
        if new_key != self.current_key:
            del self.plans_doc["planes"][self.current_key]
            self.plans_doc["planes"][new_key] = plan
            self.current_key = new_key
        self.refresh_selector(new_key)

    def set_sia_route(self, metadata):
        level = next((item for item in self.sia_doc.setdefault("niveles_estudio", []) if item.get("nombre", "").casefold() == "pregrado"), None)
        if level is None:
            level = {"value": "0", "nombre": "Pregrado", "sedes": []}
            self.sia_doc["niveles_estudio"].append(level)
        sede = next((item for item in level.setdefault("sedes", []) if str(item.get("codigo")) == metadata["sede_codigo"]), None)
        if sede is None:
            sede = {"value": metadata["valor_sede"], "nombre": metadata["sede_nombre"], "codigo": metadata["sede_codigo"], "facultades": []}
            level["sedes"].append(sede)
        else:
            sede.update(value=metadata["valor_sede"], nombre=metadata["sede_nombre"])
        self.set_sia_faculty(metadata)
        faculty = next(item for item in sede["facultades"] if str(item.get("codigo")) == metadata["facultad_codigo"])
        plans = faculty.setdefault("planes_estudio", [])
        plans[:] = [item for item in plans if str(item.get("codigo")) != metadata["codigo"]]
        plans.append({"value": metadata["valor_plan"], "nombre": f'{metadata["codigo"]} {metadata["nombre"]}', "codigo": metadata["codigo"]})

    def set_sia_faculty(self, metadata):
        level = next((item for item in self.sia_doc.setdefault("niveles_estudio", []) if item.get("nombre", "").casefold() == "pregrado"), None)
        if level is None:
            level = {"value": "0", "nombre": "Pregrado", "sedes": []}
            self.sia_doc["niveles_estudio"].append(level)
        seat = next((item for item in level.setdefault("sedes", []) if str(item.get("codigo")) == metadata["sede_codigo"]), None)
        if seat is None:
            seat = {
                "value": metadata["valor_sede"],
                "nombre": metadata["sede_nombre"],
                "codigo": metadata["sede_codigo"],
                "facultades": [],
            }
            level["sedes"].append(seat)
        else:
            seat.update(value=metadata["valor_sede"], nombre=metadata["sede_nombre"])
        faculty = next((item for item in seat.setdefault("facultades", []) if str(item.get("codigo")) == metadata["facultad_codigo"]), None)
        if faculty is None:
            faculty = {
                "value": metadata["valor_facultad"],
                "nombre": metadata["facultad_nombre"],
                "codigo": metadata["facultad_codigo"],
                "planes_estudio": [],
            }
            seat["facultades"].append(faculty)
        else:
            faculty.update(value=metadata["valor_facultad"], nombre=metadata["facultad_nombre"])

    def set_elective_route(self, metadata):
        sede = self.electives_doc.setdefault(metadata["sede_codigo"], {"sede": metadata["sede_nombre"], "planes": {}})
        sede["sede"] = metadata["sede_nombre"]
        sede.setdefault("planes", {})[f'{metadata["facultad_codigo"]}:{metadata["codigo"]}'] = {
            "facultad": metadata["facultad_nombre"],
            "plan": f'{metadata["codigo"]} {metadata["nombre"]}',
            "facultades_libre_eleccion": metadata["facultades_libre_eleccion"],
        }

    def get_elective_route(self, plan):
        seat = self.electives_doc.get(str(plan.get("sede_codigo")), {})
        route = seat.get("planes", {}).get(f'{plan.get("facultad_codigo")}:{plan.get("codigo")}', {})
        return route.get("facultades_libre_eleccion", [])

    def closeEvent(self, event):
        if self.close_after_worker:
            if self.names_worker is not None:
                event.ignore()
            else:
                event.accept()
            return
        if not self.save_current(True):
            event.ignore()
            return
        reply = QMessageBox.question(self, "Guardar cambios", "¿Guardar los cambios locales antes de cerrar?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        if reply == QMessageBox.StandardButton.Save:
            if not self.save_all():
                event.ignore()
                return
        if self.names_worker is not None:
            self.close_after_worker = True
            self.cancel_course_names()
            self.centralWidget().setEnabled(False)
            event.ignore()
            return
        event.accept()


def main():
    app = QApplication(sys.argv)
    try:
        window = EditorPlanes()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        QMessageBox.critical(None, "No se pudo abrir el editor", str(error))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
