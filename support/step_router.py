"""Router genérico entre Gherkin y Skyvern.

El router conoce operaciones:

- seleccionar profile
- navegar
- fill
- click
- extract
- validate
- operaciones con variables
- act como fallback

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

import os
import re

from .datos import DatosPrueba
from .variables import (
    ExtractorUI,
    VariablesEscenario,
    iguales,
    numero,
)


# ================================================================
# PROFILE / NAVIGATION
# ================================================================

RE_PERFIL = re.compile(
    r'(?:que\s+)?uso el perfil de prueba '
    r'"(?P<perfil>[^"]+)"',
    re.I,
)

RE_NAVEGAR = re.compile(
    r"\b(abro|abrir|entro|navego)\b",
    re.I,
)


# ================================================================
# FILL
# ================================================================

# Semántico:
#
# ingreso la variable "username" en "Username"
#
RE_FILL_VARIABLE = re.compile(
    r'^ingreso la variable "(?P<variable>[^"]+)" '
    r'en "(?P<objetivo>[^"]+)"$',
    re.I,
)


# Determinístico por ID:
#
# ingreso la variable "username"
# en el elemento con id "username"
#
RE_FILL_VARIABLE_ID = re.compile(
    r'^ingreso la variable "(?P<variable>[^"]+)" '
    r'en el elemento con id "(?P<id>[^"]+)"$',
    re.I,
)


# Determinístico por selector:
#
# ingreso la variable "username"
# en el elemento con selector "[data-testid='username']"
#
RE_FILL_VARIABLE_SELECTOR = re.compile(
    r'^ingreso la variable "(?P<variable>[^"]+)" '
    r'en el elemento con selector "(?P<selector>[^"]+)"$',
    re.I,
)


# Valor literal:
#
# ingreso el valor "hola" en "Search"
#
RE_FILL_LITERAL = re.compile(
    r'^ingreso el valor "(?P<valor>[^"]*)" '
    r'en "(?P<objetivo>[^"]+)"$',
    re.I,
)


# ================================================================
# CLICK
# ================================================================

# Determinístico:
#
# hago click en el elemento con id "submit"
#
RE_CLICK_ID = re.compile(
    r'^hago\s+(?:click|clic)\s+en\s+el elemento '
    r'con id "(?P<id>[^"]+)"$',
    re.I,
)


# Determinístico:
#
# hago click en el elemento con selector "..."
#
RE_CLICK_SELECTOR = re.compile(
    r'^hago\s+(?:click|clic)\s+en\s+el elemento '
    r'con selector "(?P<selector>[^"]+)"$',
    re.I,
)


# Semántico:
#
# hago click en "Transferencias"
#
RE_CLICK_SEMANTICO = re.compile(
    r'^hago\s+(?:click|clic)\s+en\s+'
    r'"(?P<objetivo>[^"]+)"$',
    re.I,
)


# ================================================================
# EXTRACTION
# ================================================================

# Ejemplo:
#
# guardo el valor de
# "saldo de la cuenta terminada en 000002"
# como "saldo_origen_inicial"
#
RE_GUARDAR_VALOR = re.compile(
    r'^guardo el valor de "(?P<objetivo>[^"]+)" '
    r'como "(?P<variable>[^"]+)"$',
    re.I,
)


# ================================================================
# VALIDATIONS
# ================================================================

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

    @property
    def page(self):
        return self.sesion.page

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
    # GIVEN
    # ============================================================

    def given(
        self,
        texto: str,
    ) -> None:

        if match := RE_PERFIL.fullmatch(texto):

            self.datos.usar(
                match["perfil"]
            )

            return

        if RE_NAVEGAR.search(texto):

            self.sesion.run(
                self.page.goto(
                    os.environ["BASE_URL"]
                )
            )

            return

        # Fallback agentic
        self.sesion.run(
            self.page.act(texto)
        )

    # ============================================================
    # WHEN
    # ============================================================

    def when(
        self,
        texto: str,
    ) -> None:

        # --------------------------------------------------------
        # FILL POR ID
        # --------------------------------------------------------

        if match := RE_FILL_VARIABLE_ID.fullmatch(texto):

            variable = match["variable"]
            element_id = match["id"]

            valor = self._valor(
                variable
            )

            self.sesion.run(
                self.page.fill(
                    f"#{element_id}",
                    value=str(valor),
                )
            )

            return

        # --------------------------------------------------------
        # FILL POR SELECTOR
        # --------------------------------------------------------

        if match := RE_FILL_VARIABLE_SELECTOR.fullmatch(texto):

            variable = match["variable"]
            selector = match["selector"]

            valor = self._valor(
                variable
            )

            self.sesion.run(
                self.page.fill(
                    selector,
                    value=str(valor),
                )
            )

            return

        # --------------------------------------------------------
        # FILL SEMÁNTICO
        # --------------------------------------------------------

        if match := RE_FILL_VARIABLE.fullmatch(texto):

            variable = match["variable"]
            objetivo = match["objetivo"]

            valor = self._valor(
                variable
            )

            self.sesion.run(
                self.page.fill(
                    prompt=objetivo,
                    value=str(valor),
                )
            )

            return

        # --------------------------------------------------------
        # FILL LITERAL
        # --------------------------------------------------------

        if match := RE_FILL_LITERAL.fullmatch(texto):

            valor = match["valor"]
            objetivo = match["objetivo"]

            self.sesion.run(
                self.page.fill(
                    prompt=objetivo,
                    value=valor,
                )
            )

            return

        # --------------------------------------------------------
        # CLICK POR ID
        # --------------------------------------------------------

        if match := RE_CLICK_ID.fullmatch(texto):

            self.sesion.run(
                self.page.click(
                    f'#{match["id"]}'
                )
            )

            return

        # --------------------------------------------------------
        # CLICK POR SELECTOR
        # --------------------------------------------------------

        if match := RE_CLICK_SELECTOR.fullmatch(texto):

            self.sesion.run(
                self.page.click(
                    match["selector"]
                )
            )

            return

        # --------------------------------------------------------
        # CLICK SEMÁNTICO
        # --------------------------------------------------------

        if match := RE_CLICK_SEMANTICO.fullmatch(texto):

            objetivo = match["objetivo"]

            self.sesion.run(
                self.page.click(
                    prompt=objetivo
                )
            )

            return

        # --------------------------------------------------------
        # EXTRAER + GUARDAR
        # --------------------------------------------------------

        if match := RE_GUARDAR_VALOR.fullmatch(texto):

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
        # FALLBACK AGENTIC
        # --------------------------------------------------------

        self.sesion.run(
            self.page.act(texto)
        )

    # ============================================================
    # THEN
    # ============================================================

    def then(
        self,
        texto: str,
    ) -> None:

        # --------------------------------------------------------
        # A == B
        # --------------------------------------------------------

        if match := RE_IGUAL_VARIABLE.fullmatch(texto):

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
        # VALIDACIÓN SEMÁNTICA / VISUAL
        # --------------------------------------------------------

        ok = self.sesion.run(
            self.page.validate(
                f"Verifica que: {texto}"
            )
        )

        assert ok is True, (
            f'No se cumplió la condición esperada: "{texto}"'
        )