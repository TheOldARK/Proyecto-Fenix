# Verificador de planes en Cloudflare

## Verificador directo del SIA (nuevo)

Para comprobar que los códigos del JSON siguen funcionando en el SIA, abre
`herramientas/Verificar_planes_SIA.cmd`. Revisa secuencialmente las materias
de todos los planes de Medellín guardados en `datos/planes_estudio.json`.
Incluye los códigos registrados aunque no tengan semestre; no inventa códigos
ni revisa todas las optativas o libres elecciones del SIA.

También puedes limitar la comprobación desde PowerShell, en la raíz del proyecto:

```powershell
.\.venv-distribucion\Scripts\python.exe herramientas\verificar_planes_sia.py --plan 3534
.\.venv-distribucion\Scripts\python.exe herramientas\verificar_planes_sia.py --facultad 3064
.\.venv-distribucion\Scripts\python.exe herramientas\verificar_planes_sia.py --plan 3534 --materia 1000004
```

`--planes` permite elegir otro JSON y `--salida` otra carpeta de informes. Por
defecto se guardan bajo `%LOCALAPPDATA%\Fenix\herramientas\verificacion_sia`,
en una carpeta nueva por ejecución: `informe.md` (legible), `informe.json`
(detallado) y `consulta.log` (diagnóstico). Se guardan avances después de cada
materia; Ctrl+C conserva lo comprobado e identifica la ejecución interrumpida.

Estados:

- `funciona`: el enlace del catálogo abre la ficha y los lectores de Fénix
  procesan sus grupos y requisitos. Cero grupos no invalida la ficha.
- `no_en_catalogo`: el código no aparece en el catálogo de esa carrera tras
  reintentar. No significa que no exista en otras carreras o sedes.
- `error_ficha_sia`: el SIA rechaza la ficha o no ofrece su enlace; se conserva
  el motivo. No se atribuye automáticamente a un código mal escrito.
- `no_verificada`: conexión, tiempo de espera u otro fallo impidió comprobarla.
- `sin_malla`: carrera vacía pendiente de edición, sin consultas de materias.

Las materias «sin programar» también se comprueban. Las diferencias de nombre
entre JSON y SIA se señalan para revisión, sin cambiar los nombres locales.
Cada fallo se reintenta una vez con una sesión nueva. No se reutiliza una ficha
comprobada en otra carrera, porque la oferta y los requisitos pueden cambiar.
No modifica el perfil del estudiante, los planes ni Cloudflare.

## Verificador de archivos publicados

Compara las asignaturas guardadas en el editor de planes con los archivos
`materias.json` y `oferta.json` publicados para cada carrera. No modifica
Cloudflare ni los planes. No necesita las credenciales del publicador.

Desde la raíz del repositorio, en PowerShell:

```powershell
.\.venv-distribucion\Scripts\python.exe herramientas\verificar_planes_cloudflare.py
```

Para revisar una facultad o una carrera concreta:

```powershell
.\.venv-distribucion\Scripts\python.exe herramientas\verificar_planes_cloudflare.py --facultad 3064
.\.venv-distribucion\Scripts\python.exe herramientas\verificar_planes_cloudflare.py --plan 3501
```

Para guardar el detalle con códigos y nombres:

```powershell
.\.venv-distribucion\Scripts\python.exe herramientas\verificar_planes_cloudflare.py --informe informe-planes.json
```

Revisa todas las facultades de Medellín por defecto; `--sede` permite indicar
otra sede. Se incorporan automáticamente las carreras guardadas en el editor,
sin mantener una lista fija de facultades en el verificador. Guarda los cambios
del editor antes de ejecutar la comprobación.

- **OK:** las materias locales aparecen en ambos archivos. Esto no garantiza
  grupos disponibles, cupos ni vigencia de la oferta.
- **SIN MALLA:** el plan todavía no tiene materias definidas; no se considera
  un error de publicación ni se descargan sus archivos.
- **REVISAR:** falta la carrera, un archivo o alguna materia. El detalle indica
  código, nombre y archivo donde falta. La comparación va del plan local hacia
  Cloudflare, no al revés. No se exige un archivo de Libre Elección.
- **NO VERIFICADO:** hubo un error de red, integridad o identidad del archivo.
  Las materias de ese archivo no se declaran ausentes sin poder comprobarlo.

El código de salida es 0 si no hay faltantes ni errores (puede haber planes
vacíos), 1 si hay faltantes o los filtros no coinciden con ningún plan y 2 si no
se pudo verificar algún archivo o el manifiesto. El reporte JSON incluye los
estados separados `completo`, `sin_malla`, `no_publicado`, `incompleto` y
`no_verificado`.
