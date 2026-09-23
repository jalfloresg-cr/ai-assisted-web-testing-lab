"""Sesión de navegador controlada por Skyvern.

pytest-bdd ejecuta los steps de forma síncrona y Skyvern es async, así que
mantenemos un event loop propio por escenario y lo reutilizamos en cada step.
"""
import asyncio
import os
from pathlib import Path

import httpx


class Sesion:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        # El SDK de Skyvern espera solo 60 s por defecto. Con un LLM local cada
        # acción puede tardar bastante más, así que lo subimos (configurable).
        self.timeout = float(os.getenv("SKYVERN_TIMEOUT", "600"))
        self._browser = None
        self.page = None

    def run(self, coro):
        try:
            return self.loop.run_until_complete(coro)
        except httpx.ReadTimeout as e:
            raise TimeoutError(
                f"El servidor Skyvern no respondió en {self.timeout:.0f} s. "
                "Suele ser el modelo (Ollama) demasiado lento o atascado: revisa `ollama ps` "
                "(¿100% GPU?), los logs del servidor Skyvern y, si el modelo es lento pero "
                "funciona, sube SKYVERN_TIMEOUT."
            ) from e

    def abrir(self) -> None:
        from skyvern import Skyvern  # import perezoso: solo si hay navegador real

        skyvern = Skyvern(
            base_url=os.environ["SKYVERN_BASE_URL"],
            api_key=os.environ["SKYVERN_API_KEY"],
            timeout=self.timeout,
        )
        headless = os.getenv("HEADLESS", "false").lower() == "true"
        self._browser = self.run(skyvern.launch_local_browser(headless=headless))
        self.page = self.run(self._browser.get_working_page())

    def capturar(self, ruta: Path) -> bool:
        """Guarda una captura de la página actual. Devuelve False si no se pudo (nunca lanza)."""
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            pagina = getattr(self.page, "page", self.page)  # SkyvernPage.page = Page de Playwright
            self.run(pagina.screenshot(path=str(ruta), full_page=True, timeout=15000))
            return True
        except Exception:
            return False

    def cerrar(self) -> None:
        try:
            if self._browser is not None:
                self.run(self._browser.close())
        finally:
            self.loop.close()
