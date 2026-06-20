#!/usr/bin/env python3
# DDV TV/Plataformas Cambios v6 PLATAFORMAS PRO — mail claro con delta real de plataformas.
# Compara outputs/site_platforms_global.json actual contra HEAD para distinguir:
# - nuevas disponibilidades
# - disponibilidades removidas
# - cambios solo técnicos/metadatos

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.request
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

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
MAX_TV_ITEMS = 8
MAX_PLATFORM_ITEMS = 12
MAX_PLATFORM_SUMMARY = 10

REGION_PRIORITY = {
    "AR": 0,
    "UY": 1,
    "CL": 2,
    "MX": 3,
    "US": 4,
    "ES": 5,
    "BR": 6,
    "CO": 7,
    "PE": 8,
    "GB": 9,
    "IT": 10,
    "FR": 11,
    "DE": 12,
    "CA": 13,
    "AU": 14,
}

TYPE_LABELS = {
    "flatrate": "suscripción",
    "free": "gratis",
    "ads": "gratis con publicidad",
    "rent": "alquiler",
    "buy": "compra",
    "subscription": "suscripción",
}

MOVIE_IDS = {
    "Necrofobia": "necrofobia",
    "Hermanos de Sangre": "hermanos-de-sangre",
    "Ataúd Blanco": "ataud-blanco",
    "Al 3er Día": "al-3er-dia",
    "Punto Muerto": "punto-muerto",
    "El Último Hereje": "el-ultimo-hereje",
    "Los Ojos del Abismo": "los-ojos-del-abismo",
    "Death Knows Your Name": "death-knows-your-name",
    "La Muerte Conoce tu Nombre": "death-knows-your-name",
    "Jennifer's Shadow": "jennifers-shadow",
    "Jennifer’s Shadow": "jennifers-shadow",
    "Sueño Profundo": "sueno-profundo",
    "La Última Cena": "la-ultima-cena",
    "Soy Tóxico": "soy-toxico",
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


def read_json(path: str) -> Any:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARN: no pude leer {path}: {exc}")
        return None


def read_json_from_head(path: str) -> Any:
    """Lee el archivo de la versión anterior commiteada. Si no existe, devuelve None."""
    try:
        raw = subprocess.check_output(
            ["git", "show", f"HEAD:{path}"],
            text=True,
            stderr=subprocess.STDOUT,
        )
        return json.loads(raw)
    except Exception as exc:
        print(f"WARN: no pude leer HEAD:{path}: {exc}")
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
    return first_value(item, ["work_title", "movie", "title", "programme_title", "raw_title"], "Título no identificado")


def item_channel(item: dict) -> str:
    return first_value(item, ["channel", "provider", "network", "source_name"], "Señal no identificada")


def item_date(item: dict) -> date | None:
    return parse_date(first_value(item, ["date_iso", "date", "fecha", "air_date", "start_date"]))


def item_time(item: dict) -> str:
    return parse_time(first_value(item, ["start_time", "time", "hora", "air_time"]))


def slug_for_title(title: str, fallback: str = "") -> str:
    return MOVIE_IDS.get(title) or fallback


def vip_url_from_slug(slug: str) -> str:
    return f"https://danieldelavega.com.ar/vip/pelicula.php?id={slug}" if slug else ""


def vip_url(title: str) -> str:
    return vip_url_from_slug(slug_for_title(title))


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


def platform_items_by_identity(data: Any) -> dict[str, dict]:
    """Extrae disponibilidades actuales por identidad estable, ignorando detected_at."""
    if not isinstance(data, dict):
        return {}
    by_slug = data.get("by_slug")
    if not isinstance(by_slug, dict):
        return {}

    out: dict[str, dict] = {}
    for slug, work in by_slug.items():
        if not isinstance(work, dict):
            continue
        title = str(work.get("title") or slug).strip()
        current = work.get("current") or []
        if not isinstance(current, list):
            continue
        for item in current:
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched["_slug"] = str(slug)
            enriched["_work_title"] = str(item.get("work_title") or title)
            enriched["_vip_url"] = vip_url_from_slug(str(slug))
            key = platform_identity(enriched)
            out[key] = enriched
    return out


def platform_identity(item: dict) -> str:
    # identity_fingerprint viene del radar y evita ruido por detected_at/fingerprint de corrida.
    stable = item.get("identity_fingerprint")
    if stable:
        return str(stable)
    fields = [
        item.get("_slug") or item.get("slug") or "",
        item.get("name") or item.get("provider") or item.get("platform") or "",
        item.get("region_code") or item.get("region") or item.get("country") or "",
        item.get("raw_type") or item.get("type") or "",
        item.get("url") or "",
        item.get("source") or "",
    ]
    raw = "|".join(str(x).strip().lower() for x in fields)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def platform_sort_key(item: dict):
    region = platform_region(item)
    title = platform_title(item).lower()
    provider = platform_provider(item).lower()
    typ = platform_type(item).lower()
    return (REGION_PRIORITY.get(region, 99), title, provider, typ)


def platform_title(item: dict) -> str:
    return first_value(item, ["_work_title", "work_title", "title", "movie"], "Título no identificado")


def platform_provider(item: dict) -> str:
    return first_value(item, ["name", "provider", "platform", "service"], "Plataforma no identificada")


def platform_region(item: dict) -> str:
    return first_value(item, ["region_code", "region", "country", "country_code"], "").upper()


def platform_type(item: dict) -> str:
    raw = first_value(item, ["raw_type", "type"], "")
    typ = first_value(item, ["type"], raw)
    return TYPE_LABELS.get(raw, TYPE_LABELS.get(typ, typ or "tipo no indicado"))


def platform_source(item: dict) -> str:
    return first_value(item, ["source"], "")


def platform_url(item: dict) -> str:
    return first_value(item, ["url", "link", "source_url"], "")


def collect_platform_delta() -> dict:
    current = read_json("outputs/site_platforms_global.json") or {}
    previous = read_json_from_head("outputs/site_platforms_global.json")

    cur_items = platform_items_by_identity(current)
    old_items = platform_items_by_identity(previous)

    current_loaded = bool(cur_items) or isinstance(current, dict)
    previous_loaded = bool(old_items) or isinstance(previous, dict)

    added_keys = sorted(set(cur_items) - set(old_items), key=lambda k: platform_sort_key(cur_items[k]))
    removed_keys = sorted(set(old_items) - set(cur_items), key=lambda k: platform_sort_key(old_items[k]))

    added = [cur_items[k] for k in added_keys]
    removed = [old_items[k] for k in removed_keys]

    by_title: dict[str, dict[str, int]] = {}
    for item in added:
        title = platform_title(item)
        by_title.setdefault(title, {"added": 0, "removed": 0})["added"] += 1
    for item in removed:
        title = platform_title(item)
        by_title.setdefault(title, {"added": 0, "removed": 0})["removed"] += 1

    current_by_slug = current.get("by_slug", {}) if isinstance(current, dict) else {}
    titles_with_current = 0
    titles_without_current = 0
    if isinstance(current_by_slug, dict):
        for work in current_by_slug.values():
            if isinstance(work, dict) and work.get("current"):
                titles_with_current += 1
            else:
                titles_without_current += 1

    meta = {
        "source": current.get("source") if isinstance(current, dict) else None,
        "version": current.get("version") if isinstance(current, dict) else None,
        "generated_at": current.get("generated_at") if isinstance(current, dict) else None,
        "items_count": current.get("items_count") if isinstance(current, dict) else None,
        "titles_with_current": titles_with_current,
        "titles_without_current": titles_without_current,
        "previous_loaded": previous_loaded,
        "current_loaded": current_loaded,
    }
    return {
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
        "by_title": by_title,
        "meta": meta,
    }


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


def format_platform_item(item: dict, prefix: str = "-") -> list[str]:
    title = platform_title(item)
    provider = platform_provider(item)
    region = platform_region(item)
    typ = platform_type(item)
    source = platform_source(item)
    url = platform_url(item)
    vip = item.get("_vip_url") or vip_url(title)

    head = f"{prefix} {title} — {provider}"
    details = []
    if region:
        details.append(region)
    if typ:
        details.append(typ)
    if source:
        details.append(source)
    if details:
        head += " — " + " / ".join(details)
    lines = [head]
    if url:
        lines.append(f"  Fuente: {url}")
    if vip:
        lines.append(f"  Ver en VIP: {vip}")
    return lines


def serialize_platform_item(item: dict) -> dict:
    return {
        "title": platform_title(item),
        "provider": platform_provider(item),
        "region": platform_region(item),
        "type": platform_type(item),
        "source": platform_source(item),
        "url": platform_url(item),
        "vip_url": item.get("_vip_url") or vip_url(platform_title(item)),
    }


def build_compact_mail_body(changed: list[str]) -> tuple[str, str, int, dict]:
    future, historic, tv_meta = collect_tv_items()
    platform_delta = collect_platform_delta()
    added = platform_delta["added"]
    removed = platform_delta["removed"]
    meta = platform_delta["meta"]
    platform_change_count = int(platform_delta["added_count"]) + int(platform_delta["removed_count"])
    now = datetime.now(TZ)

    if platform_change_count:
        subject = f"DDV Radar — Plataformas: +{len(added)} / -{len(removed)} cambios"
        status = "Hay cambios reales de disponibilidad en plataformas. Revisar altas y bajas."
    elif future:
        subject = f"DDV Radar — {len(future)} emisión(es) futura(s) TV/Cable"
        status = "Hay emisiones futuras o dentro de ventana de aviso. Revisar y accionar si corresponde."
    elif historic:
        subject = f"DDV Radar — sin futuras; {len(historic)} registro(s) histórico(s)"
        status = "No hay emisiones futuras nuevas. Se actualizaron registros históricos o archivos de estado."
    else:
        subject = "DDV Radar — sin cambios accionables"
        status = "No hay emisiones futuras ni cambios reales de plataformas."

    lines: list[str] = [
        "Radar DDV — TV/Cable/Plataformas",
        "",
        "RESUMEN EJECUTIVO",
        status,
        f"Control: {now.strftime('%d/%m/%Y %H:%M')} ({TZ_NAME})",
        "",
        "1. PLATAFORMAS — CAMBIOS REALES",
    ]

    if platform_change_count:
        lines.append(f"Resumen: {len(added)} nueva(s) disponibilidad(es), {len(removed)} baja(s).")
        if platform_delta["by_title"]:
            lines.append("Por película:")
            for title, counts in sorted(platform_delta["by_title"].items(), key=lambda kv: kv[0].lower())[:MAX_PLATFORM_SUMMARY]:
                lines.append(f"- {title}: +{counts.get('added', 0)} / -{counts.get('removed', 0)}")
        if added:
            lines += ["", "NUEVAS DISPONIBILIDADES"]
            for item in added[:MAX_PLATFORM_ITEMS]:
                lines.extend(format_platform_item(item, "+"))
        if removed:
            lines += ["", "DISPONIBILIDADES REMOVIDAS"]
            for item in removed[:MAX_PLATFORM_ITEMS]:
                lines.extend(format_platform_item(item, "-") )
        if len(added) > MAX_PLATFORM_ITEMS or len(removed) > MAX_PLATFORM_ITEMS:
            lines.append("")
            lines.append("Nota: hay más cambios que no se listan en el mail para evitar ruido. Revisar artifact.")
    else:
        lines.append("No se detectaron altas o bajas reales de plataformas. Si cambió state_platforms_seen.json, fue actualización técnica/metadatos.")

    lines += ["", "Estado actual de plataformas"]
    source = meta.get("source") or "Fuente no indicada"
    version = meta.get("version") or "versión no indicada"
    lines.append(f"Fuente: {source}")
    lines.append(f"Versión: {version}")
    if meta.get("titles_with_current") is not None:
        lines.append(f"Títulos con disponibilidad actual: {meta.get('titles_with_current')}")
        lines.append(f"Títulos sin disponibilidad actual: {meta.get('titles_without_current')}")

    lines += ["", "2. TV/CABLE — EMISIONES FUTURAS / ACCIONABLES"]
    if future:
        for item in future[:MAX_TV_ITEMS]:
            lines.extend(format_event(item))
            lines.append("  Estado: FUTURA / ALERTABLE")
            lines.append("")
        lines.append("Acción sugerida: verificar fuente, difundir o registrar según corresponda.")
    else:
        lines.append("No se detectaron nuevas emisiones futuras dentro de la ventana revisada.")

    lines += ["", "3. TV/CABLE — REGISTROS HISTÓRICOS O YA PASADOS"]
    if historic:
        for item in historic[:MAX_TV_ITEMS]:
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

    lines += ["", "4. CAMBIOS TÉCNICOS"]
    if changed:
        lines.append("Archivos de estado modificados:")
        lines.extend([f"- {x}" for x in changed[:8]])
    else:
        lines.append("No se modificaron archivos de estado monitoreados.")

    lines += [
        "",
        "CRITERIO",
        "- PLATAFORMAS +: nueva disponibilidad detectada.",
        "- PLATAFORMAS -: disponibilidad que dejó de aparecer en las fuentes.",
        "- FUTURA / ALERTABLE: puede requerir difusión o seguimiento.",
        "- HISTÓRICA / YA PASADA: antecedente; no es urgencia.",
        "- TÉCNICO: cambio interno del radar; no implica por sí solo una disponibilidad nueva.",
    ]

    info = {
        "future_count": len(future),
        "historic_count": len(historic),
        "platform_added_count": len(added),
        "platform_removed_count": len(removed),
        "platform_change_count": platform_change_count,
        "platform_added_sample": [serialize_platform_item(x) for x in added[:30]],
        "platform_removed_sample": [serialize_platform_item(x) for x in removed[:30]],
        "platform_meta": meta,
        "changed_files": changed,
        "mail_format": "platforms_pro_v6",
        "tv_meta": tv_meta,
    }
    # count representa hallazgos relevantes, no líneas técnicas.
    count = len(future) + len(historic) + platform_change_count
    return subject, "\n".join(lines).strip() + "\n", count, info


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
            "mode": "tv_platform_changes_platforms_pro_v6",
            "subject": subject,
            "body": body,
            "alerts_count": count,
            "source": "github-actions-ddv-radar-cambios-site-mail-v6-platforms-pro",
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
            "User-Agent": "Mozilla/5.0 (compatible; DDV-Radar/6.0; +https://danieldelavega.com.ar)",
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
        "version": "DDV_TV_CAMBIOS_MAIL_SITE_V6_PLATAFORMAS_PRO",
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

    print("--- CUERPO DEL MAIL PLATAFORMAS PRO ---")
    print(body)

    if not ok:
        future_count = int(extra.get("future_count") or 0)
        platform_change_count = int(extra.get("platform_change_count") or 0)
        if endpoint_meta.get("mail_blocked_by_security_challenge") and future_count == 0 and platform_change_count == 0:
            print("AVISO: el hosting bloqueó el POST con verificación anti-bot/WAF, pero no hay emisiones futuras ni cambios reales de plataformas.")
            print("El workflow queda verde para no generar falso rojo por históricos/técnicos. Revisar artifact para detalle.")
            return 0
        print("ERROR: el sitio no confirmó mail_sent=true. Si hay futuras o cambios reales de plataformas, falla para no ocultar el problema.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
