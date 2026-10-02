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
from datetime import date
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal, QUrl, QLockFile, QThread, qInstallMessageHandler
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QFont, QFontDatabase, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFrame, QGridLayout, QHBoxLayout, QLayout, QLabel, QListWidget, QListWidgetItem,
    QFileDialog, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QDoubleSpinBox,
    QSizeGrip, QSizePolicy, QSplitter, QStackedLayout, QTextEdit, QToolButton, QVBoxLayout, QWidget,
    QWidgetAction,
)


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from infraestructura.almacenamiento.estado_actualizacion import cargar_estado, guardar_estado
from infraestructura.almacenamiento.json_atomico import cargar_json, guardar_json_atomico
from aplicacion.arranque import comando_fenix, preparar_entorno
from configuracion import ARCHIVO_AVANCE_ACADEMICO, CARPETA_DATOS, ES_EDICION_STORE, VERSION
from infraestructura.almacenamiento.cancelacion_actualizacion import solicitar_cancelacion
from infraestructura.almacenamiento.datos_estudiante import borrar_datos_estudiante
from infraestructura.almacenamiento.estudiante import cargar_estudiante, guardar_estudiante
from infraestructura.almacenamiento.materias import cargar_materias, cargar_plan_materias, preparar_materias_para_plan
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
from servicios.elegibilidad import buscar_materias_no_disponibles
from servicios.elegibilidad import materias_visibles
from servicios.elegibilidad import motivo_materia_no_mostrable
from servicios.elegibilidad import advertencias_materia
from servicios.tipos_materia import clasificar_tipo_materia, es_materia_nivelacion
from servicios.prerrequisitos import descripcion_tipo
from servicios.historia_academica import periodos_visibles_avance, promedio_ponderado_periodo
from aplicacion.trabajador_avance import TrabajadorAvanceAcademico


RUTA_LOGO = BASE_DIR / "recursos" / "logo.png"
RUTA_QR_DONACIONES = BASE_DIR / "recursos" / "qr_donaciones.png"
RUTA_GRACIAS = BASE_DIR / "recursos" / "gracias2.png"
RUTA_BUS_INTERCAMPUS = BASE_DIR / "recursos" / "bus.png"
CARPETA_FUENTES = BASE_DIR / "recursos" / "fuentes"
FUENTE_INTERFAZ = "Source Sans Pro"
CORREO_CONTACTO = "mialvarezr@unal.edu.co"
URL_DONACIONES = "https://example.com/donaciones"
URL_PROFESORES_RECOMENDADOS = (
    "https://www.instagram.com/unmedopina/"
)


def cargar_fuente_interfaz(app):
    """Instala la tipografía incluida y la aplica sin alterar el tamaño base."""
    familias = set()
    for nombre in (
        "SourceSansPro-Regular.ttf",
        "SourceSansPro-SemiBold.ttf",
        "SourceSansPro-Bold.ttf",
    ):
        ruta = CARPETA_FUENTES / nombre
        if not ruta.is_file():
            continue
        identificador = QFontDatabase.addApplicationFont(str(ruta))
        if identificador >= 0:
            familias.update(QFontDatabase.applicationFontFamilies(identificador))
    if FUENTE_INTERFAZ not in familias:
        return False
    fuente = app.font()
    fuente.setFamily(FUENTE_INTERFAZ)
    app.setFont(fuente)
    return True

# Paleta neutra: verde = permitido, amarillo = advertencia y rojo = bloqueo.
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
COLOR_AMARILLO = "#F2C14E"
COLOR_AMARILLO_FONDO = "#493C1C"
COLOR_NARANJA_FENIX = "#FD5D09"
COLOR_PREVISUALIZACION = "#4A4A4A"
COLOR_PREVISUALIZACION_TEXTO = "#E0E0E0"

ESTILO_BARRAS_DESPLAZAMIENTO = (
    "QScrollBar:vertical { background: #1C1C1C; width: 10px; margin: 0; }"
    "QScrollBar::handle:vertical { background: #4B4B4B; border-radius: 5px; "
    "min-height: 24px; }"
    "QScrollBar::handle:vertical:hover { background: #686868; }"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #1C1C1C; }"
    "QScrollBar:horizontal { background: #1C1C1C; height: 10px; margin: 0; }"
    "QScrollBar::handle:horizontal { background: #4B4B4B; border-radius: 5px; "
    "min-width: 24px; }"
    "QScrollBar::handle:horizontal:hover { background: #686868; }"
    "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
    "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: #1C1C1C; }"
)


class BarraDialogo(QFrame):
    """Encabezado propio para mover y cerrar diálogos sin barra de Windows."""

    def __init__(self, dialogo):
        super().__init__(dialogo)
        self.dialogo = dialogo
        self._origen_arrastre = None
        self._bordes_redimension = frozenset()
        self._posicion_redimension = None
        self._geometria_redimension = None
        self.setObjectName("barraDialogoFenix")
        self.setFixedHeight(32)
        self.setStyleSheet(
            "QFrame#barraDialogoFenix { background-color: #303030; "
            "border: none; border-bottom: 1px solid #414141; }"
        )
        dialogo.installEventFilter(self)
        dialogo.setMouseTracking(True)
        self.setMouseTracking(True)
        fila = QHBoxLayout(self)
        fila.setContentsMargins(9, 2, 4, 2)
        titulo = QLabel(dialogo.windowTitle())
        titulo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        titulo.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px; border: none;"
        )
        fila.addWidget(titulo, 1)
        cerrar = QPushButton("×")
        cerrar.setObjectName("cerrarDialogoFenix")
        cerrar.setFixedSize(25, 25)
        cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        cerrar.setToolTip("Cerrar ventana")
        cerrar.setStyleSheet(
            f"QPushButton {{ color: {COLOR_TEXTO}; background: transparent; "
            "border: none; font-size: 20px; padding: 0; } "
            f"QPushButton:hover {{ background: {COLOR_ROJO_FONDO}; "
            f"color: {COLOR_ROJO}; border-radius: 4px; }}"
        )
        cerrar.clicked.connect(dialogo.reject)
        fila.addWidget(cerrar)

    def eventFilter(self, objeto, evento):
        dialogo = getattr(self, "dialogo", None)
        if dialogo is not None and objeto is dialogo:
            tipo = evento.type()
            if tipo in (QEvent.Type.Resize, QEvent.Type.Show):
                self.setGeometry(0, 0, dialogo.width(), self.height())
                self.raise_()
            elif tipo == QEvent.Type.MouseButtonPress and self._iniciar_redimension(
                evento, evento.position().toPoint()
            ):
                return True
            elif tipo == QEvent.Type.MouseMove:
                if self._mover_redimension(evento):
                    return True
                self._mostrar_cursor_borde(dialogo, evento.position().toPoint())
            elif tipo == QEvent.Type.MouseButtonRelease:
                self._terminar_redimension()
            elif tipo == QEvent.Type.Leave and not self._bordes_redimension:
                dialogo.unsetCursor()
        return super().eventFilter(objeto, evento)

    def _bordes_en(self, posicion):
        bordes = set()
        if posicion.x() < 7:
            bordes.add("izquierda")
        elif posicion.x() >= self.dialogo.width() - 7:
            bordes.add("derecha")
        if posicion.y() < 7:
            bordes.add("arriba")
        elif posicion.y() >= self.dialogo.height() - 7:
            bordes.add("abajo")
        return frozenset(bordes)

    def _mostrar_cursor_borde(self, widget, posicion):
        bordes = self._bordes_en(posicion)
        if len(bordes) == 2:
            diagonal_principal = bordes in (
                frozenset(("izquierda", "arriba")),
                frozenset(("derecha", "abajo")),
            )
            cursor = (
                Qt.CursorShape.SizeFDiagCursor if diagonal_principal
                else Qt.CursorShape.SizeBDiagCursor
            )
        elif "izquierda" in bordes or "derecha" in bordes:
            cursor = Qt.CursorShape.SizeHorCursor
        elif bordes:
            cursor = Qt.CursorShape.SizeVerCursor
        else:
            widget.unsetCursor()
            return
        widget.setCursor(cursor)

    def _iniciar_redimension(self, evento, posicion):
        if evento.button() != Qt.MouseButton.LeftButton:
            return False
        bordes = self._bordes_en(posicion)
        if not bordes:
            return False
        self._bordes_redimension = bordes
        self._posicion_redimension = evento.globalPosition().toPoint()
        self._geometria_redimension = QRect(self.dialogo.geometry())
        evento.accept()
        return True

    def _mover_redimension(self, evento):
        if not self._bordes_redimension:
            return False
        desplazamiento = evento.globalPosition().toPoint() - self._posicion_redimension
        inicial = self._geometria_redimension
        ancho_minimo = max(1, self.dialogo.minimumWidth())
        alto_minimo = max(1, self.dialogo.minimumHeight())
        ancho_maximo = self.dialogo.maximumWidth()
        alto_maximo = self.dialogo.maximumHeight()
        ancho = inicial.width()
        alto = inicial.height()
        if "izquierda" in self._bordes_redimension:
            ancho = max(ancho_minimo, min(ancho_maximo, ancho - desplazamiento.x()))
        elif "derecha" in self._bordes_redimension:
            ancho = max(ancho_minimo, min(ancho_maximo, ancho + desplazamiento.x()))
        if "arriba" in self._bordes_redimension:
            alto = max(alto_minimo, min(alto_maximo, alto - desplazamiento.y()))
        elif "abajo" in self._bordes_redimension:
            alto = max(alto_minimo, min(alto_maximo, alto + desplazamiento.y()))
        izquierda = inicial.right() - ancho + 1 if "izquierda" in self._bordes_redimension else inicial.left()
        arriba = inicial.bottom() - alto + 1 if "arriba" in self._bordes_redimension else inicial.top()
        self.dialogo.setGeometry(izquierda, arriba, ancho, alto)
        evento.accept()
        return True

    def _terminar_redimension(self):
        self._bordes_redimension = frozenset()
        self._posicion_redimension = None
        self._geometria_redimension = None

    def mousePressEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton:
            if self._iniciar_redimension(evento, self.mapTo(self.dialogo, evento.position().toPoint())):
                return
            self._origen_arrastre = evento.globalPosition().toPoint() - self.dialogo.pos()
            evento.accept()
            return
        super().mousePressEvent(evento)

    def mouseMoveEvent(self, evento):
        if self._mover_redimension(evento):
            return
        if self._origen_arrastre is not None and evento.buttons() & Qt.MouseButton.LeftButton:
            self.dialogo.move(evento.globalPosition().toPoint() - self._origen_arrastre)
            evento.accept()
            return
        self._mostrar_cursor_borde(self, self.mapTo(self.dialogo, evento.position().toPoint()))
        super().mouseMoveEvent(evento)

    def mouseReleaseEvent(self, evento):
        self._origen_arrastre = None
        self._terminar_redimension()
        super().mouseReleaseEvent(evento)


def preparar_dialogo_sin_barra(dialogo, disposicion, redimensionable=True):
    """Conserva un cierre visible y una zona de arrastre al ocultar la barra nativa."""
    dialogo.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    barra = BarraDialogo(dialogo)
    barra.setGeometry(0, 0, dialogo.width(), barra.height())
    barra.show()
    disposicion.insertSpacing(0, barra.height())
    if redimensionable:
        disposicion.addWidget(QSizeGrip(dialogo), 0, Qt.AlignmentFlag.AlignRight)


def centrar_contenido_si_no_hay_barra(area, disposicion, margen_con_barra, separacion_barra):
    """Devuelve al contenido el espacio reservado para la barra cuando esta desaparece."""
    barra = area.verticalScrollBar()
    contenido = area.widget().layout()

    def actualizar():
        con_barra = barra.maximum() > 0
        margen_derecho = margen_con_barra if con_barra else 20
        separacion = separacion_barra if con_barra else 0
        margenes = disposicion.contentsMargins()
        if margenes.right() != margen_derecho:
            disposicion.setContentsMargins(
                margenes.left(), margenes.top(), margen_derecho, margenes.bottom()
            )
        margenes_contenido = contenido.contentsMargins()
        if margenes_contenido.right() != separacion:
            contenido.setContentsMargins(
                margenes_contenido.left(), margenes_contenido.top(),
                separacion, margenes_contenido.bottom(),
            )

    barra.rangeChanged.connect(lambda *_: actualizar())
    actualizar()

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


def clave_orden_grupo(grupo):
    """Ordena grupos numéricamente y conserva un orden natural para sufijos."""
    numero = str(grupo.get("numero") or "").strip().casefold()
    partes = re.split(r"(\d+)", numero)
    natural = tuple(
        (0, int(parte)) if parte.isdigit() else (1, parte)
        for parte in partes
    )
    return natural, numero


def grupos_en_conflicto_en_bloque(materias, grupos_actuales, dia, hora, duracion):
    """Devuelve grupos de esa franja que chocan con el horario seleccionado."""
    bloqueados = []
    for materia in materias:
        for grupo in materia.get("grupos", []):
            if not grupo_ocupa_bloque(grupo, dia, hora, duracion):
                continue
            elegible, motivo = grupo_es_elegible(grupo, grupos_actuales)
            if not elegible and motivo == "Conflicto de horario":
                bloqueados.append((materia, grupo))
    return bloqueados


def buscar_grupos_en_bloque(
    materias, consulta, dia, hora, duracion, aprobadas, seleccionadas, grupos_actuales
):
    """Clasifica cada grupo encontrado; una materia puede estar en ambas listas."""
    consulta = clave_alfabetica(consulta).strip()
    if not consulta:
        return []
    resultados = []
    vistos = set()
    for materia in materias:
        codigo = codigo_base(materia.get("codigo"))
        if not codigo or codigo in vistos:
            continue
        vistos.add(codigo)
        if consulta not in clave_alfabetica(
            f"{materia.get('nombre', '')} {materia.get('codigo', '')} {codigo}"
        ):
            continue
        motivo_academico = motivo_materia_no_mostrable(
            materia, aprobadas, seleccionadas
        )
        disponibles = []
        no_disponibles = []
        for grupo in sorted(materia.get("grupos") or [], key=clave_orden_grupo):
            motivos = []
            if motivo_academico:
                motivos.append(motivo_academico)
            if not grupo_ocupa_bloque(grupo, dia, hora, duracion):
                motivos.append("No tiene clase en la franja seleccionada")
            elegible, motivo_grupo = grupo_es_elegible(grupo, grupos_actuales)
            if not elegible:
                motivos.append(motivo_grupo)
            if motivos:
                no_disponibles.append({"grupo": grupo, "motivo": ". ".join(motivos)})
            else:
                disponibles.append(grupo)
        if not disponibles and not no_disponibles:
            no_disponibles.append({
                "grupo": None,
                "motivo": ". ".join(filter(None, (
                    motivo_academico, "No tiene grupos publicados en la oferta actual"
                ))),
            })
        resultados.append({
            "materia": materia, "disponibles": disponibles,
            "no_disponibles": no_disponibles,
        })
    return sorted(resultados, key=lambda item: clave_alfabetica(item["materia"].get("nombre")))


def subtipo_materia(materia):
    """Devuelve la familia curricular usada en los submenús laterales."""
    texto = unicodedata.normalize(
        "NFD", f"{materia.get('tipologia', '')} {materia.get('nombre', '')}".casefold()
    )
    texto = "".join(
        caracter for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )
    return "FUNDAMENTACIÓN" if (
        "fundament" in texto
        or re.search(r"\bfund\.?\b", texto)
        or "basica" in texto
    ) else "DISCIPLINARES"


def codigos_prerrequisitos(materia):
    """Normaliza prerrequisitos guardados como objetos o códigos simples."""
    return [codigo for codigo, _ in relaciones_prerrequisitos(materia)]


def relaciones_prerrequisitos(materia):
    """Devuelve (código, tipo SIA), conservando metadatos de cada relación."""
    if not isinstance(materia, dict):
        return []
    relaciones = []
    for requisito in materia.get("prerrequisitos", []) or []:
        valor = requisito.get("codigo") if isinstance(requisito, dict) else requisito
        codigo = codigo_base(valor)
        tipo = (
            str(requisito.get("tipo") or "").strip().upper()
            if isinstance(requisito, dict) else ""
        )
        relacion = (codigo, tipo)
        if codigo and relacion not in relaciones:
            relaciones.append(relacion)
    return relaciones


def conexiones_entre_semestres_adyacentes(materias_por_semestre, tarjetas_por_codigo,
                                         cantidad_semestres):
    """Conecta prerrequisitos solo desde el semestre inmediatamente anterior."""
    conexiones = []
    codigos_por_semestre = {
        numero: {
            codigo_base(materia.get("codigo"))
            for materia in materias_por_semestre.get(numero, [])
        }
        for numero in range(1, cantidad_semestres + 1)
    }
    for numero in range(2, cantidad_semestres + 1):
        anteriores = codigos_por_semestre.get(numero - 1, set())
        for materia in materias_por_semestre.get(numero, []):
            destino = tarjetas_por_codigo.get(codigo_base(materia.get("codigo")))
            if destino is None:
                continue
            for requisito, tipo_requisito in relaciones_prerrequisitos(materia):
                origen = tarjetas_por_codigo.get(requisito)
                if requisito in anteriores and origen is not None and origen is not destino:
                    conexiones.append((origen, destino, tipo_requisito))
    return conexiones


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


def estilo_tarjeta_no_disponible():
    """Estilo compartido por las materias no disponibles de ambos menús."""
    return (
        f"QPushButton {{ background-color: {COLOR_ROJO_FONDO}; color: {COLOR_TEXTO}; "
        f"border: 1px solid {COLOR_ROJO}; border-radius: 6px; padding: 7px 8px; "
        "text-align: left; font-size: 11px; } "
        f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; }}"
    )


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


class SelectorSinCambioPorRueda(QComboBox):
    """Evita que la rueda cambie una selección sin abrir el desplegable."""

    def wheelEvent(self, evento):
        evento.ignore()


