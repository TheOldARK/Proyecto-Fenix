# Estructura recomendada del repositorio

```text
Proyecto-Fenix/
├── .github/workflows/validar.yml
├── aplicacion/
├── datos/
├── dominio/
├── infraestructura/
├── recursos/
├── servicios/
├── Fenix.spec
├── construir_windows.ps1
├── configuracion.py
├── main.py
├── requirements.txt
├── requirements-build.txt
├── README.md
└── LICENSE
```

Los ejecutables se adjuntan como Assets de cada Release, no dentro del código:

```text
v1.1.3
└── Fenix-1.1.3-windows-x64.zip
```

La actualización reemplaza el ZIP instalado, pero conserva `%LOCALAPPDATA%\Fenix`.
