"""Lanza la interfaz de publicación usando el runtime de Fénix."""
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
    argumentos = [str(fenix), "--publicador", *sys.argv[1:]]
    print(f"Iniciando el publicador de Fénix ({' '.join(sys.argv[1:])})…", flush=True)
    resultado = subprocess.call(argumentos, cwd=str(carpeta))
    if resultado:
        print(f"ERROR: Fénix terminó con código {resultado}.", flush=True)
        input("Presiona Enter para cerrar esta ventana…")
    return resultado


if __name__ == "__main__":
    raise SystemExit(main())
