"""Arranque compartido por el código fuente y el ejecutable Windows."""

import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import threading

from configuracion import BASE_DIR, CARPETA_DATOS, CARPETA_DATOS_BASE, VERSION
from infraestructura.almacenamiento.json_atomico import guardar_json_atomico

ARCHIVOS_BASE = (
    "catalogo_sia.json",
    "planes_estudio.json",
    "configuracion_libre_eleccion.json",
)


def comando_fenix(*argumentos):
    """El ejecutable empaquetado no es un intérprete de archivos .py."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *argumentos]
    return [sys.executable, str(BASE_DIR / "main.py"), *argumentos]


def inicializar_datos_usuario():
    """Instala solo los datos base que falten; conserva el perfil y respaldos."""
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    for nombre in ARCHIVOS_BASE:
        destino = CARPETA_DATOS / nombre
        if not destino.exists():
            with (CARPETA_DATOS_BASE / nombre).open(encoding="utf-8") as archivo:
                guardar_json_atomico(destino, json.load(archivo))


class SalidaRegistro(io.TextIOBase):
    """Conserva la salida del actualizador cuando Windows no abre consola."""

    def __init__(self, registro, nivel):
        self.registro = registro
        self.nivel = nivel

    @property
    def encoding(self):
        return "utf-8"

    def writable(self):
        return True

    def write(self, texto):
        texto = str(texto)
        if texto.strip():
            self.registro.log(self.nivel, texto.rstrip())
        return len(texto)

    def flush(self):
        for manejador in self.registro.handlers:
            manejador.flush()


def preparar_entorno():
    """Prepara datos, navegador integrado y diagnóstico antes de abrir Qt."""
    inicializar_datos_usuario()
    if getattr(sys, "frozen", False):
        # Playwright buscará su navegador dentro del paquete distribuido.
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    carpeta_logs = CARPETA_DATOS / "logs"
    carpeta_logs.mkdir(exist_ok=True)
    rol = "actualizacion" if "--actualizar-solo" in sys.argv else "interfaz"
    registro = logging.getLogger("fenix")
    if not registro.handlers:
        manejador = RotatingFileHandler(
            carpeta_logs / f"{rol}.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        registro.addHandler(manejador)
        registro.setLevel(logging.INFO)
        registro.propagate = False

    if sys.stdout is None:
        sys.stdout = SalidaRegistro(registro, logging.INFO)
    if sys.stderr is None:
        sys.stderr = SalidaRegistro(registro, logging.ERROR)

    def registrar_excepcion(tipo, valor, traza):
        registro.critical("Error no controlado", exc_info=(tipo, valor, traza))
        if not getattr(sys, "frozen", False):
            sys.__excepthook__(tipo, valor, traza)

    sys.excepthook = registrar_excepcion
    threading.excepthook = lambda argumentos: registrar_excepcion(
        argumentos.exc_type, argumentos.exc_value, argumentos.exc_traceback
    )
    registro.info("Fénix %s · %s · inicio", VERSION, rol)
