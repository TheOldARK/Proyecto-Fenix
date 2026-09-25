# =============================================================
# PARSER DE MATERIAS DEL SIA
# =============================================================
#
# Este módulo contiene las funciones encargadas de extraer las
# materias que aparecen en la tabla de resultados del catálogo
# del SIA.
#
# La información se obtiene directamente desde la página que
# está siendo controlada por Playwright.
#
# Para extraer los datos se utiliza JavaScript dentro del
# navegador mediante locator.evaluate_all().
#
# El resultado de esta etapa es una lista de diccionarios.
# Posteriormente, otra parte de la infraestructura puede
# convertir esos datos en objetos Materia.
#
# Este módulo solamente interpreta la tabla de resultados.
# No se encarga de:
#
#   - Navegar por el SIA.
#   - Abrir el detalle de una materia.
#   - Extraer grupos.
#   - Extraer prerrequisitos.
#   - Guardar información en archivos.
#

import re

from playwright.async_api import Page


# =============================================================
# UTILIDADES
# =============================================================

def normalizar_texto(texto: str) -> str:
    # El contenido de las celdas puede contener saltos de línea,
    # tabulaciones y varios espacios consecutivos.
    #
    # Se convierten todos esos espacios en uno solo y se eliminan
    # los espacios que queden al principio o al final.

    return re.sub(
        r"\s+",
        " ",
        texto
    ).strip()


# =============================================================
# EXTRAER MATERIAS DE LA TABLA
# =============================================================

async def obtener_materias_de_tabla(
    page: Page,
    incluir_no_programadas: bool = False,
):
    # Extrae las materias que aparecen en la tabla de resultados
    # del catálogo del SIA.
    #
    # Cada materia se devuelve inicialmente como un diccionario
    # con la siguiente información:
    #
    #   codigo
    #   nombre
    #   creditos
    #   tipologia
    #   descripcion
    #
    # Las materias que indiquen "NO PROGRAMADA" o "SIN PROGRAMAR"
    # se descartan porque no forman parte de la oferta que Fénix
    # necesita procesar.
    #
    # La extracción de la tabla se realiza dentro del navegador.
    # Esto permite trabajar directamente con el contenido que
    # Playwright ya recibió y renderizó.

    materias = await page.locator(
        "table.af_table_data-table"
    ).evaluate_all(
        """
        (tablas, incluirNoProgramadas) => {

            // ==================================================
            // NORMALIZAR TEXTO
            // ==================================================
            //
            // Esta función cumple dentro del navegador la misma
            // función que normalizar_texto() cumple en Python.
            //
            // Se necesita aquí porque la extracción de las celdas
            // ocurre mediante JavaScript.

            function limpiar(texto) {

                return texto
                    .replace(/\\s+/g, " ")
                    .trim();
            }

            // ==================================================
            // BUSCAR TABLA VÁLIDA
            // ==================================================
            //
            // El selector puede encontrar más de una tabla.
            // Por eso no asumimos que la primera tabla encontrada
            // sea necesariamente la tabla de materias.
            //
            // Una tabla válida debe contener al menos una fila
            // de encabezado y una fila de datos.

            for (const tabla of tablas) {

                const filas = Array.from(
                    tabla.querySelectorAll("tr")
                );

                if (filas.length < 2) {
                    continue;
                }

                const materias = [];

                // ==================================================
                // RECORRER FILAS
                // ==================================================

                for (const fila of filas) {

                    const celdas = Array.from(
                        fila.querySelectorAll("td")
                    );

                    // Esperamos las siguientes columnas:
                    //
                    // 0 -> Código
                    // 1 -> Nombre
                    // 2 -> Créditos
                    // 3 -> Tipología
                    // 4 -> Descripción
                    //
                    // Las filas que no tengan esta estructura se
                    // ignoran. Esto también evita intentar procesar
                    // filas de encabezado u otras filas auxiliares.

                    if (celdas.length < 5) {
                        continue;
                    }

                    // ==================================================
                    // DATOS BÁSICOS
                    // ==================================================

                    const codigo = limpiar(
                        celdas[0].innerText
                    );

                    const nombre = limpiar(
                        celdas[1].innerText
                    );

                    // Una fila sin código o nombre no representa
                    // una materia válida.

                    if (!codigo || !nombre) {
                        continue;
                    }

                    const creditos = limpiar(
                        celdas[2].innerText
                    );

                    const tipologia = limpiar(
                        celdas[3].innerText
                    );

                    const descripcion = limpiar(
                        celdas[4].innerText
                    );

                    // ==================================================
                    // FILTRAR MATERIAS NO PROGRAMADAS
                    // ==================================================
                    //
                    // El SIA puede mostrar materias que existen en
                    // el catálogo pero que no tienen programación
                    // disponible actualmente.
                    //
                    // Se revisan tanto el nombre como la descripción
                    // porque el mensaje puede aparecer en cualquiera
                    // de esos campos.

                    const textoCompleto = (
                        nombre + " " +
                        descripcion
                    ).toUpperCase();

                    if (
                        !incluirNoProgramadas && (
                        textoCompleto.includes(
                            "NO PROGRAMADA"
                        )
                        ||
                        textoCompleto.includes(
                            "SIN PROGRAMAR"
                        )
                        )
                    ) {
                        continue;
                    }

                    // ==================================================
                    // GUARDAR MATERIA
                    // ==================================================

                    materias.push({

                        codigo: codigo,

                        nombre: nombre,

                        creditos: creditos,

                        tipologia: tipologia,

                        descripcion: descripcion
                    });
                }

                // ==================================================
                // TABLA ENCONTRADA
                // ==================================================
                //
                // En cuanto encontramos una tabla que contiene
                // materias válidas, dejamos de revisar las demás.

                if (materias.length > 0) {
                    return materias;
                }
            }

            // Si ninguna tabla contiene materias válidas, se
            // devuelve una lista vacía para que Python pueda
            // realizar la validación correspondiente.

            return [];
        }
        """ ,
        incluir_no_programadas,
    )

    # =============================================================
    # VALIDACIÓN
    # =============================================================
    #
    # Una tabla vacía normalmente indica que el SIA no cargó los
    # resultados esperados, que cambió su estructura o que ocurrió
    # algún problema durante la navegación.
    #
    # Es preferible detener el proceso explícitamente antes que
    # continuar silenciosamente con una base de materias vacía.

    if not materias:

        raise RuntimeError(
            "No se encontraron materias "
            "en la tabla del catálogo SIA."
        )

    return materias
