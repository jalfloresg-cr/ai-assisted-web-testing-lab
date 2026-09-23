from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {
            "type": "string",
        }
    },
    "required": ["value"],
}


class VariablesEscenario:
    """
    Variables generadas durante la ejecución de un escenario.

    Ejemplos:
        saldo_inicial
        saldo_final
        numero_transaccion

    El estado vive únicamente durante el escenario actual.
    """

    def __init__(self) -> None:
        self._valores: dict[str, Any] = {}

    def guardar(
        self,
        nombre: str,
        valor: Any,
    ) -> None:
        self._valores[nombre] = valor

    def obtener(
        self,
        nombre: str,
    ) -> Any:
        if nombre not in self._valores:
            raise AssertionError(
                f'La variable de escenario "{nombre}" '
                "no ha sido definida."
            )

        return self._valores[nombre]

    def existe(
        self,
        nombre: str,
    ) -> bool:
        return nombre in self._valores

    def todos(self) -> dict[str, Any]:
        return dict(self._valores)


class ExtractorUI:
    """
    Extracción genérica de valores desde la UI mediante Skyvern.

    No conoce conceptos de negocio.
    """

    def __init__(self, sesion) -> None:
        self.sesion = sesion

    @property
    def page(self):
        return self.sesion.page

    def extraer(
        self,
        objetivo: str,
    ) -> Any:

        resultado = self.sesion.run(
            self.page.extract(
                prompt=(
                    f'Extrae únicamente el valor correspondiente a '
                    f'"{objetivo}". '
                    'Devuelve el resultado en la propiedad "value". '
                    "No agregues explicaciones."
                ),
                schema=EXTRACTION_SCHEMA,
            )
        )

        return _extraer_value(resultado)


def _extraer_value(
    resultado: Any,
) -> Any:
    """
    Tolera distintos formatos retornados por el SDK.
    """

    if resultado is None:
        raise AssertionError(
            "Skyvern no devolvió ningún valor durante la extracción."
        )

    if isinstance(resultado, dict):
        if "value" in resultado:
            return resultado["value"]

        if "data" in resultado:
            return _extraer_value(
                resultado["data"]
            )

    if hasattr(resultado, "model_dump"):
        data = resultado.model_dump()

        return _extraer_value(data)

    if hasattr(resultado, "data"):
        return _extraer_value(
            resultado.data
        )

    if hasattr(resultado, "value"):
        return resultado.value

    raise AssertionError(
        "No fue posible interpretar el valor extraído por Skyvern. "
        f"Tipo recibido: {type(resultado).__name__}"
    )


def numero(
    valor: Any,
) -> Decimal:
    """
    Convierte representaciones comunes de importes a Decimal.

    Ejemplos soportados:

        25000
        25,000
        25,000.00
        25.000,00
        CRC 25,000.00
        ₡25.000,00
    """

    if isinstance(valor, Decimal):
        return valor

    if isinstance(valor, int):
        return Decimal(valor)

    if isinstance(valor, float):
        return Decimal(str(valor))

    texto = str(valor).strip()

    texto = (
        texto
        .replace("\u00a0", "")
        .replace(" ", "")
    )

    texto = re.sub(
        r"[^\d,.\-]",
        "",
        texto,
    )

    if not texto:
        raise AssertionError(
            f'El valor "{valor}" no puede convertirse a número.'
        )

    # Caso:
    # 25,000.50
    # 25.000,50
    if "," in texto and "." in texto:

        ultima_coma = texto.rfind(",")
        ultimo_punto = texto.rfind(".")

        if ultima_coma > ultimo_punto:
            # Formato europeo / latino:
            # 25.000,50
            texto = texto.replace(".", "")
            texto = texto.replace(",", ".")

        else:
            # Formato:
            # 25,000.50
            texto = texto.replace(",", "")

    elif "," in texto:

        partes = texto.split(",")

        # 25,000
        if (
            len(partes) > 1
            and all(
                len(parte) == 3
                for parte in partes[1:]
            )
        ):
            texto = "".join(partes)

        # 25,50
        else:
            texto = texto.replace(",", ".")

    elif "." in texto:

        partes = texto.split(".")

        # 25.000
        if (
            len(partes) > 1
            and all(
                len(parte) == 3
                for parte in partes[1:]
            )
        ):
            texto = "".join(partes)

    try:
        return Decimal(texto)

    except InvalidOperation as exc:
        raise AssertionError(
            f'El valor "{valor}" no puede convertirse a número.'
        ) from exc


def iguales(
    izquierda: Any,
    derecha: Any,
) -> bool:
    """
    Intenta comparación numérica primero.
    Si los valores no son números, compara texto.
    """

    try:
        return numero(izquierda) == numero(derecha)

    except AssertionError:
        return (
            str(izquierda).strip()
            == str(derecha).strip()
        )