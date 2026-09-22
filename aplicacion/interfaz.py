"""Interfaz principal del planificador académico Fénix.

El horario permanece visible mientras las asignaturas se gestionan desde la
barra lateral. El estado de la actualización se comparte mediante un JSON.
"""

import subprocess
import os
import logging
import re
import sys
import time
import unicodedata
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, Signal, QUrl, QLockFile, qInstallMessageHandler
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFrame, QGridLayout, QHBoxLayout, QLayout, QLabel, QListWidget, QListWidgetItem,
    QFileDialog, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QStackedLayout, QTextEdit, QVBoxLayout, QWidget,
)


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from infraestructura.almacenamiento.estado_actualizacion import cargar_estado, guardar_estado
from aplicacion.arranque import comando_fenix, preparar_entorno
from configuracion import CARPETA_DATOS, VERSION
from infraestructura.almacenamiento.cancelacion_actualizacion import solicitar_cancelacion
from infraestructura.almacenamiento.datos_estudiante import borrar_datos_estudiante
from infraestructura.almacenamiento.estudiante import cargar_estudiante, guardar_estudiante
from infraestructura.almacenamiento.materias import cargar_materias, preparar_materias_para_plan
from infraestructura.almacenamiento.materias_libre_eleccion import cargar_libres_eleccion
from infraestructura.almacenamiento.oferta_academica import cargar_oferta, preparar_oferta_para_plan
from infraestructura.almacenamiento.plan_estudios import cargar_planes
from infraestructura.almacenamiento.respaldo_fnx import exportar_fnx, importar_fnx
from dominio.horario import es_sesion_virtual
from servicios.conflictos import detectar_adyacencias, detalles_conflicto, sesiones_validas
from servicios.horarios import (
    crear_referencia, grupo_es_elegible, grupo_ocupa_bloque,
    grupos_seleccionados, materias_principales, referencias_iguales,
)
from servicios.recomendaciones import (
    codigo_base, codigos_recomendados, ordenar_materias,
)
from servicios.elegibilidad import materias_visibles
from servicios.elegibilidad import motivo_materia_no_mostrable
from servicios.tipos_materia import clasificar_tipo_materia


RUTA_LOGO = BASE_DIR / "recursos" / "logo.png"
RUTA_QR_DONACIONES = BASE_DIR / "recursos" / "qr_donaciones.png"
RUTA_GRACIAS = BASE_DIR / "recursos" / "gracias.png"
CORREO_CONTACTO = "mialvarezr@unal.edu.co"
URL_DONACIONES = "https://example.com/donaciones"
URL_PROFESORES_RECOMENDADOS = (
    "https://www.instagram.com/unmedopina/"
)

# Paleta neutra: verde = permitido, rojo = no permitido.
COLOR_FONDO = "#141414"
COLOR_SUPERFICIE = "#1D1D1D"
COLOR_SUPERFICIE_CLARA = "#272727"
COLOR_BARRA = "#181818"
COLOR_LINEA = "#5B5B5B"
COLOR_TEXTO = "#F2F2F2"
COLOR_TEXTO_SECUNDARIO = "#B6B6B6"
COLOR_VERDE = "#49C77A"
COLOR_VERDE_FONDO = "#1D3828"
COLOR_ROJO = "#EF6670"
COLOR_ROJO_FONDO = "#3A2024"

ANCHO_VENTANA = 1280
ALTO_VENTANA = 720
DIAS = (
    ("LUNES", "Lunes"), ("MARTES", "Martes"), ("MIÉRCOLES", "Miércoles"),
    ("JUEVES", "Jueves"), ("VIERNES", "Viernes"), ("SÁBADO", "Sábado"),
)
BLOQUES_HORARIO = (
    (6, 8), (8, 10), (10, 12), (12, 14), (14, 16), (16, 18), (18, 20),
)
TIPOS_CREDITOS_OFICIALES = (
    "Fundamentacion Obligatoria",
    "Fundamentacion Optativa",
    "Disciplinar Obligatoria",
    "Disciplinar Optativa",
    "Libre Eleccion",
    "Nivelacion",
    "Trabajo de Grado",
)
COLORES_MATERIAS = (
    ("#313131", "#F2F2F2"), ("#3B362F", "#F2F2F2"),
    ("#303830", "#F2F2F2"), ("#3A3030", "#F2F2F2"),
    ("#353238", "#F2F2F2"),
)


def limpiar_layout(layout):
    """Elimina los widgets de un layout que se va a reconstruir."""
    while layout.count():
        elemento = layout.takeAt(0)
        widget = elemento.widget()
        if widget is not None:
            widget.deleteLater()
        elif elemento.layout() is not None:
            limpiar_layout(elemento.layout())


def nombre_corto(nombre, longitud=23):
    nombre = str(nombre or "Materia")
    return nombre if len(nombre) <= longitud else f"{nombre[:longitud - 1]}…"


def clave_alfabetica(nombre):
    """Ordena títulos ignorando mayúsculas y tildes."""
    texto = unicodedata.normalize("NFD", str(nombre or ""))
    texto = "".join(caracter for caracter in texto if unicodedata.category(caracter) != "Mn")
    return texto.casefold()


def codigos_prerrequisitos(materia):
    """Normaliza prerrequisitos guardados como objetos o códigos simples."""
    if not isinstance(materia, dict):
        return []
    codigos = []
    for requisito in materia.get("prerrequisitos", []) or []:
        valor = requisito.get("codigo") if isinstance(requisito, dict) else requisito
        codigo = codigo_base(valor)
        if codigo and codigo not in codigos:
            codigos.append(codigo)
    return codigos


def codigo_numerico_plan(codigo):
    """Devuelve el código numérico para ordenar versiones descendentes.

    Los planes antiguos permanecen disponibles; esto solo hace que, entre
    planes con el mismo nombre y ubicación, el código mayor aparezca primero.
    """
    try:
        return int(str(codigo).rsplit(":", 1)[-1])
    except (TypeError, ValueError):
        return -1


def texto_horarios(grupo):
    """Presenta las sesiones de un grupo en una sola línea."""
    dias_cortos = {
        "LUNES": "Lun", "MARTES": "Mar", "MIÉRCOLES": "Mié",
        "JUEVES": "Jue", "VIERNES": "Vie", "SÁBADO": "Sáb", "DOMINGO": "Dom",
    }
    sesiones = []
    for sesion in grupo.get("horarios", []):
        dia = dias_cortos.get(str(sesion.get("dia", "")).upper(), "")
        inicio = sesion.get("hora_inicio", "")
        fin = sesion.get("hora_fin", "")
        aula = sesion.get("aula", "")
        ubicacion = "Virtual" if es_sesion_virtual(sesion) else aula
        sesiones.append(f"{dia} {inicio}–{fin}{' · ' + ubicacion if ubicacion else ''}")
    return "  |  ".join(sesiones) or "Horario no disponible"


def detalle_sesion_en_bloque(grupo, dia, hora, duracion):
    """Devuelve horas y salón de las sesiones que ocupan una franja."""
    inicio_bloque = hora * 60
    fin_bloque = inicio_bloque + (duracion * 60)
    detalles = []
    for dia_sesion, inicio, fin, sesion in sesiones_validas(grupo):
        if dia_sesion != dia or inicio >= fin_bloque or inicio_bloque >= fin:
            continue
        horas = f"{sesion.get('hora_inicio', '')}–{sesion.get('hora_fin', '')}"
        aula = "Virtual" if es_sesion_virtual(sesion) else str(sesion.get("aula", "")).strip()
        detalles.append(f"{horas} · {aula or 'Salón por confirmar'}")
    return " / ".join(detalles) or "Salón por confirmar"


def sesiones_fuera_de_horario_normal(grupo):
    """Devuelve sesiones dominicales o fuera de 06:00–20:00."""
    sesiones = []
    for dia, inicio, fin, sesion in sesiones_validas(grupo):
        if dia not in {dia_visible for dia_visible, _ in DIAS} or inicio < 360 or fin > 1200:
            sesiones.append(sesion)
    return sesiones


