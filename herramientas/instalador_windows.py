"""Instalador gráfico autocontenido de Fénix.

El ejecutable se construye con PyInstaller incluyendo una carpeta ``Fenix``
como datos. No depende de Python en el equipo del usuario.
"""

from __future__ import annotations

import os
import json
import shutil
import ssl
import sys
import tempfile
import threading
import tkinter as tk
import subprocess
import base64
import ctypes
import queue
import urllib.request
import zipfile
import certifi
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


RELEASE_API = "https://api.github.com/repos/TheOldARK/Proyecto-Fenix/releases"


def _contexto_tls():
    return ssl.create_default_context(cafile=certifi.where())


class Instalador(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Instalar Fénix")
        self.resizable(False, False)
        self.geometry("560x300")
        self.destino = tk.StringVar(
            value=str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Fenix")
        )
        self.acceso_directo = tk.BooleanVar(value=True)
        self.estado = tk.StringVar(value="Elige dónde quieres instalar Fénix.")
        self.eventos: queue.Queue[tuple[str, object]] = queue.Queue()
        self._crear_interfaz()
        self.after(100, self._procesar_eventos)

    def _procesar_eventos(self) -> None:
        try:
            while True:
                tipo, dato = self.eventos.get_nowait()
                if tipo == "estado":
                    self.estado.set(str(dato))
                elif tipo == "correcto":
                    self._terminar(True, dato)
                    return
                elif tipo == "error":
                    self._terminar(False, dato)
                    return
        except queue.Empty:
            pass
        self.after(100, self._procesar_eventos)

    def _estado_async(self, texto: str) -> None:
        self.eventos.put(("estado", texto))

    def _crear_interfaz(self) -> None:
        marco = ttk.Frame(self, padding=18)
        marco.pack(fill="both", expand=True)
        ttk.Label(marco, text="Fénix", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(marco, text="Instalador para Windows · descargará la versión estable más reciente", foreground="#555555").pack(anchor="w", pady=(0, 14))
        ttk.Label(marco, text="Carpeta de instalación:").pack(anchor="w")
        fila = ttk.Frame(marco)
        fila.pack(fill="x", pady=(4, 12))
        ttk.Entry(fila, textvariable=self.destino, width=54).pack(side="left", fill="x", expand=True)
        ttk.Button(fila, text="Examinar…", command=self._elegir).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(marco, text="Crear un acceso directo en el escritorio", variable=self.acceso_directo).pack(anchor="w", pady=(0, 10))
        self.progreso = ttk.Progressbar(marco, mode="indeterminate")
        self.progreso.pack(fill="x", pady=(0, 8))
        ttk.Label(marco, textvariable=self.estado, wraplength=480).pack(anchor="w")
        botones = ttk.Frame(marco)
        botones.pack(anchor="e", pady=(14, 0))
        self.boton_instalar = ttk.Button(botones, text="Instalar", command=self._iniciar)
        self.boton_instalar.pack(side="left")
        ttk.Button(botones, text="Cancelar", command=self.destroy).pack(side="left", padx=(8, 0))

    def _elegir(self) -> None:
        ruta = filedialog.askdirectory(initialdir=self.destino.get(), title="Elige la carpeta de instalación")
        if ruta:
            self.destino.set(ruta)

    def _iniciar(self) -> None:
        destino = Path(self.destino.get()).expanduser()
        if (destino / "Fenix.exe").is_file():
            continuar = messagebox.askyesno(
                "Fénix ya está instalado",
                f"Ya existe una instalación en:\n{destino}\n\n¿Quieres reemplazarla?",
            )
            if not continuar:
                return
        crear_acceso = bool(self.acceso_directo.get())
        self.boton_instalar.configure(state="disabled")
        self.progreso.start(12)
        self.estado.set("Copiando archivos de Fénix…")
        threading.Thread(target=self._instalar, args=(destino, crear_acceso), daemon=True).start()

    def _instalar(self, destino: Path, crear_acceso: bool) -> None:
        try:
            self._estado_async("Comprobando la versión disponible en GitHub…")
            solicitud = urllib.request.Request(RELEASE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "Proyecto-Fenix"})
            with urllib.request.urlopen(solicitud, timeout=15, context=_contexto_tls()) as respuesta:
                releases = json.load(respuesta)
            validas = []
            for release in releases if isinstance(releases, list) else []:
                if release.get("draft") or release.get("prerelease"):
                    continue
                etiqueta = str(release.get("tag_name", "")).removeprefix("v")
                partes = etiqueta.split(".")
                if len(partes) < 3 or not all(p.isdigit() for p in partes[:3]):
                    continue
                nombre = f"Fenix-{etiqueta}-windows-x64.zip"
                asset = next((a for a in release.get("assets", []) if a.get("name") == nombre), None)
                if asset and asset.get("browser_download_url"):
                    validas.append((tuple(int(p) for p in partes[:3]), release, asset))
            if not validas:
                raise RuntimeError("No hay una versión estable de Windows publicada.")
            _, release, asset = max(validas, key=lambda item: item[0])
            if not asset:
                raise RuntimeError("La release no contiene un paquete ZIP de Windows.")
            paquete = Path(tempfile.mkstemp(prefix="fenix-paquete-", suffix=".zip")[1])
            try:
                self._estado_async(f"Descargando Fénix {release.get('tag_name', '')}…")
                descarga = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "Fenix-Installer"})
                with urllib.request.urlopen(descarga, timeout=180, context=_contexto_tls()) as origen, paquete.open("wb") as salida:
                    total = int(origen.headers.get("Content-Length", "0"))
                    copiados = 0
                    while True:
                        bloque = origen.read(1024 * 1024)
                        if not bloque:
                            break
                        salida.write(bloque)
                        copiados += len(bloque)
                        if total:
                            porcentaje = copiados * 100 // total
                            self._estado_async(f"Descargando Fénix… {porcentaje}%")
                        else:
                            megas = copiados // (1024 * 1024)
                            self._estado_async(f"Descargando Fénix… {megas} MB")
                self._estado_async("Verificando y preparando los archivos…")
                temporal = Path(tempfile.mkdtemp(prefix="fenix-instala-"))
                try:
                    with zipfile.ZipFile(paquete) as archivo:
                        raiz = temporal / "Fenix"
                        miembros = archivo.infolist()
                        total_archivos = max(1, len(miembros))
                        for indice, miembro in enumerate(miembros, 1):
                            destino_miembro = (raiz / miembro.filename).resolve()
                            if not str(destino_miembro).startswith(str(raiz.resolve()) + os.sep):
                                raise RuntimeError("El paquete contiene una ruta no válida.")
                            if miembro.is_dir():
                                destino_miembro.mkdir(parents=True, exist_ok=True)
                            else:
                                destino_miembro.parent.mkdir(parents=True, exist_ok=True)
                                with archivo.open(miembro) as origen, destino_miembro.open("wb") as salida:
                                    shutil.copyfileobj(origen, salida, 1024 * 1024)
                            porcentaje = indice * 100 // total_archivos
                            self._estado_async(f"Extrayendo archivos… {porcentaje}%")
                    if not (raiz / "Fenix.exe").is_file() and (raiz / "Fenix" / "Fenix.exe").is_file():
                        raiz = raiz / "Fenix"
                    if not (raiz / "Fenix.exe").is_file():
                        raise RuntimeError("El paquete descargado no contiene Fenix.exe.")
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    if destino.exists():
                        respaldo = destino.with_name(destino.name + ".previous")
                        shutil.rmtree(respaldo, ignore_errors=True)
                        os.replace(destino, respaldo)
                    os.replace(raiz, destino)
                    if crear_acceso:
                        self._estado_async("Creando el acceso directo…")
                        escritorio = self._escritorio()
                        acceso = escritorio / "Fénix.lnk"
                        comando = (
                            "$s=New-Object -ComObject WScript.Shell; "
                            f"$l=$s.CreateShortcut('{acceso}'); "
                            f"$l.TargetPath='{destino / 'Fenix.exe'}'; "
                            f"$l.WorkingDirectory='{destino}'; $l.Save()"
                        )
                        codificado = base64.b64encode(comando.encode("utf-16le")).decode("ascii")
                        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", codificado], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                        if not acceso.exists():
                            raise RuntimeError(f"Windows no creó el acceso directo en: {acceso}")
                        try:
                            ctypes.windll.shell32.SHChangeNotify(0x8000000, 0x1000, None, None)
                        except Exception:
                            pass
                        self._estado_async(f"Acceso directo creado en: {acceso}")
                    # El hilo principal abre Fénix y cierra el instalador. El
                    # resultado se publica antes de limpiar temporales para que
                    # una limpieza lenta nunca retenga la interfaz.
                    self.eventos.put(("correcto", destino))
                finally:
                    shutil.rmtree(temporal, ignore_errors=True)
            finally:
                paquete.unlink(missing_ok=True)
        except Exception as exc:  # pragma: no cover - depende del sistema anfitrión
            self.eventos.put(("error", str(exc)))

    @staticmethod
    def _escritorio() -> Path:
        """Obtiene el escritorio real, incluido el redirigido por OneDrive."""
        try:
            salida = subprocess.check_output(
                ["reg.exe", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders", "/v", "Desktop"],
                text=True, encoding="mbcs", creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for linea in salida.splitlines():
                if "Desktop" in linea and "REG_" in linea:
                    ruta = linea.split("REG_EXPAND_SZ", 1)[-1].strip()
                    ruta = os.path.expandvars(ruta)
                    candidato = Path(ruta)
                    candidato.mkdir(parents=True, exist_ok=True)
                    return candidato
        except Exception:
            pass
        candidatos = [
            Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop",
            Path(os.environ.get("USERPROFILE", str(Path.home()))) / "OneDrive" / "Desktop",
        ]
        for candidato in candidatos:
            if candidato.exists():
                return candidato
        candidatos[0].mkdir(parents=True, exist_ok=True)
        return candidatos[0]

    def _terminar(self, correcto: bool, dato: object) -> None:
        self.progreso.stop()
        if correcto:
            self.estado.set(f"Instalación terminada en {dato}")
            ejecutable = Path(dato) / "Fenix.exe"
            try:
                if not ejecutable.is_file():
                    raise FileNotFoundError(f"No se encontró {ejecutable}")
                os.startfile(str(ejecutable))
            except Exception as exc:
                messagebox.showerror("Fénix no pudo iniciarse", str(exc))
            self.destroy()
        else:
            self.boton_instalar.configure(state="normal")
            self.estado.set("No se pudo completar la instalación.")
            messagebox.showerror("Error de instalación", str(dato))


if __name__ == "__main__":
    Instalador().mainloop()
