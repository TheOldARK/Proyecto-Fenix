"""Interfaz central para programar publicadores de carreras de Fénix."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

if os.name == "nt":
    _windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    _python_dir = Path(sys.executable).resolve().parent
    _meipass = Path(getattr(sys, "_MEIPASS", _python_dir))
    _qt_paths = []
    for _bundle_root in (_meipass, _meipass / "_internal"):
        for _dll_dir in (_bundle_root, _bundle_root / "PySide6", _bundle_root / "shiboken6"):
            if _dll_dir.is_dir() and _dll_dir not in _qt_paths:
                _qt_paths.append(_dll_dir)
    _dll_handles = [os.add_dll_directory(str(path)) for path in _qt_paths if hasattr(os, "add_dll_directory")]
    os.environ["PATH"] = os.pathsep.join([
        *(str(path) for path in _qt_paths), str(_python_dir),
        str(_windows / "System32"), str(_windows), os.environ.get("PATH", ""),
    ])

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QProgressBar, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from configuracion import (  # noqa: E402
    ARCHIVO_CONFIGURACION_LIBRE_ELECCION,
    ARCHIVO_PLANES_ESTUDIO,
    ARCHIVO_LIBRES_ELECCION_SEDE,
    CARPETA_DATOS,
)
from herramientas.estrategia_publicadores import (  # noqa: E402
    debe_reintentar_timeout,
    medir_lote,
    es_error_timeout,
    limpiar_estadisticas_rendimiento,
    ordenar_por_actualizacion_mas_antigua,
    seleccionar_concurrencia,
    unidades_plan,
)
from infraestructura.almacenamiento.json_atomico import guardar_json_atomico  # noqa: E402
from infraestructura.almacenamiento.plan_estudios import cargar_planes  # noqa: E402
from infraestructura.almacenamiento.materias_libre_eleccion import (
    sincronizar_libres_eleccion_sede,
)  # noqa: E402
from main import (  # noqa: E402
    seleccionar_planes_publicables,
    seleccionar_planes_referencia_libres,
)

CARPETA_GESTOR = CARPETA_DATOS / "gestor_publicadores"
ARCHIVO_ESTADISTICAS = CARPETA_GESTOR / "estadisticas.json"
INTERVALO_CICLO_MIN = 1
INTERVALO_CICLO_MAX = 1440
UTC_COLOMBIA = timezone(timedelta(hours=-5))
MAX_INTENTOS_TIMEOUT = 3
ID_PUBLICADOR_LIBRES_SEDE = "__libres_sede__"


def leer_estadisticas() -> dict:
    try:
        datos = json.loads(ARCHIVO_ESTADISTICAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    if not isinstance(datos, dict):
        datos = {}
    datos.setdefault("planes", {})
    datos.setdefault("concurrencias", {})
    return datos


def guardar_estadisticas(datos: dict) -> None:
    CARPETA_GESTOR.mkdir(parents=True, exist_ok=True)
    guardar_json_atomico(ARCHIVO_ESTADISTICAS, datos)


def _hora_legible(epoch) -> str:
    if not epoch:
        return "Nunca"
    try:
        return datetime.fromtimestamp(float(epoch), UTC_COLOMBIA).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "Desconocida"


class BloqueoGestor:
    """Impide abrir dos gestores y lanzar el mismo plan dos veces."""

    def __init__(self):
        self.ruta = CARPETA_GESTOR / "gestor.lock"
        self.archivo = None

    def adquirir(self) -> bool:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.archivo = self.ruta.open("a+b")
        self.archivo.seek(0, os.SEEK_END)
        if self.archivo.tell() == 0:
            self.archivo.write(b" ")
            self.archivo.flush()
        self.archivo.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.archivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError):
            self.archivo.close()
            self.archivo = None
            return False
        return True

    def liberar(self):
        if self.archivo is None:
            return
        self.archivo.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.archivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.archivo.fileno(), fcntl.LOCK_UN)
        except (OSError, ImportError):
            pass
        self.archivo.close()
        self.archivo = None


class CicloPublicadores(QObject):
    progreso = Signal(dict)
    terminado = Signal(bool, str)

    def __init__(self, planes, seleccion, max_concurrencia, aprendizaje, automatico, intervalo_minutos, plan_contexto_sede=None):
        super().__init__()
        self.planes = planes
        self.seleccion = tuple(seleccion)
        self.plan_contexto_sede = str(plan_contexto_sede or "")
        self.max_concurrencia = max(1, int(max_concurrencia))
        self.aprendizaje = bool(aprendizaje)
        self.automatico = bool(automatico)
        self.intervalo_segundos = max(INTERVALO_CICLO_MIN, int(intervalo_minutos)) * 60
        self.detener = threading.Event()
        self.estado_actual = {}
        self.estadisticas = leer_estadisticas()

    def _emitir(self, codigo, estado, mensaje="", avance=None):
        self.estado_actual[codigo] = {"estado": estado, "mensaje": mensaje, "avance": avance}
        self.progreso.emit({
            "planes": self.estado_actual.copy(),
            "completados": sum(x.get("estado") in {"completado", "error"} for x in self.estado_actual.values()),
            "total": len(self.seleccion),
            "mensaje": mensaje,
        })

    def _ejecutar_plan(self, codigo):
        from aplicacion.arranque import comando_fenix

        datos = CARPETA_GESTOR / "datos" / codigo.replace(":", "-")
        datos.mkdir(parents=True, exist_ok=True)
        # Cada hijo tiene estado aislado, pero necesita el catálogo y las
        # configuraciones de Libre Elección actuales para resolver su plan.
        for origen in (
            ARCHIVO_PLANES_ESTUDIO,
            ARCHIVO_CONFIGURACION_LIBRE_ELECCION,
            ARCHIVO_LIBRES_ELECCION_SEDE,
        ):
            if origen.is_file():
                shutil.copy2(origen, datos / origen.name)
        entorno = os.environ.copy()
        entorno["FENIX_DATA_DIR"] = str(datos)
        # Comparte el mismo bloqueo que cualquier publicación Fénix de este
        # usuario; se puede fijar una ruta común explícita en el entorno.
        bloqueo_manifest = entorno.get("FENIX_PUBLICADOR_MANIFEST_LOCK", "").strip()
        if not bloqueo_manifest:
            base_local = Path(entorno.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            bloqueo_manifest = str(base_local / "Fenix" / "manifest-publicacion.lock")
        entorno["FENIX_PUBLICADOR_MANIFEST_LOCK"] = bloqueo_manifest
        tipo_publicador = "libres_sede" if codigo == ID_PUBLICADOR_LIBRES_SEDE else "carrera"
        if tipo_publicador == "libres_sede":
            entorno["FENIX_PUBLICADOR_LIBRES_SEDE_SALIDA"] = str(
                datos / "resultado_libres_eleccion_sede.json"
            )
        argumentos = comando_fenix(
            "--publicador-plan-worker", "--plan", codigo,
            "--tipo", tipo_publicador,
        )
        if tipo_publicador == "libres_sede":
            argumentos.extend(("--plan-contexto", self.plan_contexto_sede))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        inicio = time.monotonic()
        estado_path = datos / "estado_actualizacion.json"
        resultado_path = datos / "resultado_publicador.json"
        errores_log_path = datos / "errores_actualizacion.log"
        try:
            tamano_log_inicial = errores_log_path.stat().st_size
        except OSError:
            tamano_log_inicial = 0
        resultado = {}
        exito = False
        detalle = "La actualización no terminó correctamente."
        for intento in range(1, MAX_INTENTOS_TIMEOUT + 1):
            try:
                resultado_path.unlink(missing_ok=True)
            except OSError:
                pass
            if intento == 1:
                self._emitir(codigo, "iniciando", "Iniciando en segundo plano…", 0)
            else:
                self._emitir(
                    codigo,
                    "reintentando",
                    f"Reintentando por timeout ({intento}/{MAX_INTENTOS_TIMEOUT})…",
                    0,
                )
            proceso = subprocess.Popen(
                argumentos,
                cwd=str(ROOT),
                env=entorno,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
            while proceso.poll() is None:
                try:
                    estado = json.loads(estado_path.read_text(encoding="utf-8"))
                    mensaje = str(estado.get("mensaje") or "Consultando el SIA…")
                    estado_nombre = str(estado.get("estado") or "actualizando")
                    avance = estado.get("progreso")
                except (OSError, ValueError):
                    mensaje, estado_nombre, avance = "Iniciando consulta…", "iniciando", 0
                self._emitir(codigo, estado_nombre, mensaje, avance)
                time.sleep(0.8)
            try:
                resultado = json.loads(resultado_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                resultado = {}
            exito = proceso.returncode == 0 and resultado.get("estado") == "completado"
            detalle = str(resultado.get("error") or resultado.get("advertencia") or (
                "Actualización terminada." if exito
                else f"El proceso terminó con código {proceso.returncode}."
            ))
            try:
                contenido_log = errores_log_path.read_bytes()
                if len(contenido_log) >= tamano_log_inicial:
                    contenido_log = contenido_log[tamano_log_inicial:]
                lineas = contenido_log.decode("utf-8", errors="replace").splitlines()
                sospechosas = []
                for linea in lineas:
                    try:
                        registro = json.loads(linea)
                    except ValueError:
                        continue
                    if registro.get("posible_codigo_o_nombre_incorrecto"):
                        sospechosas.append(
                            f"{registro.get('codigo', '?')} · {registro.get('nombre', 'sin nombre')}"
                        )
                if sospechosas:
                    detalle += "\nPosibles códigos/nombres incorrectos: " + ", ".join(
                        dict.fromkeys(sospechosas)
                    )
            except OSError:
                pass
            if exito or not debe_reintentar_timeout(
                detalle, intento, MAX_INTENTOS_TIMEOUT, self.detener.is_set()
            ):
                break
            espera = 5 * (2 ** (intento - 1))
            self._emitir(
                codigo,
                "reintentando",
                f"Timeout detectado; nuevo intento en {espera} s ({intento + 1}/{MAX_INTENTOS_TIMEOUT})…",
                0,
            )
            if self.detener.wait(espera):
                detalle = "Reintento cancelado porque se solicitó detener el gestor."
                break
        duracion = time.monotonic() - inicio
        self._emitir(codigo, "completado" if exito else "error", detalle, 100 if exito else None)
        return {
            "codigo": codigo,
            "exito": exito,
            "duracion": duracion,
            "unidades": int(
                resultado.get("unidades_trabajo")
                or (1 if codigo == ID_PUBLICADOR_LIBRES_SEDE else unidades_plan(self.planes[codigo]))
            ),
            "error": "" if exito else detalle,
        }

    def _prioridad(self, codigos):
        return ordenar_por_actualizacion_mas_antigua(codigos, self.estadisticas["planes"])

    def _concurrencia_siguiente(self, disponibles):
        maximo = max(1, min(self.max_concurrencia, disponibles))
        if not self.aprendizaje:
            return maximo
        muestras = {
            int(cantidad): [float(item["unidades_por_segundo"]) for item in lote if isinstance(item, dict) and "unidades_por_segundo" in item]
            for cantidad, lote in self.estadisticas["concurrencias"].items()
            if str(cantidad).isdigit()
        }
        return seleccionar_concurrencia(maximo, muestras)

    def _guardar_resultado_plan(self, resultado):
        codigo = resultado["codigo"]
        registros = self.estadisticas["planes"]
        item = registros.setdefault(codigo, {})
        item["ultima_ejecucion"] = time.time()
        item["duracion_segundos"] = round(resultado["duracion"], 2)
        if resultado["exito"]:
            item["ultima_actualizacion_exitosa"] = item["ultima_ejecucion"]
            item["errores_consecutivos"] = 0
            item["actualizaciones_exitosas"] = int(item.get("actualizaciones_exitosas", 0)) + 1
        else:
            item["errores_consecutivos"] = int(item.get("errores_consecutivos", 0)) + 1
            item["ultimo_error"] = resultado["error"]
        guardar_estadisticas(self.estadisticas)

    @Slot()
    def ejecutar(self):
        ciclos = 0
        try:
            while not self.detener.is_set():
                ciclos += 1
                self.estado_actual = {}
                pendientes = self._prioridad(self.seleccion)
                completados = 0
                total_lote = len(pendientes)
                # La lista compartida debe preceder a las carreras: así los
                # publicadores por plan pueden reutilizarla desde el inicio
                # del ciclo y evitan volver a detallar las libres de sede.
                if ID_PUBLICADOR_LIBRES_SEDE in pendientes:
                    self.progreso.emit({
                        "completados": completados,
                        "total": total_lote,
                        "mensaje": "Actualizando primero el catálogo compartido de Libre Elección de Medellín…",
                    })
                    resultado_sede = self._ejecutar_plan(ID_PUBLICADOR_LIBRES_SEDE)
                    if resultado_sede["exito"]:
                        archivo_sede_hijo = (
                            CARPETA_GESTOR / "datos" / ID_PUBLICADOR_LIBRES_SEDE
                            / "resultado_libres_eleccion_sede.json"
                        )
                        try:
                            sincronizar_libres_eleccion_sede(
                                archivo_sede_hijo,
                                ARCHIVO_LIBRES_ELECCION_SEDE,
                            )
                            self._emitir(
                                ID_PUBLICADOR_LIBRES_SEDE,
                                "completado",
                                "Catálogo de sede publicado y listo para reutilizar por las carreras.",
                                100,
                            )
                        except (OSError, ValueError, TypeError) as error:
                            # La publicación a Cloudflare ya terminó. Si falla
                            # la copia local, las carreras siguen funcionando:
                            # consultarán el SIA sin ese catálogo compartido.
                            self._emitir(
                                ID_PUBLICADOR_LIBRES_SEDE,
                                "advertencia",
                                f"Se publicó en Cloudflare, pero no se pudo preparar el catálogo local: {error}",
                            )
                    self._guardar_resultado_plan(resultado_sede)
                    completados += 1
                    pendientes.remove(ID_PUBLICADOR_LIBRES_SEDE)
                while pendientes and not self.detener.is_set():
                    cantidad = self._concurrencia_siguiente(len(pendientes))
                    lote = pendientes[:cantidad]
                    pendientes = pendientes[cantidad:]
                    self.progreso.emit({"completados": completados, "total": total_lote, "mensaje": f"Lote de {len(lote)} publicador(es); prioridad: más tiempo sin actualizar."})
                    inicio_lote = time.monotonic()
                    resultados = []
                    with ThreadPoolExecutor(max_workers=len(lote), thread_name_prefix="fenix-publicador") as pool:
                        futuros = {pool.submit(self._ejecutar_plan, codigo): codigo for codigo in lote}
                        for futuro in as_completed(futuros):
                            codigo = futuros[futuro]
                            try:
                                resultado = futuro.result()
                            except Exception as error:
                                resultado = {"codigo": codigo, "exito": False, "duracion": 0, "error": str(error)}
                                self._emitir(codigo, "error", str(error))
                            resultados.append(resultado)
                            self._guardar_resultado_plan(resultado)
                            completados += 1
                    duracion_lote = max(0.001, time.monotonic() - inicio_lote)
                    exitos = [resultado for resultado in resultados if resultado["exito"]]
                    if exitos:
                        unidades = sum(r["unidades"] for r in exitos)
                        metrica = medir_lote(unidades, duracion_lote, len(lote))
                        metrica.update(
                            fecha=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            planes=[r["codigo"] for r in exitos],
                            lote_completo=(len(exitos) == len(lote)),
                        )
                        cantidad_real = len(lote)
                        muestras = self.estadisticas["concurrencias"].setdefault(str(cantidad_real), [])
                        muestras.append(metrica)
                        del muestras[:-100]
                        guardar_estadisticas(self.estadisticas)
                    self.progreso.emit({"completados": completados, "total": total_lote, "mensaje": f"Ciclo {ciclos}: {completados}/{total_lote} carreras procesadas."})
                if not self.automatico or self.detener.is_set():
                    break
                self.progreso.emit({"completados": total_lote, "total": total_lote, "mensaje": f"Ciclo {ciclos} completo. Próximo ciclo en {self.intervalo_segundos // 60} min."})
                self.detener.wait(self.intervalo_segundos)
            self.terminado.emit(True, "Gestor detenido de forma segura.")
        except Exception as error:
            self.terminado.emit(False, f"Error en el gestor: {error}")


def cargar_icono(app):
    candidatos = [
        ROOT / "recursos" / "logo.ico",
        Path(getattr(sys, "_MEIPASS", ROOT)) / "recursos" / "logo.ico",
        Path(sys.executable).resolve().parent / "_internal" / "recursos" / "logo.ico",
    ]
    for ruta in candidatos:
        if ruta.is_file():
            icono = QIcon(str(ruta))
            if not icono.isNull():
                return icono
    return QIcon()


class VentanaGestor(QWidget):
    def __init__(self, app):
        super().__init__()
        disponibles, omitidos = seleccionar_planes_publicables(cargar_planes())
        self.planes = disponibles
        self.planes_referencia = seleccionar_planes_referencia_libres(disponibles)
        self.omitidos = omitidos
        self.worker = None
        self.thread = None
        self.registros = leer_estadisticas()
        self.estado_por_plan = {}
        self._ultimo_mensaje_actividad = {}
        self.setWindowTitle("Gestor de publicadores · Fénix")
        self.setMinimumSize(1100, 700)
        icono = cargar_icono(app)
        self.setWindowIcon(icono)
        app.setWindowIcon(icono)
        self.setStyleSheet("""
            QWidget { background:#121212; color:#f1f1f1; }
            QTableWidget { background:#181818; gridline-color:#383838; }
            QHeaderView::section { background:#252525; color:#fff; padding:6px; }
            QPushButton, QComboBox, QSpinBox { background:#252525; border:1px solid #484848; padding:6px; }
            QPushButton:hover { background:#333; }
        """)

        titulo = QLabel("GESTOR DE PUBLICADORES")
        titulo.setStyleSheet("font-size:18px; font-weight:bold; color:#62d98b;")
        descripcion = QLabel(
            "Selecciona las carreras y cuántas actualizar en paralelo. En modo automático, "
            "el gestor aprende qué concurrencia procesa más materias por unidad de tiempo, "
            "y prioriza las carreras con la actualización exitosa más antigua. El catálogo "
            "compartido de Libre Elección usa 3 workers; cada publicador de carrera "
            "usa 2. Los procesos hijos no muestran ventanas."
        )
        descripcion.setWordWrap(True)
        self.tabla = QTableWidget()
        self._poblar_tabla(disponibles)
        self.selector_plan_sede = QComboBox()
        for codigo, plan in sorted(self.planes_referencia.items()):
            self.selector_plan_sede.addItem(
                f"{plan.facultad_nombre or 'Facultad'} · {plan.nombre}",
                str(codigo),
            )
        self.actividad = QPlainTextEdit()
        self.actividad.setReadOnly(True)
        self.actividad.setPlaceholderText(
            "Aquí aparecerán las fases, errores y materias que requieran revisión."
        )
        self.actividad.setMinimumHeight(130)

        controles = QHBoxLayout()
        controles.addWidget(QLabel("Modo"))
        self.modo = QComboBox()
        self.modo.addItem("Automático · todas las seleccionadas", "automatico")
        self.modo.addItem("Manual · una pasada de las seleccionadas", "manual")
        controles.addWidget(self.modo, 2)
        controles.addWidget(QLabel("Máximo simultáneo"))
        self.cantidad = QSpinBox()
        self.cantidad.setRange(1, max(1, len(disponibles) + 1))
        self.cantidad.setValue(min(3, max(1, len(disponibles))))
        self.cantidad.setToolTip("Cantidad de carreras cuyos publicadores correrán al mismo tiempo.")
        controles.addWidget(self.cantidad)
        self.aprender = QCheckBox("Aprender y probar otras cantidades")
        self.aprender.setChecked(True)
        self.aprender.setToolTip("Explora configuraciones con pocos datos y favorece las de mayor rendimiento medido.")
        controles.addWidget(self.aprender)

        referencia_sede = QHBoxLayout()
        referencia_sede.addWidget(QLabel("Carrera de referencia para la consulta de sede"))
        referencia_sede.addWidget(self.selector_plan_sede, 1)

        intervalo = QHBoxLayout()
        intervalo.addWidget(QLabel("Pausa automática entre ciclos (minutos)"))
        self.pausa = QSpinBox()
        self.pausa.setRange(INTERVALO_CICLO_MIN, INTERVALO_CICLO_MAX)
        self.pausa.setValue(30)
        intervalo.addWidget(self.pausa)
        intervalo.addStretch(1)

        self.progreso = QProgressBar()
        self.progreso.setRange(0, 100)
        self.progreso.setValue(0)
        self.estado = QLabel(f"{len(disponibles)} carreras listas · {len(omitidos)} planes incompletos omitidos.")
        self.estado.setWordWrap(True)
        self.resumen_rendimiento = QLabel(self._texto_rendimiento())
        self.resumen_rendimiento.setWordWrap(True)
        botones = QHBoxLayout()
        self.boton_iniciar = QPushButton("Iniciar gestor")
        self.boton_iniciar.clicked.connect(self.iniciar)
        self.boton_detener = QPushButton("Detener al terminar el lote activo")
        self.boton_detener.setEnabled(False)
        self.boton_detener.clicked.connect(self.detener)
        self.boton_actualizar = QPushButton("Actualizar lista de carreras")
        self.boton_actualizar.clicked.connect(self.recargar_planes)
        self.boton_borrar_estadisticas = QPushButton("Borrar estadísticas de velocidad")
        self.boton_borrar_estadisticas.clicked.connect(self.borrar_estadisticas_rendimiento)
        botones.addWidget(self.boton_iniciar)
        botones.addWidget(self.boton_detener)
        botones.addWidget(self.boton_actualizar)
        botones.addWidget(self.boton_borrar_estadisticas)
        layout = QVBoxLayout(self)
        layout.addWidget(titulo)
        layout.addWidget(descripcion)
        layout.addLayout(controles)
        layout.addLayout(referencia_sede)
        layout.addLayout(intervalo)
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.tabla)
        divisor.addWidget(self.actividad)
        divisor.setStretchFactor(0, 4)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([480, 170])
        layout.addWidget(divisor, 1)
        layout.addWidget(self.progreso)
        layout.addWidget(self.resumen_rendimiento)
        layout.addWidget(self.estado)
        layout.addLayout(botones)
        if not disponibles:
            self.boton_iniciar.setEnabled(False)
            self.estado.setText("No hay planes completos que el publicador pueda actualizar.")

    def seleccionados(self):
        salida = []
        for fila in range(self.tabla.rowCount()):
            item = self.tabla.item(fila, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                salida.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return salida

    def _texto_rendimiento(self):
        resumenes = []
        for cantidad, muestras in self.registros.get("concurrencias", {}).items():
            validas = [
                muestra for muestra in muestras
                if isinstance(muestra, dict)
                and isinstance(muestra.get("unidades_por_segundo"), (int, float))
            ]
            if not validas:
                continue
            media = sum(float(m["unidades_por_segundo"]) for m in validas) / len(validas)
            eficiencia = sum(float(m.get("unidades_por_publicador_segundo", 0)) for m in validas) / len(validas)
            resumenes.append((int(cantidad), media, eficiencia, len(validas)))
        if not resumenes:
            return "Rendimiento: aún no hay lotes medidos; el gestor probará distintas cantidades para aprender."
        mejor = max(resumenes, key=lambda item: (item[1], item[2], -item[0]))
        detalle = " · ".join(
            f"{n} simultáneo(s): {velocidad * 60:.1f} materias/min total "
            f"({eficiencia * 60:.1f} por publicador, {muestras} muestra(s))"
            for n, velocidad, eficiencia, muestras in sorted(resumenes)
        )
        return f"Mejor velocidad total medida: {mejor[0]} simultáneo(s). {detalle}"

    def borrar_estadisticas_rendimiento(self):
        respuesta = QMessageBox.question(
            self,
            "Borrar estadísticas de velocidad",
            "¿Eliminar todas las mediciones de velocidad y concurrencia?\n\n"
            "Se conservarán la última actualización exitosa y el estado de cada carrera.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        limpiar_estadisticas_rendimiento(self.registros)
        guardar_estadisticas(self.registros)
        for fila in range(self.tabla.rowCount()):
            self.tabla.item(fila, 5).setText("—")
        self.resumen_rendimiento.setText(self._texto_rendimiento())
        self.estado.setText(
            "Estadísticas de velocidad eliminadas; se conservó el historial de actualización por carrera."
        )

    def recargar_planes(self):
        seleccion_previa = set(self.seleccionados())
        self.registros = leer_estadisticas()
        self.planes, self.omitidos = seleccionar_planes_publicables(cargar_planes())
        self.planes_referencia = seleccionar_planes_referencia_libres(self.planes)
        self._poblar_tabla(self.planes, seleccion_previa)
        self.selector_plan_sede.clear()
        for codigo, plan in sorted(self.planes_referencia.items()):
            self.selector_plan_sede.addItem(
                f"{plan.facultad_nombre or 'Facultad'} · {plan.nombre}",
                str(codigo),
            )
        self.cantidad.setMaximum(max(1, len(self.planes) + bool(self.planes_referencia)))
        self.estado.setText(f"{len(self.planes)} carreras listas · {len(self.omitidos)} planes incompletos omitidos.")
        self.boton_iniciar.setEnabled(bool(self.planes or self.planes_referencia))

    def _poblar_tabla(self, planes, seleccion_previa=None):
        if seleccion_previa is None:
            seleccion_previa = set(planes)
            if self.planes_referencia:
                seleccion_previa.add(ID_PUBLICADOR_LIBRES_SEDE)
        else:
            seleccion_previa = set(seleccion_previa)
        tiene_fila_sede = bool(self.planes_referencia)
        self.tabla.setRowCount(len(planes) + (1 if tiene_fila_sede else 0))
        self.tabla.setColumnCount(6)
        self.tabla.setHorizontalHeaderLabels(["Carrera / activar", "Facultad", "Última actualización", "Estado", "Avance", "Última duración"])
        encabezado = self.tabla.horizontalHeader()
        encabezado.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        encabezado.setStretchLastSection(False)
        vertical = self.tabla.verticalHeader()
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        vertical.setDefaultSectionSize(54)
        self.tabla.setWordWrap(True)
        self.tabla.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.codigos_fila = []
        filas_ordenadas = []
        if tiene_fila_sede:
            filas_ordenadas.append((ID_PUBLICADOR_LIBRES_SEDE, None))
        filas_ordenadas.extend(
            (str(codigo), plan)
            for codigo, plan in sorted(
                planes.items(),
                key=lambda item: (item[1].facultad_nombre, item[1].nombre),
            )
        )
        for fila, (codigo, plan) in enumerate(filas_ordenadas):
            codigo = str(codigo)
            self.codigos_fila.append(codigo)
            es_sede = codigo == ID_PUBLICADOR_LIBRES_SEDE
            materia = QTableWidgetItem(
                "Libre Elección de sede · Medellín" if es_sede else plan.nombre
            )
            materia.setFlags(materia.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            materia.setCheckState(Qt.CheckState.Checked if codigo in seleccion_previa else Qt.CheckState.Unchecked)
            materia.setData(Qt.ItemDataRole.UserRole, codigo)
            if es_sede:
                materia.setToolTip(
                    "Catálogo compartido: actualiza una sola vez la consulta '3 SEDE MEDELLÍN'."
                )
            self.tabla.setItem(fila, 0, materia)
            self.tabla.setItem(
                fila, 1,
                QTableWidgetItem("Toda la sede" if es_sede else (plan.facultad_nombre or "—")),
            )
            registro = self.registros["planes"].get(codigo, {})
            self.tabla.setItem(fila, 2, QTableWidgetItem(_hora_legible(registro.get("ultima_actualizacion_exitosa"))))
            self.tabla.setItem(
                fila, 3,
                QTableWidgetItem("Catálogo compartido" if es_sede else "Listo"),
            )
            self.tabla.setItem(fila, 4, QTableWidgetItem("—"))
            duracion = registro.get("duracion_segundos")
            self.tabla.setItem(fila, 5, QTableWidgetItem(f"{duracion:.0f} s" if isinstance(duracion, (int, float)) else "—"))
        for columna, ancho in enumerate((250, 210, 155, 380, 90, 120)):
            self.tabla.setColumnWidth(columna, ancho)

    def iniciar(self):
        seleccion = self.seleccionados()
        if not seleccion:
            QMessageBox.warning(self, "Selecciona carreras", "Activa al menos una carrera en la tabla.")
            return
        simultaneos = min(len(seleccion), self.cantidad.value())
        carreras_seleccionadas = sum(
            codigo != ID_PUBLICADOR_LIBRES_SEDE for codigo in seleccion
        )
        carreras_simultaneas = min(carreras_seleccionadas, self.cantidad.value())
        estimado_workers = max(
            3 if ID_PUBLICADOR_LIBRES_SEDE in seleccion else 0,
            carreras_simultaneas * 2,
        )
        if simultaneos > 3 and QMessageBox.question(
            self,
            "Concurrencia alta",
            f"El límite permite hasta {simultaneos} carreras a la vez (aproximadamente "
            f"{estimado_workers} workers internos del SIA). ¿Quieres continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        automatico = self.modo.currentData() == "automatico"
        self.thread = QThread(self)
        self.worker = CicloPublicadores(
            self.planes, seleccion, self.cantidad.value(), self.aprender.isChecked(),
            automatico, self.pausa.value(), self.selector_plan_sede.currentData(),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.ejecutar)
        self.worker.progreso.connect(self.mostrar_progreso)
        self.worker.terminado.connect(self.finalizar)
        self.worker.terminado.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()
        self.boton_iniciar.setEnabled(False)
        self.boton_detener.setEnabled(True)
        # Mantener la tabla habilitada deja usar su barra de desplazamiento;
        # durante la ejecución solo se bloquean los checks para no alterar
        # silenciosamente la selección del ciclo en curso.
        for fila in range(self.tabla.rowCount()):
            item = self.tabla.item(fila, 0)
            if item is not None:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        self.modo.setEnabled(False)
        self.cantidad.setEnabled(False)
        self.aprender.setEnabled(False)
        self.boton_actualizar.setEnabled(False)
        self.boton_borrar_estadisticas.setEnabled(False)

    def detener(self):
        if self.worker:
            self.worker.detener.set()
            self.estado.setText("Deteniendo al terminar el lote que ya está ejecutándose…")
            self.boton_detener.setEnabled(False)

    @Slot(dict)
    def mostrar_progreso(self, datos):
        self.registros = leer_estadisticas()
        self.resumen_rendimiento.setText(self._texto_rendimiento())
        for codigo, estado in datos.get("planes", {}).items():
            fila = next((n for n in range(self.tabla.rowCount()) if self.tabla.item(n, 0).data(Qt.ItemDataRole.UserRole) == codigo), None)
            if fila is not None:
                self.estado_por_plan[codigo] = estado
                mensaje_estado = str(estado.get("mensaje") or estado.get("estado", ""))
                celda_estado = self.tabla.item(fila, 3)
                celda_estado.setText(mensaje_estado)
                celda_estado.setToolTip(mensaje_estado)
                if self._ultimo_mensaje_actividad.get(codigo) != mensaje_estado:
                    self.actividad.appendPlainText(f"{codigo} · {mensaje_estado}")
                    self._ultimo_mensaje_actividad[codigo] = mensaje_estado
                avance = estado.get("avance")
                self.tabla.item(fila, 4).setText(f"{max(0, min(100, int(avance)))}%" if isinstance(avance, (int, float)) else "—")
                if estado.get("estado") == "completado":
                    registro = self.registros["planes"].get(codigo, {})
                    self.tabla.item(fila, 2).setText(_hora_legible(registro.get("ultima_actualizacion_exitosa")))
                    segundos = registro.get("duracion_segundos")
                    self.tabla.item(fila, 5).setText(f"{segundos:.0f} s" if isinstance(segundos, (int, float)) else "—")
        total = max(1, int(datos.get("total", 0) or 0))
        completados = min(total, int(datos.get("completados", 0) or 0))
        self.progreso.setValue(round(completados * 100 / total))
        self.estado.setText(str(datos.get("mensaje") or "Trabajando en segundo plano…"))

    @Slot(bool, str)
    def finalizar(self, ok, mensaje):
        self.boton_iniciar.setEnabled(True)
        self.boton_detener.setEnabled(False)
        for fila in range(self.tabla.rowCount()):
            item = self.tabla.item(fila, 0)
            if item is not None:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        self.modo.setEnabled(True)
        self.cantidad.setEnabled(True)
        self.aprender.setEnabled(True)
        self.boton_actualizar.setEnabled(True)
        self.boton_borrar_estadisticas.setEnabled(True)
        self.estado.setText(mensaje)
        self.worker = None
        self.thread = None

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(
                self,
                "Publicadores activos",
                "Pulsa «Detener al terminar el lote activo» y espera a que finalice antes de cerrar el gestor.",
            )
            event.ignore()
            return
        event.accept()


def main() -> int:
    from aplicacion.arranque import inicializar_datos_usuario

    inicializar_datos_usuario()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    bloqueo = BloqueoGestor()
    if not bloqueo.adquirir():
        QMessageBox.warning(None, "Gestor ya abierto", "Ya hay otro gestor de publicadores ejecutándose.")
        return 2
    ventana = VentanaGestor(app)
    ventana.show()
    try:
        return app.exec()
    finally:
        bloqueo.liberar()


if __name__ == "__main__":
    raise SystemExit(main())
