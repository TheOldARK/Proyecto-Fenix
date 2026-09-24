import asyncio
import json
import unicodedata

from configuracion import (
    ARCHIVO_CATALOGO_SIA as RUTA_CATALOGO_SIA,
    ARCHIVO_CONFIGURACION_LIBRE_ELECCION as RUTA_CONFIGURACION_LIBRE_ELECCION,
    ARCHIVO_ESTUDIANTE as RUTA_ESTUDIANTE,
)
from infraestructura.sia.catalogo_local import clave_plan
from infraestructura.sia.errores import MateriaNoDisponibleEnSIA


class CatalogoSIA:
    # Selectores principales del formulario del catálogo SIA.

    SELECTOR_NIVEL_ESTUDIO = 'select[name="pt1:r1:0:soc1"]'
    SELECTOR_SEDE = 'select[name="pt1:r1:0:soc9"]'
    SELECTOR_FACULTAD = 'select[name="pt1:r1:0:soc2"]'
    SELECTOR_PLAN = 'select[name="pt1:r1:0:soc3"]'
    SELECTOR_TIPOLOGIA = 'select[name="pt1:r1:0:soc4"]'

    # Selectores utilizados exclusivamente por la búsqueda
    # de asignaturas de Libre Elección.

    SELECTOR_FORMA_BUSQUEDA = 'select[name="pt1:r1:0:soc5"]'
    SELECTOR_SEDE_LIBRE_ELECCION = 'select[name="pt1:r1:0:soc10"]'
    SELECTOR_FACULTAD_LIBRE_ELECCION = (
        'select[name="pt1:r1:0:soc6"]'
    )

    SELECTOR_BOTON_MOSTRAR = "text=Mostrar"

    # Archivos utilizados para obtener la configuración
    # académica del estudiante y la estructura del catálogo SIA.

    ARCHIVO_ESTUDIANTE = RUTA_ESTUDIANTE
    ARCHIVO_CATALOGO = RUTA_CATALOGO_SIA
    ARCHIVO_CONFIGURACION_LIBRE_ELECCION = RUTA_CONFIGURACION_LIBRE_ELECCION

    # Valores conocidos del formulario SIA.

    VALOR_PREGRADO = "0"

    VALOR_TIPOLOGIA_NORMAL = "0"
    VALOR_TIPOLOGIA_LIBRE_ELECCION = "2"

    # Cantidad máxima de intentos para configurar
    # la búsqueda de Libre Elección.

    MAXIMO_INTENTOS_LIBRE_ELECCION = 3
    MAXIMO_INTENTOS_PLAN = 3

    # Tiempos obtenidos experimentalmente en tester.py.
    #
    # Son esperas mínimas de asentamiento. No representan
    # tiempos fijos de carga de red.

    ESPERA_ENTRE_TECLAS = 0.05
    ESPERA_DESPUES_DE_SELECCION = 0.05
    ESPERA_DESPUES_DE_CARGA = 0.05
    ESPERA_AL_RECONSTRUIR_RAMA = 0.05

    INTERVALO_COMPROBACION = 0.1
    # El formulario de Libre Elección puede tardar bastante más que la rama
    # normal en reconstruir el botón Mostrar después de ADF.
    TIEMPO_MAXIMO_CARGA = 45

    def __init__(
        self,
        page,
        url,
        codigo_plan=None
    ):
        self.page = page
        self.url = url

        # Información obtenida de estudiante.json.

        self.plan_estudios = None
        self.materias_aprobadas = []
        self.grupos_seleccionados = []

        # Código recibido por el proceso de actualización.
        #
        # Si se proporciona, se valida contra estudiante.json.
        # Si no se proporciona, se utiliza el código de estudiante.json.

        self.codigo_plan_solicitado = (
            str(codigo_plan).strip()
            if codigo_plan is not None
            else None
        )

        # Ruta académica encontrada en catalogo_sia.json.

        self.datos_carrera = None

        self.codigo_sede = None
        self.codigo_facultad = None
        self.codigo_plan = None

        self.nombre_sede = None
        self.nombre_facultad = None
        self.nombre_plan = None

        # Configuración específica de Libre Elección.

        self.configuracion_libre_eleccion = None

        # Sede utilizada por soc10 durante la búsqueda
        # de Libre Elección.
        #
        # Esta información pertenece al nivel de sede
        # de configuracion_libre_eleccion.json, no al
        # diccionario específico del plan.

        self.nombre_sede_libre_eleccion = None

        self.opciones_libre_eleccion = []
        self.opciones_facultad_libre_eleccion = []

        self._cargar_configuracion_estudiante()

        if (
            self.codigo_plan_solicitado is not None
            and self.codigo_plan_solicitado
            != self.plan_estudios
        ):
            raise ValueError(
                "El código de plan recibido por "
                "actualizacion.py no coincide con "
                "el plan definido en estudiante.json. "
                f"Recibido: '{self.codigo_plan_solicitado}'. "
                f"estudiante.json: '{self.plan_estudios}'."
            )

        self._cargar_ruta_carrera()
        self._cargar_configuracion_libre_eleccion()

    # =========================================================
    # CARGAR ESTUDIANTE
    # =========================================================

    def _cargar_configuracion_estudiante(
        self
    ):
        if not self.ARCHIVO_ESTUDIANTE.exists():
            raise FileNotFoundError(
                "No se encontró el archivo "
                f"'{self.ARCHIVO_ESTUDIANTE}'."
            )

        try:
            with open(
                self.ARCHIVO_ESTUDIANTE,
                "r",
                encoding="utf-8"
            ) as archivo:
                estudiante = json.load(archivo)

        except json.JSONDecodeError as error:
            raise RuntimeError(
                "El archivo estudiante.json no contiene "
                "JSON válido."
            ) from error

        plan_estudios = estudiante.get(
            "plan_estudios"
        )

        if not plan_estudios:
            raise ValueError(
                "estudiante.json no contiene "
                "'plan_estudios'."
            )

        self.plan_estudios = str(
            plan_estudios
        ).strip()

        self.materias_aprobadas = (
            estudiante.get(
                "materias_aprobadas",
                []
            )
        )

        self.grupos_seleccionados = (
            estudiante.get(
                "grupos_seleccionados",
                []
            )
        )

        print(
            ">>> [ESTUDIANTE] Plan de estudios: "
            f"{self.plan_estudios}"
        )

    # =========================================================
    # CARGAR RUTA ACADÉMICA DESDE EL CATÁLOGO
    # =========================================================

    def _cargar_ruta_carrera(
        self
    ):
        if not self.ARCHIVO_CATALOGO.exists():
            raise FileNotFoundError(
                "No se encontró el catálogo SIA: "
                f"'{self.ARCHIVO_CATALOGO}'."
            )

        try:
            with open(
                self.ARCHIVO_CATALOGO,
                "r",
                encoding="utf-8"
            ) as archivo:
                catalogo = json.load(archivo)

        except json.JSONDecodeError as error:
            raise RuntimeError(
                "El archivo catalogo_sia.json no "
                "contiene JSON válido."
            ) from error

        resultado = self._buscar_plan_en_catalogo(
            catalogo,
            self.plan_estudios
        )

        if resultado is None:
            raise ValueError(
                "No se encontró el plan de estudios "
                f"'{self.plan_estudios}' en "
                "catalogo_sia.json."
            )

        self.datos_carrera = resultado

        self.codigo_sede = resultado[
            "sede"
        ]["codigo"]

        self.nombre_sede = resultado[
            "sede"
        ]["nombre"]

        self.codigo_facultad = resultado[
            "facultad"
        ]["codigo"]

        self.nombre_facultad = resultado[
            "facultad"
        ]["nombre"]

        self.codigo_plan = resultado[
            "plan"
        ].get(
            "codigo"
        ) or self.plan_estudios

        self.nombre_plan = resultado[
            "plan"
        ]["nombre"]

        print()
        print(
            "================================================"
        )
        print(
            ">>> RUTA ACADÉMICA ENCONTRADA"
        )
        print(
            "================================================"
        )
        print(
            f">>> Sede: "
            f"{self.codigo_sede} - "
            f"{self.nombre_sede}"
        )
        print(
            f">>> Facultad: "
            f"{self.codigo_facultad} - "
            f"{self.nombre_facultad}"
        )
        print(
            f">>> Plan: "
            f"{self.codigo_plan} - "
            f"{self.nombre_plan}"
        )
        print(
            "================================================"
        )

    # =========================================================
    # CARGAR CONFIGURACIÓN DE LIBRE ELECCIÓN
    # =========================================================

    def _cargar_configuracion_libre_eleccion(
        self
    ):
        if not self.ARCHIVO_CONFIGURACION_LIBRE_ELECCION.exists():
            raise FileNotFoundError(
                "No se encontró el archivo de configuración "
                "de Libre Elección: "
                f"'{self.ARCHIVO_CONFIGURACION_LIBRE_ELECCION}'."
            )

        try:
            with open(
                self.ARCHIVO_CONFIGURACION_LIBRE_ELECCION,
                "r",
                encoding="utf-8"
            ) as archivo:
                configuracion = json.load(archivo)

        except json.JSONDecodeError as error:
            raise RuntimeError(
                "El archivo "
                "configuracion_libre_eleccion.json "
                "no contiene JSON válido."
            ) from error

        # La configuración de Libre Elección está
        # organizada por sede y, dentro de cada sede,
        # por facultad y plan:
        #
        #     sede
        #         ├── sede
        #         └── planes
        #              └── facultad:plan
        #
        # Por ejemplo:
        #
        #     1102
        #         ├── sede
        #         └── planes
        #              └── 3068:3534
        #
        # Esto permite que cada plan de estudios tenga
        # su propia configuración de Libre Elección.

        codigo_sede = str(
            self.codigo_sede
        )

        clave_plan_local = (
            f"{self.codigo_facultad}:"
            f"{self.codigo_plan}"
        )

        configuracion_sede = configuracion.get(
            codigo_sede
        )

        if not isinstance(
            configuracion_sede,
            dict
        ):
            raise ValueError(
                "No existe una configuración válida "
                "para la sede "
                f"'{codigo_sede}' en "
                "configuracion_libre_eleccion.json."
            )

        # La sede de búsqueda de Libre Elección
        # pertenece a este nivel del JSON.
        #
        # Ejemplo:
        #
        #     "1102": {
        #         "sede": "1102 SEDE MEDELLÍN",
        #         "planes": {...}
        #     }

        nombre_sede_busqueda = (
            configuracion_sede.get("sede")
        )

        if not nombre_sede_busqueda:
            raise ValueError(
                "La configuración de Libre Elección "
                f"para la sede '{codigo_sede}' "
                "no contiene la clave 'sede'."
            )

        planes = configuracion_sede.get(
            "planes"
        )

        if not isinstance(
            planes,
            dict
        ):
            raise ValueError(
                "La configuración de la sede "
                f"'{codigo_sede}' no contiene "
                "un objeto 'planes' válido."
            )

        if clave_plan_local not in planes:
            clave_completa = clave_plan(
                self.codigo_sede,
                self.codigo_facultad,
                self.codigo_plan,
            )
            raise ValueError(
                "No existe configuración de Libre Elección para la ruta "
                f"'{clave_completa}'."
            )

        configuracion_plan = planes[clave_plan_local]

        if not isinstance(
            configuracion_plan,
            dict
        ):
            raise ValueError(
                "La configuración de Libre Elección "
                f"para la ruta '{clave_plan_local}' "
                "debe ser un objeto JSON."
            )

        facultades = configuracion_plan.get(
            "facultades_libre_eleccion"
        )

        # Se acepta temporalmente también la clave
        # 'facultades' para facilitar la transición
        # desde la estructura anterior.
        #
        # La estructura nueva debe utilizar:
        #
        #     facultades_libre_eleccion

        if facultades is None:
            facultades = configuracion_plan.get(
                "facultades"
            )

        if not isinstance(
            facultades,
            list
        ):
            raise ValueError(
                "La propiedad "
                "'facultades_libre_eleccion' de la "
                f"ruta '{clave_plan_local}' debe ser "
                "una lista JSON."
            )

        if not facultades:
            raise ValueError(
                "La propiedad "
                "'facultades_libre_eleccion' de la "
                f"ruta '{clave_plan_local}' está vacía."
            )

        for opcion in facultades:
            if not isinstance(
                opcion,
                str
            ) or not opcion.strip():
                raise ValueError(
                    "Todas las opciones de "
                    "'facultades_libre_eleccion' "
                    "deben ser textos no vacíos."
                )

        # Guardamos exclusivamente la configuración
        # correspondiente al plan.

        self.configuracion_libre_eleccion = (
            configuracion_plan
        )

        # Guardamos por separado la sede de búsqueda,
        # porque pertenece al nivel superior de la
        # configuración y será utilizada por soc10.

        self.nombre_sede_libre_eleccion = (
            nombre_sede_busqueda
        )

        # Estas son exclusivamente las opciones que se
        # utilizarán en el selector de facultad de Libre
        # Elección cuando SIA lo reconstruya como soc6.
        #
        # No deben confundirse con la facultad académica
        # seleccionada durante los pasos 1-4 en soc2.

        self.opciones_facultad_libre_eleccion = list(
            facultades
        )

        self.opciones_libre_eleccion = [
            self.nombre_sede_libre_eleccion,
            *self.opciones_facultad_libre_eleccion,
        ]

        print()
        print(
            "================================================"
        )
        print(
            ">>> CONFIGURACIÓN DE LIBRE ELECCIÓN"
        )
        print(
            "================================================"
        )
        print(
            f">>> Ruta académica: "
            f"{codigo_sede}:{clave_plan_local}"
        )
        print(
            f">>> Sede académica: "
            f"{self.codigo_sede} - "
            f"{self.nombre_sede}"
        )
        print(
            f">>> Facultad académica: "
            f"{self.codigo_facultad} - "
            f"{self.nombre_facultad}"
        )
        print(
            f">>> Plan académico: "
            f"{self.codigo_plan} - "
            f"{self.nombre_plan}"
        )
        print(
            f">>> Sede de búsqueda: "
            f"{self.nombre_sede_libre_eleccion}"
        )
        print(
            ">>> Opciones de facultad:"
        )

        for i, opcion in enumerate(
            self.opciones_facultad_libre_eleccion,
            start=1
        ):
            print(
                f"    {i}. {opcion}"
            )

        print(
            "================================================"
        )

    # =========================================================
    # OBTENER OPCIONES DE LIBRE ELECCIÓN
    # =========================================================

    def obtener_opciones_libre_eleccion(
        self
    ):
        return list(
            self.opciones_libre_eleccion
        )

    # =========================================================
    # BUSCAR PLAN EN EL CATÁLOGO
    # =========================================================

    def _buscar_plan_en_catalogo(
        self,
        catalogo,
        codigo_plan
    ):
        niveles = catalogo.get(
            "niveles_estudio",
            []
        )

        for nivel in niveles:
            sedes = nivel.get(
                "sedes",
                []
            )

            for sede in sedes:
                facultades = sede.get(
                    "facultades",
                    []
                )

                for facultad in facultades:
                    planes = facultad.get(
                        "planes_estudio",
                        []
                    )

                    for plan in planes:
                        codigo = plan.get(
                            "codigo"
                        )

                        if codigo is None:
                            continue

                        clave = clave_plan(
                            sede.get("codigo", ""),
                            facultad.get("codigo", ""),
                            codigo,
                        )

                        if str(codigo_plan).count(":") == 2:
                            coincide = (
                                clave == str(codigo_plan)
                            )
                        else:
                            coincide = (
                                str(codigo)
                                == str(codigo_plan)
                            )

                        if not coincide:
                            continue

                        return {
                            "nivel": nivel,
                            "sede": sede,
                            "facultad": facultad,
                            "plan": plan,
                        }

        return None

    # =========================================================
    # ABRIR CATÁLOGO
    # =========================================================

    async def abrir(
        self
    ):
        print(
            ">>> Abriendo catálogo SIA..."
        )

        await self.page.goto(
            self.url,
            wait_until="domcontentloaded",
            timeout=(
                self.TIEMPO_MAXIMO_CARGA * 1000
            )
        )

        await self.page.locator(
            self.SELECTOR_NIVEL_ESTUDIO
        ).wait_for(
            state="visible",
            timeout=(
                self.TIEMPO_MAXIMO_CARGA * 1000
            )
        )

        print(
            ">>> Catálogo SIA cargado."
        )

    # =========================================================
    # OBTENER ESTADO DEL SELECTOR
    # =========================================================

    async def obtener_estado_selector(
        self,
        selector
    ):
        elemento = self.page.locator(
            selector
        )

        return {
            "visible": await elemento.is_visible(),
            "habilitado": await elemento.is_enabled(),
            "valor": await elemento.input_value(),
            "cantidad_opciones": await elemento.locator(
                "option"
            ).count(),
        }

    # =========================================================
    # OBTENER OPCIONES
    # =========================================================

    async def obtener_opciones(
        self,
        selector
    ):
        return await self.page.locator(
            f"{selector} option"
        ).evaluate_all(
            """
            opciones => opciones.map(opcion => ({
                valor: opcion.value,
                texto: opcion.textContent.trim(),
                deshabilitada: opcion.disabled
            }))
            """
        )

    # =========================================================
    # IMPRIMIR OPCIONES
    # =========================================================

    async def imprimir_opciones(
        self,
        selector,
        nombre
    ):
        print(
            f">>> Opciones actuales de {nombre}:"
        )

        opciones = await self.obtener_opciones(
            selector
        )

        print(
            f">>> Cantidad de opciones: "
            f"{len(opciones)}"
        )

        for i, opcion in enumerate(
            opciones
        ):
            print(
                f"    [{i}] "
                f"value='{opcion['valor']}' "
                f"text='{opcion['texto']}'"
            )

    # =========================================================
    # ESPERAR SELECTOR HABILITADO
    # =========================================================

    async def esperar_selector_habilitado(
        self,
        selector,
        timeout=None
    ):
        if timeout is None:
            timeout = (
                self.TIEMPO_MAXIMO_CARGA * 1000
            )

        print(
            f">>> Esperando que se habilite: "
            f"{selector}"
        )

        await self.page.locator(
            selector
        ).wait_for(
            state="visible",
            timeout=timeout
        )

        await self.page.wait_for_function(
            """
            selector => {
                const elemento =
                    document.querySelector(selector);

                return elemento &&
                       !elemento.disabled;
            }
            """,
            arg=selector,
            timeout=timeout
        )

        print(
            f">>> Selector habilitado: {selector}"
        )

    # =========================================================
    # ESPERAR SELECTOR CON OPCIONES
    # =========================================================

    async def esperar_selector_con_opciones(
        self,
        selector,
        cantidad_minima=1,
        timeout=None
    ):
        if timeout is None:
            timeout = (
                self.TIEMPO_MAXIMO_CARGA * 1000
            )

        print(
            f">>> Esperando opciones en: "
            f"{selector}"
        )

        await self.page.wait_for_function(
            """
            ({selector, cantidadMinima}) => {
                const elemento =
                    document.querySelector(selector);

                if (!elemento || elemento.disabled) {
                    return false;
                }

                return elemento.options.length >=
                       cantidadMinima;
            }
            """,
            arg={
                "selector": selector,
                "cantidadMinima": cantidad_minima,
            },
            timeout=timeout
        )

        print(
            f">>> Selector listo con opciones: "
            f"{selector}"
        )

    # =========================================================
    # ESPERAR OPCIÓN ESPECÍFICA
    # =========================================================

    async def esperar_opcion(
        self,
        selector,
        texto_esperado,
        timeout=None
    ):
        if timeout is None:
            timeout = (
                self.TIEMPO_MAXIMO_CARGA * 1000
            )

        print(
            f">>> Esperando opción específica en "
            f"{selector}:"
        )

        print(
            f">>> '{texto_esperado}'"
        )

        objetivo = self.normalizar_texto(
            texto_esperado
        )

        await self.page.wait_for_function(
            """
            ({selector, objetivo}) => {
                const elemento =
                    document.querySelector(selector);

                if (!elemento || elemento.disabled) {
                    return false;
                }

                const opciones =
                    Array.from(elemento.options);

                return opciones.some(
                    opcion =>
                        opcion.textContent
                            .trim()
                            .normalize("NFD")
                            .replace(/[\\u0300-\\u036f]/g, "")
                            .toUpperCase()
                            .replace(/\\s+/g, " ")
                            .trim()
                        === objetivo
                );
            }
            """,
            arg={
                "selector": selector,
                "objetivo": objetivo,
            },
            timeout=timeout
        )

        print(
            f">>> Opción específica disponible: "
            f"'{texto_esperado}'"
        )

    # =========================================================
    # ESPERAR OPCIÓN Y DEJARLA ESTABILIZAR
    # =========================================================

    async def esperar_opcion_estable(
        self,
        selector,
        texto_esperado,
        tiempo_estable=None,
        timeout=None
    ):
        if tiempo_estable is None:
            tiempo_estable = (
                self.ESPERA_DESPUES_DE_CARGA
            )

        if timeout is None:
            timeout = (
                self.TIEMPO_MAXIMO_CARGA * 1000
            )

        print(
            ">>> [ADF] Esperando opción objetivo..."
        )

        await self.esperar_opcion(
            selector,
            texto_esperado,
            timeout=timeout
        )

        if tiempo_estable > 0:
            await self.page.wait_for_timeout(
                tiempo_estable * 1000
            )

        await self.esperar_opcion(
            selector,
            texto_esperado,
            timeout=timeout
        )

        print(
            ">>> [ADF] Selector estable."
        )

    # =========================================================
    # ESPERAR VALOR DEL SELECTOR
    # =========================================================

    async def esperar_valor_selector(
        self,
        selector,
        valor,
        timeout=None
    ):
        if timeout is None:
            timeout = (
                self.TIEMPO_MAXIMO_CARGA * 1000
            )

        await self.page.wait_for_function(
            """
            ({selector, valor}) => {
                const elemento =
                    document.querySelector(selector);

                return elemento &&
                       elemento.value === valor;
            }
            """,
            arg={
                "selector": selector,
                "valor": valor,
            },
            timeout=timeout
        )

    # =========================================================
    # NORMALIZAR TEXTO
    # =========================================================

    def normalizar_texto(
        self,
        texto
    ):
        if not isinstance(
            texto,
            str
        ):
            raise TypeError(
                "normalizar_texto() esperaba un texto "
                f"str y recibió "
                f"{type(texto).__name__}."
            )

        texto = unicodedata.normalize(
            "NFD",
            texto
        )

        texto = "".join(
            caracter
            for caracter in texto
            if unicodedata.category(
                caracter
            ) != "Mn"
        )

        return " ".join(
            texto.upper().split()
        )

    # =========================================================
    # EXTRAER CÓDIGO ACADÉMICO
    # =========================================================

    def extraer_codigo_academico(
        self,
        texto
    ):
        texto_normalizado = (
            self.normalizar_texto(
                texto
            )
        )

        partes = texto_normalizado.split(
            " ",
            1
        )

        if (
            len(partes) == 2
            and partes[0].isdigit()
        ):
            return partes[0]

        return None

    # =========================================================
    # OBTENER VALUE POR CÓDIGO ACADÉMICO
    # =========================================================

    async def obtener_valor_por_codigo(
        self,
        selector,
        codigo_academico
    ):
        opciones = await self.obtener_opciones(
            selector
        )

        codigo_objetivo = str(
            codigo_academico
        )

        for opcion in opciones:
            codigo = (
                self.extraer_codigo_academico(
                    opcion["texto"]
                )
            )

            if codigo == codigo_objetivo:
                return opcion["valor"]

        raise ValueError(
            f"No se encontró el código académico "
            f"'{codigo_academico}' en "
            f"'{selector}'."
        )

    # =========================================================
    # OBTENER VALUE POR TEXTO
    # =========================================================

    async def obtener_valor_por_texto(
        self,
        selector,
        texto
    ):
        opciones = await self.obtener_opciones(
            selector
        )

        texto_objetivo = self.normalizar_texto(
            texto
        )

        for opcion in opciones:
            texto_opcion = self.normalizar_texto(
                opcion["texto"]
            )

            if texto_opcion == texto_objetivo:
                return opcion["valor"]

        raise ValueError(
            f"No se encontró la opción "
            f"'{texto}' en '{selector}'."
        )

    # =========================================================
    # SELECCIONAR NATIVAMENTE
    # =========================================================

    async def seleccionar_nativamente(
        self,
        selector,
        valor,
        esperar_adf=False,
        esperar_post_seleccion=True
    ):
        print()
        print(
            f">>> Seleccionando: {selector}"
        )
        print(
            f">>> Value solicitado: '{valor}'"
        )

        elemento = self.page.locator(
            selector
        )

        await elemento.wait_for(
            state="visible",
            timeout=(
                self.TIEMPO_MAXIMO_CARGA * 1000
            )
        )

        opciones = await self.obtener_opciones(
            selector
        )

        indice_encontrado = -1

        for i, opcion in enumerate(
            opciones
        ):
            if opcion["valor"] == valor:
                indice_encontrado = i
                break

        if indice_encontrado == -1:
            await self.imprimir_opciones(
                selector,
                "SELECTOR SIN OPCIÓN SOLICITADA"
            )

            raise ValueError(
                f"No se encontró value='{valor}' "
                f"en el selector '{selector}'."
            )

        if opciones[
            indice_encontrado
        ].get("deshabilitada"):
            raise ValueError(
                f"La opción value='{valor}' "
                f"está deshabilitada en "
                f"'{selector}'."
            )

        print(
            f">>> Opción encontrada en índice "
            f"{indice_encontrado}: "
            f"'{opciones[indice_encontrado]['texto']}'"
        )

        await elemento.click()

        await self.page.keyboard.press(
            "Home"
        )

        if self.ESPERA_ENTRE_TECLAS > 0:
            await self.page.wait_for_timeout(
                self.ESPERA_ENTRE_TECLAS * 1000
            )

        for _ in range(
            indice_encontrado
        ):
            await self.page.keyboard.press(
                "ArrowDown"
            )

            if self.ESPERA_ENTRE_TECLAS > 0:
                await self.page.wait_for_timeout(
                    self.ESPERA_ENTRE_TECLAS * 1000
                )

        await self.page.keyboard.press(
            "Enter"
        )

        if esperar_adf:
            await self.esperar_valor_selector(
                selector,
                valor,
                timeout=(
                    self.TIEMPO_MAXIMO_CARGA * 1000
                )
            )

        if esperar_post_seleccion:
            if self.ESPERA_DESPUES_DE_SELECCION > 0:
                await self.page.wait_for_timeout(
                    self.ESPERA_DESPUES_DE_SELECCION
                    * 1000
                )

    # =========================================================
    # SELECCIONAR POR CÓDIGO ACADÉMICO
    # =========================================================

    async def seleccionar_por_codigo(
        self,
        selector,
        codigo_academico,
        texto_esperado=None,
        esperar_adf=False
    ):
        codigo_academico = str(
            codigo_academico
        )

        ultimo_error = None
        for intento in range(1, 4):
            try:
                if texto_esperado:
                    await self.esperar_opcion_estable(selector, texto_esperado)
                # ADF reconstruye los selectores con frecuencia; vuelve a
                # resolver el código justo antes de cada selección.
                valor = await self.obtener_valor_por_codigo(
                    selector, codigo_academico
                )
                print(
                    f">>> Código académico '{codigo_academico}' "
                    f"corresponde a value HTML '{valor}' (intento {intento}/3)."
                )
                await self.seleccionar_nativamente(
                    selector, valor, esperar_adf=esperar_adf
                )
                return valor
            except ValueError as error:
                ultimo_error = error
                if intento >= 3:
                    raise
                print(
                    f">>> El selector cambió al elegir '{codigo_academico}'; "
                    f"se consultará de nuevo ({intento}/3): {error}"
                )
                await self.page.wait_for_timeout(500 * intento)
        raise ultimo_error

    # =========================================================
    # SELECCIONAR POR TEXTO
    # =========================================================

    async def seleccionar_por_texto(
        self,
        selector,
        texto,
        codigo_academico_preferido=None,
        esperar_adf=True
    ):
        elemento = self.page.locator(
            selector
        )

        await elemento.wait_for(
            state="visible",
            timeout=(
                self.TIEMPO_MAXIMO_CARGA * 1000
            )
        )

        objetivo = self.normalizar_texto(
            texto
        )

        opciones = await self.obtener_opciones(
            selector
        )

        candidatos = []

        for i, opcion in enumerate(
            opciones
        ):
            valor = opcion["valor"]
            texto_opcion = opcion["texto"]

            texto_normalizado = (
                self.normalizar_texto(
                    texto_opcion
                )
            )

            codigo_academico = (
                self.extraer_codigo_academico(
                    texto_opcion
                )
            )

            if (
                texto_normalizado ==
                objetivo
            ):
                candidatos.append(
                    {
                        "valor": valor,
                        "indice": i,
                        "codigo_academico":
                            codigo_academico,
                        "texto": texto_opcion,
                        "tipo": "exacta",
                    }
                )

                continue

            partes = texto_normalizado.split(
                " ",
                1
            )

            if (
                len(partes) != 2
                or not partes[0].isdigit()
            ):
                continue

            texto_sin_codigo = partes[1]

            if (
                texto_sin_codigo ==
                objetivo
            ):
                candidatos.append(
                    {
                        "valor": valor,
                        "indice": i,
                        "codigo_academico":
                            codigo_academico,
                        "texto": texto_opcion,
                        "tipo": "sin_codigo",
                    }
                )

        if not candidatos:
            raise ValueError(
                f"No se encontró la opción "
                f"'{texto}' en el selector "
                f"'{selector}'."
            )

        candidato_seleccionado = None

        if codigo_academico_preferido:
            for candidato in candidatos:
                if (
                    candidato[
                        "codigo_academico"
                    ]
                    ==
                    str(
                        codigo_academico_preferido
                    )
                ):
                    candidato_seleccionado = (
                        candidato
                    )
                    break

        if candidato_seleccionado is None:
            if len(candidatos) == 1:
                candidato_seleccionado = (
                    candidatos[0]
                )

        if candidato_seleccionado is None:
            raise ValueError(
                f"La opción '{texto}' tiene "
                f"múltiples coincidencias y no "
                f"se especificó un código académico "
                f"válido."
            )

        print(
            f">>> Seleccionando "
            f"{candidato_seleccionado['texto']}"
        )

        await self.seleccionar_nativamente(
            selector,
            candidato_seleccionado["valor"],
            esperar_adf=esperar_adf
        )

        return candidato_seleccionado[
            "valor"
        ]

    # =========================================================
    # SELECCIONAR PLAN
    # =========================================================

    async def seleccionar_plan(
        self,
        nombre_plan=None
    ):
        codigo_plan = (
            self.codigo_plan
        )

        if nombre_plan is not None:
            objetivo = self.normalizar_texto(
                nombre_plan
            )

            if (
                objetivo !=
                self.normalizar_texto(
                    self.nombre_plan
                )
            ):
                raise ValueError(
                    "El plan solicitado no coincide "
                    "con el plan de estudios definido "
                    "en estudiante.json."
                )

        print(
            ">>> [PLAN] Esperando plan "
            f"{codigo_plan}..."
        )

        ultimo_error = None
        for intento in range(1, self.MAXIMO_INTENTOS_PLAN + 1):
            try:
                # No exigimos que el texto sea idéntico: el SIA a veces
                # antepone la sede/facultad o cambia espacios y mayúsculas.
                # Esperamos opciones y validamos por el código del plan.
                await self.esperar_selector_con_opciones(
                    self.SELECTOR_PLAN,
                    cantidad_minima=1
                )
                # El código es la identidad fiable del plan. El texto puede
                # cambiar de formato entre sesiones del SIA.
                await self.seleccionar_por_codigo(
                    self.SELECTOR_PLAN,
                    codigo_plan,
                    esperar_adf=False
                )
                break
            except ValueError as error:
                ultimo_error = error
                if intento >= self.MAXIMO_INTENTOS_PLAN:
                    raise
                print(
                    f">>> [PLAN] No apareció el plan en el intento "
                    f"{intento}; se vuelve a pulsar Mostrar y se reintenta."
                )
                boton = self.page.get_by_text("Mostrar", exact=True).first
                try:
                    await boton.wait_for(state="visible", timeout=5000)
                    await boton.click()
                except Exception:
                    # Algunas vistas renderizan el botón como input.
                    boton = self.page.locator(
                        'input[type="submit"], button'
                    ).filter(has_text="Mostrar").first
                    await boton.click(timeout=5000)
                await self.page.wait_for_timeout(500)
        else:
            raise ultimo_error

        print(
            ">>> [PLAN] Plan seleccionado correctamente."
        )

    # =========================================================
    # ASEGURAR FILTROS DE CARRERA
    # =========================================================

    async def asegurar_filtros_de_carrera(
        self
    ):
        print()
        print(
            "================================================"
        )
        print(
            ">>> CONFIGURANDO FILTROS DE CARRERA"
        )
        print(
            "================================================"
        )

        # -----------------------------------------------------
        # PASO 1: NIVEL DE ESTUDIO
        # -----------------------------------------------------

        print(
            ">>> PASO 1: Nivel de estudio"
        )

        await self.esperar_selector_habilitado(
            self.SELECTOR_NIVEL_ESTUDIO
        )

        await self.seleccionar_nativamente(
            self.SELECTOR_NIVEL_ESTUDIO,
            self.VALOR_PREGRADO
        )

        # -----------------------------------------------------
        # PASO 2: SEDE
        # -----------------------------------------------------

        print(
            ">>> PASO 2: Sede"
        )

        await self.esperar_selector_habilitado(
            self.SELECTOR_SEDE
        )

        await self.esperar_opcion_estable(
            self.SELECTOR_SEDE,
            self.nombre_sede
        )

        await self.seleccionar_por_codigo(
            self.SELECTOR_SEDE,
            self.codigo_sede,
            texto_esperado=self.nombre_sede,
            esperar_adf=False
        )

        print(
            f">>> Sede seleccionada: "
            f"{self.nombre_sede}"
        )

        # -----------------------------------------------------
        # PASO 3: FACULTAD
        # -----------------------------------------------------

        print(
            ">>> PASO 3: Facultad"
        )

        await self.esperar_selector_habilitado(
            self.SELECTOR_FACULTAD
        )

        await self.esperar_opcion_estable(
            self.SELECTOR_FACULTAD,
            self.nombre_facultad
        )

        await self.seleccionar_por_codigo(
            self.SELECTOR_FACULTAD,
            self.codigo_facultad,
            texto_esperado=self.nombre_facultad,
            esperar_adf=False
        )

        print(
            f">>> Facultad seleccionada: "
            f"{self.nombre_facultad}"
        )

        # -----------------------------------------------------
        # PASO 4: PLAN
        # -----------------------------------------------------

        print(
            ">>> PASO 4: Plan de estudios"
        )

        await self.esperar_selector_habilitado(
            self.SELECTOR_PLAN
        )

        await self.seleccionar_plan(self.nombre_plan)

        print(
            f">>> Plan seleccionado: "
            f"{self.nombre_plan}"
        )

        print(
            ">>> Filtros de carrera preparados."
        )

    # =========================================================
    # ESPERAR TIPOLOGÍA
    # =========================================================

    async def esperar_tipologia(
        self
    ):
        print(
            ">>> Esperando filtro de tipología..."
        )

        await self.esperar_selector_habilitado(
            self.SELECTOR_TIPOLOGIA
        )

        await self.esperar_selector_con_opciones(
            self.SELECTOR_TIPOLOGIA,
            cantidad_minima=1
        )

        print(
            ">>> Filtro de tipología disponible."
        )

    # =========================================================
    # SELECCIONAR TIPOLOGÍA LIBRE ELECCIÓN
    # =========================================================

    async def seleccionar_tipologia_libre_eleccion(
        self
    ):
        # Selecciona Libre Elección por texto y no depende
        # de un value HTML fijo.

        opciones = await self.obtener_opciones(
            self.SELECTOR_TIPOLOGIA
        )

        candidatas = []

        for opcion in opciones:
            texto = self.normalizar_texto(
                opcion.get("texto", "")
            )

            if (
                "LIBRE" in texto
                or "ELECCION" in texto
            ):
                candidatas.append(
                    opcion
                )

        if len(candidatas) == 1:
            opcion = candidatas[0]

            print(
                f">>> Tipología Libre Elección "
                f"encontrada: "
                f"{opcion['texto']} "
                f"(value='{opcion['valor']}')"
            )

            await self.seleccionar_nativamente(
                self.SELECTOR_TIPOLOGIA,
                opcion["valor"],
                esperar_adf=False,
            )

            return

        if len(candidatas) > 1:
            exactas = [
                opcion
                for opcion in candidatas
                if self.normalizar_texto(
                    opcion.get("texto", "")
                )
                == "LIBRE ELECCION"
            ]

            if len(exactas) == 1:
                await self.seleccionar_nativamente(
                    self.SELECTOR_TIPOLOGIA,
                    exactas[0]["valor"],
                    esperar_adf=False,
                )

                return

        print(
            ">>> No se encontró el texto de Libre Elección; "
            f"se intentará value="
            f"'{self.VALOR_TIPOLOGIA_LIBRE_ELECCION}'."
        )

        await self.seleccionar_nativamente(
            self.SELECTOR_TIPOLOGIA,
            self.VALOR_TIPOLOGIA_LIBRE_ELECCION,
            esperar_adf=False,
        )

    # =========================================================
    # BOTÓN MOSTRAR
    # =========================================================

    async def asegurar_boton_mostrar(
        self
    ):
        print(
            ">>> Esperando botón Mostrar..."
        )

        timeout = (
            self.TIEMPO_MAXIMO_CARGA * 1000
        )

        await self.page.wait_for_function(
            """
            () => {
                const elementos =
                    Array.from(
                        document.querySelectorAll(
                            'button, input, a, span, div'
                        )
                    );

                return elementos.some(
                    elemento => {
                        const texto =
                            (
                                elemento.innerText ||
                                elemento.value ||
                                ""
                            )
                            .trim();

                        if (texto !== "Mostrar") {
                            return false;
                        }

                        const estilo =
                            window.getComputedStyle(
                                elemento
                            );

                        if (
                            estilo.display === "none" ||
                            estilo.visibility === "hidden"
                        ) {
                            return false;
                        }

                        const rect =
                            elemento.getBoundingClientRect();

                        return (
                            rect.width > 0 &&
                            rect.height > 0 &&
                            !elemento.disabled
                        );
                    }
                );
            }
            """,
            timeout=timeout
        )

        print(
            ">>> Botón Mostrar visible y habilitado."
        )

    # =========================================================
    # CONFIGURAR CATÁLOGO NORMAL
    # =========================================================

    async def configurar(
        self,
        nombre_plan=None
    ):
        print()
        print(
            "================================================"
        )
        print(
            ">>> CONFIGURANDO CATÁLOGO NORMAL"
        )
        print(
            "================================================"
        )

        await self.asegurar_filtros_de_carrera()

        if nombre_plan:
            await self.seleccionar_plan(
                nombre_plan
            )

        await self.esperar_tipologia()

        await self.seleccionar_nativamente(
            self.SELECTOR_TIPOLOGIA,
            self.VALOR_TIPOLOGIA_NORMAL,
            esperar_adf=False
        )

        await self.asegurar_boton_mostrar()

    # =========================================================
    # SELECCIONAR FACULTAD DE LIBRE ELECCIÓN
    # =========================================================

    async def seleccionar_facultad_libre_eleccion(
        self,
        indice
    ):
        # Este método trabaja exclusivamente con soc6,
        # que es el selector que SIA utiliza para
        # "¿Por qué facultad?" después de seleccionar
        # la sede de búsqueda.
        #
        # No ejecuta los pasos 1-7.
        #
        # Esto permite:
        #
        #     1. seleccionar la primera facultad
        #     2. Mostrar
        #     3. analizar la tabla
        #     4. seleccionar la segunda facultad
        #     5. analizar la nueva tabla
        #
        # El método solamente cambia soc6. No pulsa Mostrar.

        if not isinstance(
            indice,
            int
        ):
            raise TypeError(
                "El índice de la facultad de Libre "
                "Elección debe ser un entero."
            )

        if indice < 0:
            raise ValueError(
                "El índice de la facultad de Libre "
                "Elección no puede ser negativo."
            )

        if indice >= len(
            self.opciones_facultad_libre_eleccion
        ):
            raise IndexError(
                "El índice solicitado para la facultad "
                "de Libre Elección no existe. "
                f"Índice: {indice}. "
                f"Opciones disponibles: "
                f"{len(self.opciones_facultad_libre_eleccion)}."
            )

        opcion_facultad = (
            self.opciones_facultad_libre_eleccion[
                indice
            ]
        )

        print()
        print(
            "================================================"
        )
        print(
            ">>> CAMBIANDO FACULTAD DE LIBRE ELECCIÓN"
        )
        print(
            "================================================"
        )
        print(
            f">>> Índice de búsqueda: {indice}"
        )
        print(
            f">>> Opción: {opcion_facultad}"
        )

        await self.esperar_selector_habilitado(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION
        )

        await self.esperar_selector_con_opciones(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION,
            cantidad_minima=1
        )

        await self.esperar_opcion_estable(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION,
            opcion_facultad
        )

        await self.seleccionar_por_texto(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION,
            opcion_facultad,
            esperar_adf=False
        )

        # SIA puede reconstruir el contenido asociado al
        # selector después del Enter. Esperamos el mismo
        # asentamiento utilizado en los demás selectores.

        if self.ESPERA_AL_RECONSTRUIR_RAMA > 0:
            await self.page.wait_for_timeout(
                self.ESPERA_AL_RECONSTRUIR_RAMA * 1000
            )

        await self.esperar_selector_habilitado(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION
        )

        await self.esperar_opcion_estable(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION,
            opcion_facultad
        )

        print(
            f">>> Facultad de Libre Elección "
            f"seleccionada: {opcion_facultad}"
        )

    # =========================================================
    # CONFIGURAR LIBRE ELECCIÓN - UN INTENTO
    # =========================================================

    async def _configurar_libre_eleccion_un_intento(
        self,
        nombre_plan=None
    ):
        # -----------------------------------------------------
        # PASOS 1-4:
        # Ruta académica normal del estudiante.
        #
        # Es exactamente el mismo flujo utilizado por
        # los workers normales.
        # -----------------------------------------------------

        await self.asegurar_filtros_de_carrera()

        if nombre_plan:
            await self.seleccionar_plan(
                nombre_plan
            )

        # -----------------------------------------------------
        # PASO 5:
        # Tipología = Libre Elección.
        # -----------------------------------------------------

        print(
            ">>> PASO 5: Tipología = Libre Elección"
        )

        await self.esperar_tipologia()

        await self.seleccionar_tipologia_libre_eleccion()

        print(
            ">>> Esperando reconstrucción de "
            "Libre Elección..."
        )

        # -----------------------------------------------------
        # PASO 6:
        # "Por facultad y plan".
        # -----------------------------------------------------

        print(
            ">>> PASO 6: Forma de búsqueda = "
            "Por facultad y plan"
        )

        await self.esperar_selector_habilitado(
            self.SELECTOR_FORMA_BUSQUEDA
        )

        await self.esperar_selector_con_opciones(
            self.SELECTOR_FORMA_BUSQUEDA,
            cantidad_minima=1
        )

        await self.esperar_opcion_estable(
            self.SELECTOR_FORMA_BUSQUEDA,
            "Por facultad y plan"
        )

        await self.seleccionar_por_texto(
            self.SELECTOR_FORMA_BUSQUEDA,
            "Por facultad y plan",
            esperar_adf=False
        )

        print(
            ">>> Esperando reconstrucción de "
            "la búsqueda por Facultad y Plan..."
        )

        # -----------------------------------------------------
        # PASO 7:
        # Sede de Libre Elección -> soc10.
        # -----------------------------------------------------

        print(
            ">>> PASO 7: Sede de Libre Elección"
        )

        # La sede está definida en el nivel superior
        # de configuracion_libre_eleccion.json.
        #
        # NO se debe buscar dentro de:
        #
        #     self.configuracion_libre_eleccion
        #
        # porque esa variable contiene únicamente la
        # configuración específica del plan.

        opcion_sede = (
            self.nombre_sede_libre_eleccion
        )

        if not opcion_sede:
            raise RuntimeError(
                "No existe una sede de búsqueda configurada "
                "para Libre Elección."
            )

        await self.esperar_selector_habilitado(
            self.SELECTOR_SEDE_LIBRE_ELECCION
        )

        await self.esperar_selector_con_opciones(
            self.SELECTOR_SEDE_LIBRE_ELECCION,
            cantidad_minima=1
        )

        await self.esperar_opcion_estable(
            self.SELECTOR_SEDE_LIBRE_ELECCION,
            opcion_sede
        )

        await self.seleccionar_por_texto(
            self.SELECTOR_SEDE_LIBRE_ELECCION,
            opcion_sede,
            esperar_adf=False
        )

        print(
            ">>> Sede de búsqueda seleccionada: "
            f"{opcion_sede}"
        )

        # -----------------------------------------------------
        # PASO 8:
        # ¿Por qué facultad? -> soc6.
        #
        # IMPORTANTE:
        #
        # Después de seleccionar soc10, SIA reconstruye
        # el selector de facultad como soc6.
        #
        # soc2 corresponde a la facultad de la ruta
        # académica de los pasos 1-4 y NO debe utilizarse
        # aquí.
        #
        # En esta primera búsqueda se selecciona únicamente
        # la primera opción configurada.
        #
        # Después de esta selección se pulsa Mostrar.
        # La segunda opción se seleccionará posteriormente,
        # después de analizar la primera tabla.
        # -----------------------------------------------------

        print(
            ">>> PASO 8: ¿Por qué facultad?"
        )

        if not self.opciones_facultad_libre_eleccion:
            raise RuntimeError(
                "No existen opciones configuradas "
                "para el paso 8 de Libre Elección."
            )

        opcion_facultad = (
            self.opciones_facultad_libre_eleccion[
                0
            ]
        )

        print(
            ">>> Primera búsqueda de Libre Elección:"
        )
        print(
            f">>> ¿Por qué facultad?: "
            f"{opcion_facultad}"
        )

        await self.esperar_selector_habilitado(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION
        )

        await self.esperar_selector_con_opciones(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION,
            cantidad_minima=1
        )

        await self.esperar_opcion_estable(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION,
            opcion_facultad
        )

        await self.seleccionar_por_texto(
            self.SELECTOR_FACULTAD_LIBRE_ELECCION,
            opcion_facultad,
            esperar_adf=False
        )

        # La selección de soc6 puede reconstruir parte del
        # formulario. Esperamos el asentamiento antes de
        # intentar utilizar el botón Mostrar.

        if self.ESPERA_AL_RECONSTRUIR_RAMA > 0:
            await self.page.wait_for_timeout(
                self.ESPERA_AL_RECONSTRUIR_RAMA * 1000
            )

        print(
            ">>> Primera opción de Libre Elección "
            "seleccionada correctamente."
        )

        # -----------------------------------------------------
        # PASO 9:
        # Mostrar.
        # -----------------------------------------------------

        print(
            ">>> PASO 9: Esperando aparición del botón Mostrar..."
        )

        print(
            ">>> PASO 9: Mostrar"
        )

        await self.mostrar_resultados()

        print(
            ">>> Primera búsqueda de Libre Elección "
            "ejecutada correctamente."
        )

        # En este punto la página queda mostrando la primera
        # tabla. El proceso externo puede analizarla.
        #
        # Después podrá llamar:
        #
        #     seleccionar_facultad_libre_eleccion(1)
        #
        # para cambiar soc6 a la segunda opción.
        #
        # Ese método NO vuelve a ejecutar los pasos 1-7.

    # =========================================================
    # CONFIGURAR LIBRE ELECCIÓN
    # =========================================================

    async def configurar_libre_eleccion(
        self,
        nombre_plan=None
    ):
        print()
        print(
            "================================================"
        )
        print(
            ">>> CONFIGURANDO CATÁLOGO LIBRE ELECCIÓN"
        )
        print(
            "================================================"
        )

        ultimo_error = None

        for intento in range(
            1,
            self.MAXIMO_INTENTOS_LIBRE_ELECCION + 1
        ):
            print()
            print(
                "------------------------------------------------"
            )
            print(
                ">>> INTENTO "
                f"{intento}/"
                f"{self.MAXIMO_INTENTOS_LIBRE_ELECCION} "
                "DE LIBRE ELECCIÓN"
            )
            print(
                "------------------------------------------------"
            )

            try:
                # En el primer intento se utiliza el estado
                # actual de la página.
                #
                # Si un intento anterior falló, se vuelve a
                # abrir completamente el catálogo para evitar
                # continuar sobre un formulario parcialmente
                # reconstruido por ADF.

                if intento > 1:
                    print(
                        ">>> Reiniciando catálogo SIA "
                        "para el siguiente intento..."
                    )

                    await self.abrir()

                await self._configurar_libre_eleccion_un_intento(
                    nombre_plan=nombre_plan
                )

                print()
                print(
                    "✓ Libre Elección configurada y "
                    "primera consulta ejecutada correctamente."
                )

                return

            except Exception as error:
                ultimo_error = error

                print()
                print(
                    "⚠ Falló el intento "
                    f"{intento}/"
                    f"{self.MAXIMO_INTENTOS_LIBRE_ELECCION} "
                    "de Libre Elección."
                )
                print(
                    f"⚠ Motivo: {error}"
                )

                if intento < self.MAXIMO_INTENTOS_LIBRE_ELECCION:
                    print(
                        ">>> Se volverá a intentar "
                        "la configuración desde cero..."
                    )

                    await asyncio.sleep(1)

        raise RuntimeError(
            "No fue posible configurar Libre Elección "
            f"después de "
            f"{self.MAXIMO_INTENTOS_LIBRE_ELECCION} "
            "intentos."
        ) from ultimo_error

    # =========================================================
    # MOSTRAR RESULTADOS
    # =========================================================

    async def mostrar_resultados(
        self
    ):
        print(
            ">>> Preparando clic en Mostrar..."
        )

        timeout = (
            self.TIEMPO_MAXIMO_CARGA * 1000
        )

        # Esperamos a que el botón correspondiente a la
        # configuración actual esté realmente visible,
        # habilitado y listo para ser utilizado.

        await self.asegurar_boton_mostrar()

        # Volvemos a localizar el botón justo antes del click.
        #
        # Esto es importante con ADF porque durante la
        # reconstrucción del formulario pueden desaparecer
        # nodos antiguos y aparecer otros nuevos.

        boton = self.page.get_by_text(
            "Mostrar",
            exact=True
        )

        cantidad = await boton.count()

        if cantidad == 0:
            raise RuntimeError(
                "No se encontró el botón Mostrar "
                "después de esperar su disponibilidad."
            )

        print(
            f">>> Elementos Mostrar encontrados: "
            f"{cantidad}"
        )

        boton_activo = None

        for indice in range(cantidad):
            candidato = boton.nth(indice)

            try:
                if not await candidato.is_visible():
                    continue

                if not await candidato.is_enabled():
                    continue

                boton_activo = candidato
                break

            except Exception:
                continue

        if boton_activo is None:
            raise RuntimeError(
                "Se encontraron elementos 'Mostrar', "
                "pero ninguno está visible y habilitado."
            )

        print(
            ">>> Botón Mostrar activo encontrado."
        )

        await boton_activo.click(
            timeout=timeout
        )

        print(
            ">>> Consulta enviada mediante Mostrar."
        )

        await self.esperar_resultados()

    # =========================================================
    # ESPERAR RESULTADOS
    # =========================================================

    async def esperar_resultados(
        self
    ):
        print(
            ">>> Esperando resultados..."
        )

        timeout = (
            self.TIEMPO_MAXIMO_CARGA * 1000
        )

        try:
            await self.page.locator(
                "table.af_table_data-table"
            ).first.wait_for(
                state="visible",
                timeout=timeout
            )

            await self.page.wait_for_function(
                """
                () => {
                    const tablas =
                        document.querySelectorAll(
                            'table.af_table_data-table'
                        );

                    for (const tabla of tablas) {
                        const filas =
                            tabla.querySelectorAll('tr');

                        for (const fila of filas) {
                            const celdas =
                                fila.querySelectorAll('td');

                            if (celdas.length >= 5) {
                                const codigo =
                                    celdas[0]
                                        .innerText
                                        .trim();

                                const nombre =
                                    celdas[1]
                                        .innerText
                                        .trim();

                                if (
                                    codigo &&
                                    nombre
                                ) {
                                    return true;
                                }
                            }
                        }
                    }

                    return false;
                }
                """,
                timeout=timeout
            )

            print(
                "✓ Resultados de materias detectados."
            )

        except Exception as error:
            raise RuntimeError(
                "No aparecieron los resultados de "
                "materias dentro del tiempo esperado."
            ) from error

    # =========================================================
    # ABRIR MATERIA
    # =========================================================

    async def abrir_materia(
        self,
        codigo: str
    ):
        enlace = self.page.get_by_text(
            codigo,
            exact=True
        )

        if await enlace.count() == 0:
            raise MateriaNoDisponibleEnSIA(
                f"No se encontró el enlace "
                f"de la materia {codigo}."
            )

        await enlace.first.click(
            timeout=(
                min(self.TIEMPO_MAXIMO_CARGA, 15) * 1000
            )
        )

        # Algunas referencias del catálogo conducen a la página de error
        # propia del SIA. Detectarla evita esperar todo el timeout de carga.
        if "errornavegacion.jsf" in self.page.url.casefold():
            raise MateriaNoDisponibleEnSIA(
                f"El SIA rechazó el detalle de la materia {codigo} "
                "(errorNavegacion.jsf).",
                sesion_invalidada=True,
            )

        await self.page.wait_for_function(
            """() => location.href.toLowerCase().includes('errornavegacion.jsf') ||
                Array.from(document.querySelectorAll('body *')).some(
                    e => e.children.length === 0 &&
                    e.textContent.trim() === 'Información de la asignatura'
                )""",
            timeout=min(self.TIEMPO_MAXIMO_CARGA, 15) * 1000,
        )

        if "errornavegacion.jsf" in self.page.url.casefold():
            raise MateriaNoDisponibleEnSIA(
                f"El SIA rechazó el detalle de la materia {codigo} "
                "(errorNavegacion.jsf).",
                sesion_invalidada=True,
            )

    # =========================================================
    # VOLVER AL CATÁLOGO
    # =========================================================

    async def volver(
        self
    ):
        boton = self.page.get_by_text(
            "Volver",
            exact=True
        )

        if await boton.count() == 0:
            raise RuntimeError(
                "No se encontró el botón Volver."
            )

        await boton.first.click(
            timeout=(
                self.TIEMPO_MAXIMO_CARGA * 1000
            )
        )
        
        await self.esperar_resultados()
