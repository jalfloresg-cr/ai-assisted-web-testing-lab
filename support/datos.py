"""Datos de prueba por perfil.

Los escenarios seleccionan un perfil lógico (por ejemplo ``smoke_login_personal``)
y el perfil resuelve sus valores desde ``data/profiles.yaml``.

Los secretos no viven en YAML: se referencian como ``env://VARIABLE`` y se leen
desde ``.env.<ambiente>`` o desde el secret store del CI.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class DatosPrueba:
    def __init__(self, ruta: str | None = None) -> None:
        self.ruta = Path(ruta or os.getenv("TEST_DATA_FILE", "data/profiles.yaml"))
        if not self.ruta.exists():
            raise RuntimeError(f"No existe el archivo de datos de prueba: {self.ruta}")

        contenido = yaml.safe_load(self.ruta.read_text(encoding="utf-8")) or {}
        self._profiles = contenido.get("profiles", {})
        if not isinstance(self._profiles, dict):
            raise RuntimeError(f"Formato inválido en {self.ruta}: 'profiles' debe ser un mapa")

        self.perfil_activo: str | None = None

    def usar(self, perfil: str) -> None:
        nombre = perfil.strip()
        if nombre not in self._profiles:
            disponibles = ", ".join(sorted(self._profiles)) or "(ninguno)"
            raise RuntimeError(
                f'No existe el perfil de prueba "{nombre}" en {self.ruta}. '
                f"Disponibles: {disponibles}"
            )
        self.perfil_activo = nombre

    def valor(self, nombre: str) -> Any:
        if not self.perfil_activo:
            raise RuntimeError(
                'No hay un perfil de prueba activo. Agrega un paso como: '
                'Dado que uso el perfil de prueba "smoke_login_personal"'
            )

        perfil = self._profiles[self.perfil_activo]
        if nombre not in perfil:
            raise RuntimeError(
                f'El perfil "{self.perfil_activo}" no define "{nombre}" en {self.ruta}'
            )

        return self._resolver(perfil[nombre], nombre)

    def _resolver(self, valor: Any, nombre: str) -> Any:
        if isinstance(valor, str) and valor.startswith("env://"):
            variable = valor.removeprefix("env://").strip()
            if not variable:
                raise RuntimeError(
                    f'Referencia env:// inválida para "{nombre}" en el perfil '
                    f'"{self.perfil_activo}"'
                )
            resuelto = os.getenv(variable)
            if resuelto is None or resuelto == "":
                ambiente = os.getenv("TEST_ENV", "qa")
                raise RuntimeError(
                    f'Falta la variable {variable} requerida por el perfil '
                    f'"{self.perfil_activo}" en el ambiente "{ambiente}". '
                    f'Defínela en .env.{ambiente} o como secret/variable del CI.'
                )
            return resuelto

        return valor
