"""Publicador de datos de Fénix con ventana y bandeja del sistema."""
from __future__ import annotations
import argparse, json, os, sys, threading, time, traceback
from pathlib import Path

# Evita que Qt cargue DLL homónimas de otras aplicaciones del PATH (un caso
# frecuente cuando el publicador se abre desde una terminal o un IDE).
if os.name == "nt":
    _windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    _python_dir = Path(sys.executable).resolve().parent
    # En un ejecutable one-file, PyInstaller extrae Qt en _MEIPASS. Esta ruta
    # debe estar delante de cualquier Qt instalado globalmente.
    _meipass = Path(getattr(sys, "_MEIPASS", _python_dir))
    _qt_paths = []
    for _bundle_root in (_meipass, _meipass / "_internal"):
        for _dll_dir in (
            _bundle_root,
            _bundle_root / "PySide6",
            _bundle_root / "shiboken6",
        ):
            if _dll_dir.is_dir() and _dll_dir not in _qt_paths:
                _qt_paths.append(_dll_dir)
    # Windows elimina cada ruta cuando se libera el handle; conservarlos evita
    # que la ruta desaparezca antes de importar QtCore.
    _dll_handles = [
        os.add_dll_directory(str(_dll_dir))
        for _dll_dir in _qt_paths
        if hasattr(os, "add_dll_directory")
    ]
    os.environ["PATH"] = os.pathsep.join([
        *(str(path) for path in _qt_paths),
        str(_python_dir), str(_windows / "System32"), str(_windows),
        os.environ.get("PATH", ""),
    ])

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from configuracion import ARCHIVO_ESTADO_ACTUALIZACION  # noqa: E402
from infraestructura.almacenamiento.estado_actualizacion import guardar_estado  # noqa: E402
from main import (  # noqa: E402
    cargar_planes,
    ejecutar_publicador,
    ejecutar_publicador_libres_sede,
    seleccionar_planes_publicables,
    seleccionar_planes_referencia_libres,
)


def cargar_icono(app):
    """Encuentra el logo tanto en código fuente como dentro de PyInstaller."""
    ejecutable = Path(sys.executable).resolve().parent
    candidatos = [
        ROOT / "recursos" / "logo.ico",
        Path(getattr(sys, "_MEIPASS", ROOT)) / "recursos" / "logo.ico",
        ejecutable / "_internal" / "recursos" / "logo.ico",
        ejecutable / "recursos" / "logo.ico",
    ]
    for candidato in candidatos:
        if candidato.is_file():
            icono = QIcon(str(candidato))
            if not icono.isNull():
                return icono
    return app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

