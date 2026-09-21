# Proyecto Fénix — Material para GitHub

Esta carpeta reúne la información de publicación del proyecto. El repositorio
de GitHub debe contener el código fuente y los archivos de construcción de
Fénix, pero no los ejecutables generados ni los datos personales de usuarios.

## Debe publicarse

- `aplicacion/`, `dominio/`, `infraestructura/`, `servicios/`
- `recursos/` y `datos/` únicamente con catálogos base públicos
- `main.py`, `configuracion.py`, `Fenix.spec`
- `construir_windows.ps1`, `requirements.txt`, `requirements-build.txt`
- `README.md`, `LICENSE` y `LEEME_BETA.txt`

## No debe publicarse

- `dist/`, `build/`, `.venv-distribucion/`, `__pycache__/` ni `*.pyc`
- `estudiante.json`, `materias.json`, `oferta.json`, `libres_eleccion.json`
- estados, cancelaciones, logs y diagnósticos locales

Los datos personales se guardan fuera de la instalación, en
`%LOCALAPPDATA%\Fenix`.

Cada versión debe publicarse como un GitHub Release con un ZIP completo,
por ejemplo `Fenix-0.1.0-beta.5-windows-x64.zip`, que incluya `Fenix.exe` y
su carpeta `_internal`.

