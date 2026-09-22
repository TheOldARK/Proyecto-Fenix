"""Ubicación corta de Chromium en la distribución portátil de Windows."""
from pathlib import Path
import sys


def ejecutable_integrado():
    if getattr(sys, 'frozen', False):
        return str(Path(sys.executable).parent / 'browser' / 'chrome-headless-shell.exe')
    return None
