# =============================================================
# NAVEGADOR DEL SIA
# =============================================================
#
# Este módulo administra el navegador utilizado por Fénix
# para interactuar con el Sistema de Información Académica
# (SIA).
#
# La navegación se realiza mediante Playwright.
#
# La estructura utilizada es:
#
#   Playwright
#       ↓
#   Browser (Chromium)
#       ↓
#   BrowserContext
#       ↓
#   Page
#
# El Browser representa el proceso de Chromium.
#
# Un BrowserContext representa una sesión independiente dentro
# del navegador. Cada contexto tiene sus propias cookies,
# almacenamiento y estado de navegación.
#
# Una Page representa una pestaña dentro de un contexto.
#
# Fénix mantiene un único proceso de Chromium durante la
# actualización y puede crear varios contextos independientes.
# Esto permite que diferentes workers trabajen al mismo tiempo
# sin compartir directamente sus sesiones.
#
# Además, si una sesión queda en un estado problemático,
# el contexto puede cerrarse y reemplazarse sin necesidad de
# cerrar todo Chromium.
#

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright
)


class NavegadorSIA:

    # =========================================================
    # INICIALIZAR
    # =========================================================

    def __init__(
        self,
        playwright: Playwright,
        ancho: int,
        alto: int,
        headless: bool = False
    ):
        # Instancia de Playwright proporcionada por el programa.
        #
        # Esta instancia es la que permite acceder a Chromium
        # y utilizar su API de automatización.
        self.playwright = playwright

        # Tamaño de la ventana utilizada por las páginas del SIA.
        #
        # Se conserva aquí para utilizar las mismas dimensiones
        # al crear nuevos contextos.
        self.ancho = ancho
        self.alto = alto

        # Indica si Chromium se ejecutará sin mostrar una ventana.
        #
        # En producción normalmente se utiliza headless=True.
        # Durante el desarrollo puede ser útil dejarlo en False
        # para observar directamente lo que hace el navegador.
        self.headless = headless

        # Proceso de Chromium administrado por esta instancia.
        #
        # Se crea en iniciar().
        self.browser: Browser | None = None

        # Contexto principal de la instancia.
        #
        # Este contexto se utiliza como sesión principal y puede
        # ser reemplazado mediante reiniciar_sesion().
        self.context: BrowserContext | None = None

        # Página principal asociada al contexto principal.
        self.page: Page | None = None

    # =========================================================
    # INICIAR NAVEGADOR
    # =========================================================

    async def iniciar(self):
        # Inicia Chromium y crea una primera sesión.
        #
        # El navegador se inicia una sola vez durante el ciclo
        # de actualización. Después pueden crearse contextos
        # adicionales mediante crear_contexto().
        #
        # Retorna:
        #   La primera Page creada.

        if self.browser is not None:
            raise RuntimeError(
                "El navegador ya está iniciado."
            )

        # Iniciar el proceso de Chromium.
        self.browser = (
            await self.playwright.chromium.launch(
                headless=self.headless
            )
        )

        # Crear el contexto principal.
        self.context = (
            await self.browser.new_context(
                viewport={
                    "width": self.ancho,
                    "height": self.alto
                }
            )
        )

        # Crear la primera página dentro del contexto.
        self.page = (
            await self.context.new_page()
        )

        return self.page

    # =========================================================
    # CREAR CONTEXTO
    # =========================================================

    async def crear_contexto(self):
        # Crea un BrowserContext independiente.
        #
        # Los contextos permiten que varios workers utilicen
        # el mismo proceso de Chromium sin compartir cookies,
        # almacenamiento ni estado de navegación.
        #
        # Cada worker puede recibir su propio contexto y crear
        # dentro de él las páginas que necesite.
        #
        # Retorna:
        #   Un BrowserContext nuevo.

        if self.browser is None:
            raise RuntimeError(
                "No se puede crear un contexto porque "
                "el navegador no está iniciado."
            )

        return await self.browser.new_context(
            viewport={
                "width": self.ancho,
                "height": self.alto
            }
        )

    # =========================================================
    # CREAR PÁGINA
    # =========================================================

    async def crear_pagina(
        self,
        contexto: BrowserContext
    ):
        # Crea una Page dentro del contexto indicado.
        #
        # El contexto es recibido como parámetro en lugar de
        # utilizar siempre self.context porque los workers pueden
        # trabajar con contextos diferentes.

        return await contexto.new_page()

    # =========================================================
    # CERRAR CONTEXTO
    # =========================================================

    async def cerrar_contexto(
        self,
        contexto: BrowserContext | None
    ):
        # Cierra un contexto de forma segura.
        #
        # No se considera un error intentar cerrar un contexto
        # que no existe o que ya fue cerrado.
        #
        # Se captura la excepción para evitar que un problema
        # durante la limpieza detenga innecesariamente el resto
        # de la actualización.

        if contexto is None:
            return

        try:
            await contexto.close()

        except Exception as error:
            print(
                "⚠ No se pudo cerrar correctamente "
                f"el contexto: {error}"
            )

    # =========================================================
    # REINICIAR SESIÓN
    # =========================================================

    async def reiniciar_sesion(self):
        # Reemplaza el contexto principal por una sesión nueva.
        #
        # El proceso de Chromium permanece abierto.
        #
        # Esto resulta útil cuando la sesión actual del SIA queda
        # en un estado inesperado y continuar utilizando sus
        # cookies o su estado de navegación podría causar errores.
        #
        # El procedimiento es:
        #
        #   1. Cerrar el contexto actual.
        #   2. Eliminar las referencias a ese contexto y su página.
        #   3. Crear un contexto completamente nuevo.
        #   4. Crear una nueva página.
        #
        # Retorna:
        #   La nueva Page principal.

        if self.browser is None:
            raise RuntimeError(
                "No se puede reiniciar la sesión porque "
                "el navegador no está iniciado."
            )

        print()
        print(
            "Reiniciando sesión del SIA..."
        )

        # Si existe un contexto anterior, cerrarlo antes
        # de crear la nueva sesión.
        if self.context is not None:

            await self.cerrar_contexto(
                self.context
            )

            self.context = None
            self.page = None

        # Crear una sesión completamente nueva.
        self.context = (
            await self.browser.new_context(
                viewport={
                    "width": self.ancho,
                    "height": self.alto
                }
            )
        )

        # Crear la página inicial de la nueva sesión.
        self.page = (
            await self.context.new_page()
        )

        print(
            "✓ Nueva sesión del SIA creada."
        )

        return self.page

    # =========================================================
    # CERRAR NAVEGADOR
    # =========================================================

    async def cerrar(self):
        # Libera todos los recursos administrados por esta
        # instancia.
        #
        # Primero se cierra el contexto principal y después
        # el navegador.
        #
        # Los contextos adicionales creados para otros workers
        # deben ser cerrados por quien los haya creado mediante
        # cerrar_contexto().
        #
        # El método intenta realizar la limpieza aunque alguno
        # de los recursos ya haya sido cerrado.

        if self.context is not None:

            await self.cerrar_contexto(
                self.context
            )

            self.context = None
            self.page = None

        if self.browser is not None:

            try:
                await self.browser.close()

            except Exception as error:
                print(
                    "⚠ No se pudo cerrar correctamente "
                    f"el navegador: {error}"
                )

            self.browser = None