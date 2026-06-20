#!/usr/bin/env python3
# DDV TV/Plataformas Cambios v5 WAF SAFE — mail claro compacto vía endpoint del sitio.
# Detecta bloqueo anti-bot/WAF HTML de Neolo y no deja rojo falso si no hay emisiones futuras.

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from datetime import datetime, date, time, timedelta, timezone
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

LAST_RUN_PATH = Path("outputs/tv_platform_change_mail_last_run.json")
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


def run_git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as exc:
        print(f"WARN git {' '.join(args)} falló:\n{exc.output}")
        return ""


def changed_files() -> list[str]:
    out = run_git(["diff", "--name-only", "--", *WATCH_STATE_FILES])
    return [x for x in out.splitlines() if x.strip()]


def git_stat(paths: list[str]) -> str:
    return run_git(["diff", "--stat", "--", *paths]) if paths else ""


def read_json(path: str):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARN: no pude leer {path}: {exc}")
        return None


def parse_date(value) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_time(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "00:00"
    text = text.replace("–", "-").split("-")[0].strip()
    try:
        hh, mm = text[:5].split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except Exception:
        pass
    return "00:00"


def first_value(item: dict, keys: list[str], default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return default


def item_title(item: dict) -> str:
    return first_value(
        item,
        ["work_title", "movie", "title", "programme_title", "raw_title"],
        "Título no identificado",
    )


def item_channel(item: dict) -> str:
    return first_value(
        item,
        ["channel", "provider", "network", "source_name"],
        "Señal no identificada",
    )


def item_date(item: dict) -> date | None:
    return parse_date(first_value(item, ["date_iso", "date", "fecha", "air_date", "start_date"]))


def item_time(item: dict) -> str:
    return parse_time(first_value(item, ["start_time", "time", "hora", "air_time"]))


def vip_url(title: str) -> str:
    slug = MOVIE_IDS.get(title)
    return f"https://danieldelavega.com.ar/vip/pelicula.php?id={slug}" if slug else ""


def extract_hits(data) -> list[dict]:
    if not isinstance(data, dict):
        return []
    for key in ("hits", "items", "results", "events"):
        value = data.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def collect_tv_items() -> tuple[list[dict], list[dict], dict]:
    data = read_json("outputs/site_tv_cable_global_filtered.json") or {}
    meta = {
        k: data.get(k)
        for k in ["generated_at_utc", "hits_total", "review_total", "source", "version"]
        if isinstance(data, dict) and k in data
    }
    hits = extract_hits(data)

    now = datetime.now(TZ)
    boundary = now - timedelta(minutes=PAST_GRACE_MINUTES)
    future: list[dict] = []
    historic: list[dict] = []

    for item in hits:
        title = item_title(item)
        channel = item_channel(item)
        d = item_date(item)
        t = item_time(item)
        enriched = {
            **item,
            "_title": title,
            "_channel": channel,
            "_date": d.isoformat() if d else "fecha no identificada",
            "_time": t,
        }
        if not d:
            enriched["_status"] = "FECHA NO IDENTIFICADA / REVISAR"
            historic.append(enriched)
            continue
        hh, mm = [int(x) for x in t.split(":")]
        dt = datetime.combine(d, time(hh, mm), tzinfo=TZ)
        enriched["_dt"] = dt.isoformat()
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
    if isinstance(data, dict):
        for key in ["generated_at_utc", "hits_total", "review_total", "source", "version"]:
            if key in data:
                lines.append(f"{key}: {data.get(key)}")
        hits = extract_hits(data)
        for item in hits[:MAX_ITEMS]:
            title = first_value(item, ["work_title", "title", "movie"], "Título no identificado")
            provider = first_value(item, ["provider", "platform", "service"], "Plataforma no identificada")
            country = first_value(item, ["country", "country_code", "region"], "")
            lines.append(f"- {title} · {provider}" + (f" · {country}" if country else ""))
    return lines


def format_event(item: dict) -> list[str]:
    title = str(item.get("_title") or item_title(item))
    channel = str(item.get("_channel") or item_channel(item))
    d = str(item.get("_date") or "fecha no identificada")
    t = str(item.get("_time") or "00:00")
    source = first_value(item, ["source", "fuente", "source_label"], "")
    url = first_value(item, ["source_url", "url", "link"], "")
    country = first_value(item, ["country", "country_code", "region"], "")

    lines = [f"- {title} — {channel} — {d} {t}"]
    if country:
        lines.append(f"  País/región: {country}")
    if source:
        lines.append(f"  Fuente: {source}")
    if url:
        lines.append(f"  Link fuente: {url}")
    page = vip_url(title)
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
        sections.extend(platform_lines[: MAX_ITEMS + 5])
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


def build_compact_mail_body(changed: list[str]) -> tuple[str, str, int, dict]:
    """
    Cuerpo deliberadamente compacto. El endpoint del hosting devolvió una página HTML
    de verificación anti-bot cuando el payload era más largo/técnico.
    Este mail conserva lo importante para Daniel y evita diffs largos/ruido técnico.
    """
    future, historic, tv_meta = collect_tv_items()
    platform_lines = collect_platform_summary()
    now = datetime.now(TZ)

    if future:
        subject = f"DDV Radar — {len(future)} emisión(es) futura(s) TV/Cable"
        status = "Hay emisiones futuras o dentro de ventana de aviso. Revisar y accionar si corresponde."
    elif historic:
        subject = f"DDV Radar — sin futuras; {len(historic)} registro(s) histórico(s)"
        status = "No hay emisiones futuras nuevas. Se actualizaron registros históricos o archivos de estado."
    else:
        subject = "DDV Radar — cambios técnicos sin alerta futura"
        status = "No hay emisiones futuras nuevas identificadas."

    lines: list[str] = [
        "Radar DDV — TV/Cable/Plataformas",
        "",
        "RESUMEN EJECUTIVO",
        status,
        f"Control: {now.strftime('%d/%m/%Y %H:%M')} ({TZ_NAME})",
        "",
        "1. EMISIONES FUTURAS / ACCIONABLES",
    ]

    if future:
        for item in future[:8]:
            lines.extend(format_event(item))
            lines.append("  Estado: FUTURA / ALERTABLE")
            lines.append("")
        lines.append("Acción sugerida: verificar fuente, difundir o registrar según corresponda.")
    else:
        lines.append("No se detectaron nuevas emisiones futuras dentro de la ventana revisada.")

    lines += ["", "2. REGISTROS HISTÓRICOS O YA PASADOS"]
    if historic:
        for item in historic[:8]:
            title = str(item.get("_title") or item_title(item))
            channel = str(item.get("_channel") or item_channel(item))
            d = str(item.get("_date") or "fecha no identificada")
            t = str(item.get("_time") or "00:00")
            source = first_value(item, ["source", "fuente", "source_label"], "")
            lines.append(f"- {title} — {channel} — {d} {t}")
            if source:
                lines.append(f"  Fuente: {source}")
            page = vip_url(title)
            if page:
                lines.append(f"  Ver en VIP: {page}")
            lines.append("  Estado: HISTÓRICA / YA PASADA. No requiere acción urgente.")
    else:
        lines.append("No se detectaron registros históricos nuevos en TV/Cable.")

    lines += ["", "3. PLATAFORMAS"]
    if platform_lines:
        # Evita tirar un volcado enorme. Solo lo esencial.
        for x in platform_lines[:4]:
            lines.append(x)
    else:
        lines.append("Sin resumen de plataformas disponible.")

    lines += ["", "4. CAMBIOS TÉCNICOS"]
    if changed:
        lines.append("Archivos de estado modificados:")
        lines.extend([f"- {x}" for x in changed[:8]])
    else:
        lines.append("No se modificaron archivos de estado monitoreados.")

    lines += [
        "",
        "CRITERIO",
        "- FUTURA / ALERTABLE: puede requerir difusión o seguimiento.",
        "- HISTÓRICA / YA PASADA: antecedente; no es urgencia.",
        "- TÉCNICO: cambio interno del radar; no implica por sí solo una emisión futura.",
    ]

    info = {
        "future_count": len(future),
        "historic_count": len(historic),
        "platform_summary_count": len(platform_lines),
        "changed_files": changed,
        "mail_format": "compact_v5",
        "tv_meta": tv_meta,
    }
    return subject, "\n".join(lines).strip() + "\n", len(future) + len(historic), info


def looks_like_security_challenge(raw: str) -> bool:
    low = (raw or "").lower()
    return (
        "one moment" in low
        or "request is being verified" in low
        or "please wait" in low and "verified" in low
        or "<html" in low and "spinner" in low
    )


def write_last_run(info: dict) -> None:
    LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_PATH.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def post_site(subject: str, body: str, count: int) -> tuple[bool, dict]:
    url = os.getenv("DDV_TV_ALERT_MAIL_URL", "").strip()
    meta = {
        "endpoint_configured": bool(url),
        "subject": subject,
        "body_length": len(body),
        "endpoint_http_status": None,
        "endpoint_content_type": "",
        "endpoint_raw_prefix": "",
        "endpoint_error": "",
        "mail_blocked_by_security_challenge": False,
    }
    if not url:
        meta["endpoint_error"] = "Falta DDV_TV_ALERT_MAIL_URL"
        print("ERROR: falta DDV_TV_ALERT_MAIL_URL. No hay mail garantizado.")
        return False, meta

    payload = json.dumps(
        {
            "mode": "tv_platform_changes_clear_v5_compact",
            "subject": subject,
            "body": body,
            "alerts_count": count,
            "source": "github-actions-ddv-radar-cambios-site-mail-v5",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    meta["payload_bytes"] = len(payload)

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "Mozilla/5.0 (compatible; DDV-Radar/5.0; +https://danieldelavega.com.ar)",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://danieldelavega.com.ar",
            "Referer": "https://danieldelavega.com.ar/",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", "replace")
            meta["endpoint_http_status"] = getattr(resp, "status", None)
            meta["endpoint_content_type"] = resp.headers.get("Content-Type", "")
            meta["endpoint_raw_prefix"] = raw[:800]
            print("Respuesta endpoint:")
            print(raw[:3000])

            if looks_like_security_challenge(raw):
                meta["mail_blocked_by_security_challenge"] = True
                meta["endpoint_error"] = "El hosting devolvió HTML de verificación anti-bot/WAF, no JSON."
                return False, meta

            data = json.loads(raw)
            meta["endpoint_json"] = data
            return bool(data.get("mail_sent") is True), meta
    except Exception as exc:
        meta["endpoint_error"] = str(exc)
        print(f"ERROR al llamar endpoint de mail del sitio: {exc}")
        return False, meta


def main() -> int:
    changed = changed_files()
    base = {
        "version": "DDV_TV_CAMBIOS_MAIL_SITE_V5_WAF_SAFE",
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "changes_detected": bool(changed),
    }

    if not changed:
        info = {**base, "mail_sent": False, "reason": "Sin cambios nuevos en archivos de estado monitoreados"}
        write_last_run(info)
        print("Sin cambios nuevos en state_tv_seen/state_platforms_seen. No se manda mail.")
        return 0

    subject, body, count, extra = build_compact_mail_body(changed)
    ok, endpoint_meta = post_site(subject, body, count)

    info = {**base, "mail_sent": ok, **extra, **endpoint_meta}
    write_last_run(info)

    print("--- CUERPO DEL MAIL CLARO COMPACTO ---")
    print(body)

    if not ok:
        future_count = int(extra.get("future_count") or 0)
        if endpoint_meta.get("mail_blocked_by_security_challenge") and future_count == 0:
            print("AVISO: el hosting bloqueó el POST con una verificación anti-bot/WAF, pero no hay emisiones futuras alertables.")
            print("El workflow queda verde para no generar falso rojo por históricos/técnicos. Revisar artifact para detalle.")
            return 0
        print("ERROR: el sitio no confirmó mail_sent=true. Si hay futuras, falla para no ocultar el problema.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