class DialogoPlan(QDialog):
    """Solicita el plan y las materias aprobadas durante el primer ingreso."""

    def __init__(self, planes, oferta, materias_conocidas=None, estudiante=None, parent=None, materias_libres=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar estudiante · Fénix")
        self.setModal(True)
        self.setMinimumWidth(760)
        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {COLOR_SUPERFICIE}; }}
            QLabel {{ color: {COLOR_TEXTO}; }}
            QComboBox {{ background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO};
                border: 1px solid {COLOR_LINEA}; border-radius: 7px; padding: 9px; }}
            QComboBox QAbstractItemView {{ background-color: {COLOR_SUPERFICIE_CLARA};
                color: {COLOR_TEXTO}; selection-background-color: {COLOR_VERDE};
                selection-color: #FFFFFF; }}
            QListWidget {{ background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO};
                border: 1px solid {COLOR_LINEA}; border-radius: 7px; padding: 4px; }}
            QPushButton {{ background-color: {COLOR_VERDE_FONDO}; color: {COLOR_TEXTO};
                border: 1px solid {COLOR_VERDE}; border-radius: 7px; font-weight: bold; padding: 8px 16px; }}
            QPushButton:hover {{ background-color: #294A35; }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 24)
        layout.setSpacing(12)
        titulo = QLabel("Configura tu avance académico")
        titulo.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(titulo)
        descripcion = QLabel(
            "Este es el único paso necesario para comenzar. Elige tu carrera y "
            "marca las materias que ya aprobaste; Fénix usará tu avance para "
            "mostrarte qué puedes cursar después."
        )
        descripcion.setWordWrap(True)
        descripcion.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO};")
        layout.addWidget(descripcion)
        paso_plan = QLabel("PASO 1 · Elige tu plan de estudios")
        paso_plan.setStyleSheet(
            f"color: {COLOR_VERDE}; font-size: 11px; font-weight: 700; margin-top: 5px;"
        )
        layout.addWidget(paso_plan)
        self.selector = QComboBox()
        self.selector.view().setStyleSheet(
            f"background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"selection-background-color: {COLOR_VERDE}; selection-color: #FFFFFF;"
        )
        self.selector.addItem("Selecciona tu plan de estudios…", None)
        for codigo, plan in sorted(
            planes.items(),
            key=lambda item: (
                clave_alfabetica(
                    f"{item[1].nombre} {item[1].sede_nombre} {item[1].facultad_nombre}"
                ),
                -codigo_numerico_plan(item[1].codigo),
                str(item[0]),
            ),
        ):
            ubicacion = " · ".join(
                parte for parte in (
                    plan.sede_nombre,
                    plan.facultad_nombre,
                ) if parte
            )
            etiqueta = f"{plan.nombre} · {plan.codigo}"
            if ubicacion:
                etiqueta += f" · {ubicacion}"
            self.selector.addItem(etiqueta, codigo)
        layout.addWidget(self.selector)
        paso_avance = QLabel("PASO 2 · Indica las materias que ya aprobaste")
        paso_avance.setStyleSheet(
            f"color: {COLOR_VERDE}; font-size: 11px; font-weight: 700; margin-top: 5px;"
        )
        layout.addWidget(paso_avance)
        indicacion = QLabel(
            "Selecciona una o varias materias y pulsa «Marcar como aprobadas», "
            "o haz doble clic. Las nivelaciones se incluirán automáticamente y "
            "los prerrequisitos conocidos también se marcarán."
        )
        indicacion.setWordWrap(True)
        indicacion.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        layout.addWidget(indicacion)
        self.mensaje_listas = QLabel("Elige primero tu plan de estudios para ver sus materias.")
        self.mensaje_listas.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        layout.addWidget(self.mensaje_listas)
        self.buscar_aprobadas = QLineEdit()
        self.buscar_aprobadas.setPlaceholderText("Buscar materia por nombre o código…")
        layout.addWidget(self.buscar_aprobadas)
        self.selector_tipo = QComboBox()
        self.selector_tipo.view().setStyleSheet(
            f"background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"selection-background-color: {COLOR_VERDE}; selection-color: #FFFFFF;"
        )
        self.selector_tipo.addItems([
            "Todos los tipos", "Normales", "Nivelación", "Optativas",
            "Trabajo de grado (P)", "Otros"
        ])
        self.selector_tipo.setToolTip("Filtra las materias aprobadas por tipo académico.")
        layout.addWidget(self.selector_tipo)
        listas = QHBoxLayout()
        listas.setSpacing(10)
        columna_disponibles = QVBoxLayout()
        titulo_disponibles = QLabel("MATERIAS DEL PLAN")
        titulo_disponibles.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px; font-weight: 700;"
        )
        columna_disponibles.addWidget(titulo_disponibles)
        ayuda_disponibles = QLabel("Selecciona las que ya aprobaste")
        ayuda_disponibles.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px;")
        columna_disponibles.addWidget(ayuda_disponibles)
        self.materias_disponibles = QListWidget()
        self.materias_disponibles.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.materias_disponibles.setMinimumHeight(250)
        columna_disponibles.addWidget(self.materias_disponibles)
        listas.addLayout(columna_disponibles, 1)
        controles = QVBoxLayout()
        controles.addStretch()
        self.boton_agregar_materias = QPushButton("Marcar como aprobadas  →")
        self.boton_quitar_materias = QPushButton("←  Quitar marca")
        self.boton_agregar_materias.setToolTip("Mover las materias seleccionadas a Materias aprobadas")
        self.boton_quitar_materias.setToolTip("Quitar la aprobación de las materias seleccionadas")
        controles.addWidget(self.boton_agregar_materias)
        controles.addWidget(self.boton_quitar_materias)
        controles.addStretch()
        listas.addLayout(controles)
        columna_elegidas = QVBoxLayout()
        titulo_elegidas = QLabel("MATERIAS APROBADAS")
        titulo_elegidas.setStyleSheet(
            f"color: {COLOR_VERDE}; font-size: 10px; font-weight: 700;"
        )
        columna_elegidas.addWidget(titulo_elegidas)
        ayuda_elegidas = QLabel("Nivelaciones y prerrequisitos pueden aparecer aquí automáticamente")
        ayuda_elegidas.setWordWrap(True)
        ayuda_elegidas.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px;")
        columna_elegidas.addWidget(ayuda_elegidas)
        self.materias_elegidas = QListWidget()
        self.materias_elegidas.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.materias_elegidas.setMinimumHeight(250)
        columna_elegidas.addWidget(self.materias_elegidas)
        listas.addLayout(columna_elegidas, 1)
        layout.addLayout(listas)
        self.botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.boton_confirmar = self.botones.button(QDialogButtonBox.StandardButton.Ok)
        self.botones.accepted.connect(self.accept)
        layout.addWidget(self.botones)
        self.planes = planes
        self.oferta = oferta if isinstance(oferta, dict) else {}
        self.materias_conocidas = (
            materias_conocidas if isinstance(materias_conocidas, dict) else {}
        )
        self.materias_libres = materias_libres if isinstance(materias_libres, list) else []
        if not self.oferta:
            descripcion.setText(
                "Mientras Fénix consulta la oferta, adelanta tu carrera y las materias "
                "que ya aprobaste. Podrás escoger grupos al finalizar la actualización."
            )
        aprobadas = {
            codigo_base(codigo)
            for codigo in (estudiante or {}).get("materias_aprobadas", [])
        }
        indice_plan_guardado = self.selector.findData(
            (estudiante or {}).get("plan_estudios")
        )
        if indice_plan_guardado > 0:
            self.selector.setCurrentIndex(indice_plan_guardado)
        self.aprobadas_iniciales = aprobadas
        self.selector.currentIndexChanged.connect(self.actualizar_materias)
        self.boton_agregar_materias.clicked.connect(self.agregar_materias)
        self.boton_quitar_materias.clicked.connect(self.quitar_materias)
        self.buscar_aprobadas.textChanged.connect(self.filtrar_materias)
        self.selector_tipo.currentIndexChanged.connect(self.actualizar_materias)
        self.materias_disponibles.itemDoubleClicked.connect(
            lambda item: (
                self.mover_materias(
                    self.materias_disponibles, self.materias_elegidas, [item]
                ),
                self._agregar_prerrequisitos_de_seleccionadas(),
            )
        )
        self.materias_elegidas.itemDoubleClicked.connect(
            lambda item: self.mover_materias(
                self.materias_elegidas, self.materias_disponibles, [item]
            )
        )
        self.actualizar_materias()

    def codigo_plan(self):
        return self.selector.currentData()

    def actualizar_materias(self):
        codigo_plan = self.selector.currentData()
        plan = self.planes.get(codigo_plan)
        if plan is None:
            self.materias_disponibles.clear()
            self.materias_elegidas.clear()
            self.selector_tipo.setVisible(False)
            self.selector_tipo.setEnabled(False)
            self.actualizar_estado_listas(False)
            return
        self.actualizar_estado_listas(True)
        hay_catalogo_sia = bool(self.oferta or self.materias_conocidas)
        self.selector_tipo.setVisible(hay_catalogo_sia)
        self.selector_tipo.setEnabled(hay_catalogo_sia)
        seleccionadas = {
            codigo_base(item.data(Qt.ItemDataRole.UserRole))
            for item in (
                self.materias_elegidas.item(indice)
                for indice in range(self.materias_elegidas.count())
            )
        }
        if not seleccionadas:
            seleccionadas = self.aprobadas_iniciales
        self.aprobadas_iniciales = set()
        self.materias_disponibles.clear()
        self.materias_elegidas.clear()
        codigos_plan = {
            codigo_base(codigo)
            for semestre in plan.semestres
            for codigo in semestre.asignaturas
        }
        nivelaciones = self.codigos_nivelacion(plan, codigos_plan)
        seleccionadas.update(nivelaciones)
        # Normalmente solo se muestran materias pertenecientes al plan
        # elegido. En la primera ejecución no hay catálogo SIA suficiente,
        # así que solo se permite trabajar con las obligatorias de la malla.
        # Después de analizar el SIA se amplía a otras tipologías normales,
        # pero nunca a Libre Elección dentro de este formulario.
        consulta = self.buscar_aprobadas.text().casefold().strip()
        filtro = self.selector_tipo.currentText()
        codigos = set(codigos_plan)
        if hay_catalogo_sia and (consulta or filtro != "Todos los tipos"):
            codigos.update(codigo_base(codigo) for codigo in self.oferta)
            codigos.update(codigo_base(codigo) for codigo in self.materias_conocidas)
        codigos.update(nivelaciones)
        # Un prerrequisito puede no pertenecer directamente a la malla. Si ya
        # fue añadido de forma automática debe seguir visible en Aprobadas.
        codigos.update(seleccionadas)
        opciones = []
        for codigo in codigos:
            materia = self.oferta.get(codigo) or self.materias_conocidas.get(codigo) or next(
                (
                    valor
                    for fuente in (self.oferta, self.materias_conocidas)
                    for clave, valor in fuente.items()
                    if codigo_base(clave) == codigo
                ),
                {},
            )
            tipo = self.tipo_materia(materia, codigo, codigos_plan)
            if codigo not in seleccionadas and filtro != "Todos los tipos" and tipo != filtro:
                continue
            nombre = (
                str(materia.get("nombre", "")).strip()
                or plan.nombres_asignaturas.get(codigo, "").strip()
                or "Nombre pendiente de actualización"
            )
            opciones.append((nombre, codigo, tipo))
        for nombre, codigo, tipo in sorted(opciones, key=lambda item: clave_alfabetica(item[0])):
            item = QListWidgetItem(f"{nombre}\nCódigo: {codigo} · {tipo}")
            item.setData(Qt.ItemDataRole.UserRole, codigo)
            destino = self.materias_elegidas if codigo in seleccionadas else self.materias_disponibles
            destino.addItem(item)

    def codigos_nivelacion(self, plan, codigos_plan=None):
        """Devuelve nivelaciones del plan, aunque aún no haya datos del SIA."""
        codigos_plan = codigos_plan or {
            codigo_base(codigo)
            for semestre in plan.semestres
            for codigo in semestre.asignaturas
        }
        indice = self._indice_materias_conocidas()
        nivelaciones = set()
        for codigo in codigos_plan | set(indice):
            materia = indice.get(codigo, {})
            nombre = str(
                materia.get("nombre")
                or plan.nombres_asignaturas.get(codigo, "")
            ).casefold()
            tipologia = str(materia.get("tipologia", "")).casefold()
            if "nivel" in f"{nombre} {tipologia}":
                nivelaciones.add(codigo)
        return nivelaciones

    def tipo_materia(self, materia, codigo, codigos_plan):
        return clasificar_tipo_materia(materia, codigo, codigos_plan)

    def actualizar_estado_listas(self, habilitadas):
        """Evita mostrar materias hasta que la persona escoja un plan."""
        self.materias_disponibles.setEnabled(habilitadas)
        self.materias_elegidas.setEnabled(habilitadas)
        self.boton_agregar_materias.setEnabled(habilitadas)
        self.boton_quitar_materias.setEnabled(habilitadas)
        self.boton_confirmar.setEnabled(habilitadas)
        self.mensaje_listas.setVisible(not habilitadas)

    @staticmethod
    def mover_materias(origen, destino, items=None):
        """Mueve materias entre las listas sin perder su código interno."""
        for item in list(items if items is not None else origen.selectedItems()):
            fila = origen.row(item)
            if fila >= 0:
                destino.addItem(origen.takeItem(fila))
        destino.sortItems()

    def agregar_materias(self):
        self.mover_materias(self.materias_disponibles, self.materias_elegidas)
        self._agregar_prerrequisitos_de_seleccionadas()

    def quitar_materias(self):
        self.mover_materias(self.materias_elegidas, self.materias_disponibles)

    def materias_aprobadas(self):
        codigos = [
            self.materias_elegidas.item(indice).data(Qt.ItemDataRole.UserRole)
            for indice in range(self.materias_elegidas.count())
        ]
        return self.expandir_prerrequisitos(codigos)

    def _indice_materias_conocidas(self):
        indice = {}
        for fuente in (self.oferta, self.materias_conocidas):
            for clave, materia in fuente.items():
                if not isinstance(materia, dict):
                    continue
                codigo = codigo_base(materia.get("codigo") or clave)
                if codigo:
                    anterior = indice.get(codigo, {})
                    combinada = {**anterior, **materia}
                    requisitos = []
                    for origen in (anterior, materia):
                        for requisito in origen.get("prerrequisitos", []) or []:
                            requisito_codigo = codigo_base(
                                requisito.get("codigo")
                                if isinstance(requisito, dict)
                                else requisito
                            )
                            if requisito_codigo and requisito_codigo not in {
                                codigo_base(item.get("codigo"))
                                if isinstance(item, dict)
                                else codigo_base(item)
                                for item in requisitos
                            }:
                                requisitos.append(requisito)
                    combinada["prerrequisitos"] = requisitos
                    indice[codigo] = combinada
        return indice

    def expandir_prerrequisitos(self, codigos):
        """Añade prerrequisitos conocidos de las materias seleccionadas."""
        resultado = {codigo_base(codigo) for codigo in codigos if codigo_base(codigo)}
        indice = self._indice_materias_conocidas()
        plan = self.planes.get(self.selector.currentData())
        permitidos = set(indice)
        if plan is not None:
            permitidos.update(
                codigo_base(codigo)
                for semestre in plan.semestres
                for codigo in semestre.asignaturas
            )
        pendientes = list(resultado)
        while pendientes:
            codigo = pendientes.pop()
            materia = indice.get(codigo, {})
            for requisito_codigo in codigos_prerrequisitos(materia):
                if not requisito_codigo or requisito_codigo not in permitidos:
                    continue
                if requisito_codigo not in resultado:
                    resultado.add(requisito_codigo)
                    pendientes.append(requisito_codigo)
        return sorted(resultado)

    def _agregar_prerrequisitos_de_seleccionadas(self):
        seleccionadas = [
            self.materias_elegidas.item(indice).data(Qt.ItemDataRole.UserRole)
            for indice in range(self.materias_elegidas.count())
        ]
        ampliadas = self.expandir_prerrequisitos(seleccionadas)
        nuevos = set(ampliadas) - {codigo_base(codigo) for codigo in seleccionadas}
        if not nuevos:
            return
        for indice in range(self.materias_disponibles.count() - 1, -1, -1):
            item = self.materias_disponibles.item(indice)
            if codigo_base(item.data(Qt.ItemDataRole.UserRole)) in nuevos:
                self.materias_elegidas.addItem(self.materias_disponibles.takeItem(indice))
        self.materias_elegidas.sortItems()

    def filtrar_materias(self, texto):
        """Filtra solo disponibles; las materias ganadas permanecen visibles."""
        # Al filtrar se permite buscar en el catálogo completo; sin búsqueda,
        # actualizar_materias vuelve a dejar únicamente el plan seleccionado.
        self.actualizar_materias()
        consulta = str(texto or "").casefold().strip()
        for indice in range(self.materias_disponibles.count()):
            item = self.materias_disponibles.item(indice)
            item.setHidden(bool(consulta) and consulta not in item.text().casefold())


class EtiquetaMateriaPlan(QLabel):
    """Texto de materia con caja fija y clic opcional para abrir sus grupos."""

    clicked = Signal()

    def mousePressEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(evento)


class TarjetaMateriaPlan(QFrame):
    """Tarjeta compacta que abre los grupos al hacer clic."""

    clicked = Signal()

    def __init__(self):
        super().__init__()

    def mouseReleaseEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(evento)


class CapaConexionesPlan(QWidget):
    """Dibuja flechas entre prerrequisitos de semestres consecutivos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.conexiones = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def establecer_conexiones(self, conexiones):
        self.conexiones = list(conexiones)
        self.update()

    def paintEvent(self, evento):
        super().paintEvent(evento)
        if not self.conexiones:
            return
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pintor.setPen(
            QPen(
                QColor(COLOR_VERDE).lighter(115),
                2,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        for origen, destino in self.conexiones:
            if not origen.isVisible() or not destino.isVisible():
                continue
            inicio_global = origen.mapToGlobal(
                QPoint(origen.width(), origen.height() // 2)
            )
            fin_global = destino.mapToGlobal(
                QPoint(0, destino.height() // 2)
            )
            inicio_local = self.mapFromGlobal(inicio_global)
            fin_local = self.mapFromGlobal(fin_global)
            inicio = QPointF(inicio_local)
            fin = QPointF(fin_local)
            distancia = max(12.0, (fin.x() - inicio.x()) / 2.0)
            camino = QPainterPath(inicio)
            camino.cubicTo(
                QPointF(inicio.x() + distancia, inicio.y()),
                QPointF(fin.x() - distancia, fin.y()),
                fin,
            )
            pintor.drawPath(camino)
            # Punta pequeña orientada hacia la materia dependiente.
            pintor.drawLine(fin, QPointF(fin.x() - 6, fin.y() - 4))
            pintor.drawLine(fin, QPointF(fin.x() - 6, fin.y() + 4))
        pintor.end()


class VentanaPlanEstudios(QDialog):
    """Malla curricular no modal, organizada por componente y semestre."""

    def __init__(self, ventana_principal):
        super().__init__(ventana_principal)
        self.ventana_principal = ventana_principal
        self.setWindowTitle("Plan de estudios · Fénix")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(1450, 860)
        self.setMinimumSize(900, 620)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_FONDO}; }} "
            f"QLabel {{ color: {COLOR_TEXTO}; }} "
            f"QScrollArea, QScrollArea#diagramaPlan {{ border: none; background-color: {COLOR_FONDO}; }} "
            f"QScrollArea#diagramaPlan QWidget {{ background-color: {COLOR_FONDO}; }} "
            f"QPushButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 7px; padding: 8px; "
            f"text-align: left; }} "
            f"QPushButton:hover {{ border-color: {COLOR_VERDE}; }}"
        )
        principal = QVBoxLayout(self)
        principal.setContentsMargins(20, 18, 20, 16)
        principal.setSpacing(12)
        encabezado = QHBoxLayout()
        encabezado.setSpacing(12)
        textos = QVBoxLayout()
        textos.setSpacing(3)
        self.titulo = QLabel()
        self.titulo.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {COLOR_TEXTO};")
        textos.addWidget(self.titulo)
        self.subtitulo = QLabel()
        self.subtitulo.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        textos.addWidget(self.subtitulo)
        encabezado.addLayout(textos, 1)
        self.resumen = QLabel()
        self.resumen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.resumen.setMinimumWidth(190)
        self.resumen.setStyleSheet(
            f"background-color: {COLOR_VERDE_FONDO}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_VERDE}; border-radius: 9px; "
            "padding: 9px 14px; font-size: 12px; font-weight: 800;"
        )
        encabezado.addWidget(self.resumen)
        principal.addLayout(encabezado)
        self.ayuda = QLabel(
            "La malla se lee de izquierda a derecha por semestre. Usa “Marcar aprobada” "
            "para actualizar tu avance y “Ver grupos” para llevar una materia al horario. "
            "Puedes dejar esta ventana abierta y continuar usando el planificador."
        )
        self.ayuda.setWordWrap(True)
        self.ayuda.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        principal.addWidget(self.ayuda)
        self.area = QScrollArea()
        self.area.setObjectName("diagramaPlan")
        self.area.setWidgetResizable(True)
        self.contenedor = QWidget()
        self.contenedor.setObjectName("contenedorPlan")
        self.contenedor.setStyleSheet(f"background-color: {COLOR_FONDO};")
        self.diagrama = QVBoxLayout(self.contenedor)
        self.diagrama.setContentsMargins(6, 6, 6, 12)
        self.diagrama.setSpacing(16)
        self.area.setWidget(self.contenedor)
        principal.addWidget(self.area, 1)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(self.hide)
        principal.addWidget(botones)
        self.reconstruir()

    def showEvent(self, evento):
        self.reconstruir()
        super().showEvent(evento)

    def reconstruir(self):
        limpiar_layout(self.diagrama)
        codigo_plan = self.ventana_principal.codigo_plan
        plan = self.ventana_principal.planes.get(codigo_plan) if codigo_plan else None
        if plan is None:
            self.titulo.setText("Plan de estudios no disponible")
            return
        aprobadas = self.ventana_principal.materias_aprobadas
        semestres = {semestre.numero: semestre for semestre in plan.semestres}
        cantidad_semestres = max(10, max(semestres, default=10))
        total_plan = sum(len(semestre.asignaturas) for semestre in plan.semestres)
        aprobadas_plan = {
            codigo_base(codigo)
            for semestre in plan.semestres
            for codigo in semestre.asignaturas
            if codigo_base(codigo) in aprobadas
        }
        seleccionadas = {
            codigo_base(referencia.get("codigo"))
            for referencia in self.ventana_principal.referencias
        }
        self.titulo.setText(plan.nombre)
        self.subtitulo.setText(
            f"Plan {plan.codigo} · {cantidad_semestres} semestres · desplázate horizontalmente para recorrer la malla"
        )
        self.resumen.setText(f"{len(aprobadas_plan)} de {total_plan}\naprobadas")

        indice = {
            codigo_base(materia.get("codigo")): materia
            for materias in self.ventana_principal.materias_por_origen.values()
            for materia in materias
        }
        materias_por_semestre = {}
        for numero in range(1, cantidad_semestres + 1):
            semestre = semestres.get(numero)
            for valor in (semestre.asignaturas if semestre else []):
                codigo = codigo_base(valor)
                materia = dict(indice.get(codigo, {}))
                materia.setdefault("codigo", codigo)
                materia.setdefault("nombre", plan.nombres_asignaturas.get(codigo, "Materia sin nombre"))
                tipologia = unicodedata.normalize(
                    "NFD", str(materia.get("tipologia", "")).casefold()
                )
                tipologia = "".join(c for c in tipologia if unicodedata.category(c) != "Mn")
                if "fundament" in tipologia or re.search(r"\bfund\.?\b", tipologia):
                    orden_tipo = 0
                elif "disciplin" in tipologia or not tipologia:
                    orden_tipo = 1
                else:
                    orden_tipo = 2
                materia["_orden_plan"] = orden_tipo
                materias_por_semestre.setdefault(numero, []).append(materia)

        for materias in materias_por_semestre.values():
            materias.sort(
                key=lambda materia: (
                    materia.get("_orden_plan", 2),
                    clave_alfabetica(materia.get("nombre", "")),
                )
            )
        self._ordenar_por_conexiones(materias_por_semestre, cantidad_semestres)
        self.diagrama.addWidget(
            self._crear_seccion(
                "MALLA CURRICULAR",
                "En cada semestre aparecen primero las materias de Fundamentación y luego las Disciplinares.",
                materias_por_semestre,
                cantidad_semestres,
                aprobadas,
                seleccionadas,
            )
        )
        self.diagrama.addStretch()

    @staticmethod
    def _ordenar_por_conexiones(materias_por_semestre, cantidad_semestres):
        """Alinea dependientes con sus requisitos para reducir cruces de flechas."""
        for numero in range(2, cantidad_semestres + 1):
            anteriores = materias_por_semestre.get(numero - 1, [])
            actuales = materias_por_semestre.get(numero, [])
            if not anteriores or len(actuales) < 2:
                continue
            posiciones = {
                codigo_base(materia.get("codigo")): indice
                for indice, materia in enumerate(anteriores)
            }
            ultimo_anterior = max(1, len(anteriores) - 1)
            ultimo_actual = max(1, len(actuales) - 1)

            def posicion_deseada(entrada):
                indice_original, materia = entrada
                orden_tipo = materia.get("_orden_plan", 2)
                posiciones_requisitos = [
                    posiciones[codigo]
                    for codigo in codigos_prerrequisitos(materia)
                    if codigo in posiciones
                ]
                if not posiciones_requisitos:
                    # Las materias sin conexión permanecen como separadores
                    # naturales entre las que sí necesitan alinearse. El tipo
                    # es la primera clave: Fundamentación nunca puede quedar
                    # después de Disciplinar por intentar enderezar una flecha.
                    return orden_tipo, float(indice_original), 1, indice_original
                promedio = sum(posiciones_requisitos) / len(posiciones_requisitos)
                posicion_escalada = promedio * ultimo_actual / ultimo_anterior
                return orden_tipo, posicion_escalada, 0, indice_original

            ordenadas = sorted(enumerate(actuales), key=posicion_deseada)
            materias_por_semestre[numero] = [materia for _, materia in ordenadas]

    def _crear_seccion(self, titulo, descripcion, materias, cantidad_semestres,
                       aprobadas, seleccionadas):
        seccion = QFrame()
        seccion.setObjectName("seccionPlan")
        seccion.setStyleSheet(
            f"QFrame#seccionPlan {{ background-color: {COLOR_SUPERFICIE}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 11px; }}"
        )
        layout = QVBoxLayout(seccion)
        layout.setContentsMargins(12, 11, 12, 13)
        layout.setSpacing(9)
        etiqueta = QLabel(titulo)
        etiqueta.setStyleSheet(
            f"background: transparent; color: {COLOR_VERDE}; "
            "font-size: 14px; font-weight: 900; border: none;"
        )
        layout.addWidget(etiqueta)
        ayuda = QLabel(descripcion)
        ayuda.setStyleSheet(
            f"background: transparent; color: {COLOR_TEXTO_SECUNDARIO}; "
            "font-size: 10px; border: none;"
        )
        layout.addWidget(ayuda)
        lienzo = QWidget()
        lienzo.setObjectName("lienzoPlan")
        lienzo.setStyleSheet("QWidget#lienzoPlan { background: transparent; border: none; }")
        superpuestas = QStackedLayout(lienzo)
        superpuestas.setContentsMargins(0, 0, 0, 0)
        superpuestas.setStackingMode(QStackedLayout.StackingMode.StackAll)
        base = QWidget()
        base.setObjectName("basePlan")
        base.setStyleSheet("QWidget#basePlan { background: transparent; border: none; }")
        fila = QHBoxLayout(base)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(8)
        tarjetas_por_codigo = {}
        for numero in range(1, cantidad_semestres + 1):
            columna_widget = QFrame()
            columna_widget.setObjectName("columnaSemestre")
            columna_widget.setFixedWidth(214)
            columna_widget.setStyleSheet(
                f"QFrame#columnaSemestre {{ background-color: {COLOR_FONDO}; "
                f"border: 1px solid {COLOR_LINEA}; border-radius: 8px; }}"
            )
            columna = QVBoxLayout(columna_widget)
            columna.setContentsMargins(7, 7, 7, 8)
            columna.setSpacing(7)
            encabezado = QLabel(f"SEMESTRE {numero}")
            encabezado.setAlignment(Qt.AlignmentFlag.AlignCenter)
            encabezado.setStyleSheet(
                f"color: {COLOR_TEXTO}; background-color: {COLOR_SUPERFICIE_CLARA}; "
                "border: none; border-radius: 5px; padding: 6px; font-size: 10px; font-weight: 800;"
            )
            columna.addWidget(encabezado)
            lista = materias.get(numero, [])
            if not lista:
                vacio = QLabel("—")
                vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
                vacio.setStyleSheet(f"color: {COLOR_LINEA}; border: none; padding: 12px;")
                columna.addWidget(vacio)
            for materia in lista:
                codigo = codigo_base(materia.get("codigo"))
                tarjeta = self._crear_tarjeta_materia(
                    materia, codigo in aprobadas, codigo in seleccionadas
                )
                tarjetas_por_codigo[codigo] = tarjeta
                columna.addWidget(tarjeta)
            columna.addStretch(1)
            fila.addWidget(columna_widget)
        capa = CapaConexionesPlan()
        conexiones = []
        codigos_por_semestre = {
            numero: {
                codigo_base(materia.get("codigo"))
                for materia in materias.get(numero, [])
            }
            for numero in range(1, cantidad_semestres + 1)
        }
        for numero in range(2, cantidad_semestres + 1):
            anteriores = codigos_por_semestre[numero - 1]
            for materia in materias.get(numero, []):
                destino = tarjetas_por_codigo.get(codigo_base(materia.get("codigo")))
                for requisito in codigos_prerrequisitos(materia):
                    origen = tarjetas_por_codigo.get(requisito)
                    if requisito in anteriores and origen is not None and destino is not None:
                        conexiones.append((origen, destino))
        capa.establecer_conexiones(conexiones)
        superpuestas.addWidget(base)
        superpuestas.addWidget(capa)
        superpuestas.setCurrentWidget(capa)
        ancho_lienzo = cantidad_semestres * 222
        lienzo.setMinimumWidth(ancho_lienzo)
        layout.addWidget(lienzo)
        seccion.setMinimumWidth(ancho_lienzo + 24)
        return seccion

    def _crear_tarjeta_materia(self, materia, aprobada, seleccionada):
        codigo = codigo_base(materia.get("codigo"))
        tarjeta = TarjetaMateriaPlan()
        tarjeta.setObjectName("tarjetaMateriaPlan")
        tarjeta.setFixedHeight(76)
        tarjeta.setCursor(Qt.CursorShape.PointingHandCursor)
        tarjeta.setToolTip("Haz clic en la tarjeta para consultar sus grupos.")
        acento = COLOR_VERDE if aprobada else ("#5AA9E6" if seleccionada else COLOR_LINEA)
        fondo = COLOR_VERDE_FONDO if aprobada else COLOR_SUPERFICIE_CLARA
        tarjeta.setStyleSheet(
            f"QFrame#tarjetaMateriaPlan {{ background-color: {fondo}; "
            f"border: 1px solid {COLOR_LINEA}; border-left: 4px solid {acento}; "
            "border-radius: 7px; }}"
        )
        layout = QVBoxLayout(tarjeta)
        layout.setContentsMargins(9, 6, 7, 6)
        layout.setSpacing(2)
        nombre = QLabel(str(materia.get("nombre") or "Materia sin nombre"))
        nombre.setWordWrap(True)
        nombre.setMinimumHeight(28)
        nombre.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        nombre.setStyleSheet(
            f"background: transparent; color: {COLOR_TEXTO}; border: none; "
            "font-size: 10px; font-weight: 800; padding: 0;"
        )
        layout.addWidget(nombre)
        layout.addStretch(1)
        pie = QHBoxLayout()
        pie.setContentsMargins(0, 0, 0, 0)
        pie.setSpacing(4)
        codigo_label = QLabel(f"CÓDIGO {codigo}")
        codigo_label.setStyleSheet(
            f"background: transparent; color: {COLOR_TEXTO_SECUNDARIO}; border: none; "
            "font-size: 8px; font-weight: 700; padding: 0;"
        )
        pie.addWidget(codigo_label)
        pie.addStretch(1)
        aprobacion = QPushButton("✓" if aprobada else "")
        aprobacion.setFixedSize(20, 20)
        aprobacion.setCursor(Qt.PointingHandCursor)
        aprobacion.setToolTip(
            "Haz clic para desmarcarla como aprobada."
            if aprobada else "También se añadirán sus prerrequisitos conocidos."
        )
        aprobacion.clicked.connect(
            lambda _, codigo=codigo, estado=not aprobada:
            self._cambiar_aprobacion(codigo, estado)
        )
        aprobacion.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_VERDE_FONDO if aprobada else COLOR_SUPERFICIE}; "
            f"color: {COLOR_VERDE if aprobada else COLOR_TEXTO}; border: 1px solid {COLOR_VERDE if aprobada else COLOR_LINEA}; "
            "border-radius: 4px; padding: 0; text-align: center; font-size: 12px; font-weight: 900; } "
            f"QPushButton:hover {{ border-color: {COLOR_VERDE}; color: {COLOR_VERDE}; "
            f"background-color: {COLOR_VERDE_FONDO}; }}"
        )
        pie.addWidget(aprobacion)
        layout.addLayout(pie)
        if materia.get("grupos"):
            tarjeta.clicked.connect(
                lambda codigo=codigo: self.ventana_principal.abrir_grupos_desde_plan(codigo)
            )
        else:
            tarjeta.setCursor(Qt.CursorShape.ArrowCursor)
            tarjeta.setToolTip("No hay grupos publicados en la oferta actual.")
        return tarjeta

    @staticmethod
    def _estilo_materia(aprobada):
        fondo = COLOR_VERDE_FONDO if aprobada else COLOR_SUPERFICIE_CLARA
        borde = COLOR_VERDE if aprobada else COLOR_LINEA
        return (
            f"QPushButton {{ background-color: {fondo}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {borde}; border-radius: 7px; padding: 8px; text-align: left; }} "
            f"QPushButton:hover {{ border-color: {COLOR_VERDE}; }}"
        )

    def _cambiar_aprobacion(self, codigo, aprobado):
        self.ventana_principal.cambiar_materia_aprobada_desde_plan(codigo, aprobado)


class BarraTitulo(QFrame):
    """Barra de título propia para la ventana sin decoración de Windows."""

    def __init__(self, ventana):
        super().__init__(ventana)
        self.ventana = ventana
        self.posicion_inicial = QPoint()
        self.setFixedHeight(40)
        self.setStyleSheet(
            f"background-color: {COLOR_BARRA}; border-bottom: 1px solid {COLOR_LINEA};"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 6, 0)
        layout.setSpacing(4)
        boton_archivo = QPushButton("Archivo")
        boton_archivo.setCursor(Qt.PointingHandCursor)
        menu_archivo = QMenu(boton_archivo)
        menu_archivo.setStyleSheet(
            f"QMenu {{ background-color: {COLOR_SUPERFICIE}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; padding: 4px; }} "
            f"QMenu::item {{ padding: 7px 22px 7px 10px; }} "
            f"QMenu::item:selected {{ background-color: {COLOR_SUPERFICIE_CLARA}; }}"
        )
        menu_archivo.addAction("Cambiar estudiante", ventana.reiniciar_estudiante)
        menu_archivo.addAction("Editar materias aprobadas", ventana.editar_materias_aprobadas)
        menu_archivo.addSeparator()
        menu_archivo.addAction("Exportar estado (.fnx)", ventana.exportar_estado_fnx)
        menu_archivo.addAction("Importar estado (.fnx)", ventana.importar_estado_fnx)
        menu_archivo.addSeparator()
        menu_archivo.addAction("Buscar actualización de Fénix", ventana.buscar_actualizacion_aplicacion)
        menu_archivo.addSeparator()
        menu_archivo.addAction("Tomar captura al horario", ventana.tomar_captura_horario)
        boton_archivo.setMenu(menu_archivo)
        boton_archivo.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; padding: 5px 9px; "
            "font-size: 11px; font-weight: 700; } "
            f"QPushButton:hover {{ border-color: {COLOR_VERDE}; background-color: {COLOR_VERDE_FONDO}; }}"
        )
        layout.addWidget(boton_archivo)
        boton_plan = QPushButton("Mi plan")
        boton_plan.setCursor(Qt.PointingHandCursor)
        boton_plan.clicked.connect(ventana.abrir_plan_estudios)
        boton_plan.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; padding: 5px 9px; "
            "font-size: 11px; font-weight: 700; } "
            f"QPushButton:hover {{ border-color: {COLOR_VERDE}; background-color: {COLOR_VERDE_FONDO}; }}"
        )
        layout.addWidget(boton_plan)
        separacion_archivo = QWidget()
        separacion_archivo.setFixedWidth(10)
        layout.addWidget(separacion_archivo)
        titulo = QLabel("FÉNIX  ·  PLANIFICADOR ACADÉMICO")
        titulo.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px; font-weight: 700;"
        )
        layout.addWidget(titulo)
        layout.addStretch()
        self.boton_profesores = self.crear_boton_enlace(
            "UNMedOpina",
            URL_PROFESORES_RECOMENDADOS,
        )
        self.boton_contacto = self.crear_boton_contacto(ventana)
        self.boton_donaciones = self.crear_boton_donaciones(ventana)
        layout.addWidget(self.boton_profesores)
        layout.addWidget(self.boton_contacto)
        layout.addWidget(self.boton_donaciones)
        self.boton_minimizar = self.crear_boton("—")
        self.boton_maximizar = self.crear_boton("□")
        self.boton_cerrar = self.crear_boton("×", cerrar=True)
        layout.addWidget(self.boton_minimizar)
        layout.addWidget(self.boton_maximizar)
        layout.addWidget(self.boton_cerrar)
        self.boton_minimizar.clicked.connect(ventana.showMinimized)
        self.boton_maximizar.clicked.connect(ventana.alternar_maximizacion)
        self.boton_cerrar.clicked.connect(ventana.close)

    @staticmethod
    def crear_boton(texto, cerrar=False):
        boton = QPushButton(texto)
        boton.setFixedSize(38, 34)
        hover = COLOR_ROJO_FONDO if cerrar else COLOR_SUPERFICIE_CLARA
        boton.setStyleSheet(
            f"""
            QPushButton {{ background: transparent; border: none; border-radius: 5px;
                color: {COLOR_TEXTO_SECUNDARIO}; font-size: 17px; }}
            QPushButton:hover {{ background-color: {hover}; color: {COLOR_TEXTO}; }}
            """
        )
        return boton

    @staticmethod
    def crear_boton_contacto(ventana):
        boton = QPushButton("Contacto - ¡Ayúdame a mejorar!")
        boton.setCursor(Qt.PointingHandCursor)
        boton.setFixedHeight(30)
        boton.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; "
            f"color: {COLOR_TEXTO}; font-size: 11px; font-weight: 700; "
            "padding: 5px 9px; } "
            f"QPushButton:hover {{ color: {COLOR_TEXTO}; border-color: {COLOR_VERDE}; "
            f"background-color: {COLOR_VERDE_FONDO}; }}"
        )
        boton.clicked.connect(ventana.abrir_dialogo_contacto)
        return boton

    @staticmethod
    def crear_boton_donaciones(ventana):
        boton = QPushButton("Invítame a un café!  ♥")
        boton.setCursor(Qt.PointingHandCursor)
        boton.setFixedHeight(30)
        boton.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; "
            f"color: {COLOR_TEXTO}; font-size: 11px; font-weight: 700; padding: 5px 9px; }} "
            f"QPushButton:hover {{ color: {COLOR_TEXTO}; border-color: {COLOR_ROJO}; "
            f"background-color: {COLOR_ROJO_FONDO}; }}"
        )
        boton.clicked.connect(ventana.abrir_dialogo_donaciones)
        return boton

    @staticmethod
    def crear_boton_enlace(texto, url, corazon=False):
        if corazon:
            boton = QFrame()
            boton.setCursor(Qt.PointingHandCursor)
            boton.setObjectName("enlaceDonacion")
            boton.setFixedHeight(30)
            contenido = QHBoxLayout(boton)
            contenido.setContentsMargins(9, 0, 9, 0)
            contenido.setSpacing(4)
            etiqueta = QLabel(texto)
            corazon_label = QLabel("♥")
            corazon_label.setObjectName("corazonDonacion")
            contenido.addWidget(etiqueta)
            contenido.addWidget(corazon_label)
            boton.setStyleSheet(
                f"""
                QFrame#enlaceDonacion {{
                    background-color: {COLOR_SUPERFICIE_CLARA};
                    border: 1px solid {COLOR_LINEA};
                    border-radius: 6px;
                }}
                QFrame#enlaceDonacion:hover {{
                    border-color: {COLOR_ROJO};
                    background-color: {COLOR_ROJO_FONDO};
                }}
                QFrame#enlaceDonacion QLabel {{
                    background: transparent;
                    border: none;
                    color: {COLOR_TEXTO};
                    font-size: 11px;
                    font-weight: 700;
                }}
                QFrame#enlaceDonacion QLabel#corazonDonacion {{
                    color: {COLOR_ROJO};
                    font-size: 15px;
                }}
                """
            )
            boton.mouseReleaseEvent = lambda evento: (
                QDesktopServices.openUrl(QUrl(url))
                if evento.button() == Qt.LeftButton else None
            )
            return boton

        boton = QPushButton(texto)
        boton.setCursor(Qt.PointingHandCursor)
        boton.setFixedHeight(30)
        boton.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; "
            f"color: {COLOR_TEXTO}; font-size: 11px; font-weight: 700; "
            "padding: 5px 9px; } "
            f"QPushButton:hover {{ color: {COLOR_TEXTO}; "
            f"border-color: {COLOR_VERDE}; background-color: {COLOR_VERDE_FONDO}; }}"
        )
        boton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        return boton

    def mousePressEvent(self, evento):
        if evento.button() == Qt.LeftButton:
            self.posicion_inicial = (
                evento.globalPosition().toPoint() - self.ventana.frameGeometry().topLeft()
            )
        super().mousePressEvent(evento)

    def mouseMoveEvent(self, evento):
        if evento.buttons() & Qt.LeftButton and not self.ventana.maximizada:
            self.ventana.move(evento.globalPosition().toPoint() - self.posicion_inicial)
        super().mouseMoveEvent(evento)

    def mouseDoubleClickEvent(self, evento):
        if evento.button() == Qt.LeftButton:
            self.ventana.alternar_maximizacion()
        super().mouseDoubleClickEvent(evento)


class CeldaHorario(QFrame):
    """Celda del horario semanal."""

    seleccionada = Signal(str, int, int)
    materia_accion = Signal(object, object, str)

    def __init__(self, dia, hora, duracion):
        super().__init__()
        self.dia = dia
        self.hora = hora
        self.duracion = duracion
        self.tiene_sesiones = False
        self.setCursor(Qt.PointingHandCursor)
        self.contenido = QVBoxLayout(self)
        self.contenido.setContentsMargins(6, 5, 6, 5)
        self.contenido.setSpacing(3)
        self.mostrar_sesiones([])

    def mostrar_sesiones(self, sesiones, linea_roja_superior=False, linea_roja_inferior=False):
        limpiar_layout(self.contenido)
        self.tiene_sesiones = bool(sesiones)
        self.indicador_agregar = None
        self.setCursor(
            Qt.CursorShape.ArrowCursor if self.tiene_sesiones else Qt.CursorShape.PointingHandCursor
        )
        borde_superior = f"2px solid {COLOR_ROJO}" if linea_roja_superior else f"1px solid {COLOR_LINEA}"
        borde_inferior = f"2px solid {COLOR_ROJO}" if linea_roja_inferior else f"1px solid {COLOR_LINEA}"
        self.setStyleSheet(
            f"""
            QFrame {{ background-color: {COLOR_SUPERFICIE}; border-left: 1px solid {COLOR_LINEA};
                border-right: 1px solid {COLOR_LINEA}; border-top: {borde_superior};
                border-bottom: {borde_inferior}; border-radius: 5px; }}
            QFrame:hover {{ border-color: {COLOR_VERDE}; }}
            """
        )
        for materia, grupo, color_fondo, color_texto in sesiones:
            tarjeta = TarjetaHorario(
                materia, grupo, color_fondo, color_texto,
                self.dia, self.hora, self.duracion,
            )
            tarjeta.accion.connect(self.materia_accion.emit)
            self.contenido.addWidget(tarjeta)
        if not sesiones:
            self.indicador_agregar = QLabel("+")
            self.indicador_agregar.setFixedSize(54, 54)
            self.indicador_agregar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.indicador_agregar.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            self.indicador_agregar.setStyleSheet(
                f"color: {COLOR_VERDE}; background: transparent; border: none; "
                "font-size: 34px; font-weight: 700; padding-bottom: 5px;"
            )
            self.indicador_agregar.setVisible(False)
            self.contenido.addStretch(1)
            self.contenido.addWidget(
                self.indicador_agregar,
                0,
                Qt.AlignmentFlag.AlignCenter,
            )
            self.contenido.addStretch(1)

    def mouseReleaseEvent(self, evento):
        if evento.button() == Qt.LeftButton and not self.tiene_sesiones:
            self.seleccionada.emit(self.dia, self.hora, self.duracion)
        super().mouseReleaseEvent(evento)

    def enterEvent(self, evento):
        if not self.tiene_sesiones and self.indicador_agregar is not None:
            self.indicador_agregar.setVisible(True)
        super().enterEvent(evento)

    def leaveEvent(self, evento):
        if self.indicador_agregar is not None:
            self.indicador_agregar.setVisible(False)
        super().leaveEvent(evento)


class TarjetaHorario(QFrame):
    """Tarjeta de una materia con acciones visibles al pasar el cursor."""

    accion = Signal(object, object, str)

    def __init__(self, materia, grupo, color_fondo, color_texto, dia, hora, duracion):
        super().__init__()
        self.materia = materia
        self.grupo = grupo
        self.setObjectName("tarjetaHorario")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMinimumHeight(42)
        contenido = QVBoxLayout(self)
        contenido.setContentsMargins(5, 4, 5, 4)
        contenido.setSpacing(3)
        detalle = detalle_sesion_en_bloque(grupo, dia, hora, duracion)
        etiqueta = QLabel(
            f"{nombre_corto(materia.get('nombre'), 28)}\n"
            f"G{grupo.get('numero', '')} · {detalle}"
        )
        etiqueta.setWordWrap(True)
        etiqueta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        etiqueta.setStyleSheet(
            f"background-color: {color_fondo}; color: {color_texto}; border: none; "
            f"border-left: 3px solid {COLOR_VERDE}; border-radius: 4px; font-size: 10px; "
            "font-weight: 700; padding: 5px;"
        )
        contenido.addWidget(etiqueta)
        acciones_widget = QWidget()
        acciones = QHBoxLayout(acciones_widget)
        acciones.setContentsMargins(0, 0, 0, 0)
        acciones.setSpacing(3)
        quitar = QPushButton("X")
        cambiar = QPushButton("Cambiar grupo")
        for boton in (quitar, cambiar):
            boton.setCursor(Qt.PointingHandCursor)
            boton.setMinimumHeight(32)
            boton.setStyleSheet(
                VentanaPrincipal.estilo_boton_grupo(COLOR_SUPERFICIE, COLOR_LINEA)
            )
        quitar.setFixedWidth(34)
        acciones.addWidget(quitar)
        acciones.addWidget(cambiar, 1)
        contenido.addWidget(acciones_widget)
        acciones_widget.setVisible(False)
        quitar.clicked.connect(lambda: self.accion.emit(self.materia, self.grupo, "quitar"))
        cambiar.clicked.connect(lambda: self.accion.emit(self.materia, self.grupo, "cambiar"))
        self.acciones_widget = acciones_widget
        # La celda ya dibuja el borde exterior; la tarjeta no añade otro.
        self.setStyleSheet("QFrame#tarjetaHorario { background: transparent; border: none; }")

    def enterEvent(self, evento):
        self.acciones_widget.setVisible(True)
        super().enterEvent(evento)

    def leaveEvent(self, evento):
        self.acciones_widget.setVisible(False)
        super().leaveEvent(evento)


class CuadriculaHorario(QFrame):
    """Representación semanal de las materias ya seleccionadas."""

    bloque_seleccionado = Signal(str, int, int)
    materia_accion = Signal(object, object, str)

    def __init__(self):
        super().__init__()
        self.setStyleSheet(
            f"background-color: {COLOR_SUPERFICIE}; border: 1px solid {COLOR_LINEA}; border-radius: 10px;"
        )
        self.cuadricula = QGridLayout(self)
        self.cuadricula.setContentsMargins(8, 8, 8, 8)
        self.cuadricula.setSpacing(6)

    def actualizar(self, grupos):
        limpiar_layout(self.cuadricula)
        limites_traslado = {
            (adyacencia["dia"], adyacencia["hora"])
            for adyacencia in detectar_adyacencias(grupos)
            if adyacencia.get("sedes_diferentes")
        }
        esquina = QLabel("BLOQUE")
        esquina.setAlignment(Qt.AlignCenter)
        esquina.setStyleSheet(self.estilo_encabezado())
        self.cuadricula.addWidget(esquina, 0, 0)
        for columna, (_, etiqueta) in enumerate(DIAS, start=1):
            encabezado = QLabel(etiqueta.upper())
            encabezado.setAlignment(Qt.AlignCenter)
            encabezado.setStyleSheet(self.estilo_encabezado())
            self.cuadricula.addWidget(encabezado, 0, columna)
            self.cuadricula.setColumnStretch(columna, 1)
        for fila, (hora, fin) in enumerate(BLOQUES_HORARIO, start=1):
            duracion = fin - hora
            etiqueta_hora = QLabel(f"{hora:02d}:00\n{fin:02d}:00")
            etiqueta_hora.setAlignment(Qt.AlignCenter)
            etiqueta_hora.setStyleSheet(
                f"""QLabel {{ color: {COLOR_TEXTO_SECUNDARIO}; background-color: {COLOR_BARRA};
                border: 1px solid {COLOR_LINEA}; border-radius: 5px; font-size: 11px; font-weight: 700; }}"""
            )
            self.cuadricula.addWidget(etiqueta_hora, fila, 0)
            self.cuadricula.setRowMinimumHeight(fila, 64)
            for columna, (dia, _) in enumerate(DIAS, start=1):
                celda = CeldaHorario(dia, hora, duracion)
                sesiones = []
                for indice, (materia, grupo) in enumerate(grupos):
                    if grupo_ocupa_bloque(grupo, dia, hora, duracion):
                        fondo, texto = COLORES_MATERIAS[indice % len(COLORES_MATERIAS)]
                        sesiones.append((materia, grupo, fondo, texto))
                inicio_minutos = hora * 60
                fin_minutos = fin * 60
                celda.mostrar_sesiones(
                    sesiones,
                    linea_roja_superior=(dia, inicio_minutos) in limites_traslado,
                    linea_roja_inferior=(dia, fin_minutos) in limites_traslado,
                )
                if sesiones:
                    # La franja sigue siendo de dos horas. Si hay varias
                    # sesiones consecutivas o superpuestas, la celda crece
                    # para apilar sus tarjetas sin ocultar ninguna.
                    altura_por_tarjeta = 94
                    self.cuadricula.setRowMinimumHeight(
                        fila, altura_por_tarjeta * len(sesiones)
                    )
                celda.seleccionada.connect(self.bloque_seleccionado)
                celda.materia_accion.connect(self.materia_accion)
                self.cuadricula.addWidget(celda, fila, columna)

    @staticmethod
    def estilo_encabezado():
        return (
            f"background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 5px; font-size: 11px; "
            "font-weight: 700; padding: 7px;"
        )


class DialogoEsperaActualizacion(QDialog):
    """Aviso modal mostrado durante la primera descarga del catálogo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fénix · Actualizando catálogo")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(560, 280)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_SUPERFICIE}; border: 2px solid {COLOR_VERDE}; }}"
            f"QLabel {{ color: {COLOR_TEXTO}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        titulo = QLabel("Preparando tu horario")
        titulo.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {COLOR_TEXTO};")
        layout.addWidget(titulo)
        self.mensaje = QLabel("Fénix está consultando las materias normales…")
        self.mensaje.setWordWrap(True)
        self.mensaje.setStyleSheet(f"font-size: 14px; color: {COLOR_TEXTO_SECUNDARIO};")
        layout.addWidget(self.mensaje)
        self.progreso = QProgressBar()
        self.progreso.setRange(0, 100)
        self.progreso.setTextVisible(True)
        self.progreso.setFixedHeight(28)
        self.progreso.setStyleSheet(
            f"QProgressBar {{ color: {COLOR_TEXTO}; background-color: {COLOR_BARRA}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; "
            "text-align: center; font-size: 12px; font-weight: 700; }} "
            f"QProgressBar::chunk {{ background-color: {COLOR_VERDE}; "
            "border-radius: 5px; }}"
        )
        layout.addWidget(self.progreso)
        self.tiempo = QLabel("Calculando tiempo restante…")
        self.tiempo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXTO_SECUNDARIO};")
        layout.addWidget(self.tiempo)
        aviso = QLabel("No cierres esta ventana: el horario se habilitará cuando termine la actualización.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet(f"font-size: 11px; color: {COLOR_VERDE};")
        layout.addWidget(aviso)

    def actualizar(self, mensaje, progreso, tiempo_restante):
        valor = int(progreso) if isinstance(progreso, (int, float)) else 0
        valor = max(0, min(100, valor))
        self.mensaje.setText(mensaje)
        self.progreso.setValue(valor)
        self.progreso.setFormat(f"{valor}%")
        self.tiempo.setText(tiempo_restante)


class VentanaPrincipal(QMainWindow):
    """Muestra el horario y gestiona las asignaturas desde la izquierda."""

    def __init__(self):
        super().__init__()
        self.maximizada = False
        self.planes = cargar_planes()
        self.estudiante = cargar_estudiante()
        codigo_estudiante = self.estudiante.get("plan_estudios")
        preparar_materias_para_plan(codigo_estudiante)
        preparar_oferta_para_plan(codigo_estudiante)
        self.codigo_plan = None
        self.materias_aprobadas = set()
        self.codigos_recomendados = set()
        self.materias_por_origen = {"principal": [], "libre": []}
        self.materias_para_mostrar = {"principal": [], "libre": []}
        self.secciones_expandida = {}
        self.todas_secciones_expandidas = False
        self.referencias = []
        self.grupo_previsualizado = None
        self.dialogos_no_modales = []
        self.datos_disponibles = self.hay_datos_disponibles()
        self.informacion_persistida = self.hay_informacion_persistida()
        self.debe_solicitar_perfil_inicial = (
            not self.datos_disponibles and not self.tiene_perfil_guardado()
        )
        self.ultima_actualizacion_vista = None
        self.estado_actualizacion = "sin_iniciar"
        self.libres_bloqueadas = False
        self.dialogo_espera = None
        self.ventana_plan_estudios = None
        self.inicio_primera_actualizacion = None
        self.proceso_actualizacion = None
        self.cambiando_estudiante = False
        self.comprobacion_version_pendiente = False
        self.arranque_autorizado = False

        self.configurar_ventana()
        self.crear_interfaz()
        self.temporizador_estado = QTimer(self)
        self.temporizador_estado.timeout.connect(self.revisar_actualizacion)
        self.temporizador_estado.start(1000)
        self.revisar_actualizacion()
        if self.datos_disponibles:
            self.activar_planificador()
        else:
            self.bloquear_planificador()

    def configurar_ventana(self):
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle(f"Fénix {VERSION}")
        if RUTA_LOGO.exists():
            self.setWindowIcon(QIcon(str(RUTA_LOGO)))
        self.setStyleSheet(f"QMainWindow {{ background-color: {COLOR_FONDO}; }}")

    def crear_interfaz(self):
        contenedor = QWidget()
        principal = QVBoxLayout(contenedor)
        principal.setContentsMargins(0, 0, 0, 0)
        principal.setSpacing(0)
        self.barra_titulo = BarraTitulo(self)
        principal.addWidget(self.barra_titulo)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {COLOR_LINEA}; }}")
        splitter.addWidget(self.crear_barra_lateral())
        splitter.addWidget(self.crear_contenido_horario())
        splitter.setSizes([300, 980])
        splitter.setStretchFactor(1, 1)
        principal.addWidget(splitter)
        self.setCentralWidget(contenedor)

    def crear_barra_lateral(self):
        lateral = QFrame()
        lateral.setMinimumWidth(245)
        lateral.setMaximumWidth(390)
        lateral.setStyleSheet(
            f"background-color: {COLOR_BARRA}; border-right: 1px solid {COLOR_LINEA};"
        )
        layout = QVBoxLayout(lateral)
        layout.setContentsMargins(15, 18, 15, 14)
        layout.setSpacing(9)
        marca = QLabel("FÉNIX")
        marca.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 25px; font-weight: 800;")
        layout.addWidget(marca)
        subtitulo = QLabel("Actualiza y organiza tu semestre")
        subtitulo.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        layout.addWidget(subtitulo)

        estado_marco = QFrame()
        # El mensaje de los workers puede tener varias líneas. La altura fija
        # evita que el panel inferior mueva el resto de la barra lateral.
        estado_marco.setFixedHeight(145)
        estado_marco.setStyleSheet(
            f"background-color: {COLOR_SUPERFICIE}; border: 1px solid {COLOR_LINEA}; border-radius: 8px;"
        )
        estado_layout = QVBoxLayout(estado_marco)
        estado_layout.setContentsMargins(10, 9, 10, 10)
        estado_layout.setSpacing(6)
        self.etiqueta_estado = QLabel("Comprobando datos…")
        self.etiqueta_estado.setWordWrap(True)
        self.etiqueta_estado.setFixedHeight(42)
        self.etiqueta_estado.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.etiqueta_estado.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 11px;")
        estado_layout.addWidget(self.etiqueta_estado)
        self.barra_progreso = QProgressBar()
        self.barra_progreso.setRange(0, 100)
        self.barra_progreso.setTextVisible(True)
        self.barra_progreso.setFixedHeight(17)
        estado_layout.addWidget(self.barra_progreso)
        self.boton_actualizar = QPushButton("↻  Actualizar datos")
        self.boton_actualizar.setCursor(Qt.PointingHandCursor)
        self.boton_actualizar.clicked.connect(self.iniciar_actualizacion_manual)
        self.boton_actualizar.setStyleSheet(
            f"""QPushButton {{ background-color: transparent; color: {COLOR_TEXTO};
            border: 1px solid {COLOR_LINEA}; border-radius: 6px; padding: 7px; text-align: left; }}
            QPushButton:hover {{ border-color: {COLOR_VERDE}; }}
            QPushButton:disabled {{ color: {COLOR_TEXTO_SECUNDARIO}; border-color: {COLOR_LINEA}; }}"""
        )
        estado_layout.addWidget(self.boton_actualizar)
        self.etiqueta_plan = QLabel("PLAN\nPendiente de seleccionar")
        self.etiqueta_plan.setWordWrap(True)
        self.etiqueta_plan.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px; padding: 3px 1px;"
        )
        layout.addWidget(self.etiqueta_plan)
        etiqueta = QLabel("ASIGNATURAS")
        etiqueta.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px; font-weight: 700; padding-top: 5px;"
        )
        layout.addWidget(etiqueta)
        self.buscar_asignaturas = QLineEdit()
        self.buscar_asignaturas.setPlaceholderText("Buscar por nombre o código…")
        self.buscar_asignaturas.setStyleSheet(
            f"QLineEdit {{ background-color: {COLOR_SUPERFICIE}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; padding: 7px 9px; }} "
            f"QLineEdit:focus {{ border-color: {COLOR_VERDE}; }}"
        )
        self.buscar_asignaturas.textChanged.connect(self.filtrar_asignaturas)
        layout.addWidget(self.buscar_asignaturas)
        self.boton_contraer_secciones = QPushButton("▾  Contraer todo")
        self.boton_contraer_secciones.setCursor(Qt.PointingHandCursor)
        self.boton_contraer_secciones.clicked.connect(self.contraer_todas_secciones)
        self.boton_contraer_secciones.setStyleSheet(
            f"QPushButton {{ background-color: transparent; color: {COLOR_TEXTO_SECUNDARIO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; padding: 6px 8px; "
            "text-align: left; font-size: 10px; font-weight: 700; } "
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"color: {COLOR_TEXTO}; border-color: {COLOR_VERDE}; }}"
        )
        layout.addWidget(self.boton_contraer_secciones)
        self.lista_asignaturas = self.crear_area_desplazable()
        layout.addWidget(self.lista_asignaturas, 1)
        self.aviso_libres_eleccion = QLabel()
        self.aviso_libres_eleccion.setWordWrap(True)
        self.aviso_libres_eleccion.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; background-color: {COLOR_SUPERFICIE}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; padding: 7px; font-size: 10px;"
        )
        self.aviso_libres_eleccion.hide()
        layout.addWidget(self.aviso_libres_eleccion)
        layout.addWidget(estado_marco)
        return lateral

    def crear_contenido_horario(self):
        contenido = QWidget()
        contenido.setStyleSheet(f"background-color: {COLOR_FONDO};")
        contenido.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        layout = QVBoxLayout(contenido)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        encabezado_horario = QHBoxLayout()
        titulo = QLabel("Horario semanal")
        titulo.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 24px; font-weight: 800;")
        encabezado_horario.addWidget(titulo)
        encabezado_horario.addStretch()
        self.boton_creditos = QPushButton("Créditos: 0")
        self.boton_creditos.setCursor(Qt.PointingHandCursor)
        self.boton_creditos.clicked.connect(self.mostrar_desglose_creditos)
        self.boton_creditos.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_SUPERFICIE}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 7px; padding: 8px 12px; "
            "font-size: 12px; font-weight: 700; } "
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"border-color: {COLOR_VERDE}; }}"
        )
        encabezado_horario.addWidget(self.boton_creditos)
        layout.addLayout(encabezado_horario)
        guia = QLabel("FRANJAS PRINCIPALES DE 2 HORAS · LAS DURACIONES REALES SE MUESTRAN EN CADA MATERIA")
        guia.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px; font-weight: 700;"
        )
        layout.addWidget(guia)
        self.boton_fuera_horario = QPushButton("Ver materias por fuera de horario normal")
        self.boton_fuera_horario.setCursor(Qt.PointingHandCursor)
        self.boton_fuera_horario.clicked.connect(self.mostrar_materias_fuera_horario)
        self.boton_fuera_horario.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_ROJO_FONDO}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_ROJO}; border-radius: 7px; padding: 8px; "
            "text-align: left; font-size: 11px; font-weight: 700; } "
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"border-color: {COLOR_VERDE}; }}"
        )
        self.boton_fuera_horario.hide()
        layout.addWidget(self.boton_fuera_horario)
        self.resumen = QLabel("El horario se habilitará cuando termine la primera actualización de datos.")
        self.resumen.setStyleSheet(
            f"background-color: {COLOR_SUPERFICIE}; color: {COLOR_TEXTO_SECUNDARIO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 8px; padding: 9px; font-size: 12px;"
        )
        layout.addWidget(self.resumen)
        self.cuadricula = CuadriculaHorario()
        self.cuadricula.bloque_seleccionado.connect(self.mostrar_grupos_del_bloque)
        self.cuadricula.materia_accion.connect(self.ejecutar_accion_materia)
        layout.addWidget(self.cuadricula, 1)
        ayuda_acciones = QLabel(
            "Pasa el cursor sobre una materia del horario para quitarla o cambiar su grupo."
        )
        ayuda_acciones.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px;")
        layout.addWidget(ayuda_acciones)
        self.lista_seleccionados = self.crear_area_desplazable()
        self.lista_seleccionados.setMaximumHeight(112)
        self.lista_seleccionados.hide()
        layout.addWidget(self.lista_seleccionados)
        desplazamiento = QScrollArea()
        desplazamiento.setWidgetResizable(True)
        desplazamiento.setFrameShape(QFrame.Shape.NoFrame)
        desplazamiento.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        desplazamiento.setStyleSheet(
            f"QScrollArea {{ background-color: {COLOR_FONDO}; border: none; }}"
            f"QScrollArea QWidget {{ background-color: {COLOR_FONDO}; }}"
        )
        desplazamiento.setWidget(contenido)
        return desplazamiento

    @staticmethod
    def crear_area_desplazable():
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setStyleSheet("QScrollArea { background: transparent; }")
        contenido = QWidget()
        contenido.setObjectName("contenido")
        contenido.setStyleSheet("QWidget#contenido { background: transparent; }")
        contenido.setLayout(QVBoxLayout())
        contenido.layout().setContentsMargins(0, 0, 0, 0)
        contenido.layout().setSpacing(6)
        area.setWidget(contenido)
        return area

    @staticmethod
    def hay_datos_disponibles():
        # La oferta sola no basta: el planificador necesita también el
        # catálogo estable de materias para mostrar nombres, créditos y
        # tipologías de forma consistente.
        return bool(cargar_materias()) and bool(cargar_oferta().get("materias"))

    @staticmethod
    def hay_informacion_persistida():
        return bool(
            cargar_oferta().get("materias")
            or cargar_materias()
            or cargar_libres_eleccion()
        )

    def tiene_perfil_guardado(self):
        return self.estudiante.get("plan_estudios") in self.planes

    @staticmethod
    def catalogo_para_perfil():
        """Combina datos persistidos para nombrar materias en el formulario."""
        materias = cargar_materias()
        oferta = cargar_oferta().get("materias", {})
        libres = cargar_libres_eleccion()
        return oferta, materias, libres

    def crear_dialogo_plan(self):
        oferta, materias, libres = self.catalogo_para_perfil()
        return DialogoPlan(self.planes, oferta, materias, self.estudiante, self, libres)

    def solicitar_perfil_inicial(self):
        """Pide el perfil durante la primera descarga, antes de mostrar el horario."""
        if self.tiene_perfil_guardado() or not self.planes:
            return True

        dialogo = self.crear_dialogo_plan()
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False

        self.estudiante = {
            "plan_estudios": dialogo.codigo_plan(),
            "materias_aprobadas": dialogo.materias_aprobadas(),
            "grupos_seleccionados": [],
        }
        guardar_estudiante(self.estudiante)
        self.bloquear_planificador()
        return True

    def bloquear_planificador(self):
        self.codigo_plan = None
        self.materias_por_origen = {"principal": [], "libre": []}
        self.materias_para_mostrar = {"principal": [], "libre": []}
        if self.tiene_perfil_guardado():
            plan = self.planes[self.estudiante["plan_estudios"]]
            self.etiqueta_plan.setText(
                f"PLAN\n{plan.nombre}\nPerfil guardado · esperando la actualización"
            )
        else:
            self.etiqueta_plan.setText("PLAN\nDisponible al terminar la primera actualización")
        self.cuadricula.setEnabled(False)
        self.lista_asignaturas.setEnabled(False)
        self.lista_seleccionados.setEnabled(False)
        self.reconstruir_lista_asignaturas()
        self.actualizar_horario()

    def activar_planificador(self):
        self.cuadricula.setEnabled(True)
        self.lista_asignaturas.setEnabled(True)
        self.lista_seleccionados.setEnabled(True)
        if not self.cargar_perfil():
            return
        self.recargar_datos()
        self.actualizar_interfaz()

    def cargar_perfil(self):
        if not self.planes:
            QMessageBox.critical(
                self, "No hay planes de estudio", "No fue posible cargar datos/planes_estudio.json."
            )
            return False
        codigo = self.estudiante.get("plan_estudios")
        if codigo not in self.planes:
            dialogo = self.crear_dialogo_plan()
            if dialogo.exec() != QDialog.DialogCode.Accepted:
                QTimer.singleShot(0, self.close)
                return False
            codigo = dialogo.codigo_plan()
            self.estudiante = {
                "plan_estudios": codigo,
                "materias_aprobadas": dialogo.materias_aprobadas(),
                "grupos_seleccionados": [],
            }
            guardar_estudiante(self.estudiante)
        self.codigo_plan = codigo
        self.materias_aprobadas = {
            codigo_base(valor)
            for valor in self.estudiante.get("materias_aprobadas", [])
        }
        self.codigos_recomendados = codigos_recomendados(
            self.planes[codigo], self.materias_aprobadas
        )
        self.etiqueta_plan.setText(
            f"PLAN ACTUAL\n{self.planes[codigo].nombre}\nCódigo {codigo}\n"
            f"{len(self.materias_aprobadas)} aprobada(s)"
        )
        return True

    def recargar_datos(self):
        if not self.codigo_plan:
            return
        oferta = cargar_oferta().get("materias", {})
        plan = self.planes[self.codigo_plan]
        # La oferta normal se puede usar desde que está lista. Libre Elección
        # permanece vacía hasta que la fase LE termina completamente.
        # Las libres se actualizan en segundo plano; se muestran en cuanto el
        # archivo queda disponible, sin bloquear el trabajo con materias normales.
        libres = cargar_libres_eleccion(self.codigo_plan)
        self.materias_por_origen = {
            "principal": materias_principales(plan, oferta),
            "libre": libres,
        }
        self.actualizar_aviso_libres_eleccion()
        guardadas = self.estudiante.get("grupos_seleccionados", [])
        guardadas = guardadas if isinstance(guardadas, list) else []
        validas = [
            referencia
            for referencia, _, _ in grupos_seleccionados(self.materias_por_origen, guardadas)
        ]
        self.referencias = validas
        codigos_seleccionados = {
            codigo_base(referencia.get("codigo")) for referencia in self.referencias
        }
        candidatas_recomendacion = materias_visibles(
            self.materias_por_origen["principal"],
            self.materias_aprobadas,
            codigos_seleccionados,
        )
        self.codigos_recomendados = codigos_recomendados(
            plan,
            self.materias_aprobadas,
            candidatas_recomendacion,
        )
        self.actualizar_materias_para_mostrar()
        if guardadas != validas:
            self.guardar_estado_estudiante()

    def actualizar_aviso_libres_eleccion(self):
        """Informa que Libre Elección sigue pendiente sin bloquear el horario."""
        if not self.codigo_plan or self.materias_por_origen.get("libre"):
            self.aviso_libres_eleccion.hide()
            return
        self.aviso_libres_eleccion.setText(
            "Libre Elección todavía no se ha actualizado. Esta consulta puede "
            "tardar un poco; puedes continuar organizando las materias normales."
        )
        self.aviso_libres_eleccion.show()

    def contraer_todas_secciones(self):
        """Contrae simultáneamente todas las categorías visibles."""
        self.todas_secciones_expandidas = False
        for clave, (encabezado, cuerpo) in self._secciones_asignaturas.items():
            titulo = encabezado.property("titulo_seccion") or clave
            self.secciones_expandida[clave] = False
            encabezado.setChecked(False)
            cuerpo.setVisible(False)
            encabezado.setText(f"▸  {titulo}")

    def actualizar_materias_para_mostrar(self):
        """Muestra disponibles y seleccionadas, ocultando solo las no elegibles."""
        codigos_seleccionados = {
            codigo_base(referencia.get("codigo")) for referencia in self.referencias
        }
        self.materias_para_mostrar = {}
        for origen, materias in self.materias_por_origen.items():
            visibles = materias_visibles(
                materias,
                self.materias_aprobadas,
                codigos_seleccionados,
            )
            visibles_por_codigo = {codigo_base(materia.get("codigo")) for materia in visibles}
            for materia in materias:
                codigo = codigo_base(materia.get("codigo"))
                if codigo in codigos_seleccionados and codigo not in visibles_por_codigo:
                    visibles.append(materia)
            self.materias_para_mostrar[origen] = visibles

    def guardar_estado_estudiante(self):
        if not self.codigo_plan:
            return
        self.estudiante["plan_estudios"] = self.codigo_plan
        self.estudiante["materias_aprobadas"] = sorted(self.materias_aprobadas)
        self.estudiante["grupos_seleccionados"] = self.referencias
        guardar_estudiante(self.estudiante)

    def exportar_estado_fnx(self):
        """Permite elegir dónde guardar una copia portable del estado local."""
        destino, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar estado de Fénix",
            "estado_fenix.fnx",
            "Estado de Fénix (*.fnx)",
        )
        if not destino:
            return
        if not destino.lower().endswith(".fnx"):
            destino += ".fnx"
        try:
            exportar_fnx(destino)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "No se pudo exportar", str(error))
            return
        QMessageBox.information(
            self,
            "Estado exportado",
            f"El estado actual se guardó correctamente en:\n{destino}",
        )

    def tomar_captura_horario(self):
        """Guarda como PNG la cuadrícula visible del horario actual."""
        destino, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar captura del horario",
            "horario_fenix.png",
            "Imagen PNG (*.png)",
        )
        if not destino:
            return
        if not destino.lower().endswith(".png"):
            destino += ".png"
        imagen = self.cuadricula.grab()
        if not imagen.save(destino, "PNG"):
            QMessageBox.critical(
                self,
                "No se pudo guardar la captura",
                "Fénix no pudo guardar la imagen seleccionada.",
            )
            return
        QMessageBox.information(
            self,
            "Captura guardada",
            f"La imagen del horario se guardó correctamente en:\n{destino}",
        )

    def abrir_dialogo_contacto(self):
        """Muestra los canales de contacto de Fénix."""
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Contacto · Ayúdame a mejorar Fénix")
        dialogo.setMinimumWidth(560)
        dialogo.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_SUPERFICIE}; }} "
            f"QLabel {{ color: {COLOR_TEXTO}; }} "
            f"QLineEdit {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"color: {COLOR_TEXTO}; border: 1px solid {COLOR_LINEA}; border-radius: 6px; padding: 7px; }} "
            f"QPushButton {{ background-color: {COLOR_VERDE_FONDO}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_VERDE}; border-radius: 6px; padding: 7px 12px; }} "
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; }}"
        )
        layout = QVBoxLayout(dialogo)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(7)
        titulo = QLabel("Contacto")
        titulo.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 17px; font-weight: 700;")
        layout.addWidget(titulo)
        nota = QLabel(
            "Si tienes alguna duda, detectaste un error o tienes una sugerencia "
            "para mejorar Fénix, puedes escribirme al siguiente correo:"
        )
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 12px;")
        layout.addWidget(nota)
        fila_correo = QHBoxLayout()
        correo = QLineEdit(CORREO_CONTACTO)
        correo.setReadOnly(True)
        correo.setToolTip("Selecciona el texto o usa el botón para copiarlo")
        correo.selectAll()
        fila_correo.addWidget(correo, 1)
        copiar = QPushButton("Copiar correo")
        copiar.clicked.connect(lambda: QApplication.clipboard().setText(CORREO_CONTACTO))
        fila_correo.addWidget(copiar)
        layout.addLayout(fila_correo)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(dialogo.reject)
        layout.addWidget(botones)
        dialogo.exec()

    def abrir_dialogo_donaciones(self):
        """Muestra el mensaje de apoyo y el QR para realizar una transferencia."""
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Invítame a un café · Apoya a Fénix")
        # El QR ocupa aproximadamente la mitad del ancho disponible; su altura
        # crece proporcionalmente para conservar la relación 768 × 1369.
        dialogo.setMinimumWidth(900)
        dialogo.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_SUPERFICIE}; }} "
            f"QLabel {{ color: {COLOR_TEXTO}; }} "
            f"QPushButton {{ background-color: {COLOR_VERDE_FONDO}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_VERDE}; border-radius: 6px; padding: 7px 12px; }} "
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; }}"
        )
        layout = QVBoxLayout(dialogo)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        columnas = QHBoxLayout()
        columnas.setSpacing(18)
        columna_texto = QVBoxLayout()
        columna_texto.setContentsMargins(8, 0, 8, 0)
        columna_texto.setSpacing(10)
        titulo = QLabel("Gracias por apoyar a Fénix")
        titulo.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 27px; font-weight: 700;")
        columna_texto.addWidget(titulo)

        texto = QLabel(
            "¡Hola! Soy Miguel, estudiante de Ingeniería de Sistemas de la Sede Medellín, "
            "y diseñé Fénix porque también he vivido lo tedioso que puede ser elegir "
            "las materias semestre a semestre. Por eso decidí crear "
            "esta herramienta de manera voluntaria para hacer ese proceso más sencillo.\n\n"
            "Si Fénix te ha resultado útil y deseas apoyarme, agradecería mucho tu aporte. "
            "Este proyecto me ha tomado tiempo y esfuerzo. ¡Muchas gracias por descargarlo "
            "y por ayudarme a seguir mejorándolo!"
        )
        texto.setWordWrap(True)
        texto.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 17px;")
        columna_texto.addWidget(texto)

        gracias = QLabel()
        gracias.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap_gracias = QPixmap(str(RUTA_GRACIAS))
        if not pixmap_gracias.isNull():
            # La imagen original es horizontal (1000 × 500); se ajusta sin deformarla.
            gracias.setPixmap(
                pixmap_gracias.scaled(
                    420, 210,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        columna_texto.addStretch(1)
        columna_texto.addWidget(gracias)
        columna_texto.addStretch(1)
        columnas.addLayout(columna_texto, 1)

        columna_qr = QVBoxLayout()
        columna_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr = QLabel()
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(RUTA_QR_DONACIONES))
        if not pixmap.isNull():
            # Conserva la proporción vertical original (768 × 1369) y evita deformar el QR.
            qr.setPixmap(pixmap.scaled(420, 748, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.FastTransformation))
        else:
            qr.setText("No se encontró el código QR de donaciones.")
            qr.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; padding: 30px;")
        columna_qr.addWidget(qr)
        columnas.addLayout(columna_qr)
        layout.addLayout(columnas, 1)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(dialogo.reject)
        layout.addWidget(botones)
        dialogo.exec()

    def importar_estado_fnx(self):
        """Valida un paquete FNX, confirma el reemplazo y recarga la aplicación."""
        origen, _ = QFileDialog.getOpenFileName(
            self,
            "Importar estado de Fénix",
            "",
            "Estado de Fénix (*.fnx)",
        )
        if not origen:
            return
        confirmacion = QMessageBox.question(
            self,
            "Reemplazar estado local",
            "La importación reemplazará el perfil, el horario y los datos "
            "académicos locales actuales. ¿Deseas continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmacion != QMessageBox.StandardButton.Yes:
            return
        try:
            importar_fnx(origen)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "No se pudo importar", str(error))
            return

        self.planes = cargar_planes()
        self.estudiante = cargar_estudiante()
        self.codigo_plan = None
        self.materias_aprobadas = set()
        self.referencias = []
        self.datos_disponibles = self.hay_datos_disponibles()
        if self.datos_disponibles:
            self.activar_planificador()
        else:
            self.bloquear_planificador()
        QMessageBox.information(
            self,
            "Estado importado",
            "El estado de Fénix se importó correctamente.",
        )

    def grupos_actuales(self):
        return [
            (materia, grupo)
            for _, materia, grupo in grupos_seleccionados(
                self.materias_por_origen, self.referencias
            )
        ]

    def materia_ya_seleccionada(self, materia):
        codigo = str(materia.get("codigo"))
        return any(
            str(materia_actual.get("codigo")) == codigo
            for materia_actual, _ in self.grupos_actuales()
        )

    def actualizar_interfaz(self):
        self.actualizar_recomendaciones()
        self.actualizar_materias_para_mostrar()
        self.reconstruir_lista_asignaturas()
        self.actualizar_horario()
        if (
            self.ventana_plan_estudios is not None
            and self.ventana_plan_estudios.isVisible()
        ):
            self.ventana_plan_estudios.reconstruir()

    def actualizar_recomendaciones(self):
        """Recalcula el conjunto recomendado con lo que aún está disponible."""
        if not self.codigo_plan:
            self.codigos_recomendados = set()
            return
        seleccionadas = {
            codigo_base(referencia.get("codigo")) for referencia in self.referencias
        }
        candidatas = materias_visibles(
            self.materias_por_origen.get("principal", []),
            self.materias_aprobadas,
            seleccionadas,
        )
        self.codigos_recomendados = codigos_recomendados(
            self.planes[self.codigo_plan], self.materias_aprobadas, candidatas
        )

    def abrir_plan_estudios(self):
        """Abre o enfoca la vista no modal del plan de estudios."""
        if not self.codigo_plan or self.codigo_plan not in self.planes:
            QMessageBox.information(
                self,
                "Plan no disponible",
                "Selecciona tu plan y espera a que esté disponible para abrir el diagrama.",
            )
            return
        if self.ventana_plan_estudios is None:
            self.ventana_plan_estudios = VentanaPlanEstudios(self)
        self.ventana_plan_estudios.reconstruir()
        self.ventana_plan_estudios.show()
        self.ventana_plan_estudios.raise_()
        self.ventana_plan_estudios.activateWindow()

    def _materia_por_codigo(self, codigo):
        """Busca una materia cargada o crea una referencia mínima desde el plan."""
        codigo = codigo_base(codigo)
        for materias in self.materias_por_origen.values():
            for materia in materias:
                if codigo_base(materia.get("codigo")) == codigo:
                    return materia
        plan = self.planes.get(self.codigo_plan)
        return {
            "codigo": codigo,
            "nombre": (plan.nombres_asignaturas if plan else {}).get(codigo, codigo),
            "grupos": [],
        }

    def abrir_grupos_desde_plan(self, codigo):
        """Abre el selector de grupos sin cerrar la ventana del plan."""
        materia = self._materia_por_codigo(codigo)
        fuente = "libre" if any(
            codigo_base(item.get("codigo")) == codigo_base(codigo)
            for item in self.materias_por_origen.get("libre", [])
        ) else "principal"
        self.mostrar_detalle_asignatura(materia, fuente, no_modal=True)

    def cambiar_materia_aprobada_desde_plan(self, codigo, aprobada):
        """Actualiza aprobación desde el diagrama y refresca el planificador."""
        codigo = codigo_base(codigo)
        if aprobada:
            self.materias_aprobadas.add(codigo)
            indice = {
                codigo_base(materia.get("codigo")): materia
                for materias in self.materias_por_origen.values()
                for materia in materias
            }
            pendientes = [codigo]
            while pendientes:
                actual = pendientes.pop()
                for requerido in codigos_prerrequisitos(indice.get(actual, {})):
                    if requerido and requerido not in self.materias_aprobadas:
                        self.materias_aprobadas.add(requerido)
                        pendientes.append(requerido)
        else:
            self.materias_aprobadas.discard(codigo)
        self.guardar_estado_estudiante()
        self.recargar_datos()
        self.actualizar_interfaz()

    def editar_materias_aprobadas(self):
        """Permite corregir el avance académico sin borrar el horario."""
        if not self.codigo_plan:
            return
        dialogo = self.crear_dialogo_plan()
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        self.estudiante["materias_aprobadas"] = dialogo.materias_aprobadas()
        self.materias_aprobadas = {
            codigo_base(codigo)
            for codigo in self.estudiante["materias_aprobadas"]
        }
        self.codigos_recomendados = codigos_recomendados(
            self.planes[self.codigo_plan], self.materias_aprobadas
        )
        self.guardar_estado_estudiante()
        self.recargar_datos()
        self.actualizar_interfaz()

    def reconstruir_lista_asignaturas(self):
        self._reconstruyendo_lista = True
        contenedor = self.lista_asignaturas.widget()
        limpiar_layout(contenedor.layout())
        self._secciones_asignaturas = {}
        if not self.datos_disponibles:
            mensaje = QLabel(
                "Aún no hay información académica. Espera a que termine la actualización "
                "para elegir un plan o una asignatura."
            )
            mensaje.setWordWrap(True)
            mensaje.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; padding: 7px 3px;")
            contenedor.layout().addWidget(mensaje)
        elif not self.codigo_plan:
            mensaje = QLabel("Selecciona tu plan para ver las asignaturas disponibles.")
            mensaje.setWordWrap(True)
            mensaje.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; padding: 7px 3px;")
            contenedor.layout().addWidget(mensaje)
        else:
            plan = self.planes.get(self.codigo_plan)
            codigos_plan = {
                codigo_base(codigo)
                for semestre in plan.semestres
                for codigo in semestre.asignaturas
            }
            grupos_por_tipo = {}
            for materia in self.materias_para_mostrar["principal"]:
                tipo = clasificar_tipo_materia(
                    materia,
                    codigo_base(materia.get("codigo")),
                    codigos_plan,
                )
                grupos_por_tipo.setdefault(tipo, []).append(materia)

            orden_tipos = (
                "Normales",
                "Optativas",
                "Nivelación",
                "Trabajo de grado (P)",
                "Otros",
            )
            for tipo in orden_tipos:
                materias_tipo = grupos_por_tipo.get(tipo, [])
                if not materias_tipo:
                    continue
                self.agregar_seccion_asignaturas(
                    contenedor,
                    tipo.upper(),
                    materias_tipo,
                    "principal",
                    COLOR_VERDE if any(
                        codigo_base(materia.get("codigo")) in self.codigos_recomendados
                        for materia in materias_tipo
                    ) else None,
                    recomendadas=self.codigos_recomendados,
                )
            self.agregar_seccion_asignaturas(
                contenedor, "LIBRES ELECCIÓN", self.materias_para_mostrar["libre"], "libre",
            )
            self.agregar_seccion_asignaturas(
                contenedor,
                "NO DISPONIBLES · revisa el motivo",
                self.materias_bloqueadas_buscadas(),
                "principal",
                COLOR_ROJO,
            )
            aprobadas = []
            origenes_aprobadas = {}
            codigos_aprobadas = set()
            for origen in ("principal", "libre"):
                for materia in self.materias_por_origen.get(origen, []):
                    codigo = codigo_base(materia.get("codigo"))
                    if codigo in self.materias_aprobadas and codigo not in codigos_aprobadas:
                        aprobadas.append(materia)
                        origenes_aprobadas[codigo] = origen
                        codigos_aprobadas.add(codigo)
            self.agregar_seccion_asignaturas(
                contenedor,
                "APROBADAS",
                aprobadas,
                "principal",
                COLOR_TEXTO_SECUNDARIO,
                origen_por_codigo=origenes_aprobadas,
            )
        contenedor.layout().addStretch()
        self.filtrar_asignaturas(self.buscar_asignaturas.text())
        self._reconstruyendo_lista = False

    def agregar_seccion_asignaturas(
        self, contenedor, titulo, materias, origen, color=None, recomendadas=None,
        origen_por_codigo=None,
    ):
        """Añade un grupo desplegable solamente cuando tiene materias."""
        if not materias:
            return
        clave = titulo
        expandida = self.secciones_expandida.get(
            clave, self.todas_secciones_expandidas
        )
        encabezado = QPushButton()
        encabezado.setProperty("titulo_seccion", titulo)
        encabezado.setText(f"▾  {titulo}" if expandida else f"▸  {titulo}")
        encabezado.setCursor(Qt.PointingHandCursor)
        encabezado.setMinimumHeight(27)
        encabezado.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        fuente_encabezado = encabezado.font()
        fuente_encabezado.setPointSize(10)
        fuente_encabezado.setBold(True)
        encabezado.setFont(fuente_encabezado)
        encabezado.setStyleSheet(
            f"QPushButton {{ background-color: transparent; color: {color or COLOR_TEXTO_SECUNDARIO}; "
            f"border: none; border-radius: 5px; padding: 6px 8px; text-align: left; }}"
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"color: {COLOR_TEXTO}; }}"
        )
        contenedor.layout().addWidget(encabezado)
        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: transparent;")
        cuerpo_layout = QVBoxLayout(cuerpo)
        cuerpo_layout.setContentsMargins(8, 0, 0, 3)
        cuerpo_layout.setSpacing(5)
        for materia in ordenar_materias(materias, recomendadas or set()):
            origen_materia = (origen_por_codigo or {}).get(
                codigo_base(materia.get("codigo")), origen
            )
            cuerpo_layout.addWidget(self.crear_boton_asignatura(materia, origen_materia))
        cuerpo.setVisible(expandida)
        contenedor.layout().addWidget(cuerpo)
        self._secciones_asignaturas[clave] = (encabezado, cuerpo)

        def alternar(estado):
            self.secciones_expandida[clave] = bool(estado)
            cuerpo.setVisible(bool(estado))
            encabezado.setText(f"▾  {titulo}" if estado else f"▸  {titulo}")

        encabezado.setCheckable(True)
        encabezado.setChecked(expandida)
        encabezado.toggled.connect(alternar)

    def crear_boton_asignatura(self, materia, origen):
        seleccionada = self.materia_ya_seleccionada(materia)
        marca = "✓ " if seleccionada else ""
        texto = (
            f"{marca}{materia.get('nombre', 'Materia')}\n"
            f"{materia.get('codigo', '')} · {materia.get('creditos', '?')} créditos"
        )
        boton = QPushButton(texto)
        boton.setProperty("es_materia", True)
        boton.setProperty("texto_busqueda", texto)
        motivo = motivo_materia_no_mostrable(
            materia,
            self.materias_aprobadas,
            {codigo_base(referencia.get("codigo")) for referencia in self.referencias},
        )
        if motivo:
            boton.setText(f"{texto}\nNo disponible: {motivo}")
            boton.setEnabled(False)
            boton.setStyleSheet(
                f"QPushButton {{ background-color: {COLOR_ROJO_FONDO}; color: {COLOR_TEXTO}; "
                f"border: 1px solid {COLOR_ROJO}; border-radius: 6px; padding: 7px 8px; "
                "text-align: left; font-size: 11px; }"
            )
            return boton
        boton.setCursor(Qt.PointingHandCursor)
        boton.setMinimumHeight(51)
        borde = COLOR_VERDE if seleccionada else COLOR_LINEA
        fondo = COLOR_VERDE_FONDO if seleccionada else "transparent"
        boton.setStyleSheet(
            f"""QPushButton {{ background-color: {fondo}; color: {COLOR_TEXTO}; border: 1px solid {borde};
            border-radius: 6px; padding: 7px 8px; text-align: left; font-size: 11px; }}
            QPushButton:hover {{ border-color: {COLOR_VERDE}; background-color: {COLOR_SUPERFICIE_CLARA}; }}"""
        )
        if seleccionada:
            referencia = self.referencia_de_materia(materia)
            contenedor = QWidget()
            contenedor.setProperty("es_materia", True)
            contenedor.setProperty("texto_busqueda", texto)
            columna = QVBoxLayout(contenedor)
            columna.setContentsMargins(0, 0, 0, 0)
            columna.setSpacing(3)
            columna.addWidget(boton)
            acciones = QHBoxLayout()
            acciones.setContentsMargins(0, 0, 0, 0)
            acciones.setSpacing(4)
            quitar = QPushButton("× Quitar del horario")
            cambiar = QPushButton("Cambiar grupo")
            for accion in (quitar, cambiar):
                accion.setCursor(Qt.PointingHandCursor)
                accion.setMinimumHeight(32)
                accion.setStyleSheet(self.estilo_boton_grupo(COLOR_SUPERFICIE, COLOR_LINEA))
            acciones.addWidget(quitar)
            acciones.addWidget(cambiar)
            columna.addLayout(acciones)
            quitar.clicked.connect(
                lambda _, ref=referencia: self.quitar_grupo(ref) if ref else None
            )
            cambiar.clicked.connect(
                lambda _, m=materia, fuente=origen, ref=referencia:
                self.mostrar_detalle_asignatura(m, fuente, referencia_cambio=ref)
                if ref else None
            )
            return contenedor
        boton.clicked.connect(
            lambda _, asignatura=materia, fuente=origen:
            self.mostrar_detalle_asignatura(asignatura, fuente)
        )
        return boton

    def referencia_de_materia(self, materia):
        codigo = codigo_base(materia.get("codigo"))
        for referencia in self.referencias:
            if codigo_base(referencia.get("codigo")) == codigo:
                return referencia
        return None

    def materias_bloqueadas_buscadas(self):
        """Devuelve materias bloqueadas que coinciden con el texto buscado."""
        consulta = self.buscar_asignaturas.text().casefold().strip()
        if not consulta:
            return []
        seleccionadas = {
            codigo_base(referencia.get("codigo")) for referencia in self.referencias
        }
        resultado = []
        for materia in self.materias_por_origen.get("principal", []):
            texto = f"{materia.get('nombre', '')} {materia.get('codigo', '')}".casefold()
            motivo = motivo_materia_no_mostrable(
                materia, self.materias_aprobadas, seleccionadas
            )
            if consulta in texto and motivo:
                resultado.append(materia)
        return resultado

    def filtrar_asignaturas(self, texto):
        """Filtra las tarjetas por coincidencia parcial en nombre o código."""
        def normalizar(valor):
            descompuesto = unicodedata.normalize("NFD", str(valor or ""))
            return "".join(
                caracter for caracter in descompuesto
                if unicodedata.category(caracter) != "Mn"
            ).casefold().strip()

        consulta = normalizar(texto)
        if not hasattr(self, "lista_asignaturas"):
            return
        for clave, (encabezado, cuerpo) in self._secciones_asignaturas.items():
            coincidencias = 0
            for indice in range(cuerpo.layout().count()):
                widget = cuerpo.layout().itemAt(indice).widget()
                if widget is None:
                    continue
                texto_materia = normalizar(widget.property("texto_busqueda"))
                coincide = not consulta or consulta in texto_materia
                widget.setVisible(coincide)
                coincidencias += int(coincide)
            visible = coincidencias > 0 and not (clave == "APROBADAS" and not consulta)
            encabezado.setVisible(visible)
            cuerpo.setVisible(visible and (bool(consulta) or self.secciones_expandida.get(clave, False)))
            if consulta and visible:
                encabezado.setChecked(True)

    def mostrar_menu_asignatura(self, materia, origen, posicion):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {COLOR_SUPERFICIE}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; }} "
            f"QMenu::item:selected {{ background-color: {COLOR_SUPERFICIE_CLARA}; }}"
        )
        accion = menu.addAction("Más información")
        accion.triggered.connect(
            lambda: self.mostrar_detalle_asignatura(materia, origen, solo_informacion=True)
        )
        menu.exec(posicion)

    def mostrar_detalle_asignatura(
        self, materia, origen, solo_informacion=False, referencia_cambio=None,
        no_modal=False,
    ):
        dialogo = QDialog(self)
        dialogo.setWindowTitle(f"{materia.get('nombre', 'Materia')} · Fénix")
        dialogo.setMinimumWidth(560)
        dialogo.setMinimumHeight(460)
        dialogo.setStyleSheet(
            f"""QDialog {{ background-color: {COLOR_SUPERFICIE}; }}
            QLabel {{ color: {COLOR_TEXTO}; }}
            QScrollArea {{ border: none; background: transparent; }}"""
        )
        principal = QVBoxLayout(dialogo)
        principal.setContentsMargins(20, 18, 20, 18)
        titulo = QLabel(materia.get("nombre", "Materia"))
        titulo.setWordWrap(True)
        titulo.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {COLOR_TEXTO};")
        principal.addWidget(titulo)
        datos = QLabel(
            f"Código {materia.get('codigo', '')} · {materia.get('creditos', '?')} créditos\n"
            f"{materia.get('tipologia', 'Tipología no disponible')}"
        )
        datos.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        principal.addWidget(datos)
        area = self.crear_area_desplazable()
        contenido = area.widget()
        descripcion = str(materia.get("descripcion", "")).strip()
        if descripcion:
            etiqueta_descripcion = QLabel(descripcion)
            etiqueta_descripcion.setWordWrap(True)
            etiqueta_descripcion.setStyleSheet(
                f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 12px; padding: 6px 0;"
            )
            contenido.layout().addWidget(etiqueta_descripcion)
        prerrequisitos = materia.get("prerrequisitos", [])
        if prerrequisitos:
            texto_prerrequisitos = ", ".join(str(valor) for valor in prerrequisitos)
            etiqueta_prerrequisitos = QLabel(f"Prerrequisitos: {texto_prerrequisitos}")
            etiqueta_prerrequisitos.setWordWrap(True)
            etiqueta_prerrequisitos.setStyleSheet(
                f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;"
            )
            contenido.layout().addWidget(etiqueta_prerrequisitos)
        grupos_titulo = QLabel("GRUPOS")
        grupos_titulo.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px; font-weight: 700; padding-top: 8px;"
        )
        contenido.layout().addWidget(grupos_titulo)
        grupos = materia.get("grupos", [])
        if not grupos:
            sin_grupos = QLabel("Esta materia no tiene grupos en la oferta actual.")
            sin_grupos.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; padding: 8px 0;")
            contenido.layout().addWidget(sin_grupos)
        for grupo in grupos:
            contenido.layout().addWidget(
                self.crear_boton_grupo(
                    origen, materia, grupo, dialogo, solo_informacion, referencia_cambio
                )
            )
        contenido.layout().addStretch()
        principal.addWidget(area, 1)
        cerrar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        cerrar.rejected.connect(dialogo.reject)
        principal.addWidget(cerrar)
        if no_modal:
            dialogo.setModal(False)
            dialogo.setWindowModality(Qt.WindowModality.NonModal)
            dialogo.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self.dialogos_no_modales.append(dialogo)
            dialogo.destroyed.connect(
                lambda *_args, actual=dialogo: self._olvidar_dialogo_no_modal(actual)
            )
            dialogo.show()
            dialogo.raise_()
            dialogo.activateWindow()
        else:
            dialogo.exec()

    def _olvidar_dialogo_no_modal(self, dialogo):
        if dialogo in self.dialogos_no_modales:
            self.dialogos_no_modales.remove(dialogo)

    def crear_boton_grupo(
        self, origen, materia, grupo, dialogo, solo_informacion, referencia_cambio=None
    ):
        referencia = crear_referencia(origen, materia, grupo)
        seleccionado = any(
            referencias_iguales(referencia, actual) for actual in self.referencias
        )
        es_cambio = referencia_cambio is not None
        cupos = grupo.get("cupos_disponibles")
        if cupos is None:
            cupos_texto = "Cupos no informados"
        elif cupos <= 0:
            cupos_texto = "Sin cupos · puedes añadirlo para ver el horario"
        else:
            cupos_texto = f"{cupos} cupos disponibles"
        detalle = texto_horarios(grupo)
        profesor = str(grupo.get("profesor", "")).strip()
        texto = f"Grupo {grupo.get('numero', '?')} · {cupos_texto}\n{detalle}"
        if profesor:
            texto += f"\nDocente: {profesor}"
        boton = QPushButton(texto)
        boton.setMinimumHeight(63)
        boton.setCursor(Qt.PointingHandCursor)
        if seleccionado:
            accion = "Estado: seleccionado" if solo_informacion else (
                "Grupo actual" if es_cambio else "Clic para quitar del horario"
            )
            boton.setText(f"✓ Seleccionado · {texto}\n{accion}")
            boton.setStyleSheet(self.estilo_boton_grupo(COLOR_VERDE_FONDO, COLOR_VERDE))
            if not solo_informacion and not es_cambio:
                boton.clicked.connect(
                    lambda _, ref=referencia: self.cambiar_grupo_desde_dialogo(dialogo, ref, quitar=True)
                )
            else:
                boton.setEnabled(False)
            return boton
        if self.materia_ya_seleccionada(materia) and not es_cambio:
            boton.setText(f"{texto}\nNo permitido: ya elegiste otro grupo de esta materia")
            boton.setEnabled(False)
            boton.setStyleSheet(self.estilo_boton_grupo(COLOR_ROJO_FONDO, COLOR_ROJO))
            return boton
        grupos_actuales = self.grupos_actuales()
        if es_cambio:
            grupos_actuales = [
                (materia_actual, grupo_actual)
                for materia_actual, grupo_actual in grupos_actuales
                if not referencias_iguales(
                    crear_referencia(origen, materia_actual, grupo_actual), referencia_cambio
                )
            ]
        elegible, motivo = grupo_es_elegible(grupo, grupos_actuales)
        if not elegible:
            conflictos = self.detalles_conflicto_grupo(grupo)
            if conflictos:
                resumen = "\n".join(conflictos)
                boton.setText(f"{texto}\nNo permitido: {resumen}\nClic para previsualizar el conflicto")
                boton.clicked.connect(
                    lambda _, m=materia, g=grupo, d=dialogo: self.previsualizar_conflicto(m, g, d)
                )
            else:
                boton.setText(f"{texto}\nNo permitido: {motivo}")
                boton.setEnabled(False)
            boton.setStyleSheet(self.estilo_boton_grupo(COLOR_ROJO_FONDO, COLOR_ROJO))
            return boton
        if motivo == "Sin cupos disponibles":
            accion = "Advertencia: sin cupos · clic para añadir al horario"
        else:
            accion = "Estado: permitido" if solo_informacion else "Permitido: clic para añadir al horario"
        boton.setText(f"{texto}\n{accion}")
        color_fondo = COLOR_ROJO_FONDO if motivo == "Sin cupos disponibles" else COLOR_VERDE_FONDO
        color_borde = COLOR_ROJO if motivo == "Sin cupos disponibles" else COLOR_VERDE
        boton.setStyleSheet(self.estilo_boton_grupo(color_fondo, color_borde))
        if not solo_informacion:
            if es_cambio:
                boton.clicked.connect(
                    lambda _, actual=referencia_cambio, nuevo=referencia:
                    self.reemplazar_grupo_desde_dialogo(dialogo, actual, nuevo)
                )
            else:
                boton.clicked.connect(
                    lambda _, ref=referencia: self.cambiar_grupo_desde_dialogo(dialogo, ref)
                )
        else:
            boton.setEnabled(False)
        return boton

    def detalles_conflicto_grupo(self, grupo):
        """Resume los choques del grupo contra las materias ya seleccionadas."""
        detalles = []
        for materia_actual, grupo_actual in self.grupos_actuales():
            for conflicto in detalles_conflicto(grupo, grupo_actual):
                detalles.append(
                    f"Conflicto con {materia_actual.get('nombre', 'otra materia')} "
                    f"el {conflicto['dia'].title()} "
                    f"{conflicto['hora_inicio']}–{conflicto['hora_fin']}"
                )
        return detalles

    def previsualizar_conflicto(self, materia, grupo, dialogo=None):
        """Muestra temporalmente el grupo rechazado junto al horario actual."""
        conflictos = self.detalles_conflicto_grupo(grupo)
        if not conflictos:
            return
        self.grupo_previsualizado = (materia, grupo)
        actuales = self.grupos_actuales()
        self.cuadricula.actualizar(actuales + [self.grupo_previsualizado])
        self.resumen.setText(
            "PREVISUALIZACIÓN · " + " | ".join(conflictos) +
            " · El grupo no se añadió al horario."
        )
        if dialogo is not None:
            dialogo.accept()
        QTimer.singleShot(4500, self.limpiar_previsualizacion)

    def limpiar_previsualizacion(self):
        if self.grupo_previsualizado is None:
            return
        self.grupo_previsualizado = None
        self.actualizar_horario()

    @staticmethod
    def estilo_boton_grupo(fondo, borde):
        return (
            f"QPushButton {{ background-color: {fondo}; color: {COLOR_TEXTO}; border: 1px solid {borde}; "
            "border-radius: 6px; padding: 8px 10px; text-align: left; font-size: 11px; } "
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; }} "
            f"QPushButton:disabled {{ color: {COLOR_TEXTO}; background-color: {fondo}; }}"
        )

    def cambiar_grupo_desde_dialogo(self, dialogo, referencia, quitar=False):
        if quitar:
            self.quitar_grupo(referencia)
        else:
            self.agregar_grupo(referencia)
        dialogo.accept()

    def reemplazar_grupo_desde_dialogo(self, dialogo, actual, nuevo):
        """Reemplaza el grupo conservando la materia seleccionada."""
        referencias_originales = list(self.referencias)
        self.referencias = [
            referencia
            for referencia in self.referencias
            if not referencias_iguales(referencia, actual)
        ]
        encontrados = grupos_seleccionados(self.materias_por_origen, [nuevo])
        if not encontrados:
            self.referencias = referencias_originales
            return
        _, materia, grupo = encontrados[0]
        elegible, motivo = grupo_es_elegible(grupo, self.grupos_actuales())
        if not elegible:
            self.referencias = referencias_originales
            QMessageBox.warning(self, "Grupo no disponible", motivo)
            return
        self.referencias.append(nuevo)
        self.guardar_estado_estudiante()
        self.actualizar_interfaz()
        dialogo.accept()

    def ejecutar_accion_materia(self, materia, grupo, accion):
        """Procesa las acciones mostradas sobre una tarjeta del horario."""
        referencia = self.referencia_de_materia(materia)
        if referencia is None:
            return
        if accion == "quitar":
            self.quitar_grupo(referencia)
        elif accion == "cambiar":
            origen = referencia.get("origen", "principal")
            self.mostrar_detalle_asignatura(
                materia, origen, referencia_cambio=referencia
            )

    def agregar_grupo(self, referencia):
        encontrados = grupos_seleccionados(self.materias_por_origen, [referencia])
        if not encontrados:
            return
        _, materia, grupo = encontrados[0]
        if self.materia_ya_seleccionada(materia):
            QMessageBox.warning(
                self, "Materia ya seleccionada", "Solo puedes tener un grupo seleccionado por cada materia."
            )
            return
        elegible, motivo = grupo_es_elegible(grupo, self.grupos_actuales())
        if not elegible:
            QMessageBox.warning(self, "Grupo no disponible", motivo)
            return
        self.referencias.append(referencia)
        self.guardar_estado_estudiante()
        self.actualizar_interfaz()

    def quitar_grupo(self, referencia):
        self.referencias = [
            actual for actual in self.referencias if not referencias_iguales(actual, referencia)
        ]
        self.guardar_estado_estudiante()
        self.actualizar_interfaz()

    def mostrar_materias_fuera_horario(self):
        """Muestra las sesiones que no caben en la cuadrícula principal."""
        seleccionados = (
            grupos_seleccionados(self.materias_por_origen, self.referencias)
            if self.codigo_plan else []
        )
        dias_cortos = {
            "LUNES": "Lun", "MARTES": "Mar", "MIÉRCOLES": "Mié",
            "JUEVES": "Jue", "VIERNES": "Vie", "SÁBADO": "Sáb",
            "DOMINGO": "Dom",
        }
        entradas = []
        for referencia, materia, grupo in seleccionados:
            sesiones = sesiones_fuera_de_horario_normal(grupo)
            if not sesiones:
                continue
            detalles = []
            for sesion in sesiones:
                dia = dias_cortos.get(str(sesion.get("dia", "")).upper(), sesion.get("dia", ""))
                ubicacion = "Virtual" if es_sesion_virtual(sesion) else str(sesion.get("aula", "")).strip()
                detalles.append(
                    f"{dia} {sesion.get('hora_inicio', '')}–{sesion.get('hora_fin', '')}"
                    f" · {ubicacion or 'Salón por confirmar'}"
                )
            entradas.append((referencia, materia, grupo, "  |  ".join(detalles)))

        if not entradas:
            return
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Materias por fuera de horario normal")
        dialogo.setMinimumWidth(620)
        dialogo.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_SUPERFICIE}; }} "
            f"QLabel {{ color: {COLOR_TEXTO}; }} "
        )
        layout = QVBoxLayout(dialogo)
        titulo = QLabel("Estas materias no aparecen en la cuadrícula principal")
        titulo.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 15px; font-weight: 700;")
        layout.addWidget(titulo)
        explicacion = QLabel(
            "Incluye clases del domingo o sesiones antes de las 06:00 y después de las 20:00."
        )
        explicacion.setWordWrap(True)
        explicacion.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        layout.addWidget(explicacion)
        area = self.crear_area_desplazable()
        contenido = area.widget()
        for referencia, materia, grupo, detalle in entradas:
            tarjeta = QFrame()
            tarjeta.setStyleSheet(
                f"background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
                f"border: 1px solid {COLOR_LINEA}; border-radius: 7px;"
            )
            fila = QHBoxLayout(tarjeta)
            fila.setContentsMargins(10, 8, 10, 8)
            columna = QVBoxLayout()
            columna.setContentsMargins(0, 0, 0, 0)
            nombre = QLabel(
                f"{materia.get('nombre', 'Materia')} · Grupo {grupo.get('numero', '?')}"
            )
            nombre.setStyleSheet(f"color: {COLOR_TEXTO}; font-weight: 700; border: none;")
            nombre.setWordWrap(True)
            horario = QLabel(detalle)
            horario.setStyleSheet(
                f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px; border: none;"
            )
            horario.setWordWrap(True)
            columna.addWidget(nombre)
            columna.addWidget(horario)
            fila.addLayout(columna, 1)
            cambiar = QPushButton("Cambiar grupo")
            cambiar.setStyleSheet(self.estilo_boton_grupo(COLOR_SUPERFICIE, COLOR_LINEA))
            cambiar.clicked.connect(
                lambda _, d=dialogo, r=referencia, m=materia:
                self.editar_materia_fuera_horario(d, r, m)
            )
            fila.addWidget(cambiar)
            quitar = QPushButton("X")
            quitar.setFixedWidth(34)
            quitar.setStyleSheet(self.estilo_boton_grupo(COLOR_ROJO_FONDO, COLOR_ROJO))
            quitar.clicked.connect(
                lambda _, d=dialogo, r=referencia: self.quitar_materia_fuera_horario(d, r)
            )
            fila.addWidget(quitar)
            contenido.layout().addWidget(tarjeta)
        contenido.layout().addStretch()
        layout.addWidget(area, 1)
        cerrar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        cerrar.rejected.connect(dialogo.reject)
        layout.addWidget(cerrar)
        dialogo.exec()

    def editar_materia_fuera_horario(self, dialogo, referencia, materia):
        """Cierra el listado y abre el selector de grupos de la materia."""
        origen = referencia.get("origen", "principal")
        dialogo.accept()
        self.mostrar_detalle_asignatura(materia, origen, referencia_cambio=referencia)

    def quitar_materia_fuera_horario(self, dialogo, referencia):
        """Elimina una materia fuera de horario y refresca la interfaz."""
        dialogo.accept()
        self.quitar_grupo(referencia)

    @staticmethod
    def creditos_de_materia(materia):
        """Convierte el campo de créditos del SIA a un número utilizable."""
        valor = str(materia.get("creditos", "") or "").replace(",", ".")
        coincidencia = re.search(r"\d+(?:\.\d+)?", valor)
        if not coincidencia:
            return 0.0
        try:
            return float(coincidencia.group(0))
        except ValueError:
            return 0.0

    @staticmethod
    def formato_creditos(valor):
        return str(int(valor)) if float(valor).is_integer() else f"{valor:.1f}"

    @staticmethod
    def tipo_credito_oficial(materia):
        """Normaliza la tipología del SIA a una de las siete categorías oficiales."""
        texto = unicodedata.normalize(
            "NFD",
            f"{materia.get('tipologia', '')} {materia.get('nombre', '')}".casefold(),
        )
        texto = "".join(
            caracter for caracter in texto
            if unicodedata.category(caracter) != "Mn"
        )
        if "libre" in texto:
            return "Libre Eleccion"
        if "nivel" in texto:
            return "Nivelacion"
        if "trabajo de grado" in texto or "grado (p)" in texto:
            return "Trabajo de Grado"
        if "fundament" in texto:
            return "Fundamentacion Optativa" if "optativ" in texto or "electiv" in texto else "Fundamentacion Obligatoria"
        if "disciplinar" in texto:
            return "Disciplinar Optativa" if "optativ" in texto or "electiv" in texto else "Disciplinar Obligatoria"
        # El catálogo actual usa Disciplinar como tipología por defecto cuando
        # no repite la palabra Obligatoria en cada registro.
        return "Disciplinar Obligatoria"

    def mostrar_desglose_creditos(self):
        """Muestra el total de créditos seleccionados y su distribución."""
        grupos = self.grupos_actuales() if self.codigo_plan else []
        por_tipo = {tipo: 0.0 for tipo in TIPOS_CREDITOS_OFICIALES}
        total = 0.0
        for materia, _ in grupos:
            creditos = self.creditos_de_materia(materia)
            tipo = self.tipo_credito_oficial(materia)
            por_tipo[tipo] = por_tipo.get(tipo, 0.0) + creditos
            total += creditos
        if grupos:
            desglose = "\n".join(
                f"• {tipo}: {self.formato_creditos(por_tipo[tipo])} crédito(s)"
                for tipo in TIPOS_CREDITOS_OFICIALES
            )
        else:
            desglose = "Todavía no has añadido materias al horario."
        QMessageBox.information(
            self,
            "Créditos del horario",
            f"Total: {self.formato_creditos(total)} crédito(s)\n\n{desglose}",
        )

    def actualizar_horario(self):
        grupos = self.grupos_actuales() if self.codigo_plan else []
        total_creditos = sum(
            self.creditos_de_materia(materia) for materia, _ in grupos
        )
        self.boton_creditos.setText(
            f"Créditos: {self.formato_creditos(total_creditos)}"
        )
        tiene_fuera_horario = any(
            sesiones_fuera_de_horario_normal(grupo)
            for _, grupo in grupos
        )
        self.boton_fuera_horario.setVisible(tiene_fuera_horario)
        self.cuadricula.actualizar(grupos)
        if not self.codigo_plan:
            self.resumen.setText(
                "El horario se habilitará cuando termine la primera actualización de datos."
            )
        else:
            self.resumen.setText(
                f"{len(grupos)} grupo(s) seleccionado(s) · {self.planes[self.codigo_plan].nombre}"
            )
        contenedor = self.lista_seleccionados.widget()
        limpiar_layout(contenedor.layout())
        if not grupos:
            texto = "Aún no has añadido grupos." if self.codigo_plan else "Sin grupos seleccionados todavía."
            vacio = QLabel(texto)
            vacio.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; padding: 7px;")
            contenedor.layout().addWidget(vacio)
        else:
            for referencia, materia, grupo in grupos_seleccionados(
                self.materias_por_origen, self.referencias
            ):
                contenedor.layout().addWidget(
                    self.crear_fila_seleccionada(referencia, materia, grupo)
                )
        contenedor.layout().addStretch()

    def abrir_editor_grupos(self):
        """Abre el menú para cambiar de grupo o quitar materias del horario."""
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Editar materias y grupos")
        dialogo.setMinimumWidth(620)
        dialogo.setStyleSheet(
            f"""
            QDialog {{ background-color: {COLOR_SUPERFICIE}; }}
            QLabel {{ color: {COLOR_TEXTO}; }}
            QComboBox {{
                background-color: {COLOR_SUPERFICIE_CLARA};
                color: {COLOR_TEXTO};
                border: 1px solid {COLOR_LINEA};
                border-radius: 5px;
                padding: 4px 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLOR_SUPERFICIE_CLARA};
                color: {COLOR_TEXTO};
                selection-background-color: {COLOR_VERDE};
                selection-color: #ffffff;
            }}
            """
        )
        principal = QVBoxLayout(dialogo)
        principal.setContentsMargins(20, 18, 20, 18)
        titulo = QLabel("Materias del horario")
        titulo.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 20px; font-weight: 800;")
        principal.addWidget(titulo)
        ayuda = QLabel("Cambia el grupo o quita una materia. Los cambios se guardan al aplicarlos.")
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        principal.addWidget(ayuda)
        area = self.crear_area_desplazable()
        contenido = area.widget()
        entradas = grupos_seleccionados(self.materias_por_origen, self.referencias)
        if not entradas:
            vacio = QLabel("No hay materias seleccionadas todavía.")
            vacio.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; padding: 10px;")
            contenido.layout().addWidget(vacio)
        for referencia, materia, grupo in entradas:
            tarjeta = QFrame()
            tarjeta.setStyleSheet(
                f"background-color: {COLOR_SUPERFICIE_CLARA}; border: 1px solid {COLOR_LINEA}; border-radius: 7px;"
            )
            fila = QHBoxLayout(tarjeta)
            fila.setContentsMargins(10, 8, 10, 8)
            info = QLabel(f"{materia.get('nombre', '')}\n{materia.get('codigo', '')}")
            info.setWordWrap(True)
            fila.addWidget(info, 1)
            opciones = QComboBox()
            grupos = materia.get("grupos", [])
            indice_actual = 0
            for indice, grupo_opcion in enumerate(grupos):
                opciones.addItem(
                    f"Grupo {grupo_opcion.get('numero', '?')} · {texto_horarios(grupo_opcion)}",
                    grupo_opcion,
                )
                if str(grupo_opcion.get("numero")) == str(grupo.get("numero")):
                    indice_actual = indice
            opciones.setCurrentIndex(indice_actual)
            opciones.setMinimumWidth(245)
            fila.addWidget(opciones)
            aplicar = QPushButton("Aplicar")
            aplicar.clicked.connect(
                lambda _, r=referencia, m=materia, c=opciones, d=dialogo:
                self.aplicar_cambio_grupo(r, m, c, d)
            )
            fila.addWidget(aplicar)
            quitar = QPushButton("Quitar")
            quitar.setStyleSheet(f"QPushButton {{ color: {COLOR_ROJO}; }}")
            quitar.clicked.connect(
                lambda _, r=referencia, d=dialogo: self.quitar_desde_editor(r, d)
            )
            fila.addWidget(quitar)
            contenido.layout().addWidget(tarjeta)
        contenido.layout().addStretch()
        principal.addWidget(area, 1)
        cerrar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        cerrar.rejected.connect(dialogo.reject)
        principal.addWidget(cerrar)
        dialogo.exec()

    def aplicar_cambio_grupo(self, referencia, materia, selector, dialogo):
        grupo = selector.currentData()
        if not grupo:
            return
        elegible, motivo = grupo_es_elegible(
            grupo,
            [actual for actual in self.grupos_actuales()
             if actual[0].get("codigo") != materia.get("codigo")],
        )
        if not elegible:
            QMessageBox.warning(self, "Grupo no disponible", motivo)
            return
        origen = "principal"
        for posible_origen, _, _ in grupos_seleccionados(
            self.materias_por_origen, [referencia]
        ):
            origen = posible_origen
            break
        nueva = crear_referencia(origen, materia, grupo)
        self.referencias = [
            nueva if referencias_iguales(actual, referencia) else actual
            for actual in self.referencias
        ]
        self.guardar_estado_estudiante()
        self.actualizar_interfaz()
        dialogo.accept()

    def quitar_desde_editor(self, referencia, dialogo):
        self.quitar_grupo(referencia)
        dialogo.accept()

    def crear_fila_seleccionada(self, referencia, materia, grupo):
        fila = QFrame()
        fila.setStyleSheet(
            f"background-color: {COLOR_SUPERFICIE}; border: 1px solid {COLOR_LINEA}; border-radius: 7px;"
        )
        layout = QHBoxLayout(fila)
        layout.setContentsMargins(10, 6, 8, 6)
        texto = QLabel(
            f"{materia.get('nombre', '')} · Grupo {grupo.get('numero', '')}\n{texto_horarios(grupo)}"
        )
        texto.setWordWrap(True)
        texto.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 11px;")
        layout.addWidget(texto, 1)
        quitar = QPushButton("Quitar")
        quitar.setCursor(Qt.PointingHandCursor)
        quitar.clicked.connect(lambda _, ref=referencia: self.quitar_grupo(ref))
        quitar.setStyleSheet(
            f"QPushButton {{ color: {COLOR_ROJO}; border: 1px solid {COLOR_ROJO}; border-radius: 5px; "
            "padding: 5px 7px; } "
            f"QPushButton:hover {{ background-color: {COLOR_ROJO_FONDO}; }}"
        )
        layout.addWidget(quitar)
        return fila

    def mostrar_grupos_del_bloque(self, dia, hora, duracion):
        """Permite elegir el origen y muestra grupos válidos de una franja."""
        if not self.codigo_plan:
            return

        principales = self.grupos_elegibles_en_bloque("principal", dia, hora, duracion)
        libres = self.grupos_elegibles_en_bloque("libre", dia, hora, duracion)
        if not principales and not libres:
            QMessageBox.information(
                self,
                "Sin grupos disponibles",
                "No hay grupos con clase en este día y hora que puedan añadirse "
                "sin crear un conflicto con tu horario actual."
            )
            return

        nombre_dia = dict(DIAS).get(dia, dia.title())
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {COLOR_SUPERFICIE}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; }} "
            f"QMenu::item:selected {{ background-color: {COLOR_SUPERFICIE_CLARA}; }}"
        )
        encabezado = menu.addAction(f"{nombre_dia} · {hora:02d}:00–{hora + duracion:02d}:00")
        encabezado.setEnabled(False)
        menu.addSeparator()
        accion_principales = menu.addAction(
            f"Materias principales ({len(principales)} grupo(s) disponible(s))"
        )
        accion_principales.setEnabled(bool(principales))
        accion_principales.triggered.connect(
            lambda: self.mostrar_grupos_por_origen_en_bloque(
                "principal", dia, hora, duracion, principales
            )
        )
        accion_libres = menu.addAction(
            f"Libres elecciones ({len(libres)} grupo(s) disponible(s))"
        )
        accion_libres.setEnabled(bool(libres))
        accion_libres.triggered.connect(
            lambda: self.mostrar_grupos_por_origen_en_bloque(
                "libre", dia, hora, duracion, libres
            )
        )
        menu.exec(QCursor.pos())

    def grupos_elegibles_en_bloque(self, origen, dia, hora, duracion):
        """Filtra por franja horaria y descarta grupos no seleccionables."""
        candidatos = []
        for materia in self.materias_para_mostrar.get(origen, []):
            if self.materia_ya_seleccionada(materia):
                continue
            for grupo in materia.get("grupos", []):
                if not grupo_ocupa_bloque(grupo, dia, hora, duracion):
                    continue
                elegible, _ = grupo_es_elegible(grupo, self.grupos_actuales())
                if elegible:
                    candidatos.append((materia, grupo))
        return candidatos

    def mostrar_grupos_por_origen_en_bloque(self, origen, dia, hora, duracion, candidatos):
        """Lista solo los grupos del origen elegido que coinciden con la celda."""
        nombre_origen = "Materias principales" if origen == "principal" else "Libres elecciones"
        nombre_dia = dict(DIAS).get(dia, dia.title())
        dialogo = QDialog(self)
        dialogo.setWindowTitle(
            f"{nombre_origen} · {nombre_dia} {hora:02d}:00–{hora + duracion:02d}:00"
        )
        dialogo.setMinimumWidth(560)
        dialogo.setMinimumHeight(420)
        dialogo.setStyleSheet(
            f"""QDialog {{ background-color: {COLOR_SUPERFICIE}; }}
            QLabel {{ color: {COLOR_TEXTO}; }}
            QScrollArea {{ border: none; background: transparent; }}"""
        )
        principal = QVBoxLayout(dialogo)
        principal.setContentsMargins(20, 18, 20, 18)
        titulo = QLabel(nombre_origen)
        titulo.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 20px; font-weight: 800;")
        principal.addWidget(titulo)
        descripcion = QLabel(
            f"Grupos con clase el {nombre_dia.lower()} entre las {hora:02d}:00 y "
            f"las {hora + duracion:02d}:00. "
            "Se incluyen grupos sin cupos para que puedas revisar su horario; "
            "se excluyen los que generen conflictos."
        )
        descripcion.setWordWrap(True)
        descripcion.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        principal.addWidget(descripcion)
        area = self.crear_area_desplazable()
        contenido = area.widget()
        por_materia = {}
        for materia, grupo in candidatos:
            clave = str(materia.get("codigo", ""))
            por_materia.setdefault(clave, {"materia": materia, "grupos": []})["grupos"].append(grupo)
        for entrada in sorted(
            por_materia.values(),
            key=lambda actual: clave_alfabetica(actual["materia"].get("nombre", "")),
        ):
            materia = entrada["materia"]
            tarjeta = QFrame()
            tarjeta.setStyleSheet(
                f"background-color: {COLOR_SUPERFICIE_CLARA}; border: 1px solid {COLOR_LINEA}; border-radius: 7px;"
            )
            layout = QVBoxLayout(tarjeta)
            layout.setContentsMargins(11, 9, 11, 10)
            layout.setSpacing(6)
            nombre = QLabel(
                f"{materia.get('nombre', 'Materia')} · {materia.get('creditos', '?')} créditos"
            )
            nombre.setWordWrap(True)
            nombre.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 13px; font-weight: 700;")
            layout.addWidget(nombre)
            codigo = QLabel(f"{materia.get('codigo', '')} · {materia.get('tipologia', '')}")
            codigo.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px;")
            layout.addWidget(codigo)
            for grupo in entrada["grupos"]:
                layout.addWidget(self.crear_boton_grupo(origen, materia, grupo, dialogo, False))
            contenido.layout().addWidget(tarjeta)
        contenido.layout().addStretch()
        principal.addWidget(area, 1)
        cerrar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        cerrar.rejected.connect(dialogo.reject)
        principal.addWidget(cerrar)
        dialogo.exec()

    def iniciar_actualizacion_manual(self):
        if self.proceso_actualizacion is not None:
            if self.proceso_actualizacion.poll() is None:
                return
            self.proceso_actualizacion = None
        # El proceso anterior puede haber terminado sin alcanzar a publicar
        # su estado final. No bloquear una actualización nueva por ese estado
        # obsoleto: el proceso real es la fuente de verdad.
        guardar_estado("actualizando", "Iniciando actualización manual…", 0)
        try:
            opciones = {"cwd": str(BASE_DIR)}
            if sys.platform == "win32":
                opciones["creationflags"] = subprocess.CREATE_NO_WINDOW
            self.proceso_actualizacion = subprocess.Popen(
                comando_fenix("--actualizar-solo"),
                **opciones,
            )
        except OSError as error:
            guardar_estado("error", f"No se pudo iniciar la actualización: {error}", None)
        self.revisar_actualizacion()

    def buscar_actualizacion_aplicacion(self):
        """Consulta GitHub y ofrece reiniciar Fénix con la nueva versión."""
        from servicios.actualizacion_aplicacion import (
            descargar_release,
            hay_actualizacion,
            iniciar_reemplazo,
            consultar_ultima_version,
        )

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            release = consultar_ultima_version()
            if not hay_actualizacion(release):
                QMessageBox.information(self, "Fénix actualizado", f"Ya tienes Fénix {VERSION}.")
                return
            respuesta = QMessageBox.question(
                self,
                "Actualización disponible",
                f"Está disponible Fénix {release['version']}. ¿Descargarla y reiniciar ahora?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return
            paquete = descargar_release(release)
            self.detener_actualizacion()
            iniciar_reemplazo(paquete, os.getpid())
            QApplication.quit()
        except Exception as error:
            QMessageBox.critical(self, "No se pudo actualizar Fénix", str(error))
        finally:
            QApplication.restoreOverrideCursor()

    def comprobar_version_antes_de_workers(self):
        """Autoriza el arranque solo después de revisar la versión de Fénix."""
        if self.arranque_autorizado or self.comprobacion_version_pendiente:
            return
        self.comprobacion_version_pendiente = True
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            from servicios.actualizacion_aplicacion import consultar_ultima_version, hay_actualizacion

            release = consultar_ultima_version()
            if hay_actualizacion(release):
                respuesta = QMessageBox.question(
                    self,
                    "Actualización disponible",
                    f"Está disponible Fénix {release['version']}. ¿Descargarla y reiniciar ahora?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if respuesta == QMessageBox.StandardButton.Yes:
                    from servicios.actualizacion_aplicacion import descargar_release, iniciar_reemplazo

                    paquete = descargar_release(release)
                    iniciar_reemplazo(paquete, os.getpid())
                    QApplication.quit()
                    return
            self.continuar_arranque()
        except Exception as error:
            logging.getLogger("fenix").warning("No se pudo comprobar Fénix en GitHub: %s", error)
            respuesta = QMessageBox.question(
                self,
                "No se pudo verificar Fénix",
                "No fue posible comprobar si hay una versión nueva. "
                "¿Quieres continuar sin verificar e iniciar la actualización de datos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if respuesta == QMessageBox.StandardButton.Yes:
                self.continuar_arranque()
            else:
                QApplication.quit()
        finally:
            QApplication.restoreOverrideCursor()
            self.comprobacion_version_pendiente = False

    def buscar_actualizacion_automatica(self):
        """Compatibilidad con llamadas anteriores al control de arranque."""
        self.comprobar_version_antes_de_workers()

    def continuar_arranque(self):
        """Solicita el perfil e inicia workers tras confirmar la versión."""
        if self.arranque_autorizado:
            return
        self.arranque_autorizado = True
        if self.debe_solicitar_perfil_inicial:
            self.debe_solicitar_perfil_inicial = False
            if not self.solicitar_perfil_inicial():
                QTimer.singleShot(0, QApplication.instance().quit)
                return
            self.iniciar_actualizacion_manual()
        elif self.tiene_perfil_guardado():
            self.iniciar_actualizacion_manual()
        if not self.datos_disponibles:
            self.inicio_primera_actualizacion = time.monotonic()
            self.dialogo_espera = DialogoEsperaActualizacion(self)
            self.dialogo_espera.show()
            self.revisar_actualizacion()

    def preguntar_actualizacion_guardada(self):
        """Solicita confirmación antes de reemplazar información persistida."""
        if self.estado_actualizacion == "actualizando":
            return
        respuesta = QMessageBox.question(
            self,
            "Actualizar catálogo",
            "Ya existe información guardada de materias y grupos. "
            "¿Quieres consultar nuevamente el catálogo del SIA?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta == QMessageBox.StandardButton.Yes:
            self.iniciar_actualizacion_manual()

    def revisar_actualizacion(self):
        if self.cambiando_estudiante:
            return
        estado = cargar_estado()
        nombre_estado = estado.get("estado", "sin_iniciar")
        if (
            nombre_estado == "actualizando"
            and self.proceso_actualizacion is not None
            and self.proceso_actualizacion.poll() is not None
        ):
            guardar_estado(
                "error",
                "La actualización terminó sin publicar un resultado. Puedes reintentarlo.",
                None,
            )
            estado = cargar_estado()
            nombre_estado = estado.get("estado", "error")
        progreso = estado.get("progreso")
        mensaje = estado.get("mensaje", "Esperando actualización.")
        actualizado_en = estado.get("actualizado_en")
        self.estado_actualizacion = nombre_estado
        self.actualizar_indicador_actualizacion(nombre_estado, mensaje, progreso)
        if self.dialogo_espera is not None:
            self.dialogo_espera.actualizar(
                mensaje,
                progreso,
                self.calcular_tiempo_restante(progreso),
            )
        hay_datos = self.hay_datos_disponibles()
        actualizacion_completa = nombre_estado == "completada"
        normales_listas = (
            hay_datos
            and isinstance(progreso, (int, float))
            and progreso >= 60
        )
        termino_actualizacion = (
            actualizacion_completa and actualizado_en != self.ultima_actualizacion_vista
        )
        if nombre_estado == "actualizando" and self.codigo_plan and not self.libres_bloqueadas:
            self.libres_bloqueadas = True
            self.materias_por_origen["libre"] = []
            self.actualizar_materias_para_mostrar()
            self.reconstruir_lista_asignaturas()
            self.actualizar_horario()
        # En el primer inicio la oferta normal se guarda antes de consultar
        # Libre Elección. El planificador puede habilitarse desde ese punto;
        # la sección de libres permanece oculta hasta que tenga datos.
        if hay_datos and not self.datos_disponibles and (actualizacion_completa or normales_listas):
            self.datos_disponibles = True
            self.libres_bloqueadas = not actualizacion_completa
            self.ultima_actualizacion_vista = actualizado_en
            self.activar_planificador()
            if self.dialogo_espera is not None:
                self.dialogo_espera.accept()
                self.dialogo_espera = None
        elif self.codigo_plan and nombre_estado == "actualizando":
            libres_actuales = cargar_libres_eleccion(self.codigo_plan)
            if libres_actuales != self.materias_por_origen.get("libre", []):
                self.recargar_datos()
                self.actualizar_interfaz()
        elif hay_datos and termino_actualizacion and self.codigo_plan:
            self.libres_bloqueadas = False
            self.ultima_actualizacion_vista = actualizado_en
            self.recargar_datos()
            self.actualizar_interfaz()

    def calcular_tiempo_restante(self, progreso):
        """Estima el tiempo restante a partir del progreso observado."""
        if not isinstance(progreso, (int, float)) or progreso <= 0:
            return "Calculando tiempo restante…"
        if self.inicio_primera_actualizacion is None:
            return "Calculando tiempo restante…"
        transcurrido = time.monotonic() - self.inicio_primera_actualizacion
        restante = max(0, transcurrido * (100 - progreso) / progreso)
        minutos, segundos = divmod(int(restante), 60)
        if minutos:
            return f"Tiempo estimado restante: {minutos} min {segundos:02d} s"
        return f"Tiempo estimado restante: {segundos} s"

    def actualizar_indicador_actualizacion(self, estado, mensaje, progreso):
        if estado == "actualizando":
            color = COLOR_TEXTO_SECUNDARIO
            valor = int(progreso) if isinstance(progreso, (int, float)) else 0
            self.barra_progreso.setValue(max(0, min(100, valor)))
            self.barra_progreso.setFormat(f"{valor}%")
        elif estado == "completada":
            color = COLOR_VERDE
            self.barra_progreso.setValue(100)
            self.barra_progreso.setFormat("100%")
        elif estado == "error":
            color = COLOR_ROJO
            self.barra_progreso.setValue(0)
            self.barra_progreso.setFormat("Error")
        else:
            color = COLOR_TEXTO_SECUNDARIO
            self.barra_progreso.setValue(0)
            self.barra_progreso.setFormat("Pendiente")
        self.etiqueta_estado.setText(mensaje)
        self.etiqueta_estado.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.barra_progreso.setStyleSheet(
            f"""QProgressBar {{ color: {COLOR_TEXTO}; background-color: {COLOR_BARRA}; border: 1px solid {COLOR_LINEA};
            border-radius: 5px; text-align: center; font-size: 10px; }}
            QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}"""
        )
        self.boton_actualizar.setEnabled(estado != "actualizando")

    def reiniciar_estudiante(self):
        respuesta = QMessageBox.question(
            self,
            "Cambiar estudiante",
            "Se borrarán el plan, la oferta académica y los grupos guardados. "
            "Esto forzará una actualización completa para la nueva carrera. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        self.cambiando_estudiante = True
        self.temporizador_estado.stop()
        self.cerrar_ventanas_secundarias()
        self.setEnabled(False)
        try:
            self.actualizar_indicador_actualizacion(
                "actualizando",
                "Deteniendo tareas anteriores antes de cambiar de estudiante…",
                0,
            )
            self.detener_actualizacion()
            borrar_datos_estudiante()
        except (OSError, RuntimeError) as error:
            # Reactivar antes del QMessageBox: un diálogo cuyo padre continúa
            # deshabilitado no puede recibir clics y aparenta congelar Fénix.
            self.setEnabled(True)
            self.cambiando_estudiante = False
            self.temporizador_estado.start(1000)
            QMessageBox.critical(
                self,
                "No se pudo cambiar de estudiante",
                f"Fénix no pudo detener y limpiar la sesión anterior:\n\n{error}",
            )
            return
        self.setEnabled(True)
        self.estudiante = {}
        self.referencias = []
        self.codigo_plan = None
        self.datos_disponibles = False
        self.informacion_persistida = False
        self.bloquear_planificador()
        try:
            if self.solicitar_perfil_inicial():
                self.iniciar_actualizacion_manual()
        finally:
            self.cambiando_estudiante = False
            self.temporizador_estado.start(1000)

    def cerrar_ventanas_secundarias(self):
        """Retira vistas ligadas al perfil anterior antes de borrar sus datos."""
        if self.ventana_plan_estudios is not None:
            self.ventana_plan_estudios.hide()
        for dialogo in list(self.dialogos_no_modales):
            try:
                dialogo.close()
            except RuntimeError:
                # El objeto de Qt pudo eliminarse justo antes de recorrerlo.
                pass
        self.dialogos_no_modales.clear()

    def detener_actualizacion(self):
        """Cancela cooperativamente y espera el cierre de workers/navegador."""
        solicitar_cancelacion()
        proceso = self.proceso_actualizacion
        if proceso is not None and proceso.poll() is None:
            limite = time.monotonic() + 45
            while proceso.poll() is None and time.monotonic() < limite:
                QApplication.processEvents()
                time.sleep(0.05)
            if proceso.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(proceso.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    proceso.kill()
                try:
                    proceso.wait(timeout=5)
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(
                        "El proceso de actualización anterior no pudo detenerse."
                    ) from error
        if proceso is not None and proceso.poll() is not None:
            # Una terminación forzada no alcanza el manejador del proceso que
            # publica "cancelada". Como ya acabó, es seguro cerrar su estado.
            guardar_estado(
                "cancelada",
                "Actualización detenida para cambiar de usuario.",
                None,
            )
        limite = time.monotonic() + 15
        while time.monotonic() < limite:
            if cargar_estado().get("estado") != "actualizando":
                break
            QApplication.processEvents()
            time.sleep(0.05)
        if cargar_estado().get("estado") == "actualizando":
            raise RuntimeError(
                "Las tareas anteriores no confirmaron su cierre; los datos no se borraron."
            )
        self.proceso_actualizacion = None

    def obtener_area_trabajo(self):
        pantalla = QApplication.primaryScreen()
        return pantalla.availableGeometry() if pantalla is not None else None

    def mostrar(self):
        area = self.obtener_area_trabajo()
        if area is not None:
            self.setGeometry(area)
            self.maximizada = True
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self.comprobar_version_antes_de_workers)

    def alternar_maximizacion(self):
        area = self.obtener_area_trabajo()
        if area is None:
            return
        if self.maximizada:
            self.setGeometry(
                area.x() + (area.width() - ANCHO_VENTANA) // 2,
                area.y() + (area.height() - ALTO_VENTANA) // 2,
                ANCHO_VENTANA,
                ALTO_VENTANA,
            )
            self.maximizada = False
            self.barra_titulo.boton_maximizar.setText("□")
        else:
            self.setGeometry(area)
            self.maximizada = True
            self.barra_titulo.boton_maximizar.setText("❐")


class PantallaPresentacion(QFrame):
    """Pantalla breve mostrada antes de abrir el planificador."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(360, 360)
        self.setStyleSheet(
            f"background-color: {COLOR_FONDO}; border: 1px solid {COLOR_LINEA}; border-radius: 18px;"
        )
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        if RUTA_LOGO.exists():
            logo.setPixmap(QIcon(str(RUTA_LOGO)).pixmap(180, 180))
        layout.addWidget(logo)
        nombre = QLabel("FÉNIX")
        nombre.setAlignment(Qt.AlignCenter)
        nombre.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 28px; font-weight: 800;")
        layout.addWidget(nombre)
        texto = QLabel("Preparando tu semestre")
        texto.setAlignment(Qt.AlignCenter)
        texto.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 12px;")
        layout.addWidget(texto)


def mostrar_presentacion():
    app = QApplication(sys.argv)
    app.setApplicationName("Fenix")
    app.setApplicationVersion(VERSION)
    bloqueo = QLockFile(str(CARPETA_DATOS / "fenix.lock"))
    bloqueo.setStaleLockTime(0)
    if not bloqueo.tryLock(0):
        QMessageBox.information(None, "Fénix", "Fénix ya está abierto para este usuario.")
        return 0
    import logging
    qInstallMessageHandler(
        lambda tipo, contexto, mensaje: logging.getLogger("fenix").warning("Qt: %s", mensaje)
    )
    if RUTA_LOGO.exists():
        app.setWindowIcon(QIcon(str(RUTA_LOGO)))
    splash = PantallaPresentacion()
    pantalla = app.primaryScreen()
    if pantalla is not None:
        splash.move(pantalla.availableGeometry().center() - splash.rect().center())
    splash.show()

    def abrir_ventana():
        splash.close()
        app.ventana_principal = VentanaPrincipal()
        app.ventana_principal.mostrar()

    QTimer.singleShot(900, abrir_ventana)
    return app.exec()


def iniciar_interfaz():
    sys.exit(mostrar_presentacion())


if __name__ == "__main__":
    preparar_entorno()
    iniciar_interfaz()
