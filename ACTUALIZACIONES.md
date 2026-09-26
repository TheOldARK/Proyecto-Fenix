# Fénix 2.0.5

- Ciencias aparece como una facultad seleccionable al configurar la carrera; el
  menú de carreras se filtra por facultad y recuerda el plan del estudiante.
- Se incluyen Estadística e Ingeniería Física, junto con los planes de Ciencias
  de la Computación e Ingeniería Biológica ya registrados.
- El gestor de publicadores incorpora las carreras nuevas automáticamente. Los
  planes con ruta SIA lista pero sin materias se muestran como pendientes y no
  se pueden iniciar accidentalmente.

# Fénix 2.0.4

- Al buscar una asignatura, Fénix muestra una sección dinámica de “No disponibles”
  con las materias aprobadas o bloqueadas por prerrequisitos y explica el motivo.
- La búsqueda de materias no disponibles ignora mayúsculas y tildes e incluye
  materias aprobadas aunque no estén en la oferta actual.
- El árbol de prerrequisitos representa las tipologías del SIA: M como requisito
  previo estricto, Y como simultaneidad provisional, O como requisito para
  calificar, E como prerrequisito especial y A como incompatibilidad.

# Fénix 2.0.3

- La descarga de Libre Elección ahora es opcional en Cloudflare. Si el manifiesto
  anuncia el archivo pero el objeto aún no está disponible (HTTP 404), Fénix
  conserva e instala las materias y la oferta válidas, y busca las libres en el
  SIA. La falta de ese archivo ya no invalida toda la actualización.
- Si el SIA tampoco está disponible, Fénix puede seguir usando los datos locales
  existentes y deja constancia del estado de Libre Elección.

# Actualizaciones desde 1.0.8

Instalar 1.0.8 manualmente una vez, extrayendo su ZIP completo en una carpeta nueva.
Los actualizadores anteriores siguen siendo código antiguo aunque se publique un
ZIP nuevo. Los datos del usuario permanecen en `%LOCALAPPDATA%\Fenix`.
La versión 1.0.8.1 es un dummy funcionalmente equivalente para probar el salto.

La distribución incluye `Fenix.exe`, `_internal/`, `browser/`, `updater/` y
`fenix-manifest.json`. Hay que conservar todas estas carpetas.
`privacy-sandbox-attestations.dat` se encuentra ahora en
`browser/PrivacySandboxAttestationsPreloaded/`.

## Funcionamiento

1. La interfaz consulta GitHub antes de iniciar workers, selecciona la versión
   numérica más alta con un ZIP de Windows y pide confirmación al usuario.
2. Descarga a una carpeta única y verifica tamaño, SHA-256 publicado por GitHub,
   CRC del ZIP y versión del manifiesto.
3. Detiene los workers. Copia únicamente el instalador independiente a una
   carpeta temporal y espera su confirmación de arranque antes de cerrar Qt.
4. El instalador espera a que termine el proceso original. Un bloqueo de archivo
   impide instalar dos actualizaciones simultáneas y se libera al morir el proceso.
5. Extrae usando rutas extendidas de Windows y comprueba tamaño y SHA-256 de
   todos los archivos. Solo reutiliza un archivo anterior si coincide exactamente
   con el contenido esperado. No arrastra archivos obsoletos de Chromium.
6. Intercambia las carpetas, vuelve a verificar la instalación y ejecuta un
   diagnóstico real de Qt y Chromium antes de iniciar la interfaz nueva.
7. Si falla el intercambio o diagnóstico, restaura la instalación anterior.
   El estado persistido permite recuperar un intercambio interrumpido cuando
   se vuelve a ejecutar el instalador externo. Si la carpeta original quedó
   ausente por un corte eléctrico, se puede recuperar desde `anterior/`.

El registro queda en `.fx-<identificador>/actualizacion.log`, junto a la carpeta
de instalación. Los diagnósticos usan datos aislados y no modifican el perfil.
Una carpeta `anterior/` o `fallida-*` se conserva cuando hace falta recuperación.

## Verificación reproducible

Ejecutar desde la raíz del repositorio con el Python del entorno de construcción:

```powershell
.\.venv-distribucion\Scripts\python.exe -m unittest discover -s tests -v
.\.venv-distribucion\Scripts\python.exe tests\probar_exe.py RUTA_ZIP_108 RUTA_ZIP_1081 origen-incompleto
.\.venv-distribucion\Scripts\python.exe tests\probar_exe.py RUTA_ZIP_108 RUTA_ZIP_1081 worker-activo
```

La prueba de ejecutables abre la ventana Qt empaquetada sin mostrarla en pantalla,
acciona el método real del botón, descarga el ZIP desde un servidor local de
prueba, cierra Qt normalmente y espera al instalador empaquetado. Verifica todos
los archivos finales, el diagnóstico, el nuevo arranque y un archivo de datos
personales de prueba. Solo termina los procesos que ella misma creó.
Los resultados se guardan en `D:\Fenix-Pruebas\e2e-*\informe.json`.

El modo `--prueba-actualizacion` requiere un directorio de datos aislado y solo
se activa explícitamente. No se ejecuta durante el uso normal del programa.

## Resultados de validación de 1.0.8

- 16 pruebas automatizadas: rutas mayores de 300 caracteres, SHA-256, ZIP
  incompleto/dañado, recuperación de bytes idénticos, rechazo de bytes
  incompatibles, espacio insuficiente, bloqueo concurrente, recuperación tras
  interrupción y rollback por diagnóstico o arranque fallido.
- EXE 1.0.8 abierto a 1.0.8.1: instalación inicial sin el archivo `.dat`,
  descarga y cierre normal de Qt, 705 archivos verificados y datos conservados.
  Ruta final del `.dat`: 272 caracteres. Resultado correcto.
- EXE 1.0.8 abierto a 1.0.8.1 con worker y Chromium activos: cancelación
  cooperativa confirmada, 705 archivos verificados, diagnóstico Qt/Chromium y
  arranque de la nueva interfaz confirmados. Resultado correcto.
- La primera prueba con la estructura antigua reprodujo un fallo de arranque
  de Chromium en una ruta profunda y confirmó el rollback. La distribución
  final resuelve ese caso usando la carpeta corta `browser/`.

Estas verificaciones se realizaron en Windows en el equipo de desarrollo,
con datos aislados; no sustituyen la prueba en el segundo equipo del usuario.
