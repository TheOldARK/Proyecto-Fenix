# Página web de Fénix

Sitio estático en HTML, CSS y JavaScript. Abre `index.html` en un navegador
para revisarlo localmente. Está publicado en
<https://horarios.fenix-un.workers.dev>. No se ha añadido a los
instaladores de la aplicación.

Las descargas predeterminadas apuntan a los archivos reales de la versión
2.1.1 en GitHub Releases. Al abrirse con conexión, `app.js` consulta la última
versión publicada y actualiza los enlaces de los paquetes que encuentre. Si
GitHub no responde, los enlaces predeterminados siguen disponibles. Se puede
publicar toda esta carpeta en cualquier servicio de alojamiento estático,
manteniendo juntos `index.html`, `styles.css`, `app.js` y `assets/logo.png`.

Windows, macOS (Apple Silicon e Intel) y Linux tienen instaladores publicados.
Los de macOS y Linux descargan la versión compatible más reciente al ejecutarse;
sus archivos no contienen la aplicación completa. El instalador macOS lleva
firma local, pero todavía no dispone de notarización de Apple.

Este sitio es independiente y no representa un sitio oficial de la UNAL.

## Publicación en Cloudflare Workers

`wrangler.jsonc` configura un Worker solo de archivos estáticos llamado
`horarios`. `.assetsignore` excluye los documentos de desarrollo de la
publicación. Después de autorizar Wrangler en la cuenta propietaria, desde
esta carpeta se puede ejecutar `npx wrangler deploy`. Las actualizaciones
posteriores usan el mismo nombre para conservar la dirección pública.
