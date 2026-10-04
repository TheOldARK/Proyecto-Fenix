@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv-distribucion\Scripts\python.exe" (
    echo No se encontro el Python de desarrollo de Fenix.
    echo Ejecuta herramientas\verificar_planes_sia.py con el entorno Python del proyecto.
    pause
    exit /b 2
)
".venv-distribucion\Scripts\python.exe" "herramientas\verificar_planes_sia.py" %*
echo.
echo Comprobacion finalizada. La ruta de los informes aparece arriba.
pause
