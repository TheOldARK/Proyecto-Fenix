"""Ubicación de Chromium en la distribución de Windows o en Fenix.app."""
from pathlib import Path
import sys


def ejecutable_integrado():
    if getattr(sys, 'frozen', False):
        if sys.platform == 'darwin':
            carpeta = Path(sys.executable).parent.parent / 'Resources' / 'browser'
            candidatos = [
                ruta for ruta in carpeta.rglob('*')
                if ruta.is_file() and ruta.name in ('chrome-headless-shell', 'headless_shell')
            ]
            if len(candidatos) != 1:
                raise FileNotFoundError('Fenix.app no contiene una única copia de Chromium.')
            return str(candidatos[0])
        return str(Path(sys.executable).parent / 'browser' / 'chrome-headless-shell.exe')
    return None
