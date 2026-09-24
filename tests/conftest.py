"""Cableado pytest-bdd -> router -> Skyvern.

El .feature contiene la intención de negocio. Este archivo no conoce selectores ni
páginas concretas: delega la traducción de cada step a ``StepRouter``.
"""
import json
import os
import re
import time
from urllib.parse import urlparse

import pytest
from dotenv import load_dotenv
from pytest_bdd import given, parsers, then, when

from support import evidencia
from support.browser import Sesion
from support.datos import DatosPrueba
from support.step_router import StepNoReconocido, StepRouter
from support.variables import VariablesEscenario

# El smoke principal apunta al ambiente QA/Minikube. Puede cambiarse con TEST_ENV.
os.environ.setdefault("TEST_ENV", "qa")
load_dotenv(f".env.{os.environ['TEST_ENV']}")  # el shell/CI tiene prioridad

# Skyvern bloquea localhost/IPs privadas por anti-SSRF. Permitimos únicamente el
# host configurado como BASE_URL, salvo que ALLOWED_HOSTS venga definido a mano.
_host = urlparse(os.environ.get("BASE_URL", "")).hostname
if _host and "ALLOWED_HOSTS" not in os.environ:
    os.environ["ALLOWED_HOSTS"] = json.dumps([_host])

@pytest.fixture
def variables():
    return VariablesEscenario()

@pytest.fixture
def sesion():
    s = Sesion()
    s.abrir()
    yield s
    s.cerrar()


@pytest.fixture
def datos_prueba():
    return DatosPrueba()


@pytest.fixture
def router(sesion, datos_prueba, variables):
    return StepRouter(sesion, datos_prueba, variables)


@given(parsers.re(r"(?P<texto>.+)"))
def _dado(router, texto):
    router.given(texto)


@when(parsers.re(r"(?P<texto>.+)"))
def _cuando(router, texto):
    router.when(texto)


@then(parsers.re(r"(?P<texto>.+)"))
def _entonces(router, texto):
    router.then(texto)




def _motivo_fallo(step) -> str:
    """Convierte un fallo técnico de un step en una explicación útil para QA.

    No cambia el resultado de pytest ni oculta la excepción original. Solo
    agrega una causa legible al reporte de evidencia.
    """
    texto = step.name.strip()
    tipo = str(getattr(step, "type", "") or "").lower()
    keyword = str(getattr(step, "keyword", "") or "").strip().lower()

    if tipo == "then" or keyword in {"entonces", "then"}:
        return f'No se cumplió la condición esperada: "{texto}".'

    if re.search(r"\b(click|clic|presiono|pulso)\b", texto, re.I):
        return (
            f'No fue posible completar la acción: "{texto}". '
            "El elemento requerido no estaba disponible o no pudo ser "
            "localizado en el estado actual de la aplicación."
        )

    if re.search(r"\b(ingreso|escribo|completo|lleno)\b", texto, re.I):
        return (
            f'No fue posible ingresar el dato requerido en: "{texto}". '
            "El campo esperado no estaba disponible o no pudo ser localizado."
        )

    if tipo == "given" or keyword in {"dado", "given"}:
        return f'No se pudo establecer la precondición: "{texto}".'

    return f'No fue posible completar el paso requerido: "{texto}".'


# --- Evidencia y tiempo por paso ---------------------------------------------------
def pytest_bdd_before_step_call(request, feature, scenario, step, step_func, step_func_args):
    request.node._t_paso = time.perf_counter()


def _ruta_actual(request):
    """Ruta (deterministico/semantico/agentic/sin_regla) del último step del router."""
    try:
        return request.getfixturevalue("router").ultima_ruta
    except Exception:
        return None


def _cerrar_paso(request, feature, scenario, step, estado, error=None, motivo=None):
    dt = time.perf_counter() - getattr(request.node, "_t_paso", time.perf_counter())
    captura = None
    try:
        sesion = request.getfixturevalue("sesion")
        destino = evidencia.ruta_captura(
            request.node.nodeid, feature.rel_filename, scenario.name, estado, step.name
        )
        if sesion.capturar(destino):
            captura = destino
    except Exception:
        pass
    ruta = _ruta_actual(request)
    evidencia.registrar_paso(
        request.node.nodeid,
        feature.name,
        scenario.name,
        step.keyword,
        step.name,
        estado,
        dt,
        captura,
        error,
        motivo,
        ruta,
        feature.rel_filename,
    )
    etiqueta = f"[{ruta['tipo']}]" if ruta else ""
    print(
        f"  [{dt:6.1f}s] {'ok ' if estado == 'ok' else 'ERR'} "
        f"{etiqueta:<16} {step.keyword} {step.name}"
    )
    if estado == "error" and motivo:
        print(f"           Motivo: {motivo}")


def pytest_bdd_after_step(request, feature, scenario, step, step_func, step_func_args):
    _cerrar_paso(request, feature, scenario, step, "ok")


def pytest_bdd_step_error(request, feature, scenario, step, step_func, step_func_args, exception):
    # pytest seguirá ejecutando los escenarios siguientes por defecto. Aquí no
    # interceptamos ni silenciamos la excepción: únicamente enriquecemos la
    # evidencia con una razón funcional y conservamos el detalle técnico.
    # Si el step no tiene regla (modo estricto), el mensaje de la excepción ya es
    # el motivo correcto; _motivo_fallo diría "elemento no disponible", que es falso.
    motivo = (
        str(exception)
        if isinstance(exception, StepNoReconocido)
        else _motivo_fallo(step)
    )
    _cerrar_paso(
        request,
        feature,
        scenario,
        step,
        "error",
        f"{type(exception).__name__}: {exception}"[:1000],
        motivo,
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    resultado = yield
    rep = resultado.get_result()
    if rep.when == "call" or (rep.when == "setup" and rep.failed):
        evidencia.marcar_estado(item.nodeid, rep.outcome)


def pytest_sessionfinish(session, exitstatus):
    informe = evidencia.escribir_informe()
    if informe:
        print(f"\nEvidencia: {informe}")