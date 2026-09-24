"""Evidencia de ejecución: captura por paso + informe HTML por corrida.

Cada corrida de pytest crea  evidencia/<fecha_hora>/  con:
  index.html      informe agrupado por .feature (escenarios, pasos, estado, tiempos, capturas)
  resumen.json    lo mismo en JSON
  <archivo_feature>/<escenario>/NN_<estado>_<paso>.png   una captura por paso

La carpeta de cada escenario es única dentro de la corrida: aunque dos .feature
tengan escenarios con el mismo nombre, o un Scenario Outline genere varios casos,
sus capturas nunca se sobrescriben.

Cada paso registra además su "ruta" en el router (deterministico / semantico /
agentic / sin_regla) y el encabezado resume cuántos pasos hubo de cada tipo.

Las capturas pueden mostrar datos personales o financieros: trátalas como sensibles.
"""
from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path

RAIZ = Path(os.getenv("EVIDENCIA_DIR", "evidencia"))
CORRIDA = RAIZ / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

_ESCENARIOS: dict[str, dict] = {}
_CARPETAS_USADAS: set[str] = set()
_ETIQUETA = {"passed": "Aprobado", "failed": "Fallido"}


def _slug(texto: str, largo: int = 50) -> str:
    s = re.sub(r"\W+", "_", texto, flags=re.UNICODE).strip("_")
    return s[:largo] or "sin_nombre"


def _slug_archivo(archivo: str) -> str:
    """login-empresa.feature -> login-empresa (conserva guiones para reconocer el archivo)."""
    s = re.sub(r"[^\w\-]+", "_", Path(archivo).stem, flags=re.UNICODE).strip("_")
    return s or "sin_feature"


def _carpeta(nodeid: str, archivo: str, escenario: str) -> str:
    """Carpeta única por escenario: <archivo_feature>/<escenario>[__<ejemplo>][_N]."""
    base = f"{_slug_archivo(archivo)}/{_slug(escenario)}"

    # Scenario Outline: pytest agrega los parámetros del ejemplo entre corchetes.
    parametros = nodeid.partition("[")[2].rstrip("]")
    if parametros:
        base += "__" + _slug(parametros, 30)

    carpeta, n = base, 2
    while carpeta in _CARPETAS_USADAS:  # escenarios repetidos dentro del mismo .feature
        carpeta, n = f"{base}_{n}", n + 1
    _CARPETAS_USADAS.add(carpeta)
    return carpeta


def _entrada(nodeid: str, feature: str = "", escenario: str = "", archivo: str = "") -> dict:
    e = _ESCENARIOS.setdefault(
        nodeid,
        {
            "archivo": archivo,
            "carpeta": None,
            "feature": feature,
            "escenario": escenario,
            "estado": "sin resultado",
            "inicio": datetime.now().isoformat(timespec="seconds"),
            "motivo_fallo": None,
            "paso_fallido": None,
            "pasos": [],
        },
    )
    if archivo and not e["archivo"]:
        e["archivo"] = archivo
    if escenario and not e["escenario"]:
        e["escenario"] = escenario
    if not e["carpeta"] and e["escenario"]:
        e["carpeta"] = _carpeta(nodeid, e["archivo"], e["escenario"])
    return e


def ruta_captura(nodeid: str, archivo: str, escenario: str, estado: str, texto: str) -> Path:
    e = _entrada(nodeid, escenario=escenario, archivo=archivo)
    n = len(e["pasos"]) + 1
    return CORRIDA / e["carpeta"] / f"{n:02d}_{estado}_{_slug(texto, 40)}.png"


def registrar_paso(
    nodeid,
    feature,
    escenario,
    keyword,
    texto,
    estado,
    segundos,
    captura,
    error=None,
    motivo=None,
    ruta=None,
    archivo=None,
):
    e = _entrada(nodeid, archivo=archivo or "")
    e["feature"], e["escenario"] = feature, escenario

    paso = f"{keyword} {texto}"
    e["pasos"].append(
        {
            "n": len(e["pasos"]) + 1,
            "paso": paso,
            "estado": estado,
            "segundos": round(segundos, 1),
            "captura": captura.relative_to(CORRIDA).as_posix() if captura else None,
            "motivo": motivo,
            "error": error,
            "ruta": ruta,
        }
    )

    # Guardamos el primer fallo como causa principal del escenario. Esto hace
    # que el informe explique por qué falló sin obligar a leer el traceback.
    if estado == "error" and not e.get("motivo_fallo"):
        e["motivo_fallo"] = motivo or error or "Un paso del escenario falló."
        e["paso_fallido"] = paso


def marcar_estado(nodeid: str, estado: str) -> None:
    _entrada(nodeid)["estado"] = estado


