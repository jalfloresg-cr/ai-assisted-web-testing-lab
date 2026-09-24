"""Router genérico entre Gherkin y Skyvern.

El router conoce operaciones:

- seleccionar profile
- navegar (abrir la aplicación, ir a una ruta, atrás, recargar)
- fill      (determinístico por selector/id, o semántico)
- click     (determinístico por selector/id, o semántico)
- extract   (texto por selector/id sin LLM, o semántico)
- validate  (visible / no visible / contiene texto por selector, o semántico)
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

    async def _esperar_texto(
        self,
        selector: str,
        esperado: str,
    ) -> None:
        """Reintenta hasta que el texto del elemento contenga el esperado."""

        esperado = _normalizar_texto(esperado)
        limite = time.monotonic() + _timeout_ms() / 1000
        actual = ""

        await self._esperar_estado(selector, "visible")

        while True:
            actual = _normalizar_texto(
                await self._localizar(selector).inner_text(
                    timeout=_timeout_ms()
                )
            )

            if esperado in actual:
                return

            if time.monotonic() >= limite:
                raise AssertionError(
                    f'El elemento "{selector}" no contiene el texto "{esperado}". '
                    f'Texto actual: "{actual[:200]}".'
                )

            await asyncio.sleep(0.25)

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