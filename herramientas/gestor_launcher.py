"""Abre el Gestor de publicadores incluido en Fenix.exe."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    carpeta = Path(sys.executable).resolve().parent
    fenix = carpeta / "Fenix.exe"
    if not fenix.is_file():
        print(f"ERROR: no se encontró Fenix.exe en {carpeta}", flush=True)
        input("Presiona Enter para cerrar esta ventana…")
        return 2
    return subprocess.call(
        [str(fenix), "--gestor-publicadores", *sys.argv[1:]],
        cwd=str(carpeta),
    )


if __name__ == "__main__":
    raise SystemExit(main())
