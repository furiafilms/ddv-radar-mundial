#!/usr/bin/env python3
# DDV TV/Plataformas Cambios v1 — avisa por mail del sitio si el radar agregó cambios reales.
# Se ejecuta inmediatamente después de scripts/ddv_radar_cambios.py, antes del reset/commit.

from __future__ import annotations
import json, os, subprocess, urllib.request
from pathlib import Path
from datetime import datetime

WATCH_STATE_FILES = [
    "outputs/state_tv_seen.json",
    "outputs/state_platforms_seen.json",
]
WATCH_SITE_FILES = [
    "outputs/site_tv_cable_global_filtered.json",
    "outputs/site_platforms_global.json",
]

def changed_files() -> list[str]:
    cmd = ["git", "diff", "--name-only", "--"] + WATCH_STATE_FILES
    out = subprocess.check_output(cmd, text=True).strip()
    return [x for x in out.splitlines() if x.strip()]

def git_stat(paths: list[str]) -> str:
    if not paths: return ""
    cmd = ["git", "diff", "--stat", "--"] + paths
    return subprocess.check_output(cmd, text=True).strip()

def read_json_summary(path: str) -> str:
    p = Path(path)
    if not p.exists(): return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    parts = []
    for key in ["generated_at_utc", "hits_total", "review_total", "source", "version"]:
        if key in data:
            parts.append(f"{key}: {data.get(key)}")
    if isinstance(data.get("hits"), list):
        for item in data["hits"][:8]:
            title = item.get("work_title") or item.get("title") or item.get("programme_title") or ""
            channel = item.get("channel") or item.get("provider") or ""
            date = item.get("date_iso") or item.get("date") or ""
            time = item.get("start_time") or item.get("time") or ""
            if title or channel:
                parts.append(f"- {date} {time} · {title} · {channel}".strip())
    return "\n".join(parts)

def post_site(subject: str, body: str, count: int) -> bool:
    url = os.getenv("DDV_TV_ALERT_MAIL_URL", "").strip()
    if not url:
        print("ERROR: falta DDV_TV_ALERT_MAIL_URL. No hay mail garantizado.")
        return False
    payload = json.dumps({
        "mode": "tv_platform_changes",
        "subject": subject,
        "body": body,
        "alerts_count": count,
        "source": "github-actions-ddv-radar-cambios-site-mail-v1",
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type":"application/json; charset=UTF-8", "User-Agent":"ddv-radar-cambios-site-mail-v1"})
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
    changed = changed_files()
    last_run_path = Path("outputs/tv_platform_change_mail_last_run.json")
    if not changed:
        info = {"version":"DDV_TV_CAMBIOS_MAIL_SITE_V1", "ran_at": datetime.utcnow().isoformat()+"Z", "changes_detected": False, "mail_sent": False}
        last_run_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Sin cambios nuevos en state_tv_seen/state_platforms_seen. No se manda mail.")
        return 0
    stat = git_stat(WATCH_STATE_FILES + WATCH_SITE_FILES)
    sections = [
        "Alerta DDV — cambios detectados en radar TV/Cable/Plataformas", "",
        "El radar detectó cambios reales en archivos de estado.", "",
        "Archivos de estado modificados:",
    ]
    sections += [f"- {x}" for x in changed]
    if stat:
        sections += ["", "Resumen técnico:", stat]
    for p in WATCH_SITE_FILES:
        s = read_json_summary(p)
        if s:
            sections += ["", f"Resumen de {p}:", s]
    body = "\n".join(sections).strip() + "\n"
    subject = "DDV Radar — cambios en TV/Cable/Plataformas"
    ok = post_site(subject, body, len(changed))
    info = {"version":"DDV_TV_CAMBIOS_MAIL_SITE_V1", "ran_at": datetime.utcnow().isoformat()+"Z", "changes_detected": True, "changed_files": changed, "mail_sent": ok}
    last_run_path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    if not ok:
        print("ERROR: el sitio no confirmó mail_sent=true. Falla el workflow para no ocultar el problema.")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
