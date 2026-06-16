#!/usr/bin/env python3
# DDV TV Alertas Diarias v5 — mail garantizable vía endpoint del sitio.
# Regla: avisar emisiones futuras dentro de la ventana configurada.
# Si hay alerta y el sitio no devuelve mail_sent=true, el workflow falla.

from __future__ import annotations

import json
import os
import re
import hashlib
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, date, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

MOVIES = {
    "sueno profundo": "Sueño Profundo", "sueño profundo": "Sueño Profundo",
    "la ultima cena": "La Última Cena", "la última cena": "La Última Cena",
    "el martillo": "El Martillo",
    "jennifers shadow": "Jennifer's Shadow", "jennifer's shadow": "Jennifer's Shadow", "chronicle of the raven": "Jennifer's Shadow",
    "death knows your name": "Death Knows Your Name", "la muerte conoce tu nombre": "Death Knows Your Name",
    "hermanos de sangre": "Hermanos de Sangre", "necrofobia": "Necrofobia",
    "ataud blanco": "Ataúd Blanco", "ataúd blanco": "Ataúd Blanco",
    "punto muerto": "Punto Muerto", "el ultimo hereje": "El Último Hereje", "el último hereje": "El Último Hereje",
    "los ojos del abismo": "Los Ojos del Abismo",
    "al 3er dia": "Al 3er Día", "al 3er día": "Al 3er Día", "al tercer dia": "Al 3er Día", "al tercer día": "Al 3er Día",
}
DATE_PATTERNS = [
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
    re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4})\b"),
]
TIME_RE = re.compile(r"\b(?P<h>\d{1,2}):(?P<mi>\d{2})\b")
INPUT_FILES = [
    Path("outputs/site_tv_cable_global.json"),
    Path("outputs/site_tv_cable_global_filtered.json"),
    Path("outputs/site_tv_cable_review.json"),
]

def norm(s: object) -> str:
    text = str(s or "").lower().replace("’", "'").replace("´", "'").replace("`", "'")
    return text.translate(str.maketrans("áéíóúüñ", "aeiouun"))

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

def walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_dicts(item)

def flat_text(d: dict) -> str:
    parts = []
    def walk(x):
        if isinstance(x, dict):
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
        elif x is not None:
            parts.append(str(x))
    walk(d)
    return " | ".join(parts)

def find_movie(text: str) -> str | None:
    n = norm(text)
    for key, canonical in MOVIES.items():
        if norm(key) in n:
            return canonical
    return None

def parse_date(value: object) -> date | None:
    s = str(value or "")
    for rx in DATE_PATTERNS:
        m = rx.search(s)
        if not m: continue
        try:
            return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        except ValueError:
            return None
    return None

def parse_time(value: object) -> str | None:
    m = TIME_RE.search(str(value or ""))
    if not m: return None
    h, mi = int(m.group("h")), int(m.group("mi"))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return f"{h:02d}:{mi:02d}"
    return None

def first_key(d: dict, keys: list[str]) -> object:
    wanted = {k.lower() for k in keys}
    for k, v in d.items():
        if str(k).lower() in wanted and v not in (None, ""):
            return v
    return None

@dataclass
class Event:
    movie: str
    date: str
    time: str
    channel: str
    country: str
    source: str
    url: str
    raw_title: str
    key: str
    input_file: str
    def local_datetime(self, tz: ZoneInfo) -> datetime:
        hh, mm = [int(x) for x in self.time.split(":")]
        return datetime.combine(date.fromisoformat(self.date), time(hh, mm), tzinfo=tz)

def event_from_dict(d: dict, input_file: str) -> Event | None:
    text = flat_text(d)
    movie = find_movie(text)
    if not movie: return None
    dt = None
    for k in ["date_iso", "date", "fecha", "air_date", "start_date", "datetime", "start", "starts_at", "program_date"]:
        if k in d:
            dt = parse_date(d.get(k))
            if dt: break
    if not dt: dt = parse_date(text)
    if not dt: return None
    hhmm = None
    for k in ["start_time", "time", "hora", "air_time", "datetime", "start", "starts_at"]:
        if k in d:
            hhmm = parse_time(d.get(k))
            if hhmm: break
    if not hhmm: hhmm = parse_time(text) or "00:00"
    channel = first_key(d, ["channel", "canal", "network", "provider", "source_name"]) or ""
    country = first_key(d, ["country_name", "country", "pais", "país", "region", "country_code"]) or ""
    source = first_key(d, ["source", "fuente", "source_label", "origin", "detection_type"]) or ""
    url = first_key(d, ["source_url", "url", "link", "href"]) or ""
    raw_title = first_key(d, ["programme_title", "title", "titulo", "título", "name", "program"]) or movie
    if not channel:
        n = norm(text)
        channel = "Canal á" if ("canal a" in n or "canal á" in n) else ("CINE.AR" if ("cine.ar" in n or "cinear" in n) else "TV / Cable")
    fingerprint = str(first_key(d, ["fingerprint", "id", "key"]) or "")
    key = fingerprint or hashlib.sha1("|".join([movie, dt.isoformat(), hhmm, str(channel), str(country), str(source), str(url)]).encode("utf-8")).hexdigest()[:20]
    return Event(movie, dt.isoformat(), hhmm, str(channel), str(country), str(source), str(url), str(raw_title), key, input_file)

