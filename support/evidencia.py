"""Evidencia de ejecución: captura por paso + informe HTML por corrida.

Cada corrida de pytest crea  evidencia/<fecha_hora>/  con:
  index.html      informe (escenarios, pasos, estado, tiempos, capturas)
  resumen.json    lo mismo en JSON
  <escenario>/NN_<estado>_<paso>.png   una captura por paso (y en el paso que falla)

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
_ETIQUETA = {"passed": "Aprobado", "failed": "Fallido"}


def _slug(texto: str, largo: int = 50) -> str:
    s = re.sub(r"\W+", "_", texto, flags=re.UNICODE).strip("_")
    return s[:largo] or "sin_nombre"


def _entrada(nodeid: str, feature: str = "", escenario: str = "") -> dict:
    return _ESCENARIOS.setdefault(
        nodeid,
        {
            "feature": feature,
            "escenario": escenario,
            "estado": "sin resultado",
            "inicio": datetime.now().isoformat(timespec="seconds"),
            "motivo_fallo": None,
            "paso_fallido": None,
            "pasos": [],
        },
    )


def ruta_captura(nodeid: str, escenario: str, estado: str, texto: str) -> Path:
    e = _entrada(nodeid, escenario=escenario)
    n = len(e["pasos"]) + 1
    return CORRIDA / _slug(escenario) / f"{n:02d}_{estado}_{_slug(texto, 40)}.png"


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
):
    e = _entrada(nodeid)
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
        }
    )

    # Guardamos el primer fallo como causa principal del escenario. Esto hace
    # que el informe explique por qué falló sin obligar a leer el traceback.
    if estado == "error" and not e.get("motivo_fallo"):
        e["motivo_fallo"] = motivo or error or "Un paso del escenario falló."
        e["paso_fallido"] = paso


def marcar_estado(nodeid: str, estado: str) -> None:
    _entrada(nodeid)["estado"] = estado


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
        "img{max-width:260px;border:1px solid #ccc}h2{margin-bottom:0}small{color:#555}",
        "</style></head><body><h1>Evidencia de pruebas</h1>",
        f"<p>Ambiente: <b>{esc(str(meta['ambiente']))}</b> &middot; URL: {esc(str(meta['base_url']))}"
        f" &middot; Generado: {esc(meta['generado'])}<br>"
        f"Escenarios: {len(escenarios)} &middot; Aprobados: {ok} &middot; Fallidos: {len(escenarios) - ok}</p>",
    ]
    for e in escenarios:
        clase = e["estado"] if e["estado"] in _ETIQUETA else ""
        partes.append(
            f"<h2>{esc(e['escenario'])} <span class='{clase}'>[{esc(_ETIQUETA.get(e['estado'], e['estado']))}]</span></h2>"
            f"<small>{esc(e['feature'])} &middot; inicio {esc(e['inicio'])}</small>"
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
            "<table><tr><th>#</th><th>Paso</th><th>Estado</th><th>Seg.</th><th>Captura</th></tr>"
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
            partes.append(
                f"<tr><td>{p['n']}</td><td>{esc(p['paso'])}{motivo}{detalle}</td>"
                f"<td class='{p['estado']}'>{esc(p['estado'])}</td><td>{p['segundos']}</td><td>{img}</td></tr>"
            )
        partes.append("</table>")
    partes.append("</body></html>")
    destino = CORRIDA / "index.html"
    destino.write_text("".join(partes), encoding="utf-8")
    return destino
