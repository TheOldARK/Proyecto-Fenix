# Página web de Fénix

Sitio estático en HTML, CSS y JavaScript. Abre `index.html` en un navegador
para revisarlo localmente. Está publicado en
<https://horarios.fenix-un.workers.dev>. No se ha añadido a los
instaladores de la aplicación.

La página ofrece enlaces de descarga directa y Microsoft Store para Windows,
además de instaladores para macOS (Apple Silicon e Intel) y Linux. Al abrirse
con conexión, `app.js` consulta la última versión publicada en GitHub y
actualiza los enlaces de los paquetes que encuentre. Si GitHub no responde,
se conservan los enlaces predeterminados. Los instaladores de macOS y Linux
descargan la versión compatible más reciente al ejecutarse. El instalador
macOS aún no dispone de notarización de Apple.

Este sitio es independiente y no representa un sitio oficial de la UNAL.

## Conteo agregado de clics

Al pulsar un botón de descarga, el navegador envía únicamente la categoría del
botón (`windows_directa`, `windows_store`, `macos_arm64`, `macos_x64` o `linux`)
al endpoint `/api/download-click`. No se envían UUID, cookies, datos académicos
ni identificadores persistentes. Esto cuenta clics en las opciones, no
descargas completadas ni usuarios únicos. El Worker guarda los eventos en
Cloudflare Analytics Engine; puede haber muestreo y por eso la consulta suma
`_sample_interval`.

Para consultar el total por botón de los últimos 30 días, usa el SQL API de
Analytics Engine con el ID de cuenta y un token que tenga permiso de lectura de
Analytics:

```sql
SELECT blob1 AS boton, SUM(_sample_interval) AS clics
FROM fenix_download_clicks
WHERE timestamp > NOW() - INTERVAL '30' DAY
GROUP BY boton
ORDER BY clics DESC
```

La configuración del Worker está en `wrangler.jsonc`. El dataset se crea
automáticamente con la primera escritura. `.assetsignore` evita exponer el
código del Worker y los archivos de configuración como recursos estáticos.
No se ha desplegado esta versión.
