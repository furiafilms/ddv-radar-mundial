#!/usr/bin/env python3
# DDV TV Alertas Diarias v8 NO_COMMIT_LASTRUN — no falla por commitear resumen sin alertas.
# Mantiene envío por endpoint del sitio cuando hay alertas reales o force_test.

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, date, time
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "DDV_TV_ALERTAS_DIARIAS_V8_NO_COMMIT_LASTRUN"

TZ_NAME = os.getenv("DDV_TV_ALERT_TIMEZONE", "America/Argentina/Buenos_Aires")
TZ = ZoneInfo(TZ_NAME)
LOOKAHEAD_HOURS = int(os.getenv("DDV_TV_ALERT_LOOKAHEAD_HOURS", "36") or "36")
PAST_GRACE_MINUTES = int(os.getenv("DDV_TV_ALERT_PAST_GRACE_MINUTES", "30") or "30")
MAIL_URL = (os.getenv("DDV_TV_ALERT_MAIL_URL") or "").strip()
FORCE_TEST = str(os.getenv("DDV_TV_ALERT_FORCE_TEST") or os.getenv("FORCE_TEST_MAIL") or os.getenv("INPUT_FORCE_TEST_MAIL") or "").strip().lower() in {"1", "true", "yes", "y", "si", "sí"}

INPUT_FILES = [
    "outputs/site_tv_cable_global.json",
    "outputs/site_tv_cable_global_filtered.json",
]
STATE_FILE = Path("outputs/state_tv_daily_alerts_sent.json")
LAST_RUN_FILE = Path("outputs/tv_daily_alert_last_run.json")

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
    "Soy Tóxico": "soy-toxico",
}