class PublicadorLock:
    def __init__(self):
        self.path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Fenix" / "publicador.lock"
        self.fd = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(self.path), os.O_CREAT | os.O_RDWR)
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            existente = os.read(descriptor, 256).decode("utf-8", errors="replace").strip()
            if existente:
                try:
                    registro = json.loads(existente)
                except json.JSONDecodeError:
                    registro = None
                # Compatibilidad con las versiones anteriores, que solo
                # guardaban un PID y no mantenían un bloqueo de sistema.
                if not isinstance(registro, dict):
                    try:
                        pid_antiguo = int(existente)
                    except ValueError:
                        pid_antiguo = 0
                    if pid_antiguo > 0 and self._es_lock_antiguo_activo(pid_antiguo, self.path):
                        os.close(descriptor)
                        return False

            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b" ")
                    os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)

            os.ftruncate(descriptor, 0)
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, json.dumps({"version": 2, "pid": os.getpid()}).encode("utf-8"))
            os.fsync(descriptor)
            self.fd = descriptor
            return True
        except (OSError, ImportError):
            try:
                os.close(descriptor)
            except OSError:
                pass
            return False

    @staticmethod
    def _es_lock_antiguo_activo(pid, ruta_lock=None):
        """Reconoce el dueño de un lock antiguo y descarta PID reciclados."""
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(0x1000, 0, int(pid))
            if not handle:
                # Si Windows niega el acceso, conservamos el lock por seguridad.
                return ctypes.get_last_error() == 5
            try:
                ruta = ctypes.create_unicode_buffer(32768)
                longitud = ctypes.c_uint32(len(ruta))
                consultar_ruta = kernel32.QueryFullProcessImageNameW
                consultar_ruta.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint32,
                    ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32),
                ]
                consultar_ruta.restype = ctypes.c_int
                if not consultar_ruta(handle, 0, ruta, ctypes.byref(longitud)):
                    return True
                if Path(ruta.value).name.casefold() not in {"fenix.exe", "python.exe", "pythonw.exe"}:
                    return False

                class FILETIME(ctypes.Structure):
                    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

                creado = FILETIME()
                salido = FILETIME()
                kernel = FILETIME()
                usuario = FILETIME()
                obtener_tiempos = kernel32.GetProcessTimes
                obtener_tiempos.argtypes = [
                    ctypes.c_void_p, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                    ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                ]
                obtener_tiempos.restype = ctypes.c_int
                if not obtener_tiempos(
                    handle, ctypes.byref(creado), ctypes.byref(salido),
                    ctypes.byref(kernel), ctypes.byref(usuario),
                ):
                    return True
                ticks = (creado.high << 32) | creado.low
                inicio = ticks / 10_000_000 - 11_644_473_600
                try:
                    escrito = ruta_lock.stat().st_mtime if ruta_lock and ruta_lock.is_file() else 0
                except OSError:
                    return True
                return escrito > 0 and inicio <= escrito + 3
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(int(pid), 0)
            return True
        except PermissionError:
            return True
        except (ProcessLookupError, OverflowError, SystemError):
            return False
        except OSError:
            return False

    def release(self):
        if self.fd is not None:
            try:
                os.lseek(self.fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.lockf(self.fd, fcntl.LOCK_UN, 1, 0)
            except (OSError, ImportError):
                pass
            os.close(self.fd)
            self.fd = None

class PublicadorWorker(QObject):
    terminado = Signal(bool, str)
    def __init__(self, lock, detener, intervalo, modo="automatico", codigo_plan=None):
        super().__init__()
        self.lock = lock
        self.detener = detener
        self.intervalo = intervalo
        self.modo = modo
        self.codigo_plan = codigo_plan

    @Slot()
    def ejecutar(self):
        ciclo = 0
        ultimo_error = None
        try:
            while not self.detener.is_set():
                ciclo += 1
                print(f"[Publicador] Iniciando ciclo continuo {ciclo}…", flush=True)
                guardar_estado(
                    "actualizando",
                    f"Ciclo {ciclo}: preparando los planes de Medellín…",
                    0,
                )
                try:
                    if self.modo == "libres_sede":
                        ejecutar_publicador_libres_sede(self.codigo_plan)
                    else:
                        ejecutar_publicador(
                            codigo_plan=self.codigo_plan if self.modo == "manual" else None,
                            modo=self.modo,
                        )
                except Exception as error:
                    ultimo_error = str(error)
                    traceback.print_exc()
                    guardar_estado("error", f"El ciclo {ciclo} falló: {error}", None)
                    print(f"[Publicador] El ciclo {ciclo} falló; se reintentará luego.", flush=True)
                else:
                    ultimo_error = None
                    print(f"[Publicador] Ciclo {ciclo} publicado correctamente.", flush=True)

                if self.detener.is_set():
                    break
                minutos = max(1, round(self.intervalo / 60))
                guardar_estado(
                    "esperando",
                    f"Ciclo {ciclo} terminado. Próxima actualización en aproximadamente {minutos} min.",
                    100 if ultimo_error is None else None,
                )
                print(f"[Publicador] Próximo ciclo en {minutos} min.", flush=True)
                self.detener.wait(self.intervalo)

            mensaje = "Publicador detenido después del ciclo actual."
            if ultimo_error:
                mensaje += f" Último error: {ultimo_error}"
            guardar_estado("detenido", mensaje, None)
            self.terminado.emit(ultimo_error is None, mensaje)
        finally:
            self.lock.release()


def intervalo_por_defecto() -> int:
    """Tiempo entre ciclos completos; configurable en el equipo publicador."""
    try:
        return max(60, int(os.environ.get("FENIX_PUBLICADOR_INTERVALO_SEGUNDOS", "1800")))
    except ValueError:
        return 1800

class VentanaPublicador(QWidget):
    def __init__(self, intervalo, app):
        super().__init__(); self.intervalo = intervalo; self.lock = PublicadorLock(); self.thread = None; self.worker = None; self.finalizado = False
        self.detener_evento = threading.Event()
        self.started = False
        self.setWindowTitle("Publicador de Fénix · Medellín"); self.setMinimumSize(560, 390)
        self.icono = cargar_icono(app)
        self.setWindowIcon(self.icono)
        self.setStyleSheet("QWidget { background:#121212; color:#fff; } QPushButton { padding:7px; }")
        self.titulo = QLabel("Elige cómo quieres actualizar los datos"); self.titulo.setStyleSheet("font-size:16px; font-weight:bold;")
        self.descripcion = QLabel("Automático recorre todas las carreras listas de Medellín. Manual mantiene una carrera. El modo compartido solo consulta Libre Elección por sede y publica el catálogo común de Medellín.")
        self.descripcion.setWordWrap(True)
        self.selector_modo = QComboBox()
        self.selector_modo.addItem("Automático · todas las carreras", "automatico")
        self.selector_modo.addItem("Manual · elegir una carrera", "manual")
        self.selector_modo.addItem("Compartido · Libre Elección de sede", "libres_sede")
        self.selector_carrera = QComboBox()
        self.planes_disponibles, _ = seleccionar_planes_publicables(cargar_planes())
        self.planes_referencia = seleccionar_planes_referencia_libres(self.planes_disponibles)
        self._poblar_selector_carrera(self.planes_disponibles)
        self.selector_carrera.setEnabled(False)
        self.selector_modo.currentIndexChanged.connect(self.cambiar_modo)
        self.estado = QLabel("Listo para iniciar."); self.estado.setWordWrap(True)
        self.resumen_progreso = QLabel("Aún no hay un ciclo en curso.")
        self.barra = QProgressBar(); self.barra.setRange(0, 100); self.barra.setValue(0)
        self.barra_global = QProgressBar(); self.barra_global.setRange(0, 100); self.barra_global.setValue(0)
        self.boton_iniciar = QPushButton("Iniciar publicador")
        self.boton_iniciar.clicked.connect(self.iniciar)
        self.boton = QPushButton("Ocultar en la bandeja"); self.boton.clicked.connect(self.ocultar_en_bandeja)
        layout = QVBoxLayout(self)
        layout.addWidget(self.titulo)
        layout.addWidget(self.descripcion)
        layout.addWidget(QLabel("Modo de trabajo"))
        layout.addWidget(self.selector_modo)
        layout.addWidget(QLabel("Carrera de referencia para configurar el SIA"))
        layout.addWidget(self.selector_carrera)
        layout.addWidget(self.boton_iniciar)
        layout.addSpacing(8)
        layout.addWidget(self.estado)
        layout.addWidget(QLabel("Progreso de la carrera actual"))
        layout.addWidget(self.barra)
        layout.addWidget(QLabel("Progreso total de carreras"))
        layout.addWidget(self.barra_global)
        layout.addWidget(self.resumen_progreso)
        layout.addWidget(self.boton)
        self.tray_disponible = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray = QSystemTrayIcon(self.icono, app); menu = QMenu()
        mostrar = QAction("Mostrar progreso", self); mostrar.triggered.connect(self.mostrar); menu.addAction(mostrar); menu.addSeparator()
        detener = QAction("Detener después del ciclo actual", self); detener.triggered.connect(self.solicitar_detencion); menu.addAction(detener)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Fénix Publicador · actualización en curso")
        self.tray.activated.connect(self.activar_desde_bandeja)
        if self.tray_disponible:
            self.tray.show()
        else:
            self.boton.setText("Minimizar (bandeja no disponible)")
        self.timer = QTimer(self); self.timer.timeout.connect(self.actualizar_estado); self.timer.start(500)
    def cambiar_modo(self):
        modo = self.selector_modo.currentData()
        usa_carrera = modo in {"manual", "libres_sede"}
        planes_selector = (
            self.planes_referencia if modo == "libres_sede"
            else self.planes_disponibles
        )
        codigo_previo = self.selector_carrera.currentData()
        self._poblar_selector_carrera(planes_selector, codigo_previo)
        tiene_referencias = bool(self.planes_referencia)
        self.selector_carrera.setEnabled(
            usa_carrera and self.boton_iniciar.isEnabled() and bool(planes_selector)
        )
        if modo == "libres_sede" and not tiene_referencias:
            self.estado.setText(
                "No hay planes con configuración de Libre Elección de sede. "
                "Completa configuracion_libre_eleccion.json primero."
            )
            self.boton_iniciar.setEnabled(False)
        elif self.estado.text().startswith("No hay planes con configuración de Libre Elección"):
            self.estado.setText("Listo para iniciar.")
            self.boton_iniciar.setEnabled(True)
        textos = {
            "manual": "Iniciar actualización de la carrera",
            "libres_sede": "Iniciar catálogo compartido de sede",
            "automatico": "Iniciar actualización de todas",
        }
        self.boton_iniciar.setText(textos.get(modo, "Iniciar publicador"))

    def _poblar_selector_carrera(self, planes, codigo_previo=None):
        self.selector_carrera.clear()
        for codigo, plan in sorted(planes.items()):
            facultad = plan.facultad_nombre or "Facultad"
            self.selector_carrera.addItem(f"{facultad} · {plan.nombre}", str(codigo))
        if codigo_previo:
            indice = self.selector_carrera.findData(str(codigo_previo))
            if indice >= 0:
                self.selector_carrera.setCurrentIndex(indice)

    def iniciar(self):
        try:
            adquirido = self.lock.acquire()
        except Exception as error:
            adquirido = False
            detalle = f"No se pudo comprobar el bloqueo del publicador: {error}"
        else:
            detalle = "Ya hay otro publicador de Fénix ejecutándose."
        if not adquirido:
            mensaje = detalle
            print(f"[Publicador] {mensaje}", flush=True)
            self.titulo.setText("Ya existe una instancia del publicador")
            self.estado.setText(
                mensaje + " Si ya está abierta, vuelve a esa ventana desde la bandeja de Windows."
            )
            self.boton_iniciar.setText("Reintentar inicio")
            self.show()
            self.raise_()
            self.activateWindow()
            if self.tray_disponible:
                self.tray.showMessage(
                    "Publicador ya iniciado",
                    "Hay otra instancia ejecutándose. Usa su ventana desde la bandeja o vuelve a intentar cuando se cierre.",
                    QSystemTrayIcon.MessageIcon.Warning,
                    7000,
                )
            QMessageBox.warning(self, "Publicador en ejecución", mensaje)
            return False
        modo = str(self.selector_modo.currentData() or "automatico")
        codigo_plan = self.selector_carrera.currentData() if modo in {"manual", "libres_sede"} else None
        if modo in {"manual", "libres_sede"} and not codigo_plan:
            self.lock.release()
            mensaje = (
                "No hay planes con configuración de Libre Elección de sede."
                if modo == "libres_sede"
                else "Selecciona una carrera para iniciar el modo manual."
            )
            QMessageBox.warning(self, "Carrera requerida", mensaje)
            return False
        self.selector_modo.setEnabled(False)
        self.selector_carrera.setEnabled(False)
        self.boton_iniciar.setEnabled(False)
        try:
            guardar_estado("preparando", "Preparando la lista de carreras…", 0)
            self.estado.setText("Iniciando workers…")
            self.boton_iniciar.setText("Iniciando…")
            print("[Publicador] Interfaz lista; preparando workers…", flush=True)
            self.thread = QThread(self)
            self.worker = PublicadorWorker(self.lock, self.detener_evento, self.intervalo, modo, codigo_plan)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.ejecutar)
            self.worker.terminado.connect(self.finalizar)
            self.worker.terminado.connect(self.thread.quit)
            self.thread.finished.connect(self.thread.deleteLater)
            self.thread.start()
            self.started = True
            return True
        except Exception as error:
            self.lock.release()
            self.selector_modo.setEnabled(True)
            self.selector_carrera.setEnabled(modo in {"manual", "libres_sede"})
            self.boton_iniciar.setEnabled(True)
            self.boton_iniciar.setText("Reintentar inicio")
            mensaje = f"No se pudo iniciar el publicador: {error}"
            self.estado.setText(mensaje)
            guardar_estado("error", mensaje, None)
            traceback.print_exc()
            QMessageBox.critical(self, "Error al iniciar", mensaje)
            return False
    def actualizar_estado(self):
        try: data = json.loads(ARCHIVO_ESTADO_ACTUALIZACION.read_text(encoding="utf-8"))
        except (OSError, ValueError): return
        self.estado.setText(str(data.get("mensaje") or "Trabajando…")); progreso = data.get("progreso")
        if isinstance(progreso, (int, float)): self.barra.setValue(max(0, min(100, int(progreso))))
        progreso_global = data.get("progreso_global")
        if isinstance(progreso_global, (int, float)):
            self.barra_global.setValue(max(0, min(100, int(progreso_global))))
        indice = data.get("carrera_indice")
        total = data.get("carreras_total")
        restantes = data.get("carreras_restantes")
        nombre = data.get("carrera_actual")
        if isinstance(indice, int) and isinstance(total, int):
            self.resumen_progreso.setText(
                f"Carrera {indice}/{total} · {nombre or ''} · quedan {restantes or 0}"
            )
    @Slot(bool, str)
    def finalizar(self, ok, mensaje):
        self.finalizado = True; self.timer.stop(); self.barra.setValue(100 if ok else self.barra.value()); self.estado.setText(mensaje); self.titulo.setText("Publicación completada" if ok else "Publicación con errores")
        self.boton.setText("Cerrar"); self.boton.clicked.disconnect(); self.boton.clicked.connect(self.close)
        self.boton_iniciar.setEnabled(False)
        self.tray.showMessage(
            "Publicador de Fénix",
            mensaje,
            QSystemTrayIcon.MessageIcon.Information if ok else QSystemTrayIcon.MessageIcon.Critical,
            6000,
        )
    def mostrar(self): self.show(); self.raise_(); self.activateWindow()
    def activar_desde_bandeja(self, razon):
        if razon in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.mostrar()
    def ocultar_en_bandeja(self):
        if not self.tray_disponible:
            self.showMinimized()
            return
        self.tray.show()
        self.hide()
        self.tray.showMessage(
            "Publicador en segundo plano",
            "La actualización continúa. Haz clic en el icono de Fénix para volver.",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )
    def solicitar_detencion(self):
        if self.finalizado:
            self.close()
            return
        self.detener_evento.set()
        mensaje = "Deteniendo después de terminar el ciclo en curso…"
        self.estado.setText(mensaje)
        print(f"[Publicador] {mensaje}", flush=True)

    def closeEvent(self, event):
        if not self.started:
            self.tray.hide(); event.accept()
            QTimer.singleShot(0, QApplication.instance().quit)
            return
        if not self.finalizado:
            self.ocultar_en_bandeja(); event.ignore(); return
        self.tray.hide(); event.accept()
        QTimer.singleShot(0, QApplication.instance().quit)

def main():
    parser = argparse.ArgumentParser(description="Actualiza continuamente en Cloudflare los datos académicos de Medellín")
    parser.add_argument(
        "--intervalo-segundos",
        type=int,
        default=intervalo_por_defecto(),
        help="Tiempo entre ciclos completos (también: FENIX_PUBLICADOR_INTERVALO_SEGUNDOS).",
    )
    args = parser.parse_args()
    intervalo = max(60, args.intervalo_segundos)
    app = QApplication(sys.argv); app.setQuitOnLastWindowClosed(False); ventana = VentanaPublicador(intervalo, app); ventana.show()
    return app.exec()
if __name__ == "__main__": raise SystemExit(main())
