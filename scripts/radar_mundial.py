#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DDV Radar Mundial — v001
Busca títulos de Daniel de la Vega en EPG abiertas por país.
Primera versión: no toca Neolo, no usa FTP, no usa claves externas.
Si encuentra coincidencias nuevas, crea un Issue en GitHub.
"""
from __future__ import annotations
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "catalogo.json"
SOURCES_PATH = ROOT / "data" / "sources.json"
OUTPUTS_DIR = ROOT / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)

USER_AGENT = "DDV-Radar-Mundial/0.1 (+https://danieldelavega.com.ar)"
ISSUE_LABEL = "radar-tv-hit"


def norm(s: str) -> str:
    s = s or ""
    repl = {
        "á":"a", "é":"e", "í":"i", "ó":"o", "ú":"u", "ü":"u", "ñ":"n",
        "Á":"a", "É":"e", "Í":"i", "Ó":"o", "Ú":"u", "Ü":"u", "Ñ":"n",
        "’":"'", "“":'"', "”":'"'
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def safe_text(elem: Optional[ET.Element]) -> str:
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def parse_xmltv_time(value: str) -> str:
    if not value:
        return ""
    m = re.match(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", value)
    if not m:
        return value
    y, mo, d, h, mi, sec = m.groups()
    return f"{y}-{mo}-{d} {h}:{mi}:{sec}"


def download_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def iter_xmltv_programmes(xml_bytes: bytes):
    if xml_bytes[:2] == b"\x1f\x8b":
        xml_bytes = gzip.decompress(xml_bytes)
    channel_names: dict[str, str] = {}
    f = io.BytesIO(xml_bytes)
    context = ET.iterparse(f, events=("end",))
    for _, elem in context:
        tag = elem.tag.split("}")[-1]
        if tag == "channel":
            cid = elem.attrib.get("id", "")
            names = [safe_text(x) for x in elem.findall("./display-name")]
            names = [x for x in names if x]
            if cid and names:
                channel_names[cid] = names[0]
            elem.clear()
        elif tag == "programme":
            cid = elem.attrib.get("channel", "")
            programme = {
                "title": safe_text(elem.find("./title")),
                "sub_title": safe_text(elem.find("./sub-title")),
                "desc": safe_text(elem.find("./desc")),
                "start": parse_xmltv_time(elem.attrib.get("start", "")),
                "stop": parse_xmltv_time(elem.attrib.get("stop", "")),
                "channel_id": cid,
                "channel": channel_names.get(cid, cid),
            }
            yield programme
            elem.clear()


def match_programme(programme: dict, catalog: list[dict]) -> list[dict]:
    hay = norm(" ".join([programme.get("title", ""), programme.get("sub_title", ""), programme.get("desc", "")]))
    title_only = norm(programme.get("title", ""))
    hits = []
    for item in catalog:
        for alias in item.get("aliases", []):
            needle = norm(alias)
            if not needle:
                continue
            exact_title = (needle == title_only)
            phrase = re.search(r"(^|\s)" + re.escape(needle) + r"($|\s)", hay) is not None
            if exact_title or phrase:
                hits.append({
                    "slug": item["slug"],
                    "work_title": item["title"],
                    "matched_alias": alias,
                    "match_type": "title" if exact_title else "text",
                })
                break
    return hits


def fingerprint(record: dict) -> str:
    key = "|".join([
        record.get("slug", ""), record.get("country_code", ""), record.get("channel_id", ""),
        record.get("channel", ""), record.get("programme_title", ""), record.get("start", ""), record.get("source", ""),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def scan_country(country: dict, url_template: str, catalog: list[dict]) -> list[dict]:
    code = country["code"]
    url = url_template.format(code=code)
    print(f"[scan] {code} {url}")
    hits: list[dict] = []
    try:
        data = download_bytes(url)
    except urllib.error.HTTPError as e:
        print(f"[skip] {code} HTTP {e.code}")
        return []
    except Exception as e:
        print(f"[skip] {code} {type(e).__name__}: {e}")
        return []

    try:
        for programme in iter_xmltv_programmes(data):
            for m in match_programme(programme, catalog):
                record = {
                    **m,
                    "country_code": code,
                    "country_name": country["name"],
                    "region": country.get("region", ""),
                    "source": "epg.pw XMLTV",
                    "source_url": url,
                    "programme_title": programme.get("title", ""),
                    "programme_sub_title": programme.get("sub_title", ""),
                    "channel": programme.get("channel", ""),
                    "channel_id": programme.get("channel_id", ""),
                    "start": programme.get("start", ""),
                    "stop": programme.get("stop", ""),
                    "detected_at_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
                }
                record["fingerprint"] = fingerprint(record)
                hits.append(record)
    except Exception as e:
        print(f"[error] parse {code}: {type(e).__name__}: {e}")
        return hits
    print(f"[done] {code}: {len(hits)} hit(s)")
    return hits


def github_api(method: str, path: str, token: str, payload: Optional[dict] = None) -> Any:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY no definido")
    url = f"https://api.github.com/repos/{repo}{path}"
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else None


def ensure_label(token: str) -> None:
    try:
        github_api("POST", "/labels", token, {"name": ISSUE_LABEL, "color": "b60205", "description": "Coincidencias detectadas por el radar DDV"})
    except urllib.error.HTTPError as e:
        if e.code != 422:
            print(f"[warn] label: HTTP {e.code}")


def existing_fingerprints(token: str) -> set[str]:
    fps: set[str] = set()
    for page in range(1, 6):
        try:
            issues = github_api("GET", f"/issues?state=all&labels={ISSUE_LABEL}&per_page=100&page={page}", token)
        except Exception as e:
            print(f"[warn] no pude leer issues previos: {e}")
            break
        if not issues:
            break
        for issue in issues:
            body = issue.get("body") or ""
            for fp in re.findall(r"fingerprint:\s*([a-f0-9]{16})", body):
                fps.add(fp)
    return fps


def build_issue_body(new_hits: list[dict]) -> str:
    lines = []
    lines.append("## Radar mundial DDV — coincidencias nuevas")
    lines.append("")
    lines.append(f"Detectado en corrida UTC: `{dt.datetime.utcnow().replace(microsecond=0).isoformat()}Z`")
    lines.append("")
    lines.append("| Obra | País | Región | Canal | Inicio | Fin | Programa | Fuente |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for h in new_hits:
        lines.append(f"| {h['work_title']} | {h['country_name']} ({h['country_code']}) | {h.get('region','')} | {h.get('channel','')} | {h.get('start','')} | {h.get('stop','')} | {h.get('programme_title','')} | {h.get('source','')} |")
    lines.append("")
    lines.append("### Huellas técnicas")
    lines.append("")
    for h in new_hits:
        lines.append(f"<!-- fingerprint: {h['fingerprint']} -->")
    lines.append("")
    lines.append("Este aviso fue creado automáticamente por GitHub Actions. Si alguna coincidencia es falsa, se ajustan alias o filtros.")
    return "\n".join(lines)


def create_issue_for_hits(token: str, new_hits: list[dict]) -> None:
    if not new_hits:
        print("[issue] no hay hits nuevos")
        return
    ensure_label(token)
    github_api("POST", "/issues", token, {
        "title": f"Radar mundial DDV — {len(new_hits)} coincidencia(s) nueva(s)",
        "body": build_issue_body(new_hits),
        "labels": [ISSUE_LABEL],
    })
    print("[issue] creado")


def main() -> int:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    all_hits: list[dict] = []
    url_template = sources["sources"]["epg_pw_country_gz"]
    for country in sources["countries"]:
        all_hits.extend(scan_country(country, url_template, catalog))
        time.sleep(0.5)

    out = {
        "ok": True,
        "version": "ddv-radar-mundial-v001",
        "generated_at_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "hits_total": len(all_hits),
        "hits": all_hits,
    }
    (OUTPUTS_DIR / "latest_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        seen = existing_fingerprints(token)
        new_hits = [h for h in all_hits if h.get("fingerprint") not in seen]
        create_issue_for_hits(token, new_hits)
    else:
        print("[info] GITHUB_TOKEN no disponible; no se crean issues")

    print(json.dumps({"hits_total": len(all_hits)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
