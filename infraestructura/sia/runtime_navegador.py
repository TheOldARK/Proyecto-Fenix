"""Ubicación de Chromium nativo en cada distribución de Fénix."""
from pathlib import Path
import sys


def ejecutable_integrado():
    if getattr(sys, 'frozen', False):
        if sys.platform in ('darwin', 'linux'):
            carpeta = (Path(sys.executable).parent.parent / 'Resources' / 'browser'
                       if sys.platform == 'darwin' else Path(sys.executable).parent / 'browser')
            candidatos = [
                ruta for ruta in carpeta.rglob('*')
                if ruta.is_file() and ruta.name in ('chrome-headless-shell', 'headless_shell')
            ]
            if len(candidatos) != 1:
                raise FileNotFoundError('La instalación de Fénix no contiene una única copia de Chromium.')
            return str(candidatos[0])
        return str(Path(sys.executable).parent / 'browser' / 'chrome-headless-shell.exe')
    return None