class DialogoPlan(QDialog):
    """Solicita el plan y las materias aprobadas durante el primer ingreso."""

    def __init__(self, planes, oferta, materias_conocidas=None, estudiante=None, parent=None, materias_libres=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar estudiante · Fénix")
        self.setModal(True)
        self.setMinimumWidth(760)
        pantalla = QApplication.primaryScreen()
        if pantalla is not None:
            self.setMaximumHeight(int(pantalla.availableGeometry().height() * 0.9))
        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {COLOR_SUPERFICIE}; }}
            QScrollArea, QScrollArea::viewport {{
                background-color: {COLOR_SUPERFICIE};
                border: none;
            }}
            QScrollArea QWidget {{ background-color: {COLOR_SUPERFICIE}; }}
            QLabel {{ color: {COLOR_TEXTO}; }}
            QComboBox {{ background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO};
                border: 1px solid {COLOR_LINEA}; border-radius: 7px; padding: 9px; }}
            QComboBox QAbstractItemView {{ background-color: {COLOR_SUPERFICIE_CLARA};
                color: {COLOR_TEXTO}; selection-background-color: {COLOR_VERDE};
                selection-color: #FFFFFF; }}
            QLineEdit {{ background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO};
                border: 1px solid {COLOR_LINEA}; border-radius: 7px; padding: 8px 10px;
                selection-background-color: {COLOR_VERDE}; selection-color: #FFFFFF; }}
            QLineEdit:focus {{ border-color: {COLOR_VERDE}; }}
            QListWidget {{ background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO};
                border: 1px solid {COLOR_LINEA}; border-radius: 7px; padding: 4px; }}
            QPushButton {{ background-color: {COLOR_VERDE_FONDO}; color: {COLOR_TEXTO};
                border: 1px solid {COLOR_VERDE}; border-radius: 7px; font-weight: bold; padding: 8px 16px; }}
            QPushButton:hover {{ background-color: #294A35; }}
            """
        )
        contenedor_dialogo = QVBoxLayout(self)
        contenedor_dialogo.setContentsMargins(12, 12, 12, 10)
        contenedor_dialogo.setSpacing(8)
        preparar_dialogo_sin_barra(self, contenedor_dialogo, redimensionable=False)
        self.area_desplazable = QScrollArea(self)
        self.area_desplazable.setWidgetResizable(True)
        self.area_desplazable.setFrameShape(QFrame.Shape.NoFrame)
        self.area_desplazable.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area_desplazable.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.area_desplazable.setStyleSheet(
            f"QScrollArea {{ background-color: {COLOR_SUPERFICIE}; border: none; }}"
        )
        self.area_desplazable.viewport().setStyleSheet(
            f"background-color: {COLOR_SUPERFICIE};"
        )
        contenido = QWidget()
        contenido.setStyleSheet(f"background-color: {COLOR_SUPERFICIE};")
        self.area_desplazable.setWidget(contenido)
        contenedor_dialogo.addWidget(self.area_desplazable, 1)

        layout = QVBoxLayout(contenido)
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
        estilo_selector = (
            f"background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"selection-background-color: {COLOR_VERDE}; selection-color: #FFFFFF;"
        )
        self.selector_facultad = SelectorSinCambioPorRueda()
        self.selector_facultad.view().setStyleSheet(estilo_selector)
        self.selector_facultad.addItem("Selecciona una facultad…", None)
        facultades = {}
        for plan in planes.values():
            clave_facultad = f"{plan.sede_codigo}:{plan.facultad_codigo}"
            nombre_facultad = str(plan.facultad_nombre or "").strip() or "Facultad sin nombre"
            facultades.setdefault(clave_facultad, nombre_facultad)
        for clave_facultad, nombre_facultad in sorted(
            facultades.items(), key=lambda item: clave_alfabetica(item[1])
        ):
            self.selector_facultad.addItem(nombre_facultad, clave_facultad)
        layout.addWidget(self.selector_facultad)

        self.selector = SelectorSinCambioPorRueda()
        self.selector.view().setStyleSheet(estilo_selector)
        self.selector.addItem("Selecciona tu plan de estudios…", None)
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
        self.selector_tipo = SelectorSinCambioPorRueda()
        self.selector_tipo.view().setStyleSheet(
            f"background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"selection-background-color: {COLOR_VERDE}; selection-color: #FFFFFF;"
        )
        self.selector_tipo.addItems([
            "Todos los tipos", "Obligatorias", "Nivelación", "Optativas",
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
        self.materias_disponibles.setMinimumHeight(170)
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
        self.materias_elegidas.setMinimumHeight(170)
        columna_elegidas.addWidget(self.materias_elegidas)
        listas.addLayout(columna_elegidas, 1)
        layout.addLayout(listas)
        self.botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        self.boton_confirmar = self.botones.button(QDialogButtonBox.StandardButton.Ok)
        self.botones.accepted.connect(self.accept)
        contenedor_dialogo.addWidget(self.botones)
        contenedor_dialogo.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignRight)
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
        self.aprobadas_iniciales = aprobadas
        plan_guardado = str((estudiante or {}).get("plan_estudios") or "")
        # Nivelación se marca una sola vez al elegir un plan nuevo. Si el
        # estudiante la desmarca, filtros y búsquedas no deben volver a ganarla.
        self._nivelaciones_inicializadas_por_plan = (
            {plan_guardado} if plan_guardado in planes else set()
        )
        plan_preferido = planes.get(plan_guardado)
        if plan_preferido is not None:
            clave_facultad = f"{plan_preferido.sede_codigo}:{plan_preferido.facultad_codigo}"
            indice_facultad = self.selector_facultad.findData(clave_facultad)
            if indice_facultad > 0:
                self.selector_facultad.setCurrentIndex(indice_facultad)
        self._actualizar_carreras_facultad(plan_guardado)
        self.selector_facultad.currentIndexChanged.connect(
            lambda _indice: self._actualizar_carreras_facultad()
        )
        self.selector.currentIndexChanged.connect(self.actualizar_materias)
        self.boton_agregar_materias.clicked.connect(self.agregar_materias)
        self.boton_quitar_materias.clicked.connect(self.quitar_materias)
        self.buscar_aprobadas.textChanged.connect(self.filtrar_materias)
        self.selector_tipo.currentIndexChanged.connect(self.actualizar_materias)
        self.materias_disponibles.itemDoubleClicked.connect(self.mover_materia_y_completar)
        self.materias_elegidas.itemDoubleClicked.connect(
            lambda item: self.mover_materias(
                self.materias_elegidas, self.materias_disponibles, [item]
            )
        )
        self.actualizar_materias()

    def _actualizar_carreras_facultad(self, codigo_preferido=None):
        """Muestra solo carreras de la facultad elegida, conservando el plan actual."""
        clave_facultad = self.selector_facultad.currentData()
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.addItem("Selecciona tu carrera…", None)
        opciones = [
            (codigo, plan)
            for codigo, plan in self.planes.items()
            if clave_facultad is not None
            and f"{plan.sede_codigo}:{plan.facultad_codigo}" == clave_facultad
        ]
        for codigo, plan in sorted(
            opciones,
            key=lambda item: (
                clave_alfabetica(item[1].nombre),
                -codigo_numerico_plan(item[1].codigo),
                str(item[0]),
            ),
        ):
            self.selector.addItem(f"{plan.nombre} · {plan.codigo}", codigo)
        indice = self.selector.findData(codigo_preferido) if codigo_preferido else -1
        if indice > 0:
            self.selector.setCurrentIndex(indice)
        self.selector.blockSignals(False)
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
        if codigo_plan not in self._nivelaciones_inicializadas_por_plan:
            seleccionadas.update(nivelaciones)
            self._nivelaciones_inicializadas_por_plan.add(codigo_plan)
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
        items = self.materias_disponibles.selectedItems()
        codigos = [item.data(Qt.ItemDataRole.UserRole) for item in items]
        self.mover_materias(self.materias_disponibles, self.materias_elegidas, items)
        self._agregar_prerrequisitos_de_seleccionadas(codigos)

    def mover_materia_y_completar(self, item):
        """Mueve una materia doblemente pulsada y completa solo su cadena."""
        codigo = item.data(Qt.ItemDataRole.UserRole)
        self.mover_materias(self.materias_disponibles, self.materias_elegidas, [item])
        self._agregar_prerrequisitos_de_seleccionadas([codigo])

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

    def expandir_relaciones_aprobadas(self, codigos):
        """Incluye la cadena de prerrequisitos relacionada con una selección.

        Durante la configuración inicial el usuario suele marcar materias en
        cualquier orden. Se conserva la comodidad de completar la cadena
        completa: si se marca una materia, aparecen también sus prerrequisitos
        y las materias que dependen directamente de ella (por ejemplo,
        Cálculo Diferencial/Cálculo Integral).
        """
        iniciales = {codigo_base(codigo) for codigo in codigos if codigo_base(codigo)}
        resultado = set(self.expandir_prerrequisitos(iniciales))
        indice = self._indice_materias_conocidas()
        plan = self.planes.get(self.selector.currentData())
        permitidos = set(indice)
        if plan is not None:
            permitidos.update(
                codigo_base(codigo)
                for semestre in plan.semestres
                for codigo in semestre.asignaturas
            )
        # La dirección inversa se limita al siguiente semestre de cada
        # selección. Así Cálculo Diferencial completa Cálculo Integral sin
        # convertir una sola selección en toda la malla curricular aprobada.
        semestre_por_codigo = {}
        if plan is not None:
            for semestre in plan.semestres:
                for valor in semestre.asignaturas:
                    semestre_por_codigo[codigo_base(valor)] = semestre.numero
        dependientes_directos = set()
        for inicial in iniciales:
            # La dirección inversa solo completa el primer paso de una
            # cadena; una materia que ya tiene prerrequisitos no dispara a
            # sus propios dependientes posteriores.
            if codigos_prerrequisitos(indice.get(inicial, {})):
                continue
            candidatos = [
                codigo for codigo, materia in indice.items()
                if codigo in permitidos
                and inicial in set(codigos_prerrequisitos(materia))
                and semestre_por_codigo.get(codigo, 10**6)
                    > semestre_por_codigo.get(inicial, -1)
            ]
            if candidatos:
                siguiente = min(
                    semestre_por_codigo.get(codigo, 10**6) for codigo in candidatos
                )
                dependientes_directos.update(
                    codigo for codigo in candidatos
                    if semestre_por_codigo.get(codigo, 10**6) == siguiente
                )
        resultado.update(dependientes_directos)
        resultado.update(self.expandir_prerrequisitos(resultado))
        return sorted(resultado)

    def _agregar_prerrequisitos_de_seleccionadas(self, codigos_nuevos=None):
        seleccionadas = list(codigos_nuevos or [
            self.materias_elegidas.item(indice).data(Qt.ItemDataRole.UserRole)
            for indice in range(self.materias_elegidas.count())
        ])
        ampliadas = self.expandir_relaciones_aprobadas(seleccionadas)
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
    """Dibuja relaciones de prerrequisito y correquisito en la malla."""

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
        for origen, destino, tipo in self.conexiones:
            if not origen.isVisible() or not destino.isVisible():
                continue
            mismo_semestre = origen.parentWidget() is destino.parentWidget()
            estilos = {
                "M": Qt.PenStyle.SolidLine,
                "O": Qt.PenStyle.DashLine,
                "E": Qt.PenStyle.DotLine,
                "A": Qt.PenStyle.DashDotLine,
                "Y": Qt.PenStyle.DashDotDotLine,
            }
            estilo = estilos.get(tipo, Qt.PenStyle.SolidLine)
            pintor.setPen(QPen(
                QColor(COLOR_NARANJA_FENIX), 2, estilo,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
            ))
            if mismo_semestre:
                columna = origen.parentWidget()
                izquierda = self.mapFromGlobal(
                    columna.mapToGlobal(QPoint(columna.width() - 3, 0))
                ).x()
                inicio_global = origen.mapToGlobal(
                    QPoint(origen.width(), origen.height() // 2)
                )
                fin_global = destino.mapToGlobal(
                    QPoint(destino.width(), destino.height() // 2)
                )
                inicio_local = self.mapFromGlobal(inicio_global)
                fin_local = self.mapFromGlobal(fin_global)
                inicio = QPointF(inicio_local)
                fin = QPointF(fin_local)
                camino = QPainterPath(inicio)
                camino.lineTo(izquierda, inicio.y())
                camino.lineTo(izquierda, fin.y())
                camino.lineTo(fin)
                pintor.drawPath(camino)
                pintor.drawLine(fin, QPointF(fin.x() + 6, fin.y() - 4))
                pintor.drawLine(fin, QPointF(fin.x() + 6, fin.y() + 4))
                continue
            inicio_global = origen.mapToGlobal(QPoint(origen.width(), origen.height() // 2))
            fin_global = destino.mapToGlobal(QPoint(0, destino.height() // 2))
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
        preparar_dialogo_sin_barra(self, principal, redimensionable=False)
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
            "Conexiones naranjas: M continua (aprobación previa), O discontinua "
            "(requisito para calificar), E punteada (previa o simultánea), "
            "A raya-punto (incompatibilidad) y Y raya-punto-punto "
            "(mismo semestre, interpretación provisional)."
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
        principal.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignRight)
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
        self._ordenar_prerrequisitos_mismo_semestre(materias_por_semestre)
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
        # materias.json puede conocer una nivelación aunque no tenga grupos
        # publicados en la oferta actual. También debe verse en Mi Plan.
        nivelaciones_por_codigo = {
            codigo_base(materia.get("codigo", codigo)): materia
            for codigo, materia in (self.ventana_principal.materias_locales or {}).items()
            if isinstance(materia, dict) and es_materia_nivelacion(materia)
        }
        nivelaciones_por_codigo.update({
            codigo_base(materia.get("codigo")): materia
            for materia in self.ventana_principal.materias_por_origen.get("principal", [])
            if es_materia_nivelacion(materia)
        })
        nivelaciones = list(nivelaciones_por_codigo.values())
        if nivelaciones:
            self.diagrama.addWidget(
                self._crear_seccion_nivelacion(
                    sorted(nivelaciones, key=lambda materia: clave_alfabetica(materia.get("nombre"))),
                    aprobadas,
                    seleccionadas,
                )
            )
        self.diagrama.addStretch()

    def _crear_seccion_nivelacion(self, materias, aprobadas, seleccionadas):
        """Muestra Nivelación debajo de la malla con las mismas tarjetas interactivas."""
        seccion = QFrame()
        seccion.setObjectName("seccionPlan")
        seccion.setStyleSheet(
            f"QFrame#seccionPlan {{ background-color: {COLOR_SUPERFICIE}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 11px; }}"
        )
        layout = QVBoxLayout(seccion)
        layout.setContentsMargins(12, 11, 12, 13)
        layout.setSpacing(9)
        cabecera = QHBoxLayout()
        cabecera.setContentsMargins(0, 0, 0, 0)
        titulo = QLabel("NIVELACIÓN")
        titulo.setStyleSheet(
            f"background: transparent; color: {COLOR_VERDE}; "
            "font-size: 14px; font-weight: 900; border: none;"
        )
        cabecera.addWidget(titulo)
        cabecera.addSpacing(14)
        codigos_nivelacion = {
            codigo_base(materia.get("codigo")) for materia in materias
        }
        todas_aprobadas = codigos_nivelacion.issubset(aprobadas)
        boton_todas = QPushButton(
            "Desmarcar todas" if todas_aprobadas else "Marcar todas"
        )
        boton_todas.setObjectName("botonTodasNivelaciones")
        boton_todas.setCursor(Qt.CursorShape.PointingHandCursor)
        boton_todas.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"color: {COLOR_TEXTO}; border: 1px solid {COLOR_LINEA}; "
            "border-radius: 5px; padding: 5px 9px; font-size: 10px; font-weight: 700; } "
            f"QPushButton:hover {{ border-color: {COLOR_VERDE}; }}"
        )
        boton_todas.clicked.connect(
            lambda: self.ventana_principal.cambiar_materias_aprobadas_desde_plan(
                codigos_nivelacion, not todas_aprobadas
            )
        )
        cabecera.addWidget(boton_todas)
        cabecera.addStretch(1)
        layout.addLayout(cabecera)
        descripcion = QLabel(
            "Estas materias aparecen aprobadas por defecto en un perfil nuevo. "
            "Puedes marcar o desmarcar cada una con su casilla."
        )
        descripcion.setWordWrap(True)
        descripcion.setStyleSheet(
            f"background: transparent; color: {COLOR_TEXTO_SECUNDARIO}; "
            "font-size: 10px; border: none;"
        )
        layout.addWidget(descripcion)
        contenedor_tarjetas = QWidget()
        contenedor_tarjetas.setStyleSheet("background: transparent; border: none;")
        contenedor_tarjetas.setFixedWidth(5 * 222)
        cuadricula = QGridLayout(contenedor_tarjetas)
        cuadricula.setContentsMargins(0, 0, 0, 0)
        cuadricula.setSpacing(8)
        for columna in range(5):
            cuadricula.setColumnMinimumWidth(columna, 214)
        for indice, materia in enumerate(materias):
            codigo = codigo_base(materia.get("codigo"))
            tarjeta = self._crear_tarjeta_materia(
                materia, codigo in aprobadas, codigo in seleccionadas
            )
            tarjeta.setFixedWidth(214)
            cuadricula.addWidget(tarjeta, indice // 5, indice % 5)
        layout.addWidget(contenedor_tarjetas)
        seccion.setMinimumWidth(5 * 222 + 24)
        return seccion

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

    @staticmethod
    def _ordenar_prerrequisitos_mismo_semestre(materias_por_semestre):
        """Alinea requisitos que pueden cursarse juntos sin cambiar la tipología.

        Fundamentación conserva prioridad absoluta sobre Disciplinar.
        """
        for numero, materias in materias_por_semestre.items():
            resultado = []
            for tipo in sorted({materia.get("_orden_plan", 2) for materia in materias}):
                grupo = [materia for materia in materias if materia.get("_orden_plan", 2) == tipo]
                por_codigo = {codigo_base(m.get("codigo")): m for m in grupo}
                posiciones = {codigo: indice for indice, codigo in enumerate(por_codigo)}
                pendientes = set(por_codigo)
                ordenados = []
                while pendientes:
                    disponibles = [
                        codigo for codigo in pendientes
                        if not any(
                            requisito_tipo in ("M", "O", "E", "Y")
                            and requisito in pendientes
                            and requisito != codigo
                            for requisito, requisito_tipo in relaciones_prerrequisitos(
                                por_codigo[codigo]
                            )
                        )
                    ]
                    if not disponibles:
                        # Ciclo o autorreferencia: no arriesgarse a perder cursos.
                        disponibles = list(pendientes)
                    disponibles.sort(key=lambda codigo: posiciones[codigo])
                    for codigo in disponibles:
                        pendientes.remove(codigo)
                        ordenados.append(por_codigo[codigo])
                resultado.extend(ordenados)
            materias_por_semestre[numero] = resultado

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
        fila.setSpacing(11)
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
        conexiones = conexiones_entre_semestres_adyacentes(
            materias, tarjetas_por_codigo, cantidad_semestres
        )
        capa.establecer_conexiones(conexiones)
        superpuestas.addWidget(base)
        superpuestas.addWidget(capa)
        superpuestas.setCurrentWidget(capa)
        ancho_lienzo = cantidad_semestres * 214 + (cantidad_semestres - 1) * 11
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
        tooltip = "Haz clic en la tarjeta para consultar sus grupos."
        relaciones = []
        for requisito, tipo in relaciones_prerrequisitos(materia):
            objeto = next((valor for valor in materia.get("prerrequisitos", [])
                           if isinstance(valor, dict)
                           and codigo_base(valor.get("codigo")) == requisito
                           and str(valor.get("tipo") or "").strip().upper() == tipo), None)
            nombre_requisito = str((objeto or {}).get("nombre") or requisito)
            relaciones.append(
                f"{tipo or '?'} · {nombre_requisito}: {descripcion_tipo(tipo)}"
            )
        if relaciones:
            tooltip += "\n\n" + "\n".join(relaciones)
        tarjeta.setToolTip(tooltip)
        acento = COLOR_VERDE if aprobada else ("#5AA9E6" if seleccionada else COLOR_LINEA)
        fondo = COLOR_VERDE_FONDO if aprobada else COLOR_SUPERFICIE_CLARA
        tarjeta.setStyleSheet(
            f"QFrame#tarjetaMateriaPlan {{ background-color: {fondo}; "
            f"border: 1px solid {COLOR_LINEA}; border-left: 4px solid {acento}; "
            "border-radius: 7px; }"
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


class TarjetaAvance(QFrame):
    pulsada = Signal()

    def mouseReleaseEvent(self, evento):
        if evento.button() == Qt.MouseButton.LeftButton and self.rect().contains(evento.pos()):
            self.pulsada.emit()
        super().mouseReleaseEvent(evento)


class VentanaPromedioActual(QDialog):
    notas_cambiadas = Signal(dict)

    @staticmethod
    def _estilo_oscuro():
        return (
            f"QDialog#ventanaPromedioActual {{ background-color: {COLOR_FONDO}; color: {COLOR_TEXTO}; }}"
            f"QDialog#ventanaPromedioActual QLabel {{ color: {COLOR_TEXTO}; "
            "background: transparent; border: none; }"
            f"QDialog#ventanaPromedioActual QScrollArea {{ background: {COLOR_SUPERFICIE}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; }}"
            f"QDialog#ventanaPromedioActual QScrollArea > QWidget > QWidget {{ "
            f"background: {COLOR_SUPERFICIE}; }}"
            f"QDialog#ventanaPromedioActual QLineEdit, "
            f"QDialog#ventanaPromedioActual QComboBox, "
            f"QDialog#ventanaPromedioActual QSpinBox, "
            f"QDialog#ventanaPromedioActual QDoubleSpinBox {{ "
            f"background: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 5px; padding: 5px; "
            "selection-background-color: #396A4B; }"
            f"QDialog#ventanaPromedioActual QComboBox QAbstractItemView {{ "
            f"background: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; selection-background-color: #396A4B; }}"
            f"QDialog#ventanaPromedioActual QPushButton {{ "
            f"background: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 5px; padding: 6px 10px; }}"
            f"QDialog#ventanaPromedioActual QPushButton:hover {{ border-color: {COLOR_VERDE}; }}"
            + ESTILO_BARRAS_DESPLAZAMIENTO
        )

    def __init__(self, datos, parent=None):
        super().__init__(parent)
        self.periodo = f"{date.today().year}-{1 if date.today().month <= 6 else 2}S"
        self.setWindowTitle(f"Promedios · {self.periodo}")
        self.setObjectName("ventanaPromedioActual")
        self.resize(650, 580)
        self.setStyleSheet(self._estilo_oscuro())
        self.datos = datos
        detalles = datos.get("calificaciones_detalle", [])
        self.materias = {(str(m.get("periodo")), str(m.get("codigo"))): m
                         for m in detalles if m.get("periodo") == self.periodo and m.get("codigo")}
        catalogo = cargar_materias() if cargar_plan_materias() == datos.get("plan_estudios") else {}
        self.creditos_materias = {}
        for clave, materia in self.materias.items():
            dato = catalogo.get(clave[1], {}) if isinstance(catalogo, dict) else {}
            self.creditos_materias[clave] = (dato.get("creditos") if isinstance(dato, dict) else None) or materia.get("creditos")
        self.evaluaciones = {}
        editadas = datos.get("notas_editadas", {})
        self.claves_editadas = set(editadas)
        manuales = datos.get("notas_manuales", {})
        for clave, materia in self.materias.items():
            texto = "|".join(clave)
            origen = editadas.get(texto) if texto in editadas else (
                list(materia.get("parciales", [])) + list(manuales.get(texto, [])))
            self.evaluaciones[texto] = [dict(nota) for nota in origen if isinstance(nota, dict)]
        raiz = QVBoxLayout(self)
        titulo = QLabel(f"PROMEDIOS DEL SEMESTRE {self.periodo}")
        titulo.setStyleSheet("font-size: 18px; font-weight: 800;")
        raiz.addWidget(titulo)
        ayuda = QLabel("Se usan las notas consultadas en el SIA y las que añadas aquí. "
                       "El promedio es provisional mientras falten evaluaciones.")
        ayuda.setWordWrap(True)
        raiz.addWidget(ayuda)
        indicadores = QFrame()
        indicadores.setObjectName("indicadoresPromedioActual")
        indicadores.setStyleSheet(
            f"QFrame#indicadoresPromedioActual {{ background: {COLOR_SUPERFICIE}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 7px; }}"
        )
        tabla = QGridLayout(indicadores)
        tabla.setContentsMargins(12, 10, 12, 10)
        tabla.setHorizontalSpacing(0)
        tabla.setVerticalSpacing(3)
        self.papa_proyectado = QLabel("—")
        self.papa_proyectado.setObjectName("papaProyectado")
        self.papi_provisional = QLabel("—")
        self.papi_provisional.setObjectName("papiProvisional")
        for columna, (nombre, valor) in enumerate((
            ("P.A.P.A. · general proyectado", self.papa_proyectado),
            ("P.A.P.I. · semestre provisional", self.papi_provisional),
        )):
            etiqueta = QLabel(nombre)
            etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
            etiqueta.setStyleSheet(
                f"color: {COLOR_TEXTO_SECUNDARIO}; background: transparent; border: none; "
                "font-size: 11px; font-weight: 700;"
            )
            valor.setAlignment(Qt.AlignmentFlag.AlignCenter)
            valor.setStyleSheet(
                f"color: {COLOR_TEXTO}; background: transparent; border: none; "
                "font-size: 26px; font-weight: 800;"
            )
            tabla.addWidget(etiqueta, 0, columna)
            tabla.addWidget(valor, 1, columna)
            tabla.setColumnStretch(columna, 1)
        raiz.addWidget(indicadores)
        self.resumen_materia = QLabel()
        self.resumen_materia.setWordWrap(True)
        self.resumen_materia.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; background: transparent; border: none; font-size: 11px;"
        )
        raiz.addWidget(self.resumen_materia)
        self.selector = QComboBox()
        for clave, materia in self.materias.items():
            self.selector.addItem(f"{materia.get('nombre') or clave[1]} ({clave[1]})", clave)
        self.selector.currentIndexChanged.connect(self._actualizar)
        raiz.addWidget(self.selector)
        self.etiqueta_creditos = QLabel()
        raiz.addWidget(self.etiqueta_creditos)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.lista = QWidget()
        self.lista.setStyleSheet(f"background: {COLOR_SUPERFICIE};")
        self.filas = QVBoxLayout(self.lista)
        self.area.setWidget(self.lista)
        raiz.addWidget(self.area, 1)
        formulario = QHBoxLayout()
        self.nombre_nota = QLineEdit()
        self.nombre_nota.setPlaceholderText("Nombre de la evaluación")
        self.nota = QLineEdit()
        self.nota.setPlaceholderText("Nota (0 a 5)")
        self.porcentaje = QDoubleSpinBox()
        self.porcentaje.setRange(0, 100)
        self.porcentaje.setSuffix(" %")
        self.porcentaje.setDecimals(2)
        boton_agregar = QPushButton("Añadir nota")
        boton_agregar.clicked.connect(self._agregar)
        for widget in (self.nombre_nota, self.nota, self.porcentaje, boton_agregar):
            formulario.addWidget(widget)
        raiz.addLayout(formulario)
        preparar_dialogo_sin_barra(self, raiz)
        if not self.materias:
            ayuda.setText("Aún no hay materias de este semestre en Mis Calificaciones. "
                          "Consulta el SIA desde Mi Avance para cargarlas.")
            for widget in (self.nombre_nota, self.porcentaje, self.nota, boton_agregar):
                widget.setEnabled(False)
        self._actualizar()

    def _clave(self):
        return self.selector.currentData()

    def _aviso(self, titulo, mensaje, advertencia=False):
        dialogo = QMessageBox(self)
        dialogo.setWindowTitle(titulo)
        dialogo.setText(mensaje)
        dialogo.setIcon(QMessageBox.Icon.Warning if advertencia else QMessageBox.Icon.Information)
        dialogo.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialogo.setStyleSheet(
            f"QMessageBox {{ background: {COLOR_FONDO}; }} "
            f"QLabel {{ color: {COLOR_TEXTO}; background: transparent; border: none; }} "
            f"QPushButton {{ color: {COLOR_TEXTO}; background: {COLOR_SUPERFICIE_CLARA}; "
            f"border: 1px solid {COLOR_LINEA}; padding: 5px 12px; }}"
        )
        dialogo.exec()

    def _guardar(self):
        self.datos["notas_editadas"] = {
            clave: self.evaluaciones[clave] for clave in self.claves_editadas
        }
        self.datos.pop("notas_manuales", None)
        self.datos.pop("creditos_promedio", None)
        self.notas_cambiadas.emit(self.datos)

    @staticmethod
    def _nota_numerica(texto):
        texto = str(texto or "").strip().replace(",", ".")
        if not texto:
            return None
        valor = float(texto)
        if not 0 <= valor <= 5:
            raise ValueError("La nota debe estar entre 0 y 5.")
        return valor

    def _guardar_fila(self, clave, indice, nombre, nota, porcentaje):
        try:
            valor = self._nota_numerica(nota.text())
        except ValueError:
            self._aviso("Nota no válida", "La nota debe ser un número entre 0 y 5, o quedar vacía.", True)
            self._actualizar()
            return
        peso = porcentaje.value()
        otras = sum(float(item.get("porcentaje") or 0) for i, item in
                    enumerate(self.evaluaciones[clave]) if i != indice)
        if otras + peso > 100.001:
            self._aviso("Porcentaje excedido", "Las evaluaciones de esta materia superarían el 100 %.", True)
            self._actualizar()
            return
        self.evaluaciones[clave][indice] = {
            "nombre": nombre.text().strip() or f"Evaluación {indice + 1}",
            "nota": valor, "porcentaje": peso,
        }
        self.claves_editadas.add(clave)
        self._guardar()
        self._actualizar()

    def _agregar(self):
        clave = self._clave()
        nombre = self.nombre_nota.text().strip()
        if not clave or not nombre:
            self._aviso("Falta el nombre", "Escribe el nombre de la evaluación.")
            return
        try:
            nota = self._nota_numerica(self.nota.text())
        except ValueError:
            self._aviso("Nota no válida", "La nota debe ser un número entre 0 y 5, o quedar vacía.", True)
            return
        usada = sum(float(p.get("porcentaje") or 0) for p in self.evaluaciones.get("|".join(clave), []))
        if usada + self.porcentaje.value() > 100.001:
            self._aviso("Porcentaje excedido", "Las evaluaciones de esta materia superarían el 100 %.", True)
            return
        self.evaluaciones.setdefault("|".join(clave), []).append({
            "nombre": nombre, "porcentaje": self.porcentaje.value(), "nota": nota
        })
        self.claves_editadas.add("|".join(clave))
        self.nombre_nota.clear()
        self.nota.clear()
        self._guardar()
        self._actualizar()

    def _eliminar(self, clave, indice):
        self.evaluaciones[clave].pop(indice)
        self.claves_editadas.add(clave)
        self._guardar()
        self._actualizar()

    def _actualizar(self):
        limpiar_layout(self.filas)
        clave = self._clave()
        if not clave:
            self.papa_proyectado.setText("—")
            self.papi_provisional.setText("—")
            self.resumen_materia.setText("Sin materias para calcular")
            return
        materia = self.materias[clave]
        clave_texto = "|".join(clave)
        creditos_materia = self.creditos_materias.get(clave)
        self.etiqueta_creditos.setText(
            f"Créditos de la materia: {creditos_materia}" if creditos_materia else
            "Créditos no disponibles en el catálogo; esta materia no entra en el promedio general."
        )
        notas = self.evaluaciones.get(clave_texto, [])
        evaluado = 0.0
        puntos = 0.0
        for indice, parcial in enumerate(notas):
            fila = QHBoxLayout()
            peso = float(parcial.get("porcentaje") or 0)
            nota = parcial.get("nota")
            nombre_campo = QLineEdit(str(parcial.get("nombre") or ""))
            nombre_campo.setObjectName("nombreEvaluacion")
            nota_campo = QLineEdit("" if nota is None else str(nota))
            nota_campo.setObjectName("notaEvaluacion")
            nota_campo.setPlaceholderText("Sin nota")
            porcentaje_campo = QDoubleSpinBox()
            porcentaje_campo.setObjectName("porcentajeEvaluacion")
            porcentaje_campo.setRange(0, 100)
            porcentaje_campo.setDecimals(2)
            porcentaje_campo.setSuffix(" %")
            porcentaje_campo.setValue(peso)
            guardar_fila = lambda k=clave_texto, i=indice, n=nombre_campo, v=nota_campo, p=porcentaje_campo: self._guardar_fila(k, i, n, v, p)
            nombre_campo.editingFinished.connect(guardar_fila)
            nota_campo.editingFinished.connect(guardar_fila)
            porcentaje_campo.lineEdit().editingFinished.connect(guardar_fila)
            fila.addWidget(nombre_campo, 1)
            fila.addWidget(nota_campo)
            fila.addWidget(porcentaje_campo)
            quitar = QPushButton("Quitar")
            quitar.clicked.connect(lambda _, k=clave_texto, i=indice: self._eliminar(k, i))
            fila.addWidget(quitar)
            self.filas.addLayout(fila)
            if nota is not None and peso > 0:
                try:
                    puntos += peso * float(nota)
                    evaluado += peso
                except (TypeError, ValueError):
                    pass
        self.filas.addStretch(1)
        proyeccion = puntos / evaluado if evaluado else None
        aporte = puntos / 100
        total_ponderado = total_creditos = 0.0
        papa_numerador = papa_creditos = 0.0
        definitivas_actual = set()
        for intento in self.datos.get("asignaturas", []):
            try:
                if intento.get("estado") == "cancelada" or intento.get("nota") is None:
                    continue
                creditos = float(intento.get("creditos") or 0)
                papa_numerador += creditos * float(intento["nota"])
                papa_creditos += creditos
                if intento.get("periodo") == self.periodo:
                    definitivas_actual.add(str(intento.get("codigo")))
                    total_ponderado += creditos * float(intento["nota"])
                    total_creditos += creditos
            except (TypeError, ValueError):
                continue
        for otra_clave, otra in self.materias.items():
            peso_nota = peso_evaluado = 0.0
            actividades = self.evaluaciones.get("|".join(otra_clave), [])
            for actividad in actividades:
                try:
                    if actividad.get("nota") is not None:
                        peso = float(actividad.get("porcentaje") or 0)
                        peso_nota += peso * float(actividad["nota"])
                        peso_evaluado += peso
                except (TypeError, ValueError):
                    continue
            try:
                creditos = float(str(self.creditos_materias.get(otra_clave) or 0).replace(",", "."))
            except ValueError:
                creditos = 0
            if peso_evaluado and creditos:
                if otra_clave[1] not in definitivas_actual:
                    total_ponderado += creditos * peso_nota / peso_evaluado
                    total_creditos += creditos
                    papa_numerador += creditos * peso_nota / peso_evaluado
                    papa_creditos += creditos
        self.papi_provisional.setText(
            f"{total_ponderado / total_creditos:.2f}" if total_creditos else "—"
        )
        self.papi_provisional.setToolTip(
            f"Estimación con {total_creditos:g} créditos de materias que ya tienen notas."
            if total_creditos else "Pendiente: faltan notas o créditos del catálogo."
        )
        detalle = (f"{materia.get('nombre')}: promedio de lo evaluado {proyeccion:.2f} · "
                   f"{evaluado:g}% con nota · aporte acumulado {aporte:.2f}/5"
                   if proyeccion is not None else f"{materia.get('nombre')}: sin notas todavía")
        self.papa_proyectado.setText(
            f"{papa_numerador / papa_creditos:.2f}" if papa_creditos else "—"
        )
        self.papa_proyectado.setToolTip(
            "Proyección que combina la historia académica y las notas disponibles del semestre actual."
        )
        self.resumen_materia.setText(detalle)


class VentanaActividadAvance(QDialog):
    cerrada = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actividad del SIA · Fénix")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumSize(420, 300)
        self.resize(640, 450)
        self.setStyleSheet(
            f"QDialog {{ background: {COLOR_FONDO}; }} "
            f"QLabel {{ color: {COLOR_TEXTO}; background: transparent; border: none; }}"
        )
        self._captura = QPixmap()
        contenido = QVBoxLayout(self)
        contenido.setContentsMargins(12, 10, 12, 10)
        aviso = QLabel("Vista de solo lectura · No se muestra el inicio de sesión ni se guardan imágenes.")
        aviso.setWordWrap(True)
        contenido.addWidget(aviso)
        self.imagen = QLabel("Esperando la primera imagen de la consulta…")
        self.imagen.setObjectName("imagenActividadAvance")
        self.imagen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.imagen.setStyleSheet(
            f"background: {COLOR_SUPERFICIE}; border: 1px solid {COLOR_LINEA};"
        )
        contenido.addWidget(self.imagen, 1)
        preparar_dialogo_sin_barra(self, contenido)

    def actualizar_captura(self, datos):
        imagen = QPixmap()
        if imagen.loadFromData(datos, "JPEG"):
            self._captura = imagen
            self._ajustar_imagen()

    def _ajustar_imagen(self):
        if not self._captura.isNull():
            self.imagen.setPixmap(self._captura.scaled(
                self.imagen.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self._ajustar_imagen()

    def closeEvent(self, evento):
        self.limpiar_captura()
        self.cerrada.emit()
        super().closeEvent(evento)

    def limpiar_captura(self):
        self._captura = QPixmap()
        self.imagen.setText("Esperando la primera imagen de la consulta…")


class VentanaAvanceAcademico(QDialog):
    """Historial local por periodos, independiente de la malla curricular."""

    consultar_sia = Signal()
    cancelar_consulta = Signal()
    guardar_notas = Signal(dict)
    mostrar_actividad = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mi Avance · Fénix")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumSize(720, 520)
        self.resize(1160, 740)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_FONDO}; }} "
            f"QLabel {{ color: {COLOR_TEXTO}; }} "
            f"QScrollArea {{ border: none; background-color: {COLOR_FONDO}; }}"
        )
        principal = QVBoxLayout(self)
        principal.setContentsMargins(20, 18, 20, 16)
        principal.setSpacing(10)
        cabecera_principal = QHBoxLayout()
        titulo = QLabel("MI AVANCE")
        titulo.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {COLOR_TEXTO};")
        cabecera_principal.addWidget(titulo)
        cabecera_principal.addStretch(1)
        self.papa = QLabel("P.A.P.A.  —")
        self.papa.setObjectName("papaMiAvance")
        self.papa.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.papa.setStyleSheet(
            f"color: {COLOR_VERDE}; background: transparent; "
            "font-size: 26px; font-weight: 800;"
        )
        self.papa.setToolTip(
            "Promedio acumulado: suma de (créditos × nota) de todas las materias "
            "con nota numérica, dividida entre la suma de sus créditos. "
            "Cada intento cursado cuenta por separado."
        )
        cabecera_principal.addWidget(self.papa)
        principal.addLayout(cabecera_principal)
        ayuda = QLabel(
            "Consulta tu historia académica en el SIA. Inicias sesión tú mismo en "
            "el navegador; Fénix no guarda tu usuario, contraseña ni cookies. "
            "Las asignaturas y notas se guardan solo en este equipo."
        )
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        principal.addWidget(ayuda)
        acciones = QHBoxLayout()
        self.boton_consultar = QPushButton("Consultar SIA")
        self.boton_consultar.setObjectName("consultarSiaAvance")
        self.boton_consultar.clicked.connect(self.consultar_sia.emit)
        self.boton_cancelar = QPushButton("Cancelar consulta")
        self.boton_cancelar.setObjectName("cancelarSiaAvance")
        self.boton_cancelar.clicked.connect(self.cancelar_consulta.emit)
        self.boton_cancelar.hide()
        self.boton_actividad = QPushButton("Mostrar actividad")
        self.boton_actividad.setObjectName("mostrarActividadAvance")
        self.boton_actividad.setCheckable(True)
        self.boton_actividad.toggled.connect(self._alternar_actividad)
        self.boton_actividad.hide()
        self.ventana_actividad = None
        for boton in (self.boton_consultar, self.boton_cancelar, self.boton_actividad):
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setStyleSheet(
                f"QPushButton {{ background: {COLOR_SUPERFICIE_CLARA}; "
                f"color: {COLOR_TEXTO}; border: 1px solid {COLOR_LINEA}; "
                "border-radius: 6px; padding: 7px 12px; } "
                f"QPushButton:hover {{ border-color: {COLOR_VERDE}; }}"
            )
            acciones.addWidget(boton)
        acciones.addStretch(1)
        principal.addLayout(acciones)
        self.boton_promedios = QPushButton("Calcular promedios del semestre actual")
        self.boton_promedios.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boton_promedios.setStyleSheet(
            f"QPushButton {{ background: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; padding: 7px 12px; }} "
            f"QPushButton:hover {{ border-color: {COLOR_VERDE}; }}"
        )
        self.boton_promedios.clicked.connect(self._abrir_promedios)
        principal.addWidget(self.boton_promedios, 0, Qt.AlignmentFlag.AlignLeft)
        self.estado = QLabel("Aún no hay una consulta en curso.")
        self.estado.setObjectName("estadoConsultaAvance")
        self.estado.setWordWrap(True)
        self.estado.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        principal.addWidget(self.estado)
        self.barra_consulta = QProgressBar()
        self.barra_consulta.setObjectName("barraConsultaAvance")
        self.barra_consulta.setTextVisible(True)
        self.barra_consulta.setStyleSheet(
            f"QProgressBar {{ background: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 5px; min-height: 16px; "
            "text-align: center; } "
            f"QProgressBar::chunk {{ background: {COLOR_VERDE}; border-radius: 4px; }}"
        )
        self.barra_consulta.hide()
        principal.addWidget(self.barra_consulta)
        self.resumen = QLabel("")
        self.resumen.setStyleSheet(f"color: {COLOR_VERDE}; font-size: 12px; font-weight: 700;")
        principal.addWidget(self.resumen)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.contenedor = QWidget()
        self.contenedor.setStyleSheet(f"background-color: {COLOR_FONDO};")
        self.contenido = QVBoxLayout(self.contenedor)
        self.contenido.setContentsMargins(0, 4, 0, 8)
        self.contenido.setSpacing(16)
        self.fila_periodos = QWidget()
        self.columnas = QHBoxLayout(self.fila_periodos)
        self.columnas.setContentsMargins(0, 4, 0, 8)
        self.columnas.setSpacing(11)
        self.contenido.addWidget(self.fila_periodos)
        self.nivelacion = QFrame()
        self.nivelacion.setObjectName("seccionNivelacionAvance")
        self.nivelacion.setStyleSheet(
            f"QFrame#seccionNivelacionAvance {{ background-color: {COLOR_SUPERFICIE}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 8px; }}"
        )
        self.layout_nivelacion = QVBoxLayout(self.nivelacion)
        self.layout_nivelacion.setContentsMargins(10, 10, 10, 10)
        self.layout_nivelacion.setSpacing(8)
        self.contenido.addWidget(self.nivelacion)
        self.nivelacion.hide()
        self.contenido.addStretch(1)
        self.area.setWidget(self.contenedor)
        principal.addWidget(self.area, 1)
        preparar_dialogo_sin_barra(self, principal)
        self.rejected.connect(self.cancelar_consulta.emit)
        self.mostrar_datos(None)

    def marcar_consulta(self, en_curso):
        self.boton_consultar.setEnabled(not en_curso)
        self.boton_cancelar.setVisible(en_curso)
        self.boton_actividad.setVisible(en_curso)
        if not en_curso:
            self.boton_actividad.setChecked(False)
            if self.ventana_actividad is not None:
                self.ventana_actividad.close()
        self.barra_consulta.setVisible(en_curso)
        if en_curso:
            self.barra_consulta.setRange(0, 0)
        else:
            self.barra_consulta.setRange(0, 100)
            self.barra_consulta.setValue(0)

    def _alternar_actividad(self, mostrar):
        self.boton_actividad.setText("Ocultar actividad" if mostrar else "Mostrar actividad")
        self.mostrar_actividad.emit(mostrar)
        if mostrar:
            if self.ventana_actividad is None:
                self.ventana_actividad = VentanaActividadAvance(self)
                self.ventana_actividad.cerrada.connect(
                    lambda: self.boton_actividad.setChecked(False)
                )
            self.ventana_actividad.show()
            self.ventana_actividad.raise_()
        elif self.ventana_actividad is not None:
            self.ventana_actividad.limpiar_captura()
            self.ventana_actividad.hide()

    def actualizar_captura(self, datos):
        if self.ventana_actividad is not None and self.boton_actividad.isChecked():
            self.ventana_actividad.actualizar_captura(datos)

    def actualizar_progreso(self, porcentaje):
        if porcentaje <= 15:
            self.barra_consulta.setRange(0, 0)
        else:
            self.barra_consulta.setRange(0, 100)
            self.barra_consulta.setValue(min(100, max(0, porcentaje)))

    def mostrar_datos(self, datos):
        self.datos_avance = datos if isinstance(datos, dict) else {}
        limpiar_layout(self.columnas)
        limpiar_layout(self.layout_nivelacion)
        calificaciones = datos.get("calificaciones_detalle", []) if isinstance(datos, dict) else []
        notas_editadas = datos.get("notas_editadas", {}) if isinstance(datos, dict) else {}
        detalles_por_materia = {}
        for detalle in calificaciones:
            clave = (str(detalle.get("periodo") or ""), str(detalle.get("codigo") or ""))
            detalle_visible = dict(detalle)
            if "|".join(clave) in notas_editadas:
                detalle_visible["parciales"] = notas_editadas["|".join(clave)]
            detalles_por_materia.setdefault(clave, []).append(detalle_visible)
        asignaturas = datos.get("asignaturas", []) if isinstance(datos, dict) else []
        if not asignaturas:
            self.papa.setText("P.A.P.A.  —")
            self.resumen.setText("")
            self.nivelacion.hide()
            vacio = QLabel("Todavía no hay historia académica importada para este plan.")
            vacio.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; padding: 16px 0;")
            self.columnas.addWidget(vacio)
            self.columnas.addStretch(1)
            self.contenedor.setMinimumWidth(0)
            return
        promedio_acumulado = promedio_ponderado_periodo(asignaturas)
        self.papa.setText(
            f"P.A.P.A.  {promedio_acumulado}" if promedio_acumulado is not None else "P.A.P.A.  —"
        )
        por_periodo = {}
        materias_nivelacion = []
        for materia in asignaturas:
            if "nivelaci" in str(materia.get("tipologia") or "").casefold():
                materias_nivelacion.append(materia)
            else:
                por_periodo.setdefault(materia.get("periodo") or "Sin periodo", []).append(materia)
        periodos = periodos_visibles_avance(
            materia.get("periodo") for materia in asignaturas
        )
        reprobadas = sum(materia.get("estado") == "reprobada" for materia in asignaturas)
        self.resumen.setText(
            f"{len(periodos)} periodos · {len(asignaturas)} registros · "
            f"{reprobadas} reprobada(s)"
        )
        for periodo in periodos:
            columna = QFrame()
            columna.setObjectName("columnaPeriodoAvance")
            columna.setFixedWidth(214)
            columna.setStyleSheet(
                f"QFrame#columnaPeriodoAvance {{ background-color: {COLOR_SUPERFICIE}; "
                f"border: 1px solid {COLOR_LINEA}; border-radius: 8px; }}"
            )
            disposicion = QVBoxLayout(columna)
            disposicion.setContentsMargins(7, 7, 7, 8)
            disposicion.setSpacing(7)
            materias_periodo = por_periodo.get(periodo, [])
            promedio = promedio_ponderado_periodo(materias_periodo)
            encabezado = QLabel(
                f"{periodo}\nPromedio: {promedio}"
                if promedio is not None else
                (f"{periodo}\nSin asignaturas" if not materias_periodo else f"{periodo}\nPromedio pendiente")
            )
            encabezado.setAlignment(Qt.AlignmentFlag.AlignCenter)
            encabezado.setStyleSheet(
                f"background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; "
                "border: none; border-radius: 5px; padding: 6px; font-weight: 800;"
            )
            encabezado.setToolTip(
                "PAPI: suma de (créditos × nota) dividida entre los créditos de materias "
                "con nota numérica en este período. No incluye materias sin nota ni de nivelación."
            )
            disposicion.addWidget(encabezado)
            for materia in materias_periodo:
                clave = (str(materia.get("periodo") or ""), str(materia.get("codigo") or ""))
                disposicion.addWidget(self._tarjeta_materia(materia, detalles_por_materia.get(clave, [])))
            disposicion.addStretch(1)
            self.columnas.addWidget(columna)
        self.columnas.addStretch(1)
        self.contenedor.setMinimumWidth(len(periodos) * 214 + max(0, len(periodos) - 1) * 11)
        if materias_nivelacion:
            encabezado = QLabel("NIVELACIÓN")
            encabezado.setStyleSheet(
                f"color: {COLOR_TEXTO}; background: transparent; font-size: 13px; font-weight: 800; border: none;"
            )
            self.layout_nivelacion.addWidget(encabezado)
            fila = QHBoxLayout()
            fila.setSpacing(9)
            for materia in materias_nivelacion:
                clave = (str(materia.get("periodo") or ""), str(materia.get("codigo") or ""))
                tarjeta = self._tarjeta_materia(materia, detalles_por_materia.get(clave, []))
                tarjeta.setFixedWidth(200)
                fila.addWidget(tarjeta)
            fila.addStretch(1)
            self.layout_nivelacion.addLayout(fila)
            self.nivelacion.show()
        else:
            self.nivelacion.hide()
    def _tarjeta_materia(self, materia, detalles):
        estado = materia.get("estado")
        if estado == "reprobada":
            fondo, borde = COLOR_ROJO_FONDO, COLOR_ROJO
        elif estado == "aprobada":
            fondo, borde = COLOR_VERDE_FONDO, COLOR_VERDE
        else:
            fondo, borde = COLOR_SUPERFICIE_CLARA, COLOR_LINEA
        tarjeta = TarjetaAvance()
        tarjeta.setObjectName("tarjetaMateriaAvance")
        tarjeta.setProperty("estado_academico", estado)
        tarjeta.setCursor(Qt.CursorShape.PointingHandCursor)
        tarjeta.setStyleSheet(
            f"QFrame#tarjetaMateriaAvance {{ background-color: {fondo}; "
            f"border: 1px solid {borde}; border-radius: 6px; }}"
        )
        layout = QVBoxLayout(tarjeta)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        nombre = QLabel(str(materia.get("nombre") or "Materia sin nombre"))
        nombre.setWordWrap(True)
        nombre.setStyleSheet(f"color: {COLOR_TEXTO}; background: transparent; font-size: 11px; font-weight: 700; border: none;")
        layout.addWidget(nombre)
        creditos = str(materia.get("creditos") or "").strip()
        codigo_texto = str(materia.get("codigo") or "Sin código")
        codigo = QLabel(
            f"{codigo_texto} · {creditos} crédito{'s' if creditos != '1' else ''}"
            if creditos else codigo_texto
        )
        codigo.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; background: transparent; font-size: 9px; border: none;")
        layout.addWidget(codigo)
        nota = materia.get("nota")
        estado_texto = str(estado or "sin_estado").replace("_", " ").upper()
        calificacion = QLabel(
            f"Nota: {nota}" if nota is not None else f"{estado_texto} · sin nota numérica"
        )
        calificacion.setStyleSheet(f"color: {borde if estado == 'reprobada' else COLOR_TEXTO}; "
                                    "background: transparent; font-size: 11px; font-weight: 800; border: none;")
        layout.addWidget(calificacion)
        detalle = QLabel(f"{materia.get('tipologia', '')} · {estado_texto}")
        detalle.setWordWrap(True)
        detalle.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; background: transparent; font-size: 9px; border: none;")
        layout.addWidget(detalle)
        for etiqueta in (nombre, codigo, calificacion, detalle):
            etiqueta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        tarjeta.setToolTip("Clic para ver el resumen de notas")
        tarjeta.pulsada.connect(lambda m=materia, d=detalles: self._mostrar_notas_materia(m, d))
        return tarjeta

    def _abrir_promedios(self):
        ventana = VentanaPromedioActual(self.datos_avance, self)
        ventana.notas_cambiadas.connect(self.guardar_notas.emit)
        ventana.notas_cambiadas.connect(self.mostrar_datos)
        ventana.exec()

    def _mostrar_notas_materia(self, materia, detalles):
        titulo = f"{materia.get('nombre') or 'Materia'} · {materia.get('periodo') or 'Sin período'}"
        filas = [f"Código: {materia.get('codigo') or '—'}",
                 f"Créditos: {materia.get('creditos') or '—'}",
                 f"Nota definitiva: {materia.get('nota') if materia.get('nota') is not None else 'Sin nota numérica'}"]
        if not detalles:
            filas.append("No hay calificaciones parciales disponibles para este intento.")
        for detalle in detalles:
            if detalle.get("error"):
                filas.append(f"No se pudieron consultar los parciales: {detalle['error']}")
            elif not detalle.get("parciales"):
                filas.append("Sin notas parciales registradas.")
            for parcial in detalle.get("parciales", []):
                peso = f" · {parcial['porcentaje']}%" if parcial.get("porcentaje") else ""
                filas.append(f"{parcial.get('nombre') or 'Actividad'}{peso}: {parcial.get('nota') or 'Sin nota'}")
        dialogo = QMessageBox(self)
        dialogo.setWindowTitle("Notas · Mi Avance")
        dialogo.setText(titulo)
        dialogo.setInformativeText("\n".join(filas))
        dialogo.setStandardButtons(QMessageBox.StandardButton.Close)
        dialogo.setStyleSheet(
            f"QMessageBox {{ background: {COLOR_FONDO}; }} "
            f"QLabel {{ color: {COLOR_TEXTO}; min-width: 330px; }} "
            f"QPushButton {{ color: {COLOR_TEXTO}; background: {COLOR_SUPERFICIE_CLARA}; "
            f"border: 1px solid {COLOR_LINEA}; padding: 5px 12px; }}"
        )
        dialogo.exec()


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
        if not ES_EDICION_STORE:
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
        boton_avance = QPushButton("Mi Avance")
        boton_avance.setCursor(Qt.CursorShape.PointingHandCursor)
        boton_avance.clicked.connect(ventana.abrir_mi_avance)
        boton_avance.setStyleSheet(boton_plan.styleSheet())
        layout.addWidget(boton_avance)
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


class BotonTextoAjustable(QPushButton):
    """Botón de varias líneas que se adapta al ancho disponible."""

    def __init__(self, texto):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setText(texto)

    def setText(self, texto):
        """Distribuye el detalle en varias líneas para permitir ventanas angostas."""
        self._texto_completo = str(texto)
        self.setToolTip(self._texto_completo)
        self._ajustar_texto(max(120, self.width() - 20))

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self._ajustar_texto(max(120, self.width() - 20))

    def _ajustar_texto(self, ancho_disponible):
        metricas = self.fontMetrics()
        lineas = []
        for parrafo in self._texto_completo.splitlines():
            # Agrupa tantas sesiones como quepan en cada línea: 4, 2+2 o 1+1+1+1.
            sesiones = parrafo.split("  |  ")
            parrafos = []
            grupo = ""
            for sesion in sesiones:
                candidato = f"{grupo}  |  {sesion}" if grupo else sesion
                if grupo and metricas.horizontalAdvance(candidato) > ancho_disponible:
                    parrafos.append(grupo)
                    grupo = sesion
                else:
                    grupo = candidato
            parrafos.append(grupo)
            for tramo in parrafos:
                if metricas.horizontalAdvance(tramo) <= ancho_disponible:
                    lineas.append(tramo)
                    continue
                actual = ""
                for palabra in tramo.split():
                    candidato = f"{actual} {palabra}" if actual else palabra
                    if actual and metricas.horizontalAdvance(candidato) > ancho_disponible:
                        lineas.append(actual)
                        actual = palabra
                    else:
                        actual = candidato
                lineas.append(actual)
        texto = "\n".join(lineas)
        if texto != super().text():
            super().setText(texto)
        self.setMinimumHeight(max(63, 16 + 18 * len(lineas)))


class BotonGrupoHorario(BotonTextoAjustable):
    """Botón del selector que previsualiza la franja del grupo al pasar el cursor."""

    cursor_entro = Signal(object)
    cursor_salio = Signal()

    def __init__(self, texto, grupo):
        super().__init__(texto)
        self.grupo = grupo
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, evento):
        self.cursor_entro.emit(self.grupo)
        super().enterEvent(evento)

    def leaveEvent(self, evento):
        self.cursor_salio.emit()
        super().leaveEvent(evento)


class CeldaHorario(QFrame):
    """Celda del horario semanal."""

    seleccionada = Signal(str, int, int)
    materia_accion = Signal(object, object, str)
    geometria_cambiada = Signal()

    def __init__(self, dia, hora, duracion):
        super().__init__()
        self.dia = dia
        self.hora = hora
        self.duracion = duracion
        self.tiene_sesiones = False
        self.previsualizacion_grupo_activa = False
        self.linea_roja_superior = False
        self.linea_roja_inferior = False
        self.setCursor(Qt.PointingHandCursor)
        self.contenido = QVBoxLayout(self)
        self.contenido.setContentsMargins(6, 5, 6, 5)
        self.contenido.setSpacing(3)
        self.mostrar_sesiones([])

    def mostrar_sesiones(
        self, sesiones, linea_roja_superior=False, linea_roja_inferior=False,
        tooltip_traslado="",
    ):
        limpiar_layout(self.contenido)
        self.tiene_sesiones = bool(sesiones)
        self.indicador_agregar = None
        self.setCursor(
            Qt.CursorShape.ArrowCursor if self.tiene_sesiones else Qt.CursorShape.PointingHandCursor
        )
        self.linea_roja_superior = linea_roja_superior
        self.linea_roja_inferior = linea_roja_inferior
        self.setToolTip(tooltip_traslado)
        self._aplicar_estilo_borde()
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

    def establecer_previsualizacion_grupo(self, activa):
        activa = bool(activa)
        if self.previsualizacion_grupo_activa == activa:
            return
        self.previsualizacion_grupo_activa = activa
        self._aplicar_estilo_borde()

    def _aplicar_estilo_borde(self):
        if self.previsualizacion_grupo_activa:
            izquierdo = derecho = superior = inferior = f"2px solid {COLOR_TEXTO}"
            color_hover = COLOR_TEXTO
        else:
            izquierdo = derecho = f"1px solid {COLOR_LINEA}"
            superior = (
                f"2px solid {COLOR_AMARILLO}"
                if self.linea_roja_superior else f"1px solid {COLOR_LINEA}"
            )
            inferior = (
                f"2px solid {COLOR_AMARILLO}"
                if self.linea_roja_inferior else f"1px solid {COLOR_LINEA}"
            )
            color_hover = COLOR_VERDE
        self.setStyleSheet(
            f"""
            QFrame {{ background-color: {COLOR_SUPERFICIE}; border-left: {izquierdo};
                border-right: {derecho}; border-top: {superior};
                border-bottom: {inferior}; border-radius: 5px; }}
            QFrame:hover {{ border-color: {color_hover}; }}
            """
        )

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

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self.geometria_cambiada.emit()

    def moveEvent(self, evento):
        super().moveEvent(evento)
        self.geometria_cambiada.emit()


class CapaIntercampus(QWidget):
    """Dibuja rótulos encima de las líneas usando la geometría real de las celdas."""

    TEXTO = "Intercampus"

    def __init__(self, parent):
        super().__init__(parent)
        self.limites = {}
        self.icono_bus = QPixmap(str(RUTA_BUS_INTERCAMPUS))
        if not self.icono_bus.isNull() and self.icono_bus.hasAlphaChannel():
            # Solo ajustar el encuadre al dibujar: el PNG original no se modifica.
            contenido = QRegion(self.icono_bus.mask()).boundingRect()
            if not contenido.isEmpty():
                self.icono_bus = self.icono_bus.copy(contenido)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.aviso = QLabel(self, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.aviso.setObjectName("avisoIntercampus")
        self.aviso.setTextFormat(Qt.TextFormat.PlainText)
        self.aviso.setWordWrap(True)
        self.aviso.setFixedWidth(340)
        self.aviso.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.aviso.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.aviso.setStyleSheet(
            f"QLabel#avisoIntercampus {{ background-color: #1C1B14; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_AMARILLO}; border-radius: 5px; "
            "padding: 8px; font-size: 12px; }"
        )
        self.aviso.hide()
        self._posicion_cursor = None
        self._actualizacion_aviso_pendiente = False
        # La capa sigue dejando pasar clics. Observamos los eventos de los
        # widgets reales debajo del icono, también en los huecos entre celdas.
        QApplication.instance().installEventFilter(self)

    def establecer_limites(self, limites):
        self.aviso.hide()
        self._posicion_cursor = None
        self.limites = dict(limites)
        self.update()

    def etiqueta_en(self, posicion):
        """Zona sensible: todo el recuadro y las dos líneas de su mismo límite."""
        for clave, rectangulo in self.rectangulos_etiquetas():
            if rectangulo.contains(posicion):
                return clave, rectangulo
            dia, hora = clave
            cuadricula = self.parentWidget()
            franja = None
            for (dia_celda, inicio, duracion), celda in cuadricula.celdas_por_bloque.items():
                if dia_celda != dia:
                    continue
                geometria = QRectF(celda.geometry()).translated(-self.x(), -self.y())
                if (inicio + duracion) * 60 == hora:
                    linea = QRectF(geometria.left(), geometria.bottom() - 3, geometria.width(), 6)
                elif inicio * 60 == hora:
                    linea = QRectF(geometria.left(), geometria.top() - 3, geometria.width(), 6)
                else:
                    continue
                franja = linea if franja is None else franja.united(linea)
            if franja is not None and franja.contains(posicion):
                return clave, rectangulo
        return None

    def mostrar_aviso(self, clave, rectangulo):
        texto = self.limites[clave]
        if self.aviso.text() != texto:
            self.aviso.setText(texto)
            self.aviso.adjustSize()
        # Esquina inferior izquierda del mensaje sobre la superior derecha del
        # recuadro: la posición jamás se calcula a partir del cursor.
        ancla = self.mapToGlobal(rectangulo.topRight().toPoint())
        posicion = QPoint(ancla.x(), ancla.y() - self.aviso.height())
        pantalla = QApplication.screenAt(ancla)
        if pantalla:
            disponible = pantalla.availableGeometry()
            posicion.setX(max(disponible.left(), min(posicion.x(), disponible.right() - self.aviso.width() + 1)))
            posicion.setY(max(disponible.top(), min(posicion.y(), disponible.bottom() - self.aviso.height() + 1)))
        if self.aviso.pos() != posicion:
            self.aviso.move(posicion)
        if not self.aviso.isVisible():
            self.aviso.show()

    def _actualizar_aviso_cursor(self):
        self._actualizacion_aviso_pendiente = False
        etiqueta = None
        if self._posicion_cursor is not None and self.isVisible():
            punto = self.mapFromGlobal(self._posicion_cursor)
            # No activar avisos de zonas recortadas por el scroll.
            if self.visibleRegion().contains(punto):
                etiqueta = self.etiqueta_en(QPointF(punto))
        if etiqueta:
            self.mostrar_aviso(*etiqueta)
        else:
            self.aviso.hide()

    def _programar_actualizacion_aviso(self):
        if self._posicion_cursor is not None and not self._actualizacion_aviso_pendiente:
            self._actualizacion_aviso_pendiente = True
            QTimer.singleShot(0, self._actualizar_aviso_cursor)

    def eventFilter(self, objeto, evento):
        tipo = evento.type()
        cuadricula = self.parentWidget()
        if tipo in (QEvent.Type.ToolTip, QEvent.Type.MouseMove):
            if not isinstance(objeto, QWidget):
                return False
            if objeto is self.aviso:
                return False
            dentro = objeto is cuadricula or cuadricula.isAncestorOf(objeto)
            # Un mismo movimiento puede propagarse desde una celda hasta el
            # scroll o la ventana. El receptor no indica que el cursor salió.
            if objeto.window() is cuadricula.window():
                self._posicion_cursor = (evento.globalPos() if tipo == QEvent.Type.ToolTip
                                         else evento.globalPosition().toPoint())
                self._actualizar_aviso_cursor()
            else:
                self._posicion_cursor = None
                self.aviso.hide()
            if tipo == QEvent.Type.ToolTip and dentro:
                # Evitar que Qt vuelva a mostrar el tooltip nativo al lado del cursor.
                evento.accept()
                return True
        elif self._posicion_cursor is not None:
            if tipo == QEvent.Type.WindowDeactivate and objeto is cuadricula.window():
                self._posicion_cursor = None
                self.aviso.hide()
            elif tipo == QEvent.Type.Hide and isinstance(objeto, QWidget) and (
                objeto is self or objeto is cuadricula or objeto.isAncestorOf(cuadricula)
            ):
                self._posicion_cursor = None
                self.aviso.hide()
            elif tipo in (QEvent.Type.Hide, QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Wheel):
                if isinstance(objeto, QWidget) and objeto is not self.aviso and (
                    objeto is cuadricula or objeto.isAncestorOf(cuadricula) or cuadricula.isAncestorOf(objeto)
                ):
                    # Mostrar/ocultar botones de una tarjeta no es salir de la
                    # zona amarilla. Recalcular una vez que termine el layout.
                    self._programar_actualizacion_aviso()
            elif tipo == QEvent.Type.Leave and objeto is cuadricula.window():
                self._posicion_cursor = None
                self.aviso.hide()
        return False

    def rectangulos_etiquetas(self):
        """Devuelve las cajas calculadas a partir de la posición actual de cada celda."""
        if not self.isVisible():
            return []

        cuadricula = self.parentWidget()
        resultado = []
        fuente = QFont(FUENTE_INTERFAZ, 8, QFont.Weight.Bold)
        metricas = QFontMetrics(fuente)
        ancho = metricas.horizontalAdvance(self.TEXTO) + 12
        alto = max(22, metricas.height() + 4)

        for dia, hora in self.limites:
            anterior = next(
                ((inicio, fin) for inicio, fin in BLOQUES_HORARIO if fin * 60 == hora),
                None,
            )
            siguiente = next(
                ((inicio, fin) for inicio, fin in BLOQUES_HORARIO if inicio * 60 == hora),
                None,
            )
            if anterior is None or siguiente is None:
                continue

            celda_anterior = cuadricula.celdas_por_bloque.get(
                (dia, anterior[0], anterior[1] - anterior[0])
            )
            celda_siguiente = cuadricula.celdas_por_bloque.get(
                (dia, siguiente[0], siguiente[1] - siguiente[0])
            )
            if celda_anterior is None or celda_siguiente is None:
                continue

            # Las celdas y esta capa comparten padre. Sus geometrías ya están
            # en coordenadas de la cuadrícula; mapTo entre hermanos añadía
            # el desplazamiento de los contenedores de la ventana.
            rect_anterior = QRectF(celda_anterior.geometry())
            rect_siguiente = QRectF(celda_siguiente.geometry())
            centro_x = (
                rect_anterior.center().x() + rect_siguiente.center().x()
            ) / 2 - self.x()
            centro_y = (
                rect_anterior.bottom() + rect_siguiente.top()
            ) / 2 - self.y()
            resultado.append((
                (dia, hora),
                QRectF(centro_x - ancho / 2, centro_y - alto / 2, ancho, alto),
            ))
        return resultado

    def paintEvent(self, evento):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setFont(QFont(FUENTE_INTERFAZ, 8, QFont.Weight.Bold))
        painter.setPen(QColor("#171717"))
        for _, rectangulo in self.rectangulos_etiquetas():
            painter.setBrush(QColor(COLOR_AMARILLO))
            painter.drawRoundedRect(rectangulo, 5, 5)
            if self.icono_bus.isNull():
                # Mantener el aviso si falta el recurso en una instalación dañada.
                painter.drawText(rectangulo, Qt.AlignmentFlag.AlignCenter, self.TEXTO)
                continue
            espacio = rectangulo.adjusted(6, 3, -6, -3)
            tamano = self.icono_bus.size().scaled(
                espacio.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio
            )
            destino = QRectF(0, 0, tamano.width(), tamano.height())
            destino.moveCenter(rectangulo.center())
            painter.drawPixmap(destino, self.icono_bus, QRectF(self.icono_bus.rect()))


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
        contenido.setContentsMargins(5, 4, 2, 4)
        contenido.setSpacing(3)
        detalle = detalle_sesion_en_bloque(grupo, dia, hora, duracion)
        etiqueta = QLabel(
            f"{materia.get('nombre') or 'Materia'}\n"
            f"G{grupo.get('numero', '')} · {detalle}"
        )
        etiqueta.setTextFormat(Qt.TextFormat.PlainText)
        etiqueta.setWordWrap(True)
        # El título completo aprovecha el ancho disponible y gana líneas al
        # estrechar el horario, en lugar de recortarse por número de caracteres.
        politica = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        politica.setHeightForWidth(True)
        etiqueta.setSizePolicy(politica)
        borde_tarjeta = (
            COLOR_LINEA if color_fondo == COLOR_PREVISUALIZACION else COLOR_VERDE
        )
        etiqueta.setStyleSheet(
            f"background-color: {color_fondo}; color: {color_texto}; border: none; "
            f"border-left: 3px solid {borde_tarjeta}; border-radius: 4px; font-size: 10px; "
            "font-weight: 700; padding: 5px 2px 5px 5px;"
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
            f" QToolTip {{ color: {COLOR_TEXTO}; background-color: {COLOR_BARRA}; "
            f"border: 1px solid {COLOR_AMARILLO}; padding: 5px; }}"
        )
        self.cuadricula = QGridLayout(self)
        self.cuadricula.setContentsMargins(8, 8, 8, 8)
        self.cuadricula.setSpacing(6)
        self.celdas_por_bloque = {}
        self.capa_intercampus = CapaIntercampus(self)
        self.bloques_previsualizados = set()
        self.temporizador_limpiar_previsualizacion = QTimer(self)
        self.temporizador_limpiar_previsualizacion.setSingleShot(True)
        self.temporizador_limpiar_previsualizacion.setInterval(90)
        self.temporizador_limpiar_previsualizacion.timeout.connect(
            self.limpiar_previsualizacion_grupo
        )

    def actualizar(self, grupos, grupos_previsualizados=None):
        """Redibuja el horario, distinguiendo grupos reales de previsualizaciones."""
        self.limpiar_previsualizacion_grupo()
        self.celdas_por_bloque = {}
        self.capa_intercampus.establecer_limites({})
        limpiar_layout(self.cuadricula)
        grupos_previsualizados = grupos_previsualizados or ()
        limites_traslado = {}
        for adyacencia in detectar_adyacencias(grupos):
            if not adyacencia.get("sedes_diferentes"):
                continue
            anterior = adyacencia["anterior"][4].get("sede", "campus anterior")
            siguiente = adyacencia["siguiente"][4].get("sede", "campus siguiente")
            limites_traslado[(adyacencia["dia"], adyacencia["hora"])] = (
                "Traslado de campus: esta línea amarilla indica que debes "
                f"desplazarte de {anterior} a {siguiente} entre clases."
            )
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
                        es_previsualizado = any(
                            materia is materia_preview and grupo is grupo_preview
                            for materia_preview, grupo_preview in grupos_previsualizados
                        )
                        if es_previsualizado:
                            fondo, texto = (
                                COLOR_PREVISUALIZACION,
                                COLOR_PREVISUALIZACION_TEXTO,
                            )
                        else:
                            fondo, texto = COLORES_MATERIAS[indice % len(COLORES_MATERIAS)]
                        sesiones.append((materia, grupo, fondo, texto))
                inicio_minutos = hora * 60
                fin_minutos = fin * 60
                celda.mostrar_sesiones(
                    sesiones,
                    linea_roja_superior=(dia, inicio_minutos) in limites_traslado,
                    linea_roja_inferior=(dia, fin_minutos) in limites_traslado,
                    tooltip_traslado=(
                        limites_traslado.get((dia, inicio_minutos))
                        or limites_traslado.get((dia, fin_minutos))
                        or ""
                    ),
                )
                clave_bloque = (dia, hora, duracion)
                self.celdas_por_bloque[clave_bloque] = celda
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
                celda.geometria_cambiada.connect(self._solicitar_actualizacion_intercampus)
                self.cuadricula.addWidget(celda, fila, columna)
        self.capa_intercampus.establecer_limites(limites_traslado)
        self.setMouseTracking(True)
        for widget in self.findChildren(QWidget):
            widget.setMouseTracking(True)
        self.cuadricula.activate()
        self.capa_intercampus.setGeometry(self.rect())
        self.capa_intercampus.raise_()
        self.capa_intercampus.show()
        self.capa_intercampus.update()

    def _solicitar_actualizacion_intercampus(self):
        self.capa_intercampus.update()

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self.capa_intercampus.setGeometry(self.rect())
        self.capa_intercampus.raise_()
        self.capa_intercampus.update()

    def previsualizar_grupo(self, grupo):
        """Delinea las celdas que ocuparía un grupo sin añadirlo al horario."""
        self.temporizador_limpiar_previsualizacion.stop()
        self.limpiar_previsualizacion_grupo()
        for clave, celda in self.celdas_por_bloque.items():
            dia, hora, duracion = clave
            if grupo_ocupa_bloque(grupo, dia, hora, duracion):
                celda.establecer_previsualizacion_grupo(True)
                self.bloques_previsualizados.add(clave)

    def programar_limpieza_previsualizacion(self):
        if self.bloques_previsualizados:
            self.temporizador_limpiar_previsualizacion.start()

    def limpiar_previsualizacion_grupo(self):
        self.temporizador_limpiar_previsualizacion.stop()
        for clave in self.bloques_previsualizados:
            celda = self.celdas_por_bloque.get(clave)
            if celda is not None:
                celda.establecer_previsualizacion_grupo(False)
        self.bloques_previsualizados.clear()

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
        preparar_dialogo_sin_barra(self, layout, redimensionable=False)
        titulo = QLabel("Preparando tu horario")
        titulo.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {COLOR_TEXTO};")
        layout.addWidget(titulo)
        self.mensaje = QLabel("Fénix está consultando las materias obligatorias…")
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
            "text-align: center; font-size: 12px; font-weight: 700; } "
            f"QProgressBar::chunk {{ background-color: {COLOR_VERDE}; "
            "border-radius: 5px; }"
        )
        layout.addWidget(self.progreso)
        self.tiempo = QLabel("Calculando tiempo restante…")
        self.tiempo.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXTO_SECUNDARIO};")
        layout.addWidget(self.tiempo)
        aviso = QLabel(
            "Puedes cerrar este aviso; la actualización continuará en segundo plano "
            "y el horario se habilitará al terminar."
        )
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


class DialogoProgresoVersion(QDialog):
    """Da feedback del chequeo/descarga sin bloquear la ventana ni el cursor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fénix · Actualización")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(440)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_SUPERFICIE}; }}"
            f"QLabel {{ color: {COLOR_TEXTO}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        preparar_dialogo_sin_barra(self, layout, redimensionable=False)
        titulo = QLabel("Preparando actualización")
        titulo.setStyleSheet(f"font-size: 19px; font-weight: 800; color: {COLOR_TEXTO};")
        layout.addWidget(titulo)
        self.mensaje = QLabel("Conectando con GitHub…")
        self.mensaje.setWordWrap(True)
        self.mensaje.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXTO_SECUNDARIO};")
        layout.addWidget(self.mensaje)
        self.progreso = QProgressBar()
        self.progreso.setRange(0, 0)
        self.progreso.setTextVisible(False)
        self.progreso.setFixedHeight(12)
        self.progreso.setStyleSheet(
            f"QProgressBar {{ background: {COLOR_BARRA}; border: 0; border-radius: 6px; }}"
            f"QProgressBar::chunk {{ background: {COLOR_VERDE}; border-radius: 6px; }}"
        )
        layout.addWidget(self.progreso)
        self.porcentaje = QLabel("")
        self.porcentaje.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.porcentaje.setStyleSheet(f"font-size: 11px; color: {COLOR_TEXTO_SECUNDARIO};")
        layout.addWidget(self.porcentaje)

    def actualizar_descarga(self, recibidos, total):
        if total and total > 0:
            porcentaje = max(0, min(100, int(recibidos * 100 / total)))
            self.progreso.setRange(0, 100)
            self.progreso.setValue(porcentaje)
            self.mensaje.setText("Descargando la nueva versión…")
            self.porcentaje.setText(f"{porcentaje}% · {recibidos // (1024 * 1024)} de {total // (1024 * 1024)} MB")
        else:
            self.mensaje.setText("Descargando la nueva versión…")
            self.porcentaje.setText(f"{recibidos // (1024 * 1024)} MB recibidos")


class TrabajadorVersion(QThread):
    consultada = Signal(object)
    descargada = Signal(object)
    progreso_descarga = Signal(int, int)
    fallo = Signal(str)

    def __init__(self, release=None, parent=None):
        super().__init__(parent)
        self.release = release

    def run(self):
        try:
            from servicios.actualizacion_aplicacion import consultar_ultima_version, descargar_release

            if self.release is None:
                self.consultada.emit(consultar_ultima_version())
                return
            paquete = descargar_release(
                self.release,
                progreso=lambda recibidos, total: self.progreso_descarga.emit(recibidos, total),
            )
            self.descargada.emit(str(paquete))
        except Exception as error:
            self.fallo.emit(str(error))


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
        self.materias_locales = {}
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
        self.ventana_mi_avance = None
        self.trabajador_avance = None
        self.inicio_primera_actualizacion = None
        self.proceso_actualizacion = None
        self.cambiando_estudiante = False
        self._indice_animacion_carga = 0
        self._frames_animacion_carga = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        self.comprobacion_version_pendiente = False
        self.arranque_autorizado = False

        self.configurar_ventana()
        self.crear_interfaz()
        self.temporizador_estado = QTimer(self)
        self.temporizador_estado.timeout.connect(self.revisar_actualizacion)
        self.temporizador_estado.start(1000)
        self.temporizador_previsualizacion = QTimer(self)
        self.temporizador_previsualizacion.setInterval(350)
        self.temporizador_previsualizacion.timeout.connect(
            self._alternar_parpadeo_previsualizacion
        )
        self.parpadeos_previsualizacion_restantes = 0
        self.previsualizacion_resaltada = False
        self.temporizador_animacion_carga = QTimer(self)
        self.temporizador_animacion_carga.setInterval(120)
        self.temporizador_animacion_carga.timeout.connect(self.animar_actualizacion)
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
        estado_fila = QHBoxLayout()
        estado_fila.setContentsMargins(0, 0, 0, 0)
        estado_fila.setSpacing(6)
        estado_fila.addWidget(self.etiqueta_estado, 1)
        self.indicador_carga = QLabel("⟳")
        self.indicador_carga.setFixedWidth(20)
        self.indicador_carga.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.indicador_carga.setStyleSheet(
            f"color: {COLOR_AMARILLO}; font-size: 17px; font-weight: 700;"
        )
        self.indicador_carga.hide()
        estado_fila.addWidget(self.indicador_carga)
        estado_layout.addLayout(estado_fila)
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
            f"QPushButton {{ background-color: {COLOR_AMARILLO_FONDO}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_AMARILLO}; border-radius: 7px; padding: 8px; "
            "text-align: left; font-size: 11px; font-weight: 700; } "
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
            f"border-color: {COLOR_AMARILLO}; }}"
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
            "nivelaciones_pendientes": not bool(dialogo.codigos_nivelacion(
                self.planes[dialogo.codigo_plan()]
            )),
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
                "nivelaciones_pendientes": not bool(dialogo.codigos_nivelacion(
                    self.planes[codigo]
                )),
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
        self.materias_locales = cargar_materias()
        if self.estudiante.get("nivelaciones_pendientes"):
            nivelaciones = {
                codigo_base(materia.get("codigo", codigo))
                for codigo, materia in self.materias_locales.items()
                if isinstance(materia, dict) and es_materia_nivelacion(materia)
            }
            nivelaciones.update(
                codigo_base(materia.get("codigo"))
                for materia in oferta.values()
                if isinstance(materia, dict) and es_materia_nivelacion(materia)
            )
            if nivelaciones:
                self.materias_aprobadas.update(nivelaciones)
                self.estudiante["nivelaciones_pendientes"] = False
                self.guardar_estado_estudiante()
                self.etiqueta_plan.setText(
                    f"PLAN ACTUAL\n{plan.nombre}\nCódigo {self.codigo_plan}\n"
                    f"{len(self.materias_aprobadas)} aprobada(s)"
                )
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
            "tardar un poco; puedes continuar organizando las obligatorias y optativas."
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
        preparar_dialogo_sin_barra(dialogo, layout)
        dialogo.exec()

    def abrir_dialogo_donaciones(self):
        """Muestra la tarjeta gráfica de apoyo a Fénix."""
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Invítame a un café · Apoya a Fénix")
        dialogo.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_SUPERFICIE}; }} "
            f"QPushButton {{ background-color: {COLOR_VERDE_FONDO}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_VERDE}; border-radius: 6px; padding: 7px 12px; }} "
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; }}"
        )
        layout = QVBoxLayout(dialogo)
        layout.setContentsMargins(18, 18, 18, 12)
        layout.setSpacing(12)

        tarjeta = QLabel()
        tarjeta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(RUTA_GRACIAS))
        if pixmap.isNull():
            tarjeta.setText("No se encontró la imagen de donaciones.")
            tarjeta.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; padding: 30px;")
        else:
            tarjeta.setPixmap(pixmap.scaled(
                1000, 500,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        layout.addWidget(tarjeta)

        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        botones.rejected.connect(dialogo.reject)
        layout.addWidget(botones)
        preparar_dialogo_sin_barra(dialogo, layout)
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

    def abrir_mi_avance(self):
        """Abre el historial y solicita una consulta voluntaria al SIA."""
        if not self.codigo_plan:
            QMessageBox.information(
                self, "Plan no disponible", "Selecciona tu plan antes de consultar Mi Avance."
            )
            return
        if self.ventana_mi_avance is None:
            self.ventana_mi_avance = VentanaAvanceAcademico(self)
            self.ventana_mi_avance.consultar_sia.connect(self.iniciar_consulta_avance)
            self.ventana_mi_avance.cancelar_consulta.connect(self.cancelar_consulta_avance)
            self.ventana_mi_avance.guardar_notas.connect(self._guardar_notas_avance)
        datos = cargar_json(ARCHIVO_AVANCE_ACADEMICO, {})
        if isinstance(datos, dict) and datos.get("plan_estudios") == self.codigo_plan:
            self.ventana_mi_avance.mostrar_datos(datos)
        else:
            self.ventana_mi_avance.mostrar_datos(None)
        self.ventana_mi_avance.show()
        self.ventana_mi_avance.raise_()
        self.ventana_mi_avance.activateWindow()

    def iniciar_consulta_avance(self):
        if self.trabajador_avance is not None and self.trabajador_avance.isRunning():
            return
        if not self.codigo_plan or self.ventana_mi_avance is None:
            return
        trabajador = TrabajadorAvanceAcademico(self.codigo_plan, self)
        self.trabajador_avance = trabajador
        trabajador.estado.connect(self.ventana_mi_avance.estado.setText)
        trabajador.progreso.connect(self.ventana_mi_avance.actualizar_progreso)
        trabajador.captura.connect(self.ventana_mi_avance.actualizar_captura)
        self.ventana_mi_avance.mostrar_actividad.connect(trabajador.activar_vista)
        trabajador.completado.connect(self._avance_consultado)
        trabajador.fallo.connect(self._avance_fallido)
        trabajador.cancelado.connect(self._avance_cancelado)
        trabajador.finished.connect(self._finalizar_trabajador_avance)
        trabajador.finished.connect(trabajador.deleteLater)
        self.ventana_mi_avance.marcar_consulta(True)
        self.ventana_mi_avance.estado.setText("Preparando navegador privado…")
        trabajador.start()

    def cancelar_consulta_avance(self):
        trabajador = self.trabajador_avance
        if trabajador is not None and trabajador.isRunning():
            trabajador.cancelar()
            if self.ventana_mi_avance is not None:
                self.ventana_mi_avance.estado.setText("Cancelando la consulta y cerrando el navegador…")

    def _avance_consultado(self, datos):
        if datos.get("plan_estudios") != self.codigo_plan or self.cambiando_estudiante:
            return
        try:
            anterior = cargar_json(ARCHIVO_AVANCE_ACADEMICO, {})
            if isinstance(anterior, dict) and anterior.get("plan_estudios") == self.codigo_plan:
                for clave in ("notas_editadas", "notas_manuales"):
                    if clave in anterior:
                        datos[clave] = anterior[clave]
            guardar_json_atomico(ARCHIVO_AVANCE_ACADEMICO, datos)
        except OSError as error:
            self._avance_fallido(f"No se pudo guardar la historia académica: {error}")
            return
        if self.ventana_mi_avance is not None:
            self.ventana_mi_avance.mostrar_datos(datos)
            self.ventana_mi_avance.estado.setText(
                datos.get("aviso_calificaciones")
                or "Historia académica y calificaciones actualizadas. La sesión del navegador se cerró."
            )
            self.ventana_mi_avance.marcar_consulta(False)

    def _guardar_notas_avance(self, datos):
        if datos.get("plan_estudios") != self.codigo_plan:
            return
        try:
            guardar_json_atomico(ARCHIVO_AVANCE_ACADEMICO, datos)
        except OSError as error:
            QMessageBox.warning(self, "No se guardaron las notas", str(error))

    def _avance_fallido(self, mensaje):
        if self.ventana_mi_avance is not None:
            self.ventana_mi_avance.estado.setText(f"No se pudo consultar el SIA: {mensaje}")
            self.ventana_mi_avance.marcar_consulta(False)

    def _avance_cancelado(self):
        if self.ventana_mi_avance is not None:
            self.ventana_mi_avance.estado.setText("Consulta cancelada; los datos anteriores se conservaron.")
            self.ventana_mi_avance.marcar_consulta(False)

    def _finalizar_trabajador_avance(self):
        if self.trabajador_avance is self.sender():
            if self.ventana_mi_avance is not None:
                try:
                    self.ventana_mi_avance.mostrar_actividad.disconnect(
                        self.trabajador_avance.activar_vista
                    )
                except (RuntimeError, TypeError):
                    pass
            self.trabajador_avance = None

    def detener_trabajador_avance(self):
        trabajador = self.trabajador_avance
        if trabajador is not None and trabajador.isRunning():
            trabajador.cancelar()
            if not trabajador.wait(15000):
                raise RuntimeError("El navegador de Mi Avance todavía no confirmó su cierre.")

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
        self.cambiar_materias_aprobadas_desde_plan({codigo}, aprobada)

    def cambiar_materias_aprobadas_desde_plan(self, codigos, aprobada):
        """Marca un conjunto de materias con una sola persistencia y actualización."""
        codigos = {codigo_base(codigo) for codigo in codigos if codigo_base(codigo)}
        if not codigos:
            return
        if aprobada:
            indice = {
                codigo_base(materia.get("codigo", codigo)): materia
                for codigo, materia in (self.materias_locales or {}).items()
                if isinstance(materia, dict)
            }
            indice.update({
                codigo_base(materia.get("codigo")): materia
                for materias in self.materias_por_origen.values()
                for materia in materias
            })
            self.materias_aprobadas.update(codigos)
            pendientes = list(codigos)
            while pendientes:
                actual = pendientes.pop()
                for requerido in codigos_prerrequisitos(indice.get(actual, {})):
                    if requerido and requerido not in self.materias_aprobadas:
                        self.materias_aprobadas.add(requerido)
                        pendientes.append(requerido)
        else:
            self.materias_aprobadas.difference_update(codigos)
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
                "Obligatorias",
                "Optativas",
                "Nivelación",
                "Trabajo de grado (P)",
                "Otros",
            )
            for tipo in orden_tipos[:2]:
                materias_tipo = grupos_por_tipo.get(tipo, [])
                if not materias_tipo:
                    continue
                familias = {
                    familia: [materia for materia in materias_tipo if subtipo_materia(materia) == familia]
                    for familia in ("FUNDAMENTACIÓN", "DISCIPLINARES")
                }
                self.agregar_seccion_compuesta(
                    contenedor,
                    tipo.upper(),
                    familias,
                    "principal",
                    recomendadas=self.codigos_recomendados,
                )
            for tipo in orden_tipos[2:]:
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

    def agregar_seccion_compuesta(
        self, contenedor, titulo, familias, origen, recomendadas=None
    ):
        """Crea una sección principal con subdesplegables curriculares."""
        if not any(familias.values()):
            return
        expandida = self.secciones_expandida.get(titulo, self.todas_secciones_expandidas)
        # Conserva el estado inicial para que el filtro no interprete la
        # sección como contraída hasta que el usuario la cambie manualmente.
        self.secciones_expandida.setdefault(titulo, expandida)
        encabezado = QPushButton(f"▾  {titulo}" if expandida else f"▸  {titulo}")
        encabezado.setProperty("titulo_seccion", titulo)
        encabezado.setCheckable(True)
        encabezado.setChecked(expandida)
        encabezado.setCursor(Qt.PointingHandCursor)
        encabezado.setMinimumHeight(27)
        fuente_encabezado = encabezado.font()
        fuente_encabezado.setPointSize(10)
        fuente_encabezado.setBold(True)
        encabezado.setFont(fuente_encabezado)
        encabezado.setStyleSheet(
            f"QPushButton {{ background-color: transparent; color: {COLOR_TEXTO_SECUNDARIO}; "
            f"border: none; border-radius: 5px; padding: 6px 8px; text-align: left; "
            "}"
            f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; color: {COLOR_TEXTO}; }}"
        )
        contenedor.layout().addWidget(encabezado)
        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: transparent;")
        cuerpo_layout = QVBoxLayout(cuerpo)
        cuerpo_layout.setContentsMargins(8, 0, 0, 3)
        cuerpo_layout.setSpacing(3)
        for familia in ("FUNDAMENTACIÓN", "DISCIPLINARES"):
            materias = familias.get(familia, [])
            if not materias:
                continue
            self.agregar_seccion_asignaturas(
                cuerpo,
                f"{titulo} · {familia}",
                materias,
                origen,
                COLOR_VERDE if any(
                    codigo_base(materia.get("codigo")) in self.codigos_recomendados
                    for materia in materias
                ) else None,
                recomendadas=recomendadas,
            )
        contenedor.layout().addWidget(cuerpo)
        # Añadir primero al árbol de widgets y ocultar después evita que Qt
        # vuelva a mostrar el cuerpo al reparenterarlo en el layout.
        cuerpo.setVisible(expandida)
        self._secciones_asignaturas[titulo] = (encabezado, cuerpo)

        def alternar(estado):
            self.secciones_expandida[titulo] = bool(estado)
            cuerpo.setVisible(bool(estado))
            encabezado.setText(f"▾  {titulo}" if estado else f"▸  {titulo}")

        encabezado.toggled.connect(alternar)

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
        self.secciones_expandida.setdefault(clave, expandida)
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
        contenedor.layout().addWidget(cuerpo)
        # El estado visual debe aplicarse después de insertarlo en el layout;
        # de lo contrario Qt puede mostrarlo al cambiarle el padre.
        cuerpo.setVisible(expandida)
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
        if motivo and not seleccionada:
            boton.setText(f"{texto}\nNo disponible: {motivo}")
            boton.setEnabled(False)
            boton.setStyleSheet(estilo_tarjeta_no_disponible())
            return boton
        avisos = advertencias_materia(
            materia,
            self.materias_aprobadas,
            {codigo_base(referencia.get("codigo")) for referencia in self.referencias},
        )
        if avisos:
            boton.setToolTip("\n".join(avisos))
            boton.setStyleSheet(
                f"QPushButton {{ background-color: transparent; color: {COLOR_TEXTO}; "
                f"border: 1px solid {COLOR_AMARILLO}; border-radius: 6px; padding: 7px 8px; "
                "text-align: left; font-size: 11px; }"
                f"QPushButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; }}"
            )
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
            superposicion = QGridLayout(contenedor)
            superposicion.setContentsMargins(0, 0, 0, 0)
            superposicion.addWidget(boton, 0, 0)
            boton.setStyleSheet(
                f"""QPushButton {{ background-color: {fondo}; color: {COLOR_TEXTO};
                border: 1px solid {borde}; border-radius: 6px;
                padding: 7px 32px 7px 8px; text-align: left; font-size: 11px; }}
                QPushButton:hover {{ border-color: {COLOR_VERDE};
                background-color: {COLOR_SUPERFICIE_CLARA}; }}"""
            )
            quitar = QPushButton("×", contenedor)
            quitar.setObjectName("quitarMateriaSeleccionada")
            quitar.setToolTip("Quitar del horario")
            quitar.setCursor(Qt.PointingHandCursor)
            quitar.setFixedSize(22, 22)
            quitar.setStyleSheet(
                f"QPushButton {{ background-color: {COLOR_SUPERFICIE}; color: {COLOR_TEXTO}; "
                f"border: 1px solid {COLOR_LINEA}; border-radius: 4px; "
                "font-size: 16px; padding: 0; }"
                f"QPushButton:hover {{ border-color: {COLOR_ROJO}; color: {COLOR_ROJO}; }}"
            )
            superposicion.addWidget(
                quitar, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
            )
            quitar.clicked.connect(
                lambda _, ref=referencia: self.quitar_grupo(ref) if ref else None
            )
            boton.clicked.connect(
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
        """Devuelve las materias no disponibles que coinciden con la búsqueda."""
        seleccionadas = {
            codigo_base(referencia.get("codigo")) for referencia in self.referencias
        }
        codigos_en_oferta = {
            codigo_base(materia.get("codigo"))
            for materias in self.materias_por_origen.values()
            for materia in materias
        }
        plan = self.planes.get(self.codigo_plan)
        nombres_plan = getattr(plan, "nombres_asignaturas", {}) or {}
        materias_locales = self.materias_locales or {}
        locales_por_codigo = {
            codigo_base(materia.get("codigo", codigo)): materia
            for codigo, materia in materias_locales.items()
            if isinstance(materia, dict)
        }
        adicionales = []
        for codigo in self.materias_aprobadas - codigos_en_oferta:
            materia = dict(locales_por_codigo.get(codigo, {}))
            materia.setdefault("codigo", codigo)
            materia.setdefault(
                "nombre",
                nombres_plan.get(codigo) or nombres_plan.get(str(codigo)) or f"Materia {codigo}",
            )
            tipo = str(materia.get("tipologia", materia.get("tipo", ""))).casefold()
            origen = "libre" if "libre" in tipo else "principal"
            adicionales.append({"materia": materia, "origen": origen})
        return buscar_materias_no_disponibles(
            self.materias_por_origen,
            self.buscar_asignaturas.text(),
            self.materias_aprobadas,
            seleccionadas,
            adicionales,
        )

    def _actualizar_seccion_no_disponibles(self, contenedor):
        """Reconstruye la categoría de resultados no disponibles en cada búsqueda."""
        titulo = "NO DISPONIBLES · revisa el motivo"
        anterior = self._secciones_asignaturas.pop(titulo, None)
        if anterior:
            for widget in anterior:
                contenedor.layout().removeWidget(widget)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        resultados = self.materias_bloqueadas_buscadas()
        if not resultados:
            return
        materias = [resultado["materia"] for resultado in resultados]
        origenes = {
            codigo_base(resultado["materia"].get("codigo")): resultado["origen"]
            for resultado in resultados
        }
        self.agregar_seccion_asignaturas(
            contenedor,
            titulo,
            materias,
            "principal",
            COLOR_ROJO,
            origen_por_codigo=origenes,
        )

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
        contenedor = self.lista_asignaturas.widget()
        if contenedor is not None and hasattr(self, "_secciones_asignaturas"):
            self._actualizar_seccion_no_disponibles(contenedor)
        for clave, (encabezado, cuerpo) in self._secciones_asignaturas.items():
            # Obligatorias y Optativas son contenedores: sus hijos son
            # encabezados y cuerpos, no tarjetas de materias. Si se recorren
            # aquí, el filtro vuelve a mostrar los cuerpos cerrados al tratar
            # sus widgets internos como coincidencias.
            if clave in ("OBLIGATORIAS", "OPTATIVAS"):
                continue
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
        # Las secciones de Obligatorias y Optativas contienen otras dos
        # secciones. Su visibilidad debe depender de esas subsecciones, no
        # de los widgets de nivel intermedio que no tienen texto de búsqueda.
        for clave in ("OBLIGATORIAS", "OPTATIVAS"):
            entrada = self._secciones_asignaturas.get(clave)
            if not entrada:
                continue
            encabezado, cuerpo = entrada
            hijas = [
                valor for nombre, valor in self._secciones_asignaturas.items()
                if nombre.startswith(clave + " · ")
            ]
            # isVisible() también depende de que el cuerpo exterior esté
            # expandido; para decidir si el encabezado debe existir usamos
            # isHidden(), que refleja el resultado del filtro real.
            visible = any(not hija[0].isHidden() for hija in hijas)
            encabezado.setVisible(visible)
            cuerpo.setVisible(
                visible and (bool(consulta) or self.secciones_expandida.get(clave, False))
            )

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
        dialogo.setMinimumWidth(320)
        dialogo.setMinimumHeight(460)
        dialogo.resize(440, 520)
        dialogo.setStyleSheet(
            f"""QDialog {{ background-color: {COLOR_SUPERFICIE}; }}
            QLabel {{ color: {COLOR_TEXTO}; }}
            QScrollArea {{ border: none; background: transparent; }}"""
        )
        principal = QVBoxLayout(dialogo)
        principal.setContentsMargins(20, 18, 12, 18)
        titulo = QLabel(materia.get("nombre", "Materia"))
        titulo.setWordWrap(True)
        titulo.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {COLOR_TEXTO};")
        principal.addWidget(titulo)
        datos = QLabel(
            f"Código {materia.get('codigo', '')} · {materia.get('creditos', '?')} créditos\n"
            f"{materia.get('tipologia', 'Tipología no disponible')}"
        )
        datos.setWordWrap(True)
        datos.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        principal.addWidget(datos)
        area = self.crear_area_desplazable()
        contenido = area.widget()
        descripcion = str(materia.get("descripcion", "")).strip()
        if descripcion:
            desplegable_descripcion = QToolButton()
            desplegable_descripcion.setObjectName("desplegableDescripcionMateria")
            desplegable_descripcion.setText("▸  DESCRIPCIÓN")
            desplegable_descripcion.setCheckable(True)
            desplegable_descripcion.setArrowType(Qt.ArrowType.NoArrow)
            desplegable_descripcion.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            desplegable_descripcion.setCursor(Qt.CursorShape.PointingHandCursor)
            desplegable_descripcion.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            desplegable_descripcion.setMinimumWidth(0)
            desplegable_descripcion.setStyleSheet(
                f"QToolButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
                f"color: {COLOR_TEXTO}; border: 1px solid {COLOR_LINEA}; "
                "border-radius: 5px; padding: 6px; text-align: left; }"
            )
            contenido.layout().addWidget(desplegable_descripcion)
            cuerpo_descripcion = QWidget()
            cuerpo_descripcion.setObjectName("contenidoDescripcionMateria")
            disposicion_descripcion = QVBoxLayout(cuerpo_descripcion)
            disposicion_descripcion.setContentsMargins(8, 0, 8, 6)
            etiqueta_descripcion = QLabel(descripcion)
            etiqueta_descripcion.setWordWrap(True)
            etiqueta_descripcion.setStyleSheet(
                f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 12px;"
            )
            disposicion_descripcion.addWidget(etiqueta_descripcion)
            contenido.layout().addWidget(cuerpo_descripcion)
            cuerpo_descripcion.setVisible(False)

            def alternar_descripcion(expandida):
                cuerpo_descripcion.setVisible(expandida)
                desplegable_descripcion.setText(
                    "▾  DESCRIPCIÓN" if expandida else "▸  DESCRIPCIÓN"
                )

            desplegable_descripcion.toggled.connect(alternar_descripcion)
        prerrequisitos = materia.get("prerrequisitos", [])
        if prerrequisitos:
            lineas_prerrequisitos = []
            for requisito in prerrequisitos:
                if isinstance(requisito, dict):
                    tipo = str(requisito.get("tipo") or "?").strip().upper()
                    codigo = str(requisito.get("codigo") or "").strip()
                    nombre = str(requisito.get("nombre") or codigo or "Requisito")
                    lineas_prerrequisitos.append(
                        f"{tipo} · {nombre} ({codigo}): {descripcion_tipo(tipo)}"
                    )
                else:
                    lineas_prerrequisitos.append(str(requisito))
            texto_prerrequisitos = "\n".join(lineas_prerrequisitos)
            desplegable_prerrequisitos = QToolButton()
            desplegable_prerrequisitos.setObjectName("desplegablePrerrequisitosMateria")
            desplegable_prerrequisitos.setText("▸  PRERREQUISITOS")
            desplegable_prerrequisitos.setCheckable(True)
            desplegable_prerrequisitos.setArrowType(Qt.ArrowType.NoArrow)
            desplegable_prerrequisitos.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            desplegable_prerrequisitos.setCursor(Qt.CursorShape.PointingHandCursor)
            desplegable_prerrequisitos.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            desplegable_prerrequisitos.setMinimumWidth(0)
            desplegable_prerrequisitos.setStyleSheet(
                f"QToolButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
                f"color: {COLOR_TEXTO}; border: 1px solid {COLOR_LINEA}; "
                "border-radius: 5px; padding: 6px; text-align: left; }"
            )
            contenido.layout().addWidget(desplegable_prerrequisitos)
            cuerpo_prerrequisitos = QWidget()
            cuerpo_prerrequisitos.setObjectName("contenidoPrerrequisitosMateria")
            disposicion_prerrequisitos = QVBoxLayout(cuerpo_prerrequisitos)
            disposicion_prerrequisitos.setContentsMargins(8, 0, 8, 6)
            etiqueta_prerrequisitos = QLabel(texto_prerrequisitos)
            etiqueta_prerrequisitos.setWordWrap(True)
            etiqueta_prerrequisitos.setStyleSheet(
                f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;"
            )
            disposicion_prerrequisitos.addWidget(etiqueta_prerrequisitos)
            contenido.layout().addWidget(cuerpo_prerrequisitos)
            cuerpo_prerrequisitos.setVisible(False)

            def alternar_prerrequisitos(expandido):
                cuerpo_prerrequisitos.setVisible(expandido)
                desplegable_prerrequisitos.setText(
                    "▾  PRERREQUISITOS" if expandido else "▸  PRERREQUISITOS"
                )

            desplegable_prerrequisitos.toggled.connect(alternar_prerrequisitos)
        grupos_titulo = QLabel("GRUPOS")
        grupos_titulo.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px; font-weight: 700; padding-top: 8px;"
        )
        contenido.layout().addWidget(grupos_titulo)
        grupos = sorted(materia.get("grupos", []), key=clave_orden_grupo)
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
        centrar_contenido_si_no_hay_barra(area, principal, 12, 16)
        cerrar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        cerrar.rejected.connect(dialogo.reject)
        principal.addWidget(cerrar)
        preparar_dialogo_sin_barra(dialogo, principal)
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
        boton = BotonGrupoHorario(texto, grupo)
        boton.cursor_entro.connect(self.cuadricula.previsualizar_grupo)
        boton.cursor_salio.connect(self.cuadricula.programar_limpieza_previsualizacion)
        if not dialogo.property("limpiar_previsualizacion_grupo_conectado"):
            dialogo.setProperty("limpiar_previsualizacion_grupo_conectado", True)
            dialogo.finished.connect(self.cuadricula.limpiar_previsualizacion_grupo)
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
        color_fondo = COLOR_AMARILLO_FONDO if motivo == "Sin cupos disponibles" else COLOR_VERDE_FONDO
        color_borde = COLOR_AMARILLO if motivo == "Sin cupos disponibles" else COLOR_VERDE
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
        """Destaca el grupo rechazado con tres parpadeos, sin añadirlo al horario."""
        conflictos = self.detalles_conflicto_grupo(grupo)
        if not conflictos:
            return
        self.previsualizar_grupo_no_disponible(
            materia, grupo, " | ".join(conflictos), dialogo
        )

    def previsualizar_grupo_no_disponible(self, materia, grupo, motivo, dialogo=None):
        """Parpadea tres veces el grupo, aunque la causa sea la franja elegida."""
        self.temporizador_previsualizacion.stop()
        self.grupo_previsualizado = (materia, grupo)
        self.previsualizacion_resaltada = True
        self.parpadeos_previsualizacion_restantes = 6
        self._actualizar_cuadricula_previsualizada()
        self.resumen.setText(
            "PREVISUALIZACIÓN · " + motivo +
            " · El grupo no se añadió al horario; parpadea 3 veces."
        )
        if dialogo is not None:
            dialogo.accept()
        self.temporizador_previsualizacion.start()

    def _actualizar_cuadricula_previsualizada(self):
        if self.grupo_previsualizado is None:
            return
        grupos = self.grupos_actuales() + [self.grupo_previsualizado]
        resaltados = [self.grupo_previsualizado] if self.previsualizacion_resaltada else []
        self.cuadricula.actualizar(grupos, grupos_previsualizados=resaltados)

    def _alternar_parpadeo_previsualizacion(self):
        if self.grupo_previsualizado is None:
            self.temporizador_previsualizacion.stop()
            return
        self.parpadeos_previsualizacion_restantes -= 1
        if self.parpadeos_previsualizacion_restantes <= 0:
            self.limpiar_previsualizacion()
            return
        self.previsualizacion_resaltada = not self.previsualizacion_resaltada
        self._actualizar_cuadricula_previsualizada()

    def limpiar_previsualizacion(self):
        self.temporizador_previsualizacion.stop()
        if self.grupo_previsualizado is None:
            return
        self.grupo_previsualizado = None
        self.previsualizacion_resaltada = False
        self.parpadeos_previsualizacion_restantes = 0
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
        preparar_dialogo_sin_barra(dialogo, layout)
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
        dialogo.setMinimumWidth(320)
        dialogo.resize(440, 520)
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
            columna = QVBoxLayout(tarjeta)
            columna.setContentsMargins(10, 8, 10, 8)
            columna.setSpacing(6)
            info = QLabel(f"{materia.get('nombre', '')}\n{materia.get('codigo', '')}")
            info.setWordWrap(True)
            columna.addWidget(info)
            opciones = QComboBox()
            opciones.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            opciones.setMinimumWidth(0)
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
            opciones.setToolTip(opciones.currentText())
            opciones.currentTextChanged.connect(opciones.setToolTip)
            columna.addWidget(opciones)
            acciones = QHBoxLayout()
            acciones.setContentsMargins(0, 0, 0, 0)
            acciones.addStretch(1)
            aplicar = QPushButton("Aplicar")
            aplicar.clicked.connect(
                lambda _, r=referencia, m=materia, c=opciones, d=dialogo:
                self.aplicar_cambio_grupo(r, m, c, d)
            )
            acciones.addWidget(aplicar)
            quitar = QPushButton("Quitar")
            quitar.setStyleSheet(f"QPushButton {{ color: {COLOR_ROJO}; }}")
            quitar.clicked.connect(
                lambda _, r=referencia, d=dialogo: self.quitar_desde_editor(r, d)
            )
            acciones.addWidget(quitar)
            columna.addLayout(acciones)
            contenido.layout().addWidget(tarjeta)
        contenido.layout().addStretch()
        principal.addWidget(area, 1)
        cerrar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        cerrar.rejected.connect(dialogo.reject)
        principal.addWidget(cerrar)
        preparar_dialogo_sin_barra(dialogo, principal)
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
        grupos_actuales = self.grupos_actuales()
        principales_bloqueados = grupos_en_conflicto_en_bloque(
            [materia for materia in self.materias_para_mostrar.get("principal", [])
             if not self.materia_ya_seleccionada(materia)],
            grupos_actuales, dia, hora, duracion,
        )
        libres_bloqueados = grupos_en_conflicto_en_bloque(
            [materia for materia in self.materias_para_mostrar.get("libre", [])
             if not self.materia_ya_seleccionada(materia)],
            grupos_actuales, dia, hora, duracion,
        )
        catalogo_principal = self.catalogo_buscable_en_bloque("principal")
        catalogo_libre = self.catalogo_buscable_en_bloque("libre")
        if not catalogo_principal and not catalogo_libre:
            QMessageBox.information(
                self,
                "Sin grupos disponibles",
                "Todavía no hay materias en el catálogo para buscar en esta franja."
            )
            return

        nombre_dia = dict(DIAS).get(dia, dia.title())
        menu = QMenu(self)
        menu.setObjectName("menuOrigenGruposBloque")
        menu.setStyleSheet(
            f"QMenu {{ background-color: {COLOR_SUPERFICIE}; "
            f"border: 1px solid {COLOR_LINEA}; }}"
        )
        panel = QWidget(menu)
        panel.setStyleSheet(f"background-color: {COLOR_SUPERFICIE};")
        opciones = QVBoxLayout(panel)
        opciones.setContentsMargins(10, 10, 10, 10)
        opciones.setSpacing(6)
        encabezado = QLabel(f"{nombre_dia.upper()} · {hora:02d}:00–{hora + duracion:02d}:00")
        encabezado.setStyleSheet(
            f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 10px; font-weight: 700; "
            "padding: 0 3px 3px;"
        )
        opciones.addWidget(encabezado)

        def agregar_opcion(origen, titulo, disponibles, bloqueados, catalogo):
            materias_bloqueadas = {
                str(materia.get("codigo") or materia.get("nombre") or id(materia))
                for materia, _ in bloqueados
            }
            if catalogo:
                resumen = (
                    f"{len(disponibles)} grupos en esta franja · "
                    f"{len(materias_bloqueadas)} materias con cruces"
                )
            else:
                resumen = "Catálogo aún no disponible"
            boton = QPushButton(f"{titulo}\n{resumen}")
            boton.setObjectName(f"elegirOrigenGrupos_{origen}")
            boton.setEnabled(bool(catalogo))
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setMinimumWidth(310)
            boton.setStyleSheet(
                f"QPushButton {{ background-color: {COLOR_SUPERFICIE_CLARA}; "
                f"color: {COLOR_TEXTO}; border: 1px solid {COLOR_LINEA}; "
                "border-radius: 6px; padding: 10px 12px; text-align: left; } "
                f"QPushButton:hover {{ border-color: {COLOR_VERDE}; "
                f"background-color: {COLOR_VERDE_FONDO}; }} "
                f"QPushButton:disabled {{ color: {COLOR_TEXTO_SECUNDARIO}; "
                f"background-color: {COLOR_FONDO}; }}"
            )

            def abrir():
                menu.hide()
                self.mostrar_grupos_por_origen_en_bloque(
                    origen, dia, hora, duracion, disponibles, bloqueados
                )

            boton.clicked.connect(abrir)
            opciones.addWidget(boton)

        agregar_opcion(
            "principal", "Obligatorias y optativas", principales,
            principales_bloqueados, catalogo_principal,
        )
        agregar_opcion("libre", "Libre elección", libres, libres_bloqueados, catalogo_libre)
        accion_panel = QWidgetAction(menu)
        accion_panel.setDefaultWidget(panel)
        menu.addAction(accion_panel)
        menu.exec(QCursor.pos())

    def catalogo_buscable_en_bloque(self, origen):
        """Incluye materias conocidas sin grupos, sin duplicar las ofertadas."""
        por_codigo = {}
        if origen == "principal":
            for codigo, materia in (self.materias_locales or {}).items():
                if isinstance(materia, dict):
                    por_codigo[codigo_base(materia.get("codigo", codigo))] = materia
        for materia in self.materias_por_origen.get(origen, []):
            por_codigo[codigo_base(materia.get("codigo"))] = materia
        return [materia for codigo, materia in por_codigo.items() if codigo]

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

    def mostrar_grupos_por_origen_en_bloque(
        self, origen, dia, hora, duracion, candidatos, grupos_bloqueados=()
    ):
        """Lista solo los grupos del origen elegido que coinciden con la celda."""
        nombre_origen = "Obligatorias y optativas" if origen == "principal" else "Libre elección"
        nombre_dia = dict(DIAS).get(dia, dia.title())
        dialogo = QDialog(self)
        dialogo.setObjectName("dialogoGruposBloque")
        dialogo.setWindowTitle(
            f"{nombre_origen} · {nombre_dia} {hora:02d}:00–{hora + duracion:02d}:00"
        )
        dialogo.setMinimumWidth(320)
        dialogo.setMinimumHeight(420)
        dialogo.resize(440, 520)
        dialogo.setStyleSheet(
            f"""QDialog {{ background-color: {COLOR_SUPERFICIE}; }}
            QLabel {{ color: {COLOR_TEXTO}; }}
            QScrollArea {{ border: none; background: transparent; }}"""
        )
        principal = QVBoxLayout(dialogo)
        principal.setContentsMargins(20, 18, 8, 18)
        titulo = QLabel(nombre_origen)
        titulo.setStyleSheet(f"color: {COLOR_TEXTO}; font-size: 20px; font-weight: 800;")
        principal.addWidget(titulo)
        descripcion = QLabel(
            f"Grupos con clase el {nombre_dia.lower()} entre las {hora:02d}:00 y "
            f"las {hora + duracion:02d}:00. "
            "Busca una materia para ver todos sus grupos: los aptos aparecen arriba "
            "y los demás en No Disponibles con su motivo."
        )
        descripcion.setWordWrap(True)
        descripcion.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; font-size: 11px;")
        principal.addWidget(descripcion)
        buscador = QLineEdit()
        buscador.setObjectName("buscarMateriaBloque")
        buscador.setPlaceholderText("Buscar materia por nombre o código, incluso si no está disponible…")
        buscador.setClearButtonEnabled(True)
        buscador.setStyleSheet(
            f"QLineEdit {{ background-color: {COLOR_FONDO}; color: {COLOR_TEXTO}; "
            f"border: 1px solid {COLOR_LINEA}; border-radius: 6px; padding: 8px; }} "
            f"QLineEdit:focus {{ border-color: {COLOR_VERDE}; }}"
        )
        principal.addWidget(buscador)
        area = self.crear_area_desplazable()
        contenido = area.widget()
        cuerpo_disponibles = QWidget()
        cuerpo_disponibles.setObjectName("gruposDisponiblesBloque")
        layout_disponibles = QVBoxLayout(cuerpo_disponibles)
        layout_disponibles.setContentsMargins(0, 0, 0, 0)
        layout_disponibles.setSpacing(6)
        contenido.layout().addWidget(cuerpo_disponibles)
        por_materia = {}
        for materia, grupo in candidatos:
            clave = str(materia.get("codigo", ""))
            por_materia.setdefault(clave, {"materia": materia, "grupos": []})["grupos"].append(grupo)

        def mostrar_disponibles(entradas, consulta, hay_coincidencias):
            limpiar_layout(layout_disponibles)
            if not entradas:
                if consulta and not hay_coincidencias:
                    texto_mensaje = "No se encontró ninguna materia con ese nombre o código."
                elif consulta:
                    texto_mensaje = "No hay grupos aptos en esta franja. Consulta No Disponibles."
                else:
                    texto_mensaje = "No hay grupos aptos en esta franja. Puedes buscar otras materias."
                mensaje = QLabel(texto_mensaje)
                mensaje.setStyleSheet(f"color: {COLOR_TEXTO_SECUNDARIO}; padding: 8px;")
                layout_disponibles.addWidget(mensaje)
            for entrada in sorted(
                entradas, key=lambda actual: clave_alfabetica(actual["materia"].get("nombre", ""))
            ):
                materia = entrada["materia"]
                tarjeta = QFrame()
                tarjeta.setObjectName("tarjetaDisponibleBloque")
                tarjeta.setStyleSheet(
                    f"background-color: {COLOR_SUPERFICIE_CLARA}; "
                    f"border: 1px solid {COLOR_LINEA}; border-radius: 7px;"
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
                for grupo in sorted(entrada["grupos"], key=clave_orden_grupo):
                    layout.addWidget(self.crear_boton_grupo(origen, materia, grupo, dialogo, False))
                layout_disponibles.addWidget(tarjeta)

        bloqueados_por_materia = {}
        for materia, grupo in grupos_bloqueados:
            clave = str(materia.get("codigo") or materia.get("nombre") or id(materia))
            bloqueados_por_materia.setdefault(
                clave, {"materia": materia, "grupos": []}
            )["grupos"].append(grupo)
        boton_no_disponibles = QToolButton()
        boton_no_disponibles.setObjectName("seccionNoDisponiblesBloque")
        boton_no_disponibles.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        boton_no_disponibles.setMinimumWidth(0)
        boton_no_disponibles.setCheckable(True)
        boton_no_disponibles.setChecked(False)
        boton_no_disponibles.setArrowType(Qt.ArrowType.RightArrow)
        boton_no_disponibles.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        boton_no_disponibles.setCursor(Qt.PointingHandCursor)
        boton_no_disponibles.setStyleSheet(
            f"QToolButton {{ color: {COLOR_ROJO}; background-color: {COLOR_ROJO_FONDO}; "
            f"border: 1px solid {COLOR_ROJO}; border-radius: 7px; padding: 9px; "
            "font-weight: 700; text-align: left; } "
            f"QToolButton:hover {{ background-color: {COLOR_SUPERFICIE_CLARA}; }}"
        )
        contenido.layout().addWidget(boton_no_disponibles)
        cuerpo_no_disponibles = QWidget()
        cuerpo_no_disponibles.setObjectName("gruposNoDisponiblesBloque")
        layout_no_disponibles = QVBoxLayout(cuerpo_no_disponibles)
        layout_no_disponibles.setContentsMargins(4, 4, 4, 4)
        layout_no_disponibles.setSpacing(6)
        cuerpo_no_disponibles.setVisible(False)
        contenido.layout().addWidget(cuerpo_no_disponibles)

        def actualizar_seccion_no_disponibles(expandida):
            cuerpo_no_disponibles.setVisible(expandida)
            boton_no_disponibles.setArrowType(
                Qt.ArrowType.DownArrow if expandida else Qt.ArrowType.RightArrow
            )

        boton_no_disponibles.toggled.connect(actualizar_seccion_no_disponibles)

        catalogo = self.catalogo_buscable_en_bloque(origen)

        def actualizar_busqueda(texto):
            consulta = texto.strip()
            if consulta:
                resultados = buscar_grupos_en_bloque(
                    catalogo, consulta, dia, hora, duracion,
                    self.materias_aprobadas,
                    {codigo_base(ref.get("codigo")) for ref in self.referencias},
                    self.grupos_actuales(),
                )
                disponibles = [
                    {"materia": entrada["materia"], "grupos": entrada["disponibles"]}
                    for entrada in resultados if entrada["disponibles"]
                ]
                no_disponibles = [
                    {"materia": entrada["materia"], **grupo}
                    for entrada in resultados for grupo in entrada["no_disponibles"]
                ]
            else:
                disponibles = list(por_materia.values())
                no_disponibles = [
                    {"materia": entrada["materia"], "grupo": grupo,
                     "motivo": "Conflicto de horario"}
                    for entrada in sorted(
                        bloqueados_por_materia.values(),
                        key=lambda actual: clave_alfabetica(actual["materia"].get("nombre", "")),
                    )
                    for grupo in entrada["grupos"]
                ]
            mostrar_disponibles(disponibles, consulta, bool(disponibles or no_disponibles))
            limpiar_layout(layout_no_disponibles)
            for entrada in no_disponibles:
                materia = entrada["materia"]
                grupo = entrada["grupo"]
                motivo = entrada["motivo"]
                if grupo is not None:
                    conflictos = self.detalles_conflicto_grupo(grupo)
                    if conflictos:
                        motivo = motivo.replace("Conflicto de horario", "; ".join(conflictos))
                lineas = [str(materia.get("nombre") or "Materia"), str(materia.get("codigo") or "")]
                if grupo is not None:
                    lineas[1] += f" · Grupo {grupo.get('numero', '?')}"
                    lineas.append(texto_horarios(grupo))
                lineas.append(f"No disponible: {motivo}")
                tarjeta = BotonTextoAjustable("\n".join(lineas))
                tarjeta.setObjectName("tarjetaNoDisponibleBloque")
                tarjeta.setStyleSheet(estilo_tarjeta_no_disponible())
                tarjeta.setToolTip(
                    "Haz clic para previsualizar este grupo sin modificar tu horario."
                    if grupo else "No hay un grupo que se pueda previsualizar."
                )
                if grupo is not None:
                    tarjeta.setCursor(Qt.PointingHandCursor)
                    tarjeta.clicked.connect(
                        lambda _, m=materia, g=grupo, razon=motivo, d=dialogo:
                        self.previsualizar_grupo_no_disponible(m, g, razon, d)
                    )
                else:
                    tarjeta.setEnabled(False)
                layout_no_disponibles.addWidget(tarjeta)
            boton_no_disponibles.setText(f"No Disponibles ({len(no_disponibles)})")
            boton_no_disponibles.setVisible(bool(no_disponibles))
            boton_no_disponibles.setChecked(bool(consulta and no_disponibles))

        buscador.textChanged.connect(actualizar_busqueda)
        actualizar_busqueda("")
        contenido.layout().addStretch()
        principal.addWidget(area, 1)
        centrar_contenido_si_no_hay_barra(area, principal, 8, 12)
        cerrar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        cerrar.rejected.connect(dialogo.reject)
        principal.addWidget(cerrar)
        preparar_dialogo_sin_barra(dialogo, principal)
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
        """Consulta y descarga en segundo plano sin cambiar el cursor global."""
        self._iniciar_comprobacion_version(desde_arranque=False)

    def _iniciar_comprobacion_version(self, desde_arranque):
        if getattr(self, "instalando_version", False):
            return
        self.instalando_version = True
        self.comprobacion_version_pendiente = desde_arranque
        self.actualizacion_desde_arranque = desde_arranque
        trabajador = TrabajadorVersion(parent=self)
        self.trabajador_version = trabajador
        trabajador.consultada.connect(self._version_consultada)
        trabajador.fallo.connect(self._fallo_version)
        trabajador.finished.connect(trabajador.deleteLater)
        trabajador.start()

    def _version_consultada(self, release):
        self.comprobacion_version_pendiente = False
        from servicios.actualizacion_aplicacion import hay_actualizacion

        if release.get("sin_paquete_compatible"):
            self.instalando_version = False
            if self.actualizacion_desde_arranque:
                self.continuar_arranque()
            else:
                QMessageBox.information(
                    self, "Versiones compatibles",
                    "Todavía no hay una versión publicada para este sistema y arquitectura. "
                    "Puedes seguir usando la versión instalada.",
                )
            return
        if not hay_actualizacion(release):
            self.instalando_version = False
            if self.actualizacion_desde_arranque:
                self.continuar_arranque()
            else:
                QMessageBox.information(self, "Fénix actualizado", f"Ya tienes Fénix {VERSION}.")
            return
        if release.get("instalacion_manual"):
            instrucciones = (
                "Cuando termine la descarga, cierra Fénix y extrae el paquete tar.gz "
                "en una carpeta nueva. Abre el ejecutable Fenix de esa carpeta. "
                if sys.platform == "linux" else
                "Cuando termine la descarga, cierra Fénix y reemplaza Fenix.app en Aplicaciones. "
            )
            respuesta = QMessageBox.question(
                self, "Actualización disponible",
                f"Está disponible Fénix {release['version']}. ¿Abrir su descarga?\n\n"
                + instrucciones + "Tu perfil y horario se conservan.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            self.instalando_version = False
            if respuesta == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(release["url"]))
            if self.actualizacion_desde_arranque:
                self.continuar_arranque()
            return
        respuesta = QMessageBox.question(
            self,
            "Actualización disponible",
            f"Está disponible Fénix {release['version']}. ¿Descargarla y reiniciar ahora?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            self.instalando_version = False
            if self.actualizacion_desde_arranque:
                self.continuar_arranque()
            return
        self.dialogo_progreso_version = DialogoProgresoVersion(self)
        self.dialogo_progreso_version.show()
        trabajador = TrabajadorVersion(release=release, parent=self)
        self.trabajador_version = trabajador
        trabajador.progreso_descarga.connect(self.dialogo_progreso_version.actualizar_descarga)
        trabajador.descargada.connect(self._version_descargada)
        trabajador.fallo.connect(self._fallo_version)
        trabajador.finished.connect(trabajador.deleteLater)
        trabajador.start()

    def _version_descargada(self, paquete):
        if getattr(self, "dialogo_progreso_version", None) is not None:
            self.dialogo_progreso_version.close()
            self.dialogo_progreso_version = None
        try:
            from servicios.actualizacion_aplicacion import iniciar_reemplazo

            self.detener_actualizacion()
            iniciar_reemplazo(paquete, os.getpid())
            QApplication.quit()
        except Exception as error:
            self._fallo_version(str(error))

    def _fallo_version(self, mensaje):
        if getattr(self, "dialogo_progreso_version", None) is not None:
            self.dialogo_progreso_version.close()
            self.dialogo_progreso_version = None
        self.comprobacion_version_pendiente = False
        self.instalando_version = False
        if self.actualizacion_desde_arranque:
            logging.getLogger("fenix").warning("No se pudo preparar la actualización: %s", mensaje)
            respuesta = QMessageBox.question(
                self,
                "No se pudo verificar Fénix",
                "No fue posible comprobar o descargar una versión nueva. "
                "¿Quieres continuar e iniciar la actualización de datos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if respuesta == QMessageBox.StandardButton.Yes:
                self.continuar_arranque()
            else:
                QApplication.quit()
        else:
            QMessageBox.critical(self, "No se pudo actualizar Fénix", mensaje)

    def comprobar_version_antes_de_workers(self):
        """Autoriza el arranque solo después de revisar la versión de Fénix."""
        if self.arranque_autorizado or self.comprobacion_version_pendiente or getattr(self, "instalando_version", False):
            return
        self._iniciar_comprobacion_version(desde_arranque=True)

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
            self.indicador_carga.show()
            if not self.temporizador_animacion_carga.isActive():
                self.temporizador_animacion_carga.start()
        elif estado == "completada":
            color = COLOR_VERDE
            self.barra_progreso.setValue(100)
            self.barra_progreso.setFormat("100%")
            self.indicador_carga.hide()
            self.temporizador_animacion_carga.stop()
        elif estado == "error":
            color = COLOR_ROJO
            self.barra_progreso.setValue(0)
            self.barra_progreso.setFormat("Error")
            self.indicador_carga.hide()
            self.temporizador_animacion_carga.stop()
        else:
            color = COLOR_TEXTO_SECUNDARIO
            self.barra_progreso.setValue(0)
            self.barra_progreso.setFormat("Pendiente")
            self.indicador_carga.hide()
            self.temporizador_animacion_carga.stop()
        self.etiqueta_estado.setText(mensaje)
        self.etiqueta_estado.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.barra_progreso.setStyleSheet(
            f"""QProgressBar {{ color: {COLOR_TEXTO}; background-color: {COLOR_BARRA}; border: 1px solid {COLOR_LINEA};
            border-radius: 5px; text-align: center; font-size: 10px; }}
            QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}"""
        )
        self.boton_actualizar.setEnabled(estado != "actualizando")

    def animar_actualizacion(self):
        """Anima un indicador pequeño sin poner el cursor global en espera."""
        if not getattr(self, "indicador_carga", None) or self.estado_actualizacion != "actualizando":
            return
        self.indicador_carga.setText(
            self._frames_animacion_carga[self._indice_animacion_carga]
        )
        self._indice_animacion_carga = (
            self._indice_animacion_carga + 1
        ) % len(self._frames_animacion_carga)

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
        self.setEnabled(False)
        try:
            self.cerrar_ventanas_secundarias()
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
        self.detener_trabajador_avance()
        if self.ventana_plan_estudios is not None:
            self.ventana_plan_estudios.hide()
        if self.ventana_mi_avance is not None:
            self.ventana_mi_avance.hide()
            self.ventana_mi_avance.mostrar_datos(None)
        for dialogo in list(self.dialogos_no_modales):
            try:
                dialogo.close()
            except RuntimeError:
                # El objeto de Qt pudo eliminarse justo antes de recorrerlo.
                pass
        self.dialogos_no_modales.clear()

    def closeEvent(self, evento):
        try:
            self.detener_trabajador_avance()
        except RuntimeError as error:
            evento.ignore()
            QMessageBox.warning(self, "Consulta en curso", str(error))
            return
        super().closeEvent(evento)

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
    cargar_fuente_interfaz(app)
    # Los tooltips nativos pueden ignorar el estilo del widget que los emite.
    # Declararlo a nivel de QApplication garantiza contraste en el tema oscuro.
    app.setStyleSheet(
        f"QToolTip {{ color: {COLOR_TEXTO}; background-color: {COLOR_BARRA}; "
        f"border: 1px solid {COLOR_AMARILLO}; padding: 5px; }}"
        + ESTILO_BARRAS_DESPLAZAMIENTO
    )
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