def read_json(path: str | Path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"No pude leer {p}: {exc}")
        return None


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_hits(data) -> list[dict]:
    if isinstance(data, dict):
        for key in ("hits", "items", "events", "results", "tv_cable"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def title_of(item: dict) -> str:
    return str(item.get("title") or item.get("work_title") or item.get("movie") or item.get("programme_title") or item.get("raw_title") or "Título no identificado").strip()


def channel_of(item: dict) -> str:
    return str(item.get("channel") or item.get("platform") or item.get("source_name") or "Canal no identificado").strip()


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


def parse_time(value) -> time:
    text = str(value or "").strip().replace("–", "-").split("-")[0].strip()
    if not text:
        return time(0, 0)
    try:
        hh, mm = text[:5].split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return time(h, m)
    except Exception:
        pass
    return time(0, 0)


def event_datetime(item: dict) -> datetime | None:
    d = parse_date(item.get("date_iso") or item.get("date") or item.get("air_date"))
    if not d:
        return None
    t = parse_time(item.get("start_time") or item.get("time") or item.get("hour"))
    return datetime.combine(d, t, tzinfo=TZ)


def event_key(item: dict) -> str:
    dt = event_datetime(item)
    date_part = dt.strftime("%Y-%m-%dT%H:%M") if dt else str(item.get("date_iso") or item.get("date") or "sin-fecha")
    return "|".join([
        str(item.get("slug") or item.get("id") or MOVIE_IDS.get(title_of(item), title_of(item))).strip().lower(),
        title_of(item).strip().lower(),
        channel_of(item).strip().lower(),
        date_part,
    ])


def load_sent_keys() -> set[str]:
    data = read_json(STATE_FILE)
    if isinstance(data, dict):
        for key in ("sent_keys", "sent", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return {str(x) for x in value}
        # Formato mapa key:true
        return {str(k) for k, v in data.items() if v is True}
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def save_sent_keys(keys: set[str]) -> None:
    write_json(STATE_FILE, {
        "version": VERSION,
        "updated_at": datetime.now(TZ).isoformat(),
        "sent_keys": sorted(keys),
    })


def vip_url(item: dict) -> str:
    slug = str(item.get("slug") or item.get("id") or MOVIE_IDS.get(title_of(item), "")).strip()
    return f"https://danieldelavega.com.ar/vip/pelicula.php?id={slug}" if slug else "https://danieldelavega.com.ar/vip/"


def source_line(item: dict) -> str:
    src = str(item.get("source") or item.get("source_label") or "Fuente no informada").strip()
    url = str(item.get("source_url") or "").strip()
    return f"{src} — {url}" if url else src


def format_event(item: dict) -> str:
    dt = event_datetime(item)
    dt_text = dt.strftime("%d/%m/%Y %H:%M") if dt else "fecha/hora no identificada"
    end_time = str(item.get("end_time") or "").strip()
    if end_time:
        dt_text += f"–{end_time}"
    return "\n".join([
        f"- {title_of(item)} — {channel_of(item)} — {dt_text}",
        f"  Fuente: {source_line(item)}",
        f"  Ver en VIP: {vip_url(item)}",
    ])


def post_mail(subject: str, body: str, mode: str, alerts_count: int) -> tuple[bool, dict | str]:
    if not MAIL_URL:
        return False, "Falta secret DDV_TV_ALERT_MAIL_URL"
    payload = json.dumps({
        "subject": subject,
        "body": body,
        "mode": mode,
        "alerts_count": alerts_count,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        MAIL_URL,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "DDV-GitHub-Actions-TV-Alertas/7.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
            except Exception:
                return False, raw[:500]
            return bool(data.get("ok") or data.get("mail_sent")), data
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    now = datetime.now(TZ)
    window_start = now.replace() - __import__("datetime").timedelta(minutes=PAST_GRACE_MINUTES)
    window_end = now + __import__("datetime").timedelta(hours=LOOKAHEAD_HOURS)

    loaded = []
    all_events: list[dict] = []
    seen_keys_for_loaded = set()
    for path in INPUT_FILES:
        data = read_json(path)
        if data is None:
            continue
        loaded.append(path)
        for item in get_hits(data):
            key = event_key(item)
            if key in seen_keys_for_loaded:
                continue
            seen_keys_for_loaded.add(key)
            all_events.append(item)

    sent_keys = load_sent_keys()
    due: list[dict] = []
    for item in all_events:
        dt = event_datetime(item)
        if not dt:
            continue
        if window_start <= dt <= window_end and event_key(item) not in sent_keys:
            due.append(item)

    mail_sent = False
    endpoint_response = None
    mode = "force_test_mail" if FORCE_TEST else "daily_tv_alert"
    exit_code = 0

    if FORCE_TEST:
        subject = "DDV TV/Cable — prueba final desde GitHub"
        body = "Prueba final del workflow DDV TV Alertas Diarias.\n\nEl endpoint del sitio respondió al llamado de GitHub Actions.\n"
        mail_sent, endpoint_response = post_mail(subject, body, mode, 1)
        exit_code = 0 if mail_sent else 1
    elif due:
        subject = f"DDV TV/Cable — {len(due)} emisión(es) futura(s) detectada(s)"
        body = "Radar DDV — TV/Cable\n\nEMISIONES FUTURAS / ACCIONABLES\n\n"
        body += "\n\n".join(format_event(x) for x in due)
        body += "\n\nCRITERIO\nEste mail solo se envía cuando hay emisiones futuras dentro de la ventana revisada.\n"
        mail_sent, endpoint_response = post_mail(subject, body, mode, len(due))
        if mail_sent:
            for item in due:
                sent_keys.add(event_key(item))
            save_sent_keys(sent_keys)
            exit_code = 0
        else:
            exit_code = 1
    else:
        # Punto central del parche V7:
        # no hay nada para avisar, por lo tanto NO mandar mail y NO fallar el workflow.
        mail_sent = False
        endpoint_response = "Sin emisiones futuras; no corresponde enviar mail."
        exit_code = 0

    summary = {
        "version": VERSION,
        "ran_at": now.isoformat(),
        "timezone": TZ_NAME,
        "lookahead_hours": LOOKAHEAD_HOURS,
        "past_grace_minutes": PAST_GRACE_MINUTES,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "input_files_loaded": loaded,
        "events_total": len(all_events),
        "events_due": len(due),
        "events_unsent": 0 if mail_sent or not due else len(due),
        "unsent": [] if mail_sent or not due else [format_event(x) for x in due],
        "mail_sent": mail_sent,
        "mode": mode if FORCE_TEST else "normal",
        "endpoint_response": endpoint_response,
        "no_events_is_success": True,
    }
    write_json(LAST_RUN_FILE, summary)

    if not due and not FORCE_TEST:
        print("Sin emisiones futuras en la ventana revisada. Workflow OK sin enviar mail.")
    elif mail_sent:
        print("Mail enviado correctamente.")
    else:
        print("No se pudo enviar mail cuando correspondía.")
        print(endpoint_response)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
