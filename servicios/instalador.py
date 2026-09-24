"""Instalador independiente: no importa Qt, Playwright ni datos del estudiante."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
import threading
import time
import traceback
from zipfile import ZipFile

MANIFIESTO = "fenix-manifest.json"


def ruta_larga(ruta):
    texto = os.path.abspath(ruta)
    if os.name == "nt" and not texto.startswith("\\\\?\\"):
        texto = "\\\\?\\UNC\\" + texto[2:] if texto.startswith("\\\\") else "\\\\?\\" + texto
    return Path(texto)


def sha256(ruta):
    with ruta_larga(ruta).open("rb") as archivo:
        return hashlib.file_digest(archivo, "sha256").hexdigest()


def nombre_seguro(nombre):
    nombre = nombre.replace("\\", "/")
    partes = nombre.split("/")
    if (PureWindowsPath(nombre).drive or nombre.startswith("/") or
            any(p in ("", ".", "..") or ":" in p or p.rstrip(" .") != p for p in partes)):
        raise ValueError(f"Ruta no permitida en el paquete: {nombre}")
    if any(PureWindowsPath(p).is_reserved() for p in partes):
        raise ValueError(f"Nombre reservado en el paquete: {nombre}")
    return nombre


def leer_paquete(archivo):
    miembros = {}
    vistos = set()
    for info in archivo.infolist():
        nombre = nombre_seguro(info.filename.rstrip("/\\"))
        if nombre.casefold() in vistos:
            raise ValueError("El ZIP contiene rutas duplicadas.")
        vistos.add(nombre.casefold())
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("El ZIP contiene enlaces simbólicos.")
        if not info.is_dir() and not info.filename.endswith("\\"):
            miembros[nombre] = info
    prefijo = "Fenix/"
    if prefijo + MANIFIESTO not in miembros:
        raise ValueError("El paquete no contiene el manifiesto de integridad de Fénix.")
    manifiesto = json.loads(archivo.read(miembros[prefijo + MANIFIESTO]))
    if manifiesto.get("schema") != 1 or not manifiesto.get("version"):
        raise ValueError("Manifiesto incompatible.")
    esperados = manifiesto["files"]
    if not isinstance(esperados, dict) or not esperados:
        raise ValueError("Manifiesto vacío.")
    for nombre, datos in esperados.items():
        if nombre_seguro(nombre) != nombre or len(datos["sha256"]) != 64 or datos["size"] < 0:
            raise ValueError("Entrada de manifiesto inválida.")
        info = miembros.get(prefijo + nombre)
        if info is None or info.file_size != datos["size"]:
            raise ValueError(f"Paquete incompleto: {nombre}")
    if set(miembros) != {prefijo + n for n in esperados} | {prefijo + MANIFIESTO}:
        raise ValueError("El ZIP y el manifiesto no contienen los mismos archivos.")
    for requerido in ("Fenix.exe", "updater/FenixUpdater.exe"):
        if requerido not in esperados:
            raise ValueError(f"Falta {requerido}")
    if not any(n.startswith("_internal/") for n in esperados):
        raise ValueError("Falta el runtime de Fénix.")
    return manifiesto, miembros


def coincide(ruta, esperado):
    try:
        return ruta_larga(ruta).stat().st_size == esperado["size"] and sha256(ruta) == esperado["sha256"]
    except OSError:
        return False


def extraer_verificado(paquete, nuevo, anterior, registrar=print, progreso=None):
    nuevo, anterior = ruta_larga(nuevo), ruta_larga(anterior)
    with ZipFile(ruta_larga(paquete)) as archivo:
        manifiesto, miembros = leer_paquete(archivo)
        total_bytes = sum(datos["size"] for datos in manifiesto["files"].values()) or 1
        bytes_completados = 0
        necesarios = sum(d["size"] for d in manifiesto["files"].values()) + 64 * 1024**2
        if shutil.disk_usage(nuevo.parent).free < necesarios:
            raise OSError("No hay espacio suficiente para preparar la actualización.")
        nuevo.mkdir(parents=True, exist_ok=True)
        for nombre, esperado in manifiesto["files"].items():
            salida = nuevo / nombre
            salida.parent.mkdir(parents=True, exist_ok=True)
            error = None
            for intento in range(3):
                try:
                    with archivo.open(miembros["Fenix/" + nombre]) as origen, salida.open("wb") as destino:
                        shutil.copyfileobj(origen, destino, 1024 * 1024)
                    if not coincide(salida, esperado):
                        raise ValueError(f"Contenido incorrecto: {nombre}")
                    error = None
                    break
                except (OSError, ValueError) as fallo:
                    error = fallo
                    time.sleep(0.2)
            if error is not None:
                origen = anterior / nombre
                # Reutilizar únicamente bytes idénticos a los publicados.
                if coincide(origen, esperado):
                    shutil.copyfile(origen, salida)
                    registrar(f"Recuperado de la instalación anterior: {nombre}")
                if not coincide(salida, esperado):
                    raise OSError(f"No se pudo recuperar {nombre}: {error}") from error
            bytes_completados += esperado["size"]
            if progreso is not None:
                avance = 5 + int(bytes_completados * 73 / total_bytes)
                progreso(f"Instalando archivos… {nombre}", avance)
        (nuevo / MANIFIESTO).write_text(json.dumps(manifiesto), encoding="utf-8")
    verificar_instalacion(nuevo, manifiesto)
    return manifiesto


def verificar_instalacion(raiz, manifiesto):
    for nombre, esperado in manifiesto["files"].items():
        if not coincide(ruta_larga(raiz) / nombre, esperado):
            raise ValueError(f"Verificación de integridad fallida: {nombre}")


def esperar_cierre(pid, timeout=120000):
    if pid == os.getpid():
        raise RuntimeError("El instalador no puede actualizarse a sí mismo.")
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(handle, timeout) != 0:
            raise RuntimeError("Fénix sigue abierto; cierra todas sus ventanas y vuelve a intentar.")
    finally:
        kernel.CloseHandle(handle)


def mover(origen, destino):
    for intento in range(60):
        try:
            ruta_larga(origen).rename(ruta_larga(destino))
            return
        except OSError as error:
            if getattr(error, "winerror", None) not in (5, 32, 33) or intento == 59:
                raise
            time.sleep(0.5)


def guardar(ruta, valor):
    ruta = ruta_larga(ruta)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(valor, ensure_ascii=False), encoding="utf-8")
    temporal.replace(ruta)


def diagnosticar(destino, datos):
    entorno = os.environ.copy()
    entorno["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    entorno["FENIX_DATA_DIR"] = str(datos)
    proceso = subprocess.Popen([str(destino / "Fenix.exe"), "--diagnostico"],
                               cwd=str(destino.parent), env=entorno)
    try:
        codigo = proceso.wait(timeout=90)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/PID", str(proceso.pid), "/T", "/F"], capture_output=True)
        proceso.wait(timeout=10)
        raise RuntimeError("La nueva versión no terminó su diagnóstico.")
    if codigo:
        raise RuntimeError(f"La nueva versión falló su diagnóstico ({codigo}).")


class VentanaProgresoWindows:
    """Pequeña ventana nativa que mantiene visible el trabajo del updater.

    El actualizador se ejecuta después de cerrar Fénix y no puede reutilizar
    Qt porque debe seguir siendo un ejecutable pequeño e independiente. Esta
    ventana usa únicamente User32 y anima un indicador mientras se extraen,
    verifican e intercambian los archivos.
    """

    def __init__(self):
        self._texto = "Preparando la actualización…"
        self._indice = 0
        self._progreso = 0
        self._frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        self._bloqueo = threading.Lock()
        self._detener = threading.Event()
        self._listo = threading.Event()
        self._hwnd = None
        self._error = None
        self._hilo = threading.Thread(target=self._ejecutar, daemon=True)
        self._hilo.start()
        self._listo.wait(2)

    def actualizar(self, texto, progreso=None):
        with self._bloqueo:
            self._texto = str(texto)
            if progreso is not None:
                self._progreso = max(0, min(100, int(progreso)))

    def cerrar(self):
        self._detener.set()
        if self._hwnd:
            try:
                import ctypes
                ctypes.windll.user32.PostMessageW(self._hwnd, 0x0010, 0, 0)
            except OSError:
                pass
        self._hilo.join(timeout=2)

    def _ejecutar(self):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE,
                wintypes.LPVOID,
            ]
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.LoadCursorW.restype = wintypes.HANDLE
            user32.GetSystemMetrics.restype = ctypes.c_int
            gdi32 = ctypes.windll.gdi32
            gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
            gdi32.SetTextColor.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            gdi32.SetBkMode.argtypes = [wintypes.HANDLE, ctypes.c_int]
            gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
            kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                wintypes.WPARAM, wintypes.LPARAM,
            )

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            clase = "FenixUpdaterProgress"
            instancia = kernel32.GetModuleHandleW(None)
            fondo = gdi32.CreateSolidBrush(0x00202020)
            control = {"estado": None, "progreso": None, "pie": None}

            @WNDPROC
            def procedimiento(hwnd, mensaje, wparam, lparam):
                if mensaje == 0x0113:  # WM_TIMER
                    with self._bloqueo:
                        texto = self._texto
                        porcentaje = self._progreso
                        frame = self._frames[self._indice]
                        self._indice = (self._indice + 1) % len(self._frames)
                    if control["estado"]:
                        user32.SetWindowTextW(
                            control["estado"], f"{frame}   {texto}"
                        )
                    if control["progreso"]:
                        user32.SendMessageW(control["progreso"], 0x0402, porcentaje, 0)
                    if control["pie"]:
                        user32.SetWindowTextW(control["pie"], f"{porcentaje}% completado")
                    return 0
                if mensaje == 0x0138:  # WM_CTLCOLORSTATIC
                    gdi32.SetTextColor(wintypes.HANDLE(wparam), 0x00F2F2F2)
                    gdi32.SetBkMode(wintypes.HANDLE(wparam), 1)  # TRANSPARENT
                    return fondo
                if mensaje == 0x0010:  # WM_CLOSE
                    user32.DestroyWindow(hwnd)
                    return 0
                if mensaje == 0x0002:  # WM_DESTROY
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, mensaje, wparam, lparam)

            clase_info = WNDCLASSW()
            clase_info.lpfnWndProc = procedimiento
            clase_info.hInstance = instancia
            clase_info.hCursor = user32.LoadCursorW(None, 32512)  # IDC_ARROW: el updater nunca activa cursor de espera
            clase_info.lpszClassName = clase
            clase_info.hbrBackground = fondo
            user32.RegisterClassW(ctypes.byref(clase_info))
            ancho, alto = 520, 205
            x = max(0, (user32.GetSystemMetrics(0) - ancho) // 2)
            y = max(0, (user32.GetSystemMetrics(1) - alto) // 2)
            hwnd = user32.CreateWindowExW(
                0, clase, "Fénix · Actualizando", 0x00C80000,
                x, y, ancho, alto,
                None, None, instancia, None,
            )
            if not hwnd:
                return
            self._hwnd = hwnd
            control["estado"] = user32.CreateWindowExW(
                0, "STATIC", "Preparando la actualización…", 0x50000000,
                22, 24, 470, 42, hwnd, None, instancia, None,
            )
            control["progreso"] = user32.CreateWindowExW(
                0, "msctls_progress32", "", 0x50000001,
                22, 83, 470, 20, hwnd, None, instancia, None,
            )
            control["pie"] = user32.CreateWindowExW(
                0, "STATIC", "0% completado", 0x50000000,
                22, 116, 470, 24, hwnd, None, instancia, None,
            )
            pie_info = user32.CreateWindowExW(
                0, "STATIC", "Fénix volverá a abrirse al terminar.", 0x50000000,
                22, 150, 470, 24, hwnd, None, instancia, None,
            )
            user32.SendMessageW(control["progreso"], 0x0401, 0, 100)  # PBM_SETRANGE32
            fuente = ctypes.windll.gdi32.GetStockObject(17)  # DEFAULT_GUI_FONT
            for control_texto in (control["estado"], control["pie"], pie_info):
                user32.SendMessageW(control_texto, 0x0030, fuente, 1)  # WM_SETFONT
            user32.ShowWindow(hwnd, 1)
            user32.UpdateWindow(hwnd)
            user32.SetTimer(hwnd, 1, 120, None)
            self._listo.set()
            mensaje = wintypes.MSG()
            while not self._detener.is_set():
                resultado = user32.GetMessageW(ctypes.byref(mensaje), None, 0, 0)
                if resultado <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(mensaje))
                user32.DispatchMessageW(ctypes.byref(mensaje))
        except Exception as error:
            # La interfaz es auxiliar: nunca debe impedir una actualización.
            self._error = repr(error)
            self._listo.set()
        finally:
            self._hwnd = None
            if 'fondo' in locals() and fondo:
                gdi32.DeleteObject(fondo)


def instalar(job):
    destino = Path(job["instalacion"]).resolve()
    if destino.parent == destino or not destino.name:
        raise ValueError("Carpeta de instalación inválida.")
    identidad = hashlib.sha256(str(destino).casefold().encode()).hexdigest()[:12]
    trabajo = destino.parent / (".fx-" + identidad)
    ruta_larga(trabajo).mkdir(exist_ok=True)
    nuevo, respaldo = trabajo / "nuevo", trabajo / "anterior"
    estado = trabajo / "estado.json"
    registro = trabajo / "actualizacion.log"

    def registrar(texto):
        with ruta_larga(registro).open("a", encoding="utf-8") as salida:
            salida.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")

    # El bloqueo lo libera Windows incluso si el instalador se interrumpe.
    lock = ruta_larga(trabajo / "lock").open("a+b")
    adquirido = False
    ventana = None
    try:
        if os.name == "nt":
            import msvcrt
            lock.write(b"0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        adquirido = True
        if getattr(sys, "frozen", False) and os.name == "nt" and not job.get("prueba"):
            ventana = VentanaProgresoWindows()
        guardar(job["ready"], {"pid": os.getpid()})
        registrar("Esperando cierre de Fénix")
        if ventana:
            ventana.actualizar("Esperando a que Fénix termine…", 2)
        esperar_cierre(int(job["pid"]))
        previo = json.loads(ruta_larga(estado).read_text(encoding="utf-8")) if ruta_larga(estado).exists() else {}
        if ruta_larga(respaldo).exists():
            if previo.get("fase") == "completada":
                shutil.rmtree(ruta_larga(respaldo))
            else:
                if ruta_larga(destino).exists():
                    fallida = trabajo / ("interrumpida-" + str(time.time_ns()))
                    mover(destino, fallida)
                mover(respaldo, destino)
                registrar("Instalación anterior restaurada tras interrupción")
        if not ruta_larga(destino / "Fenix.exe").is_file():
            raise ValueError("No se encontró Fenix.exe en la instalación original.")
        if ruta_larga(nuevo).exists():
            shutil.rmtree(ruta_larga(nuevo))
        guardar(estado, {"fase": "preparando"})
        registrar("Extrayendo y verificando todos los archivos")
        if ventana:
            ventana.actualizar("Preparando archivos para instalar…", 4)
        manifiesto = extraer_verificado(
            job["paquete"], nuevo, destino, registrar,
            progreso=ventana.actualizar if ventana else None,
        )
        guardar(estado, {"fase": "intercambiando", "version": manifiesto["version"]})
        if ventana:
            ventana.actualizar("Verificando y activando la nueva versión…", 82)
        mover(destino, respaldo)
        try:
            mover(nuevo, destino)
            verificar_instalacion(destino, manifiesto)
            registrar("Comprobando Qt y Chromium desde la instalación final")
            if ventana:
                ventana.actualizar("Comprobando Fénix y Chromium…", 90)
            diagnosticar(destino, trabajo / "diagnostico")
            entorno = os.environ.copy()
            entorno["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            proceso = subprocess.Popen([str(destino / "Fenix.exe")], cwd=str(destino.parent), env=entorno)
        except Exception:
            if ruta_larga(destino).exists():
                mover(destino, trabajo / ("fallida-" + str(time.time_ns())))
            mover(respaldo, destino)
            registrar("Se restauró la versión anterior")
            raise
        guardar(estado, {"fase": "completada", "version": manifiesto["version"]})
        guardar(job["resultado"], {"ok": True, "version": manifiesto["version"], "pid": proceso.pid, "log": str(registro)})
        registrar("Actualización completada; nueva interfaz iniciada")
        if ventana:
            ventana.actualizar("Actualización completada. Iniciando Fénix…", 100)
        try:
            shutil.rmtree(ruta_larga(respaldo))
        except OSError as error:
            registrar(f"Respaldo conservado: {error}")
        return 0
    except Exception as error:
        registrar(traceback.format_exc())
        guardar(job["resultado"], {"ok": False, "error": str(error), "log": str(registro)})
        return 1
    finally:
        if ventana:
            ventana.actualizar("Fénix se reiniciará en un momento…", 100)
            ventana.cerrar()
        if adquirido and os.name == "nt":
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


def main():
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        codigo = instalar(job)
    except Exception as error:
        guardar(job["resultado"], {"ok": False, "error": str(error)})
        codigo = 1
    if codigo and os.name == "nt" and not job.get("prueba"):
        import ctypes
        detalle = json.loads(Path(job["resultado"]).read_text(encoding="utf-8"))
        ctypes.windll.user32.MessageBoxW(None, "No se pudo completar la actualización.\n" + detalle["error"] +
                                       "\nRegistro: " + detalle.get("log", job["resultado"]), "Fénix", 0x10)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
