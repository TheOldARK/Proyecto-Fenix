"""Abre el Gestor de publicadores incluido en Fenix.exe."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _buscar_fenix(carpeta: Path) -> Path | None:
    """Localiza Fénix junto al gestor o en el paquete distribuible Fenix/."""
    for candidato in (carpeta / "Fenix.exe", carpeta / "Fenix" / "Fenix.exe"):
        if candidato.is_file():
            return candidato
    return None


def _mostrar_error(mensaje: str) -> None:
    """Muestra errores aunque el lanzador se haya construido sin consola."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, mensaje, "Gestor de Fénix", 0x10)
            return
        except (AttributeError, OSError):
            pass
    print(mensaje, file=sys.stderr, flush=True)


def main() -> int:
    carpeta = Path(sys.executable).resolve().parent
    fenix = _buscar_fenix(carpeta)
    if fenix is None:
        _mostrar_error(
            "No se encontró Fenix.exe junto al gestor ni dentro de la carpeta Fenix.\n\n"
            f"Ubicación del gestor: {carpeta}\n"
            "Ejecuta FenixGestor.exe desde la carpeta completa de Fénix."
        )
        return 2
    return subprocess.call(
        [str(fenix), "--gestor-publicadores", *sys.argv[1:]],
        cwd=str(carpeta),
    )


if __name__ == "__main__":
    raise SystemExit(main())
