#!/usr/bin/env python3
# DDV TV Alertas Diarias v1
# Lee outputs/site_tv_cable_global_filtered.json y avisa por mail las emisiones del día.
# Si faltan secrets SMTP, crea issue en GitHub como respaldo.

from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import sys
import hashlib
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

MOVIES = {
    "sueno profundo": "Sueño Profundo",
    "sueño profundo": "Sueño Profundo",
    "la ultima cena": "La Última Cena",
    "la última cena": "La Última Cena",
    "el martillo": "El Martillo",
    "jennifers shadow": "Jennifer's Shadow",
    "jennifer's shadow": "Jennifer's Shadow",
    "chronicle of the raven": "Jennifer's Shadow",
    "death knows your name": "Death Knows Your Name",
    "la muerte conoce tu nombre": "Death Knows Your Name",
    "hermanos de sangre": "Hermanos de Sangre",
    "necrofobia": "Necrofobia",
    "ataud blanco": "Ataúd Blanco",
    "ataúd blanco": "Ataúd Blanco",
    "punto muerto": "Punto Muerto",
    "el ultimo hereje": "El Último Hereje",
    "el último hereje": "El Último Hereje",
    "los ojos del abismo": "Los Ojos del Abismo",
    "al 3er dia": "Al 3er Día",
    "al 3er día": "Al 3er Día",
    "al tercer dia": "Al 3er Día",
    "al tercer día": "Al 3er Día",
}

DATE_PATTERNS = [
    re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4})\b"),
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
]
TIME_RE = re.compile(r"\b(?P<h>\d{1,2}):(?P<mi>\d{2})\b")


def norm(s: object) -> str:
    text = str(s or "").lower()
    text = text.replace("’", "'").replace("´", "'").replace("`", "'")
    return text.translate(str.maketrans("áéíóúüñ", "aeiouun"))


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}")
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
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
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
        if not m:
            continue
        y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def parse_time(value: object) -> str | None:
    s = str(value or "")
    m = TIME_RE.search(s)
    if not m:
        return None
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


def event_from_dict(d: dict) -> Event | None:
    text = flat_text(d)
    movie = find_movie(text)
    if not movie:
        return None

    dt = None
    for k in ["date", "fecha", "air_date", "start_date", "datetime", "start", "starts_at", "program_date"]:
        if k in d:
            dt = parse_date(d.get(k))
            if dt:
                break
    if not dt:
        dt = parse_date(text)
    if not dt:
        return None

    hhmm = None
    for k in ["time", "hora", "air_time", "start_time", "datetime", "start", "starts_at"]:
        if k in d:
            hhmm = parse_time(d.get(k))
            if hhmm:
                break
    if not hhmm:
        hhmm = parse_time(text) or "00:00"

    channel = first_key(d, ["channel", "canal", "network", "provider", "source_name"]) or ""
    country = first_key(d, ["country", "pais", "país", "region"]) or ""
    source = first_key(d, ["source", "fuente", "source_label", "origin"]) or ""
    url = first_key(d, ["url", "source_url", "link", "href"]) or ""
    raw_title = first_key(d, ["title", "titulo", "título", "name", "program"]) or movie

    if not channel:
        n = norm(text)
        if "canal a" in n:
            channel = "Canal A"
        elif "cine ar" in n or "cine.ar" in n or "cinear" in n:
            channel = "CINE.AR"
        else:
            channel = "TV / Cable"

    key_raw = "|".join([movie, dt.isoformat(), hhmm, str(channel), str(country), str(source), str(url)])
    key = hashlib.sha1(key_raw.encode("utf-8")).hexdigest()[:20]

    return Event(movie, dt.isoformat(), hhmm, str(channel), str(country), str(source), str(url), str(raw_title), key)


def collect_events(data) -> list[Event]:
    events: dict[str, Event] = {}
    for d in walk_dicts(data):
        ev = event_from_dict(d)
        if ev:
            events[ev.key] = ev
    return sorted(events.values(), key=lambda e: (e.date, e.time, e.movie, e.channel))


