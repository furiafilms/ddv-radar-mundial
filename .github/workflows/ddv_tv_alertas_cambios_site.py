#!/usr/bin/env python3
# DDV TV/Plataformas Cambios v2 — mail claro vía endpoint del sitio.
# Objetivo: separar alertas futuras, registros históricos y cambios técnicos.

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from datetime import datetime, date, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

WATCH_STATE_FILES = [
    "outputs/state_tv_seen.json",
    "outputs/state_platforms_seen.json",
]

WATCH_SITE_FILES = [
    "outputs/site_tv_cable_global_filtered.json",
    "outputs/site_platforms_global.json",
]

TZ_NAME = os.getenv("DDV_TV_ALERT_TIMEZONE", "America/Argentina/Buenos_Aires")
TZ = ZoneInfo(TZ_NAME)
PAST_GRACE_MINUTES = int(os.getenv("DDV_TV_ALERT_PAST_GRACE_MINUTES", "30") or "30")
MAX_ITEMS = 12

MOVIE_IDS = {
    "Necrofobia": "necrofobia",
    "Hermanos de Sangre": "hermanos-de-sangre",
    "Ataúd Blanco": "ataud-blanco",
    "Al 3er Día": "al-3er-dia",
    "Punto Muerto": "punto-muerto",
    "El Último Hereje": "el-ultimo-hereje",
    "Los Ojos del Abismo": "los-ojos-del-abismo",
    "Death Knows Your Name": "death-knows-your-name",
    "Jennifer's Shadow": "jennifers-shadow",
    "Sueño Profundo": "sueno-profundo",
    "La Última Cena": "la-ultima-cena",
}


def changed_files() -> list[str]:
    cmd = ["git", "diff", "--name-only", "--"] + WATCH_STATE_FILES
    out = subprocess.check_output(cmd, text=True).strip()
    return [x for x in out.splitlines() if x.strip()]


def git_stat(paths: list[str]) -> str:
    if not paths:
        return ""
    cmd = ["git", "diff", "--stat", "--"] + paths
    return subprocess.check_output(cmd, text=True).strip()


def read_json(path: str):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"No pude leer {path}: {exc}")
        return None


def parse_date(value) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return None