def collect_events() -> tuple[list[Event], list[str]]:
    events: dict[str, Event] = {}
    loaded = []
    for path in INPUT_FILES:
        if not path.exists(): continue
        loaded.append(str(path))
        data = load_json(path)
        for d in walk_dicts(data):
            ev = event_from_dict(d, str(path))
            if ev: events[ev.key] = ev
    return sorted(events.values(), key=lambda e: (e.date, e.time, e.movie, e.channel)), loaded

def post_site_mail(subject: str, body: str, alerts: list[Event], mode: str) -> bool:
    url = os.getenv("DDV_TV_ALERT_MAIL_URL", "").strip()
    if not url:
        print("ERROR: falta DDV_TV_ALERT_MAIL_URL. No hay canal de mail garantizado.")
        return False
    payload = json.dumps({
        "mode": mode,
        "subject": subject,
        "body": body,
        "alerts_count": len(alerts),
        "alerts": [asdict(e) for e in alerts],
        "source": "github-actions-ddv-tv-alertas-diarias-v5",
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json; charset=UTF-8", "User-Agent": "ddv-tv-alertas-diarias-v5"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8", "replace")
            print(raw)
            data = json.loads(raw)
            return bool(data.get("mail_sent") is True)
    except Exception as e:
        print(f"ERROR al llamar endpoint de mail del sitio: {e}")
        return False

def main() -> int:
    tz_name = os.getenv("DDV_TV_ALERT_TIMEZONE", "America/Argentina/Buenos_Aires")
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    lookahead_hours = int(os.getenv("DDV_TV_ALERT_LOOKAHEAD_HOURS", "36") or "36")
    grace_minutes = int(os.getenv("DDV_TV_ALERT_PAST_GRACE_MINUTES", "30") or "30")
    window_start = now - timedelta(minutes=grace_minutes)
    window_end = now + timedelta(hours=lookahead_hours)
    state_path = Path("outputs/state_tv_daily_alerts_sent.json")
    last_run_path = Path("outputs/tv_daily_alert_last_run.json")
    state = load_json(state_path) if state_path.exists() else {"sent": {}}
    sent = state.setdefault("sent", {})
    events, loaded_files = collect_events()
    due = [e for e in events if window_start <= e.local_datetime(tz) <= window_end]
    unsent = [e for e in due if e.key not in sent]
    run_info = {
        "version": "DDV_TV_ALERTAS_DIARIAS_V6_MAIL_DESDE_SITIO_FINAL",
        "ran_at": now.isoformat(), "timezone": tz_name,
        "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
        "lookahead_hours": lookahead_hours, "past_grace_minutes": grace_minutes,
        "input_files_loaded": loaded_files, "events_total": len(events), "events_due": len(due), "events_unsent": len(unsent),
        "mail_sent": False, "unsent": [asdict(e) for e in unsent],
    }
    if os.getenv("DDV_TV_ALERT_FORCE_TEST", "").strip() == "1":
        body = (
            "Prueba final desde GitHub hacia el endpoint de mail del sitio.\n\n"
            "Si recibiste este mail, quedó conectado:\n"
            "GitHub Actions → danieldelavega.com.ar → mail a furiafilms@gmail.com.\n"
        )
        ok = post_site_mail("DDV TV/Cable — prueba final desde GitHub", body, [], "github_final_connection_test")
        run_info["mode"] = "force_test_mail"
        run_info["mail_sent"] = ok
        save_json(last_run_path, run_info)
        return 0 if ok else 1
    if not unsent:
        print("Sin emisiones futuras nuevas para avisar en la ventana configurada.")
        save_json(last_run_path, run_info)
        return 0
    lines = [
        "Alerta DDV — próximas emisiones TV/Cable", "",
        f"Control: {now.strftime('%d/%m/%Y %H:%M')} ({tz_name})",
        f"Ventana revisada: {window_start.strftime('%d/%m/%Y %H:%M')} a {window_end.strftime('%d/%m/%Y %H:%M')}", "",
    ]
    for e in unsent:
        local_dt = e.local_datetime(tz)
        lines.append(f"- {local_dt.strftime('%d/%m/%Y %H:%M')} — {e.movie} — {e.channel}".strip())
        if e.country: lines.append(f"  País/región: {e.country}")
        if e.source: lines.append(f"  Fuente: {e.source}")
        if e.url: lines.append(f"  Link: {e.url}")
        lines.append("")
    body = "\n".join(lines).strip() + "\n"
    subject = f"DDV TV/Cable — {len(unsent)} próxima(s) emisión(es)"
    mail_ok = post_site_mail(subject, body, unsent, "tv_daily_upcoming")
    run_info["mail_sent"] = mail_ok
    if not mail_ok:
        run_info["error"] = "El sitio no confirmó mail_sent=true. No se marca como avisado."
        save_json(last_run_path, run_info)
        print(run_info["error"])
        return 1
    for e in unsent:
        sent[e.key] = {"sent_at": now.isoformat(), "event": asdict(e), "mail_sent": True}
    save_json(state_path, state)
    save_json(last_run_path, run_info)
    print(body)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