def send_mail(subject: str, body: str) -> bool:
    host = os.getenv("DDV_ALERT_SMTP_HOST", "").strip()
    port = int(os.getenv("DDV_ALERT_SMTP_PORT", "587").strip() or "587")
    user = os.getenv("DDV_ALERT_SMTP_USER", "").strip()
    password = os.getenv("DDV_ALERT_SMTP_PASS", "").strip()
    mail_from = os.getenv("DDV_ALERT_MAIL_FROM", "").strip() or user
    mail_to = os.getenv("DDV_ALERT_MAIL_TO", "").strip()

    if not (host and user and password and mail_from and mail_to):
        print("MAIL: faltan secrets SMTP; no se envía mail.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.set_content(body)

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
    print(f"MAIL: enviado a {mail_to}.")
    return True


def create_issue(subject: str, body: str) -> bool:
    if os.getenv("CREATE_ISSUES", "0") != "1":
        return False
    token = os.getenv("GITHUB_TOKEN", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("ISSUE: faltan GITHUB_TOKEN/GITHUB_REPOSITORY.")
        return False

    url = f"https://api.github.com/repos/{repo}/issues"
    payload = json.dumps({"title": subject, "body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ddv-tv-alertas-diarias",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        print(f"ISSUE: creado, HTTP {resp.status}.")
    return True


def main() -> int:
    tz_name = os.getenv("DDV_TV_ALERT_TIMEZONE", "America/Argentina/Buenos_Aires")
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    today = now.date()
    days_ahead = int(os.getenv("DDV_TV_ALERT_DAYS_AHEAD", "0") or "0")
    target_dates = {today + timedelta(days=i) for i in range(days_ahead + 1)}

    data_path = Path("outputs/site_tv_cable_global_filtered.json")
    state_path = Path("outputs/state_tv_daily_alerts_sent.json")
    last_run_path = Path("outputs/tv_daily_alert_last_run.json")

    data = load_json(data_path)
    state = load_json(state_path) if state_path.exists() else {"sent": {}}
    sent = state.setdefault("sent", {})

    events = collect_events(data)
    due = [e for e in events if date.fromisoformat(e.date) in target_dates]
    unsent = [e for e in due if e.key not in sent]

    run_info = {
        "version": "DDV_TV_ALERTAS_DIARIAS_V1",
        "ran_at": now.isoformat(),
        "timezone": tz_name,
        "target_dates": sorted(d.isoformat() for d in target_dates),
        "events_total": len(events),
        "events_due": len(due),
        "events_unsent": len(unsent),
        "mail_sent": False,
        "issue_created": False,
        "unsent": [asdict(e) for e in unsent],
    }

    if not unsent:
        print("Sin emisiones nuevas para avisar hoy.")
        save_json(last_run_path, run_info)
        return 0

    lines = [
        "Alerta diaria DDV — emisiones TV/Cable",
        "",
        f"Fecha de control: {today.strftime('%d/%m/%Y')}",
        "",
    ]
    for e in unsent:
        d = date.fromisoformat(e.date).strftime("%d/%m/%Y")
        lines.append(f"- {d} {e.time} — {e.movie} — {e.channel}".strip())
        if e.country:
            lines.append(f"  País/región: {e.country}")
        if e.source:
            lines.append(f"  Fuente: {e.source}")
        if e.url:
            lines.append(f"  Link: {e.url}")
        lines.append("")
    body = "\n".join(lines).strip() + "\n"
    subject = f"DDV TV/Cable — {len(unsent)} emisión(es) para avisar"

    mail_ok = send_mail(subject, body)
    issue_ok = False
    if not mail_ok:
        issue_ok = create_issue(subject, body)

    if not mail_ok and not issue_ok:
        run_info["error"] = "No se pudo notificar: faltan secrets SMTP y no se creó issue."
        save_json(last_run_path, run_info)
        print(run_info["error"])
        return 1

    for e in unsent:
        sent[e.key] = {
            "sent_at": now.isoformat(),
            "event": asdict(e),
            "mail_sent": mail_ok,
            "issue_created": issue_ok,
        }

    run_info["mail_sent"] = mail_ok
    run_info["issue_created"] = issue_ok
    save_json(state_path, state)
    save_json(last_run_path, run_info)

    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
