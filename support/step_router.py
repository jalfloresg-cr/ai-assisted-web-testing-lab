"""Router genérico entre Gherkin y Skyvern.

El router conoce operaciones:

- seleccionar profile
- navegar (abrir la aplicación, ir a una ruta, atrás, recargar)
- fill      (determinístico por selector/id, o semántico)
- click     (determinístico por selector/id, o semántico)
- select, check, teclas, limpiar, hover, adjuntar, scroll (determinísticos)
- extract   (texto por selector/id sin LLM, o semántico)
- validate  (visible, texto, valor, cantidad, URL, habilitado, marcado
             por selector; o semántico)
- operaciones con variables
- act como fallback (bloqueable con ROUTER_STRICT=true)

Cada step registra en ``ultima_ruta`` cómo se resolvió
(deterministico / semantico / agentic / sin_regla) para la evidencia.

Dado y Cuando comparten el mismo vocabulario de acciones: la palabra clave
expresa la intención para el lector (contexto vs. acción bajo prueba), no
limita la operación. Entonces tiene su propio vocabulario de afirmaciones.

No conoce conceptos específicos de una aplicación como:

- username
- password
- otp
- cuentas
- tarjetas
- menús
- botones concretos
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

from .datos import DatosPrueba
from .variables import (
    ExtractorUI,
    VariablesEscenario,
    iguales,
    numero,
)


class StepNoReconocido(AssertionError):
    """El step no coincide con ninguna regla del router y el modo estricto está activo."""


def _modo_estricto() -> bool:
    return os.getenv("ROUTER_STRICT", "false").strip().lower() in {"1", "true", "si", "sí"}


# ================================================================
# PROFILE / NAVIGATION
# ================================================================

RE_PERFIL = re.compile(
    r'(?:que\s+)?uso el perfil de prueba '
    r'"(?P<perfil>[^"]+)"',
    re.I,
)

# Frase completa y explícita. Antes bastaba la palabra "abro" en cualquier
# parte del step, así que "abro el menú de transferencias" volvía al login.
#
# abro la aplicación / abro la banca en línea / navego a la aplicación
#
RE_ABRIR_APP = re.compile(
    r"(?:abro|navego a|entro a) la "
    r"(?:aplicaci[oó]n|banca en l[ií]nea)",
    re.I,
)

# navego a la ruta "/transfers"
#
RE_NAVEGAR_RUTA = re.compile(
    r'navego a la ruta "(?P<ruta>[^"]+)"',
    re.I,
)

# regreso a la página anterior   (botón atrás del navegador)
#
RE_ATRAS = re.compile(
    r"regreso a la p[aá]gina anterior",
    re.I,
)

# recargo la página
#
RE_RECARGAR = re.compile(
    r"recargo la p[aá]gina",
    re.I,
)

RE_PREFIJO_QUE = re.compile(r"^que\s+", re.I)


def _sin_que(texto: str) -> str:
    """ "que abro la aplicación" -> "abro la aplicación" (el "que" es típico de Dado)."""
    return RE_PREFIJO_QUE.sub("", texto.strip(), count=1)


def _timeout_ms() -> int:
    """Espera máxima para localizar elementos por selector (SELECTOR_TIMEOUT_MS)."""
    return int(os.getenv("SELECTOR_TIMEOUT_MS", "10000"))


def _normalizar_texto(texto: str) -> str:
    """Colapsa espacios y saltos de línea: "Product\n  Summary" -> "Product Summary"."""
    return " ".join(str(texto).split())


# Nombres de teclas en español -> nombres de Playwright. Cualquier otro nombre
# (ArrowDown, Control+A, F5...) se envía tal cual.
_TECLAS = {
    "enter": "Enter",
    "intro": "Enter",
    "tab": "Tab",
    "tabulador": "Tab",
    "escape": "Escape",
    "esc": "Escape",
    "espacio": "Space",
    "retroceso": "Backspace",
    "suprimir": "Delete",
    "flecha abajo": "ArrowDown",
    "flecha arriba": "ArrowUp",
    "flecha izquierda": "ArrowLeft",
    "flecha derecha": "ArrowRight",
}


def _tecla(nombre: str) -> str:
    return _TECLAS.get(nombre.strip().lower(), nombre.strip())


def _primera_linea(exc: Exception) -> str:
    """Los errores de Playwright traen un log de varias líneas; basta la primera."""
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0][:300]


def _archivo_adjunto(ruta: str) -> str:
    """Ruta relativa a la raíz del proyecto, que debe existir."""
    archivo = Path(ruta)
    if archivo.is_absolute():
        raise AssertionError(
            f'La ruta "{ruta}" debe ser relativa a la raíz del proyecto '
            '(ej. "data/archivos/comprobante.pdf").'
        )
    if not archivo.is_file():
        raise AssertionError(
            f'No existe el archivo a adjuntar "{ruta}" (relativo a {Path.cwd()}).'
        )
    return str(archivo.resolve())


def _url_ruta(base: str, ruta: str) -> str:
    """Une BASE_URL con una ruta relativa conservando el path base (p. ej. /app/)."""
    if "://" in ruta:
        raise AssertionError(
            f'La ruta "{ruta}" debe ser relativa a BASE_URL (ej. "/transfers"). '
            "Las URL absolutas no se permiten para no salir del ambiente bajo prueba."
        )
    return base.rstrip("/") + "/" + ruta.lstrip("/")


# ================================================================
# OBJETIVO DETERMINÍSTICO (selector o id)
# ================================================================
#
# Formas aceptadas, cortas y largas:
#
#   el selector "#continueButton"
#   el elemento con selector "[data-testid='sign-in']"
#   el elemento con id "username"          (también acepta "#username")
#
# Dentro del selector usa comillas simples: [data-testid='x']
#
_DET = (
    r'(?:el selector|el elemento con selector) "(?P<selector>[^"]+)"'
    r'|el elemento con id "(?P<id>[^"]+)"'
)

# Misma idea con "del" para extracciones: "guardo el texto del selector ..."
_DET_DEL = (
    r'(?:del selector|del elemento con selector) "(?P<selector>[^"]+)"'
    r'|del elemento con id "(?P<id>[^"]+)"'
)


# ================================================================
# FILL
# ================================================================

# Determinístico:
#
# ingreso la variable "username" en el selector "#username"
# ingreso la variable "username" en el elemento con id "username"
#
RE_FILL_VARIABLE_DET = re.compile(
    rf'ingreso la variable "(?P<variable>[^"]+)" en (?:{_DET})',
    re.I,
)

# Determinístico, valor literal:
#
# ingreso el valor "25000" en el selector "#monto"
#
RE_FILL_LITERAL_DET = re.compile(
    rf'ingreso el valor "(?P<valor>[^"]*)" en (?:{_DET})',
    re.I,
)

# Semántico:
#
# ingreso la variable "username" en "campo Username"
#
RE_FILL_VARIABLE = re.compile(
    r'ingreso la variable "(?P<variable>[^"]+)" '
    r'en "(?P<objetivo>[^"]+)"',
    re.I,
)

# Semántico, valor literal:
#
# ingreso el valor "hola" en "campo Buscar"
#
RE_FILL_LITERAL = re.compile(
    r'ingreso el valor "(?P<valor>[^"]*)" '
    r'en "(?P<objetivo>[^"]+)"',
    re.I,
)


# ================================================================
# CLICK
# ================================================================

# Determinístico:
#
# hago click en el selector "#continueButton"
# hago click en el elemento con id "continueButton"
#
RE_CLICK_DET = re.compile(
    rf"hago\s+(?:click|clic)\s+en\s+(?:{_DET})",
    re.I,
)

# Semántico:
#
# hago click en "botón Continue"
#
RE_CLICK_SEMANTICO = re.compile(
    r'hago\s+(?:click|clic)\s+en\s+'
    r'"(?P<objetivo>[^"]+)"',
    re.I,
)


# ================================================================
# INTERACCIONES (determinísticas)
# ================================================================

# selecciono la opción "Cuenta 000002" en el selector "#cuenta-origen"
#
RE_SELECCIONAR_DET = re.compile(
    rf'selecciono la opci[oó]n "(?P<opcion>[^"]+)" en (?:{_DET})',
    re.I,
)

# selecciono la opción de la variable "source_account" en el selector "#cuenta-origen"
#
RE_SELECCIONAR_VAR_DET = re.compile(
    rf'selecciono la opci[oó]n de la variable "(?P<variable>[^"]+)" en (?:{_DET})',
    re.I,
)

# marco el selector "#acepto"  /  desmarco el selector "#acepto"
#
RE_MARCAR_DET = re.compile(
    rf"(?P<accion>marco|desmarco) (?:{_DET})",
    re.I,
)

# presiono la tecla "Enter" en el selector "#buscar"
#
RE_TECLA_DET = re.compile(
    rf'presiono la tecla "(?P<tecla>[^"]+)" en (?:{_DET})',
    re.I,
)

# presiono la tecla "Enter"      (sobre el elemento que tenga el foco)
#
RE_TECLA = re.compile(
    r'presiono la tecla "(?P<tecla>[^"]+)"',
    re.I,
)

# limpio el selector "#monto"
#
RE_LIMPIAR_DET = re.compile(
    rf"limpio (?:{_DET})",
    re.I,
)

# paso el mouse sobre el selector "#menu-productos"
#
RE_HOVER_DET = re.compile(
    rf"paso el mouse sobre (?:{_DET})",
    re.I,
)

# adjunto el archivo "data/archivos/comprobante.pdf" en el selector "#archivo"
#
RE_ADJUNTAR_DET = re.compile(
    rf'adjunto el archivo "(?P<archivo>[^"]+)" en (?:{_DET})',
    re.I,
)

# hago scroll hasta el selector "#footer"
#
RE_SCROLL_DET = re.compile(
    rf"hago scroll hasta (?:{_DET})",
    re.I,
)


# ================================================================
# EXTRACTION
# ================================================================

# Determinístico (texto visible del elemento, sin LLM):
#
# guardo el texto del selector "#saldo-000002" como "saldo_origen_inicial"
#
RE_GUARDAR_TEXTO_DET = re.compile(
    rf'guardo el texto (?:{_DET_DEL}) como "(?P<variable>[^"]+)"',
    re.I,
)

# Semántico (LLM):
#
# guardo el valor de "saldo de la cuenta terminada en 000002" como "saldo_origen_inicial"
#
RE_GUARDAR_VALOR = re.compile(
    r'guardo el valor de "(?P<objetivo>[^"]+)" '
    r'como "(?P<variable>[^"]+)"',
    re.I,
)


# ================================================================
# VALIDATIONS
# ================================================================

# Determinísticas por elemento (esperan hasta SELECTOR_TIMEOUT_MS):
#
# el selector "#posicion" está visible
# el selector "#error" no está visible
# el selector "#titulo" contiene el texto "Product Summary"
#
RE_VISIBLE_DET = re.compile(
    rf"(?:{_DET}) est[aá] visible",
    re.I,
)

RE_NO_VISIBLE_DET = re.compile(
    rf"(?:{_DET}) no est[aá] visible",
    re.I,
)

RE_CONTIENE_TEXTO_DET = re.compile(
    rf'(?:{_DET}) contiene el texto "(?P<texto>[^"]*)"',
    re.I,
)

# el selector "#titulo" tiene el texto "Product Summary"     (exacto)
#
RE_TEXTO_EXACTO_DET = re.compile(
    rf'(?:{_DET}) tiene el texto "(?P<texto>[^"]*)"',
    re.I,
)

# el selector "#monto" tiene el valor "25000"     (campos de formulario)
#
RE_VALOR_DET = re.compile(
    rf'(?:{_DET}) tiene el valor "(?P<valor>[^"]*)"',
    re.I,
)

# el selector ".card-cuenta" tiene 2 elementos
#
RE_CANTIDAD_DET = re.compile(
    rf"(?:{_DET}) tiene (?P<cantidad>\d+) elementos?",
    re.I,
)

# la URL contiene "/dashboard"
#
RE_URL_CONTIENE = re.compile(
    r'la url contiene "(?P<texto>[^"]+)"',
    re.I,
)

# el selector "#btn" está habilitado  /  está deshabilitado
#
RE_HABILITADO_DET = re.compile(
    rf"(?:{_DET}) est[aá] (?P<estado>habilitado|deshabilitado)",
    re.I,
)

# el selector "#acepto" está marcado  /  no está marcado
#
RE_MARCADO_DET = re.compile(
    rf"(?:{_DET}) (?P<negacion>no )?est[aá] marcado",
    re.I,
)

# variable == variable
#
RE_IGUAL_VARIABLE = re.compile(
    r'^la variable "(?P<izquierda>[^"]+)" '
    r'debe ser igual a la variable '
    r'"(?P<derecha>[^"]+)"$',
    re.I,
)


# variable == literal
#
RE_IGUAL_LITERAL = re.compile(
    r'^la variable "(?P<variable>[^"]+)" '
    r'debe ser igual a "(?P<valor>[^"]+)"$',
    re.I,
)


# resultado = base - operando
#
RE_RESTA = re.compile(
    r'^la variable "(?P<resultado>[^"]+)" '
    r'debe ser igual a la variable '
    r'"(?P<base>[^"]+)" '
    r'menos la variable '
    r'"(?P<operando>[^"]+)"$',
    re.I,
)


# resultado = base + operando
#
RE_SUMA = re.compile(
    r'^la variable "(?P<resultado>[^"]+)" '
    r'debe ser igual a la variable '
    r'"(?P<base>[^"]+)" '
    r'mas la variable '
    r'"(?P<operando>[^"]+)"$',
    re.I,
)


# resultado > comparación
#
RE_MAYOR = re.compile(
    r'^la variable "(?P<izquierda>[^"]+)" '
    r'debe ser mayor que la variable '
    r'"(?P<derecha>[^"]+)"$',
    re.I,
)


# resultado < comparación
#
RE_MENOR = re.compile(
    r'^la variable "(?P<izquierda>[^"]+)" '
    r'debe ser menor que la variable '
    r'"(?P<derecha>[^"]+)"$',
    re.I,
)


class StepRouter:

    def __init__(
        self,
        sesion,
        datos: DatosPrueba,
        variables: VariablesEscenario,
    ) -> None:

        self.sesion = sesion
        self.datos = datos
        self.variables = variables

        self.extractor = ExtractorUI(
            sesion
        )

        # Cómo se resolvió el último step. Lo lee conftest para la evidencia.
        self.ultima_ruta: dict | None = None

    @property
    def page(self):
        return self.sesion.page

    @property
    def _pw(self):
        """Page de Playwright bajo SkyvernPage (go_back/reload no son primitivas de Skyvern)."""
        return getattr(self.page, "page", self.page)

    # ============================================================
    # OBJETIVO DETERMINÍSTICO
    # ============================================================

    @staticmethod
    def _selector(
        match: re.Match,
    ) -> tuple[str, str]:
        """
        Devuelve (selector CSS, tipo) desde un match de _DET/_DET_DEL.

        Por id se acepta con o sin "#": "username" y "#username" -> "#username".
        """

        if match["selector"]:
            return match["selector"], "selector"

        return "#" + match["id"].lstrip("#"), "id"

    def _localizar(
        self,
        selector: str,
    ):
        return self._pw.locator(selector).first

    async def _esperar_estado(
        self,
        selector: str,
        estado: str,
    ) -> None:
        """estado: "visible" | "hidden" (oculto o inexistente)."""

        try:
            await self._localizar(selector).wait_for(
                state=estado,
                timeout=_timeout_ms(),
            )
        except Exception as exc:
            descripcion = "visible" if estado == "visible" else "oculto o ausente"
            raise AssertionError(
                f'El elemento "{selector}" no quedó {descripcion} '
                f"en {_timeout_ms()} ms."
            ) from exc

    async def _texto_elemento(
        self,
        selector: str,
    ) -> str:

        await self._esperar_estado(selector, "visible")

        return _normalizar_texto(
            await self._localizar(selector).inner_text(
                timeout=_timeout_ms()
            )
        )

    async def _esperar_condicion(
        self,
        evaluar,
        mensaje_fallo: str,
        etiqueta_actual: str = "Valor actual",
    ) -> None:
        """
        Reintenta evaluar() cada 250 ms hasta SELECTOR_TIMEOUT_MS.

        evaluar: función async que devuelve (cumple: bool, valor_actual).
        """

        limite = time.monotonic() + _timeout_ms() / 1000
        actual = None

        while True:
            try:
                cumple, actual = await evaluar()
            except Exception as exc:
                cumple, actual = False, f"(error: {_primera_linea(exc)})"

            if cumple:
                return

            if time.monotonic() >= limite:
                if isinstance(actual, (list, tuple)):
                    mostrado = ", ".join(f'"{x}"' for x in actual) or "(ninguna)"
                else:
                    mostrado = f'"{str(actual)[:200]}"'
                raise AssertionError(
                    f"{mensaje_fallo} {etiqueta_actual}: {mostrado}."
                )

            await asyncio.sleep(0.25)

    async def _esperar_texto(
        self,
        selector: str,
        esperado: str,
        exacto: bool = False,
    ) -> None:
        """Reintenta hasta que el texto del elemento contenga (o sea igual a) el esperado."""

        esperado = _normalizar_texto(esperado)

        await self._esperar_estado(selector, "visible")

        async def evaluar():
            actual = _normalizar_texto(
                await self._localizar(selector).inner_text(timeout=_timeout_ms())
            )
            return (actual == esperado if exacto else esperado in actual), actual

        verbo = "no tiene exactamente el texto" if exacto else "no contiene el texto"
        await self._esperar_condicion(
            evaluar,
            f'El elemento "{selector}" {verbo} "{esperado}".',
        )

    async def _ejecutar(
        self,
        descripcion: str,
        selector: str | None,
        coro,
    ) -> None:
        """Ejecuta una acción de Playwright y traduce su error a un mensaje legible."""

        try:
            await coro
        except AssertionError:
            raise
        except Exception as exc:
            donde = f' (selector "{selector}")' if selector else ""
            raise AssertionError(
                f"No fue posible {descripcion}{donde}: {_primera_linea(exc)}"
            ) from exc

    async def _seleccionar_opcion(
        self,
        selector: str,
        deseada: str,
    ) -> None:
        """
        Selecciona en un <select> la opción cuyo texto visible (o value) coincide.

        Espera a que la opción exista: las listas suelen cargarse desde una API.
        """

        deseada_norm = _normalizar_texto(deseada)
        elegida: dict = {}

        await self._esperar_estado(selector, "visible")

        async def evaluar():
            opciones = await self._localizar(selector).evaluate(
                "el => Array.from(el.options || []).map(o => [o.label, o.value])"
            )
            for etiqueta, valor in opciones:
                if _normalizar_texto(etiqueta) == deseada_norm or valor == deseada:
                    elegida["value"] = valor
                    return True, None
            return False, [etiqueta for etiqueta, _ in opciones]

        await self._esperar_condicion(
            evaluar,
            f'El elemento "{selector}" no tiene la opción "{deseada}". '
            "Revisa que sea un <select> nativo; las listas hechas con div se "
            "manejan con dos clicks.",
            etiqueta_actual="Opciones disponibles",
        )

        await self._ejecutar(
            f'seleccionar la opción "{deseada}"',
            selector,
            self._localizar(selector).select_option(
                value=elegida["value"],
                timeout=_timeout_ms(),
            ),
        )

    # ============================================================
    # VARIABLE RESOLUTION
    # ============================================================

    def _valor(
        self,
        nombre: str,
    ):
        """
        Orden de resolución:

        1. Variables generadas durante el escenario
        2. Variables del profile
        """

        if self.variables.existe(nombre):
            return self.variables.obtener(nombre)

        return self.datos.valor(nombre)

    # ============================================================
    # TRAZABILIDAD
    # ============================================================

    def _ruta(
        self,
        tipo: str,
        regla: str,
    ) -> None:
        """
        Registra cómo se resolvió el step:

        deterministico | semantico | agentic | sin_regla
        """

        self.ultima_ruta = {
            "tipo": tipo,
            "regla": regla,
        }

    def _fallback_act(
        self,
        texto: str,
    ) -> None:

        if _modo_estricto():

            self._ruta("sin_regla", "bloqueado")

            raise StepNoReconocido(
                f'El step "{texto}" no coincide con ninguna regla del router '
                "(ROUTER_STRICT=true). Reescríbelo con el vocabulario soportado "
                "o desactiva el modo estricto para exploración."
            )

        self._ruta("agentic", "act")

        self.sesion.run(
            self.page.act(texto)
        )

    # ============================================================
    # GIVEN
    # ============================================================

    def given(
        self,
        texto: str,
    ) -> None:
        """Dado: contexto o precondición. Mismo vocabulario que Cuando."""

        self._accion(texto)

    # ============================================================
    # WHEN
    # ============================================================

    def when(
        self,
        texto: str,
    ) -> None:
        """Cuando: acción bajo prueba. Mismo vocabulario que Dado."""

        self._accion(texto)

    # ============================================================
    # ACCIONES (compartidas por Dado y Cuando)
    # ============================================================

    def _accion(
        self,
        texto: str,
    ) -> None:

        self.ultima_ruta = None

        accion = _sin_que(texto)

        # --------------------------------------------------------
        # PERFIL
        # --------------------------------------------------------

        if match := RE_PERFIL.fullmatch(accion):

            self._ruta("deterministico", "perfil")

            self.datos.usar(
                match["perfil"]
            )

            return

        # --------------------------------------------------------
        # ABRIR APLICACIÓN
        # --------------------------------------------------------

        if RE_ABRIR_APP.fullmatch(accion):

            self._ruta("deterministico", "goto")

            self.sesion.run(
                self.page.goto(
                    os.environ["BASE_URL"]
                )
            )

            return

        # --------------------------------------------------------
        # NAVEGAR A RUTA
        # --------------------------------------------------------

        if match := RE_NAVEGAR_RUTA.fullmatch(accion):

            self._ruta("deterministico", "goto_ruta")

            self.sesion.run(
                self.page.goto(
                    _url_ruta(
                        os.environ["BASE_URL"],
                        match["ruta"],
                    )
                )
            )

            return

        # --------------------------------------------------------
        # ATRÁS (navegador)
        # --------------------------------------------------------

        if RE_ATRAS.fullmatch(accion):

            self._ruta("deterministico", "go_back")

            url_antes = self._pw.url

            self.sesion.run(
                self._pw.go_back(
                    wait_until="load"
                )
            )

            if self._pw.url == url_antes:
                raise AssertionError(
                    "No hay una página anterior en el historial del navegador "
                    f"(la URL sigue siendo {url_antes})."
                )

            return

        # --------------------------------------------------------
        # RECARGAR
        # --------------------------------------------------------

        if RE_RECARGAR.fullmatch(accion):

            self._ruta("deterministico", "reload")

            self.sesion.run(
                self._pw.reload(
                    wait_until="load"
                )
            )

            return

        # --------------------------------------------------------
        # FILL DETERMINÍSTICO (variable)
        # --------------------------------------------------------

        if match := RE_FILL_VARIABLE_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"fill_{tipo}")

            valor = self._valor(
                match["variable"]
            )

            self.sesion.run(
                self.page.fill(
                    selector,
                    value=str(valor),
                )
            )

            return

        # --------------------------------------------------------
        # FILL DETERMINÍSTICO (literal)
        # --------------------------------------------------------

        if match := RE_FILL_LITERAL_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"fill_literal_{tipo}")

            self.sesion.run(
                self.page.fill(
                    selector,
                    value=match["valor"],
                )
            )

            return

        # --------------------------------------------------------
        # FILL SEMÁNTICO
        # --------------------------------------------------------

        if match := RE_FILL_VARIABLE.fullmatch(accion):

            self._ruta("semantico", "fill")

            valor = self._valor(
                match["variable"]
            )

            self.sesion.run(
                self.page.fill(
                    prompt=match["objetivo"],
                    value=str(valor),
                )
            )

            return

        # --------------------------------------------------------
        # FILL SEMÁNTICO (literal)
        # --------------------------------------------------------

        if match := RE_FILL_LITERAL.fullmatch(accion):

            self._ruta("semantico", "fill_literal")

            self.sesion.run(
                self.page.fill(
                    prompt=match["objetivo"],
                    value=match["valor"],
                )
            )

            return

        # --------------------------------------------------------
        # CLICK DETERMINÍSTICO
        # --------------------------------------------------------
        # Solo selector, sin prompt: Skyvern reintenta el selector y, si no
        # lo encuentra, lanza el error original sin recurrir al LLM.

        if match := RE_CLICK_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"click_{tipo}")

            self.sesion.run(
                self.page.click(
                    selector
                )
            )

            return

        # --------------------------------------------------------
        # CLICK SEMÁNTICO
        # --------------------------------------------------------

        if match := RE_CLICK_SEMANTICO.fullmatch(accion):

            self._ruta("semantico", "click")

            self.sesion.run(
                self.page.click(
                    prompt=match["objetivo"]
                )
            )

            return

        # --------------------------------------------------------
        # INTERACCIONES DETERMINÍSTICAS
        # --------------------------------------------------------

        if match := RE_SELECCIONAR_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"select_{tipo}")

            self.sesion.run(
                self._seleccionar_opcion(selector, match["opcion"])
            )

            return

        if match := RE_SELECCIONAR_VAR_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"select_variable_{tipo}")

            self.sesion.run(
                self._seleccionar_opcion(
                    selector,
                    str(self._valor(match["variable"])),
                )
            )

            return

        if match := RE_MARCAR_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            marcar = match["accion"].lower() == "marco"
            self._ruta("deterministico", f"{'check' if marcar else 'uncheck'}_{tipo}")

            elemento = self._localizar(selector)
            self.sesion.run(
                self._ejecutar(
                    "marcar" if marcar else "desmarcar",
                    selector,
                    (elemento.check if marcar else elemento.uncheck)(
                        timeout=_timeout_ms()
                    ),
                )
            )

            return

        if match := RE_TECLA_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"tecla_{tipo}")

            self.sesion.run(
                self._ejecutar(
                    f'presionar la tecla "{match["tecla"]}"',
                    selector,
                    self._localizar(selector).press(
                        _tecla(match["tecla"]),
                        timeout=_timeout_ms(),
                    ),
                )
            )

            return

        if match := RE_TECLA.fullmatch(accion):

            self._ruta("deterministico", "tecla")

            self.sesion.run(
                self._ejecutar(
                    f'presionar la tecla "{match["tecla"]}"',
                    None,
                    self._pw.keyboard.press(_tecla(match["tecla"])),
                )
            )

            return

        if match := RE_LIMPIAR_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"limpiar_{tipo}")

            self.sesion.run(
                self._ejecutar(
                    "limpiar el campo",
                    selector,
                    self._localizar(selector).fill("", timeout=_timeout_ms()),
                )
            )

            return

        if match := RE_HOVER_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"hover_{tipo}")

            self.sesion.run(
                self._ejecutar(
                    "pasar el mouse",
                    selector,
                    self._localizar(selector).hover(timeout=_timeout_ms()),
                )
            )

            return

        if match := RE_ADJUNTAR_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"adjuntar_{tipo}")

            archivo = _archivo_adjunto(match["archivo"])

            self.sesion.run(
                self._ejecutar(
                    f'adjuntar "{match["archivo"]}"',
                    selector,
                    self._localizar(selector).set_input_files(
                        archivo,
                        timeout=_timeout_ms(),
                    ),
                )
            )

            return

        if match := RE_SCROLL_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"scroll_{tipo}")

            self.sesion.run(
                self._ejecutar(
                    "hacer scroll",
                    selector,
                    self._localizar(selector).scroll_into_view_if_needed(
                        timeout=_timeout_ms()
                    ),
                )
            )

            return

        # --------------------------------------------------------
        # EXTRAER TEXTO DETERMINÍSTICO + GUARDAR
        # --------------------------------------------------------

        if match := RE_GUARDAR_TEXTO_DET.fullmatch(accion):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"texto_{tipo}")

            valor = self.sesion.run(
                self._texto_elemento(selector)
            )

            self.variables.guardar(
                match["variable"],
                valor,
            )

            print(
                f'      variable runtime "{match["variable"]}" = {valor}'
            )

            return

        # --------------------------------------------------------
        # EXTRAER SEMÁNTICO + GUARDAR
        # --------------------------------------------------------

        if match := RE_GUARDAR_VALOR.fullmatch(accion):

            self._ruta("semantico", "extract")

            objetivo = match["objetivo"]
            variable = match["variable"]

            valor = self.extractor.extraer(
                objetivo
            )

            self.variables.guardar(
                variable,
                valor,
            )

            print(
                f'      variable runtime "{variable}" = {valor}'
            )

            return

        # --------------------------------------------------------
        # FALLBACK AGENTIC (bloqueado si ROUTER_STRICT=true)
        # --------------------------------------------------------

        self._fallback_act(texto)

    # ============================================================
    # THEN
    # ============================================================

    def then(
        self,
        texto: str,
    ) -> None:

        self.ultima_ruta = None

        # --------------------------------------------------------
        # A == B
        # --------------------------------------------------------

        if match := RE_IGUAL_VARIABLE.fullmatch(texto):

            self._ruta("deterministico", "assert_igual_variable")

            izquierda = self._valor(
                match["izquierda"]
            )

            derecha = self._valor(
                match["derecha"]
            )

            assert iguales(
                izquierda,
                derecha,
            ), (
                f'La variable "{match["izquierda"]}" '
                f"tiene valor {izquierda}, "
                f'pero "{match["derecha"]}" '
                f"tiene valor {derecha}."
            )

            return

        # --------------------------------------------------------
        # VARIABLE == LITERAL
        # --------------------------------------------------------

        if match := RE_IGUAL_LITERAL.fullmatch(texto):

            self._ruta("deterministico", "assert_igual_literal")

            actual = self._valor(
                match["variable"]
            )

            esperado = match["valor"]

            assert iguales(
                actual,
                esperado,
            ), (
                f'La variable "{match["variable"]}" '
                f"tiene valor {actual}, "
                f"pero se esperaba {esperado}."
            )

            return

        # --------------------------------------------------------
        # RESULTADO = BASE - OPERANDO
        # --------------------------------------------------------

        if match := RE_RESTA.fullmatch(texto):

            self._ruta("deterministico", "assert_resta")

            actual = numero(
                self._valor(
                    match["resultado"]
                )
            )

            base = numero(
                self._valor(
                    match["base"]
                )
            )

            operando = numero(
                self._valor(
                    match["operando"]
                )
            )

            esperado = base - operando

            assert actual == esperado, (
                f'La variable "{match["resultado"]}" '
                f"tiene valor {actual}, "
                f"pero se esperaba {esperado}. "
                f"Cálculo: {base} - {operando}."
            )

            return

        # --------------------------------------------------------
        # RESULTADO = BASE + OPERANDO
        # --------------------------------------------------------

        if match := RE_SUMA.fullmatch(texto):

            self._ruta("deterministico", "assert_suma")

            actual = numero(
                self._valor(
                    match["resultado"]
                )
            )

            base = numero(
                self._valor(
                    match["base"]
                )
            )

            operando = numero(
                self._valor(
                    match["operando"]
                )
            )

            esperado = base + operando

            assert actual == esperado, (
                f'La variable "{match["resultado"]}" '
                f"tiene valor {actual}, "
                f"pero se esperaba {esperado}. "
                f"Cálculo: {base} + {operando}."
            )

            return

        # --------------------------------------------------------
        # MAYOR QUE
        # --------------------------------------------------------

        if match := RE_MAYOR.fullmatch(texto):

            self._ruta("deterministico", "assert_mayor")

            izquierda = numero(
                self._valor(
                    match["izquierda"]
                )
            )

            derecha = numero(
                self._valor(
                    match["derecha"]
                )
            )

            assert izquierda > derecha, (
                f'Se esperaba que "{match["izquierda"]}" '
                f"({izquierda}) fuera mayor que "
                f'"{match["derecha"]}" ({derecha}).'
            )

            return

        # --------------------------------------------------------
        # MENOR QUE
        # --------------------------------------------------------

        if match := RE_MENOR.fullmatch(texto):

            self._ruta("deterministico", "assert_menor")

            izquierda = numero(
                self._valor(
                    match["izquierda"]
                )
            )

            derecha = numero(
                self._valor(
                    match["derecha"]
                )
            )

            assert izquierda < derecha, (
                f'Se esperaba que "{match["izquierda"]}" '
                f"({izquierda}) fuera menor que "
                f'"{match["derecha"]}" ({derecha}).'
            )

            return

        # --------------------------------------------------------
        # ELEMENTO: NO VISIBLE
        # --------------------------------------------------------

        if match := RE_NO_VISIBLE_DET.fullmatch(texto):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"no_visible_{tipo}")

            self.sesion.run(
                self._esperar_estado(selector, "hidden")
            )

            return

        # --------------------------------------------------------
        # ELEMENTO: VISIBLE
        # --------------------------------------------------------

        if match := RE_VISIBLE_DET.fullmatch(texto):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"visible_{tipo}")

            self.sesion.run(
                self._esperar_estado(selector, "visible")
            )

            return

        # --------------------------------------------------------
        # ELEMENTO: CONTIENE TEXTO
        # --------------------------------------------------------

        if match := RE_CONTIENE_TEXTO_DET.fullmatch(texto):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"contiene_texto_{tipo}")

            self.sesion.run(
                self._esperar_texto(selector, match["texto"])
            )

            return

        # --------------------------------------------------------
        # ELEMENTO: TEXTO EXACTO
        # --------------------------------------------------------

        if match := RE_TEXTO_EXACTO_DET.fullmatch(texto):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"texto_exacto_{tipo}")

            self.sesion.run(
                self._esperar_texto(selector, match["texto"], exacto=True)
            )

            return

        # --------------------------------------------------------
        # ELEMENTO: VALOR DE CAMPO
        # --------------------------------------------------------

        if match := RE_VALOR_DET.fullmatch(texto):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"valor_{tipo}")
            esperado = match["valor"].strip()

            async def evaluar_valor():
                actual = (
                    await self._localizar(selector).input_value(timeout=_timeout_ms())
                ).strip()
                return actual == esperado, actual

            self.sesion.run(
                self._esperar_condicion(
                    evaluar_valor,
                    f'El campo "{selector}" no tiene el valor "{esperado}".',
                )
            )

            return

        # --------------------------------------------------------
        # ELEMENTO: CANTIDAD
        # --------------------------------------------------------

        if match := RE_CANTIDAD_DET.fullmatch(texto):

            selector, tipo = self._selector(match)
            self._ruta("deterministico", f"cantidad_{tipo}")
            esperada = int(match["cantidad"])

            async def evaluar_cantidad():
                actual = await self._pw.locator(selector).count()
                return actual == esperada, actual

            self.sesion.run(
                self._esperar_condicion(
                    evaluar_cantidad,
                    f'El selector "{selector}" no tiene {esperada} elemento(s).',
                )
            )

            return

        # --------------------------------------------------------
        # URL
        # --------------------------------------------------------

        if match := RE_URL_CONTIENE.fullmatch(texto):

            self._ruta("deterministico", "url")
            esperado = match["texto"]

            async def evaluar_url():
                return esperado in self._pw.url, self._pw.url

            self.sesion.run(
                self._esperar_condicion(
                    evaluar_url,
                    f'La URL no contiene "{esperado}".',
                )
            )

            return

        # --------------------------------------------------------
        # ELEMENTO: HABILITADO / DESHABILITADO
        # --------------------------------------------------------

        if match := RE_HABILITADO_DET.fullmatch(texto):

            selector, tipo = self._selector(match)
            habilitado = match["estado"].lower() == "habilitado"
            self._ruta("deterministico", f"{match['estado'].lower()}_{tipo}")

            async def evaluar_habilitado():
                actual = await self._localizar(selector).is_enabled(timeout=_timeout_ms())
                return actual == habilitado, "habilitado" if actual else "deshabilitado"

            self.sesion.run(
                self._esperar_condicion(
                    evaluar_habilitado,
                    f'El elemento "{selector}" no está {match["estado"].lower()}.',
                )
            )

            return

        # --------------------------------------------------------
        # ELEMENTO: MARCADO / NO MARCADO
        # --------------------------------------------------------

        if match := RE_MARCADO_DET.fullmatch(texto):

            selector, tipo = self._selector(match)
            marcado = not match["negacion"]
            self._ruta("deterministico", f"{'marcado' if marcado else 'no_marcado'}_{tipo}")

            async def evaluar_marcado():
                actual = await self._localizar(selector).is_checked(timeout=_timeout_ms())
                return actual == marcado, "marcado" if actual else "no marcado"

            self.sesion.run(
                self._esperar_condicion(
                    evaluar_marcado,
                    f'El elemento "{selector}" '
                    f'{"no está marcado" if marcado else "está marcado"}.',
                )
            )

            return

        # --------------------------------------------------------
        # VALIDACIÓN SEMÁNTICA / VISUAL
        # --------------------------------------------------------

        self._ruta("semantico", "validate")

        ok = self.sesion.run(
            self.page.validate(
                f"Verifica que: {texto}"
            )
        )

        assert ok is True, (
            f'No se cumplió la condición esperada: "{texto}"'
        )