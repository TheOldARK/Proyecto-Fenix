# Fénix

Fénix es una herramienta de escritorio para consultar la oferta académica del Sistema de Información Académica (SIA) y organizar horarios compatibles para estudiantes de la **Universidad Nacional de Colombia**.

## Alcance de esta versión

La primera versión presentable está deliberadamente enfocada en una única ruta académica:

- **Sede:** Medellín (`1102`)
- **Facultad:** Minas (`3068`)
- **Nivel:** Pregrado
- **Planes incluidos:** los 12 planes de pregrado actualmente registrados para la Facultad de Minas

El alcance reducido no es una limitación accidental: permite estabilizar la navegación del SIA, validar la experiencia de usuario y presentar una base funcional antes de incorporar otras facultades o sedes.

## Funcionalidades

Fénix puede conectarse al catálogo público del SIA, obtener materias normales y de Libre Elección, extraer créditos, prerrequisitos, grupos, docentes, cupos y horarios, y guardar los datos localmente. La información se conserva separando los datos relativamente estables de las materias y la oferta académica del período actual.

La aplicación permite seleccionar materias y grupos, detectar cruces de horario, mostrar detalles de cada asignatura, restaurar selecciones entre ejecuciones y exportar o importar el estado del estudiante mediante archivos `.fnx`. La actualización se ejecuta en segundo plano, utiliza varios workers con sesiones independientes y cuenta con reintentos para tolerar la inestabilidad del SIA.

## Instalación

Para desarrollar se requiere Python 3.11 o posterior. La construcción para
Windows usa Python 3.12 de 64 bits. Las dependencias principales son PySide6,
Playwright y BeautifulSoup4. Los usuarios del ZIP no necesitan instalar Python.

```bash
pip install -r requirements.txt
playwright install chromium
```

## Ejecución

Desde la carpeta raíz del proyecto:

```bash
python main.py
```

Para ejecutar únicamente la actualización sin abrir la interfaz:

```bash
python main.py --actualizar-solo
```

## Arquitectura

```text
Fénix/
├── main.py
├── configuracion.py
├── requirements.txt
├── LICENSE
├── README.md
├── aplicacion/
│   ├── estado.py
│   └── interfaz.py
├── dominio/
│   ├── grupo.py
│   ├── horario.py
│   ├── materia.py
│   └── plan_estudios.py
├── infraestructura/
│   ├── almacenamiento/
│   └── sia/
│       ├── navegador.py
│       ├── catalogo_local.py
│       ├── catalogo_sia.py
│       ├── extractor_asignatura.py
│       └── parser/
├── servicios/
│   ├── actualizacion.py
│   ├── conflictos.py
│   ├── elegibilidad.py
│   ├── horarios.py
│   ├── prerrequisitos.py
│   ├── recomendaciones.py
│   └── tipos_materia.py
├── datos/
└── recursos/
```

La capa `dominio` contiene las entidades académicas. `infraestructura` se ocupa del SIA y de la persistencia JSON. `servicios` coordina la actualización, la elegibilidad, las recomendaciones y los conflictos de horario. `aplicacion` conecta la lógica con la interfaz gráfica.

## Datos locales

La carpeta `datos/` del proyecto contiene exclusivamente las plantillas base:

- `catalogo_sia.json`: ruta académica disponible en el SIA, limitada a Medellín–Minas.
- `planes_estudio.json`: planes, asignaturas y créditos de Minas.
- `configuracion_libre_eleccion.json`: rutas de Libre Elección para los planes de Minas incluidos.

Al iniciar, las plantillas que falten se copian a `%LOCALAPPDATA%\Fenix`.
En esa carpeta se conservan el estado del estudiante, las materias descargadas,
la oferta, el progreso y la cancelación de tareas. No se sobrescriben los datos
existentes al instalar una versión nueva. La persistencia usa escritura atómica.
Los registros rotativos de diagnóstico están en `%LOCALAPPDATA%\Fenix\logs`.
La variable opcional `FENIX_DATA_DIR` permite elegir otra carpeta de datos para
comprobaciones aisladas; se hereda en el proceso actualizador.

## Primera ejecución

Esta copia se entrega sin perfil de estudiante, materias descargadas ni horario
guardado. La carpeta `datos/` contiene únicamente los tres archivos base
indicados arriba; deben conservarse para poder elegir un plan y consultar el SIA.

Al abrir Fénix por primera vez, se solicita el plan de estudios y el avance
académico. La oferta se obtiene del SIA y los datos de uso se generan durante la
ejecución. Se necesita conexión a Internet para esa descarga inicial.

Esta versión no incluye las pruebas automatizadas ni el editor administrativo de
planes. En el paquete Windows se abre `Fenix.exe`; para ejecutar el código fuente
se requieren Python y las dependencias de la sección Instalación.

## Generar una versión para Windows

Desde PowerShell, en esta carpeta y con Python 3.12 x64 instalado:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\construir_windows.ps1
```

El script crea `.venv-distribucion`, instala las versiones fijadas en
`requirements-build.txt`, descarga Chromium y construye el programa usando
`Fenix.spec`. Puede indicarse otro intérprete mediante `-Python "C:\ruta\python.exe"`.
Se necesita Internet y espacio para el entorno, el navegador y el ZIP.

El resultado es `dist\Fenix\Fenix.exe` y un ZIP con el número de versión actual,
por ejemplo `dist\Fenix-1.1.2-windows-x64.zip`.
Se comparte el ZIP completo; el destinatario debe extraerlo antes de abrir el
ejecutable y conservar `_internal`. El paquete incluye Python, Qt, Chromium,
recursos y solo las tres plantillas base. No incluye perfiles ni descargas aunque
existan en el equipo de desarrollo. La salida puede firmarse digitalmente mediante
el parámetro `-Certificado`; sin certificado, el ejecutable no lleva firma digital.

Para revisar una instalación sin descargar la oferta académica:

```powershell
Start-Process -FilePath .\dist\Fenix\Fenix.exe -ArgumentList '--diagnostico' -Wait
```

El resultado queda en `%LOCALAPPDATA%\Fenix\logs\diagnostico_instalacion.json`.
Añadir `--consultar-sia` comprueba también que se abre el formulario público del
SIA. El diagnóstico verifica Qt, los recursos, los planes y el Chromium integrado.
Antes de publicar una versión, comprobar también primer inicio, guardado y
restauración de horarios en otro equipo Windows sin Python.

## Próximas ampliaciones

La incorporación de otras facultades y sedes deberá hacerse como una ampliación explícita del catálogo, de los planes y de las rutas de Libre Elección. No se recomienda reintroducir todas las rutas en esta versión hasta contar con diagnósticos y pruebas específicas para cada facultad.

## Licencia

El proyecto se distribuye bajo los términos indicados en `LICENSE`.