def _html_escenario(e: dict) -> list[str]:
    """HTML de un escenario: encabezado, motivo de fallo y tabla de pasos."""
    esc = html.escape
    partes: list[str] = []
    clase = e["estado"] if e["estado"] in _ETIQUETA else ""
    partes.append(
        f"<h3>{esc(e['escenario'])} <span class='{clase}'>[{esc(_ETIQUETA.get(e['estado'], e['estado']))}]</span></h3>"
        f"<small>inicio {esc(e['inicio'])} &middot; capturas en {esc(str(e.get('carpeta') or '—'))}/</small>"
    )
    if e.get("motivo_fallo"):
        partes.append(
            "<div class='motivo'>"
            f"<b>Motivo del fallo:</b> {esc(str(e['motivo_fallo']))}"
            + (
                f"<br><span class='detalle'>Paso: {esc(str(e['paso_fallido']))}</span>"
                if e.get("paso_fallido")
                else ""
            )
            + "</div>"
        )
    partes.append(
        "<table><tr><th>#</th><th>Paso</th><th>Estado</th><th>Ruta</th><th>Seg.</th><th>Captura</th></tr>"
    )
    for p in e["pasos"]:
        img = (
            f"<a href='{esc(p['captura'], quote=True)}'><img src='{esc(p['captura'], quote=True)}' alt='captura'></a>"
            if p["captura"]
            else "&mdash;"
        )
        motivo = (
            f"<br><small class='error'>{esc(p['motivo'])}</small>"
            if p.get("motivo")
            else ""
        )
        detalle = (
            f"<br><small class='detalle'>Detalle técnico: {esc(p['error'])}</small>"
            if p.get("error")
            else ""
        )
        ruta = p.get("ruta") or {}
        celda_ruta = (
            f"<td class='{esc(ruta.get('tipo', 'sin_ruta'), quote=True)}'>"
            f"{esc(ruta.get('tipo', '—'))}<br><small>{esc(ruta.get('regla', ''))}</small></td>"
        )
        partes.append(
            f"<tr><td>{p['n']}</td><td>{esc(p['paso'])}{motivo}{detalle}</td>"
            f"<td class='{p['estado']}'>{esc(p['estado'])}</td>{celda_ruta}"
            f"<td>{p['segundos']}</td><td>{img}</td></tr>"
        )
    partes.append("</table>")
    return partes


def escribir_informe() -> Path | None:
    if not _ESCENARIOS:
        return None
    CORRIDA.mkdir(parents=True, exist_ok=True)
    escenarios = list(_ESCENARIOS.values())
    meta = {
        "ambiente": os.getenv("TEST_ENV"),
        "base_url": os.getenv("BASE_URL"),
        "generado": datetime.now().isoformat(timespec="seconds"),
    }

    # Resumen de autonomía: cuántos pasos se resolvieron por cada ruta del router.
    por_tipo: dict[str, int] = {}
    for e in escenarios:
        for p in e["pasos"]:
            tipo = (p.get("ruta") or {}).get("tipo", "sin_ruta")
            por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
    meta["rutas"] = por_tipo

    # Agrupación por archivo .feature, en orden de ejecución.
    por_feature: dict[str, list[dict]] = {}
    for e in escenarios:
        por_feature.setdefault(e.get("archivo") or "sin_feature", []).append(e)
    meta["features"] = {
        archivo: {
            "nombre": lista[0]["feature"],
            "escenarios": len(lista),
            "aprobados": sum(1 for e in lista if e["estado"] == "passed"),
        }
        for archivo, lista in por_feature.items()
    }

    (CORRIDA / "resumen.json").write_text(
        json.dumps({**meta, "escenarios": escenarios}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    esc = html.escape
    ok = sum(1 for e in escenarios if e["estado"] == "passed")
    partes = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'><title>Evidencia de pruebas</title><style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;max-width:1100px}",
        "table{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}",
        "td,th{border:1px solid #ddd;padding:.4rem;text-align:left;vertical-align:top;font-size:.9rem}",
        ".passed,.ok{color:#0a7d33}.failed,.error{color:#b00020;font-weight:600}",
        ".motivo{background:#fff4f4;border-left:4px solid #b00020;padding:.7rem 1rem;margin:.6rem 0 1rem}",
        ".detalle{color:#666;font-size:.82rem}",
        ".agentic,.sin_ruta,.sin_regla{color:#b36b00;font-weight:600}",
        ".deterministico{color:#0a7d33}.semantico{color:#1a5fb4}",
        "img{max-width:260px;border:1px solid #ccc}h3{margin-bottom:0}small{color:#555}",
        ".feature{border-top:3px solid #333;margin-top:2.5rem;padding-top:.5rem}",
        ".feature>h2{margin:0}.archivo{font-family:monospace;color:#555;margin:.2rem 0 1rem}",
        "</style></head><body><h1>Evidencia de pruebas</h1>",
        f"<p>Ambiente: <b>{esc(str(meta['ambiente']))}</b> &middot; URL: {esc(str(meta['base_url']))}"
        f" &middot; Generado: {esc(meta['generado'])}<br>"
        f"Escenarios: {len(escenarios)} &middot; Aprobados: {ok} &middot; Fallidos: {len(escenarios) - ok}<br>"
        "Rutas: "
        + (" &middot; ".join(
            f"<span class='{esc(k)}'>{esc(k)}</span>: <b>{v}</b>" for k, v in sorted(por_tipo.items())
        ) or "&mdash;")
        + "</p>",
    ]
    for archivo, lista in por_feature.items():
        resumen_f = meta["features"][archivo]
        partes.append(
            "<section class='feature'>"
            f"<h2>{esc(resumen_f['nombre'] or archivo)}</h2>"
            f"<p class='archivo'>{esc(archivo)} &middot; Escenarios: {resumen_f['escenarios']}"
            f" &middot; Aprobados: {resumen_f['aprobados']}"
            f" &middot; Fallidos: {resumen_f['escenarios'] - resumen_f['aprobados']}</p>"
        )
        for e in lista:
            partes.extend(_html_escenario(e))
        partes.append("</section>")
    partes.append("</body></html>")
    destino = CORRIDA / "index.html"
    destino.write_text("".join(partes), encoding="utf-8")
    return destino