def parse_time(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "00:00"
    # Acepta HH:MM o HH:MM–HH:MM; se queda con inicio.
    text = text.replace("–", "-").split("-")[0].strip()
    try:
        hh, mm = text[:5].split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except Exception:
        pass
    return "00:00"


def item_title(item: dict) -> str:
    return str(
        item.get("work_title")
        or item.get("movie")
        or item.get("title")
        or item.get("programme_title")
        or item.get("raw_title")
        or "Título no identificado"
    ).strip()


def item_channel(item: dict) -> str:
    return str(
        item.get("channel")
        or item.get("provider")
        or item.get("network")
        or item.get("source_name")
        or "Señal no identificada"
    ).strip()


def item_date(item: dict) -> date | None:
    return parse_date(
        item.get("date_iso")
        or item.get("date")
        or item.get("fecha")
        or item.get("air_date")
        or item.get("start_date")
    )


def item_time(item: dict) -> str:
    return parse_time(
        item.get("start_time")
        or item.get("time")
        or item.get("hora")
        or item.get("air_time")
    )


def vip_url(title: str) -> str:
    slug = MOVIE_IDS.get(title)
    if not slug:
        return ""
    return f"https://danieldelavega.com.ar/vip/pelicula.php?id={slug}"


def collect_tv_items() -> tuple[list[dict], list[dict], dict]:
    """Devuelve: futuras, históricas, metadata."""
    data = read_json("outputs/site_tv_cable_global_filtered.json") or {}
    meta = {k: data.get(k) for k in ["generated_at_utc", "hits_total", "review_total", "source", "version"] if k in data}
    hits = data.get("hits") if isinstance(data.get("hits"), list) else []

    now = datetime.now(TZ)
    boundary = now - timedelta(minutes=PAST_GRACE_MINUTES)
    future: list[dict] = []
    historic: list[dict] = []

    for item in hits:
        if not isinstance(item, dict):
            continue
        d = item_date(item)
        t = item_time(item)
        if not d:
            historic.append({**item, "_status": "FECHA NO IDENTIFICADA"})
            continue
        hh, mm = [int(x) for x in t.split(":")]
        dt = datetime.combine(d, time(hh, mm), tzinfo=TZ)
        enriched = {
            **item,
            "_title": item_title(item),
            "_channel": item_channel(item),
            "_date": d.isoformat(),
            "_time": t,
            "_dt": dt.isoformat(),
        }
        if dt >= boundary:
            enriched["_status"] = "FUTURA / ALERTABLE"
            future.append(enriched)
        else:
            enriched["_status"] = "HISTÓRICA / YA PASADA"
            historic.append(enriched)

    future.sort(key=lambda x: (x.get("_date", ""), x.get("_time", ""), x.get("_title", "")))
    historic.sort(key=lambda x: (x.get("_date", ""), x.get("_time", ""), x.get("_title", "")), reverse=True)
    return future, historic, meta


def collect_platform_summary() -> list[str]:
    data = read_json("outputs/site_platforms_global.json") or {}
    lines: list[str] = []
    for key in ["generated_at_utc", "hits_total", "review_total", "source", "version"]:
        if key in data:
            lines.append(f"{key}: {data.get(key)}")
    hits = data.get("hits") if isinstance(data.get("hits"), list) else []
    for item in hits[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        title = item.get("work_title") or item.get("title") or item.get("movie") or "Título no identificado"
        provider = item.get("provider") or item.get("platform") or item.get("service") or "Plataforma no identificada"
        country = item.get("country") or item.get("country_code") or item.get("region") or ""
        lines.append(f"- {title} · {provider}" + (f" · {country}" if country else ""))
    return lines


def format_event(item: dict) -> list[str]:
    title = item.get("_title") or item_title(item)
    channel = item.get("_channel") or item_channel(item)
    d = item.get("_date") or "fecha no identificada"
    t = item.get("_time") or "00:00"
    source = item.get("source") or item.get("fuente") or item.get("source_label") or ""
    url = item.get("source_url") or item.get("url") or item.get("link") or ""
    country = item.get("country") or item.get("country_code") or item.get("region") or ""
    lines = [f"- {title} — {channel} — {d} {t}"]
    if country:
        lines.append(f"  País/región: {country}")
    if source:
        lines.append(f"  Fuente: {source}")
    if url:
        lines.append(f"  Link fuente: {url}")
    page = vip_url(str(title))
    if page:
        lines.append(f"  Ver en VIP: {page}")
    return lines


def build_mail_body(changed: list[str]) -> tuple[str, str, int, dict]:
    future, historic, tv_meta = collect_tv_items()
    platform_lines = collect_platform_summary()
    stat = git_stat(WATCH_STATE_FILES + WATCH_SITE_FILES)
    now = datetime.now(TZ)

    if future:
        subject = f"DDV Radar — {len(future)} emisión(es) futura(s) TV/Cable"
        status = "Hay emisiones futuras o dentro de ventana de aviso. Revisar y accionar si corresponde."
    elif historic:
        subject = "DDV Radar — registros históricos actualizados, sin alerta futura"
        status = "No hay emisiones futuras nuevas. Se actualizaron registros históricos o archivos de estado."
    else:
        subject = "DDV Radar — cambios técnicos sin alerta TV futura"
        status = "No hay emisiones futuras nuevas identificadas. Los cambios son técnicos o de plataformas."

    sections: list[str] = [
        "Radar DDV — TV/Cable/Plataformas",
        "",
        "RESUMEN EJECUTIVO",
        status,
        f"Control: {now.strftime('%d/%m/%Y %H:%M')} ({TZ_NAME})",
        "",
        "1. EMISIONES FUTURAS / ACCIONABLES",
    ]

    if future:
        for item in future[:MAX_ITEMS]:
            sections.extend(format_event(item))
            sections.append("  Estado: FUTURA / ALERTABLE")
        sections.append("")
        sections.append("Acción sugerida: verificar fuente, difundir o registrar según corresponda.")
    else:
        sections.append("No se detectaron nuevas emisiones futuras dentro de la ventana revisada.")

    sections += ["", "2. REGISTROS HISTÓRICOS O YA PASADOS"]
    if historic:
        for item in historic[:MAX_ITEMS]:
            sections.extend(format_event(item))
            sections.append("  Estado: HISTÓRICA / YA PASADA. No requiere acción urgente.")
    else:
        sections.append("No se detectaron registros históricos nuevos en TV/Cable.")

    sections += ["", "3. PLATAFORMAS"]
    if platform_lines:
        sections.extend(platform_lines[:MAX_ITEMS + 5])
    else:
        sections.append("Sin resumen de plataformas disponible.")

    sections += ["", "4. CAMBIOS TÉCNICOS"]
    if changed:
        sections.append("Archivos de estado modificados:")
        sections.extend([f"- {x}" for x in changed])
    else:
        sections.append("No se modificaron archivos de estado monitoreados.")

    if tv_meta:
        sections += ["", "Metadata TV/Cable:"]
        sections.extend([f"- {k}: {v}" for k, v in tv_meta.items()])

    if stat:
        sections += ["", "Resumen técnico Git:", stat]

    sections += [
        "",
        "CRITERIO DEL MAIL",
        "- FUTURA / ALERTABLE: puede requerir difusión o seguimiento.",
        "- HISTÓRICA / YA PASADA: queda como antecedente; no es urgencia.",
        "- TÉCNICO: cambios internos del radar; no implica por sí solo una emisión futura.",
    ]

    info = {
        "future_count": len(future),
        "historic_count": len(historic),
        "platform_summary_count": len(platform_lines),
        "changed_files": changed,
    }
    return subject, "\n".join(sections).strip() + "\n", len(future) + len(historic), info


def post_site(subject: str, body: str, count: int) -> bool:
    url = os.getenv("DDV_TV_ALERT_MAIL_URL", "").strip()
    if not url:
        print("ERROR: falta DDV_TV_ALERT_MAIL_URL. No hay mail garantizado.")
        return False

    payload = json.dumps(
        {
            "mode": "tv_platform_changes_clear_v2",
            "subject": subject,
            "body": body,
            "alerts_count": count,
            "source": "github-actions-ddv-radar-cambios-site-mail-v2",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "ddv-radar-cambios-site-mail-v2",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", "replace")
            print(raw)
            data = json.loads(raw)
            return bool(data.get("mail_sent") is True)
    except Exception as exc:
        print(f"ERROR al llamar endpoint de mail del sitio: {exc}")
        return False


def main() -> int:
    changed = changed_files()
    last_run_path = Path("outputs/tv_platform_change_mail_last_run.json")

    if not changed:
        info = {
            "version": "DDV_TV_CAMBIOS_MAIL_SITE_V2_CLEAR",
            "ran_at": datetime.utcnow().isoformat() + "Z",
            "changes_detected": False,
            "mail_sent": False,
        }
        last_run_path.parent.mkdir(parents=True, exist_ok=True)
        last_run_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Sin cambios nuevos en state_tv_seen/state_platforms_seen. No se manda mail.")
        return 0

    subject, body, count, extra = build_mail_body(changed)
    ok = post_site(subject, body, count)

    info = {
        "version": "DDV_TV_CAMBIOS_MAIL_SITE_V2_CLEAR",
        "ran_at": datetime.utcnow().isoformat() + "Z",
        "changes_detected": True,
        "mail_sent": ok,
        **extra,
    }
    last_run_path.parent.mkdir(parents=True, exist_ok=True)
    last_run_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    if not ok:
        print("ERROR: el sitio no confirmó mail_sent=true. Falla el workflow para no ocultar el problema.")
        return 1

    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
