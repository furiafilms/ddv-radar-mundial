#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DDV Radar Mundial — v004
Crawler experimental de EPG abiertas.

Cambios v004:
- Amplía países por regiones: Estados Unidos, Norteamérica, Latinoamérica, Europa y resto del mundo.
- Mantiene filtros estrictos de v002 para evitar falsos positivos.
- Agrega catálogo de alias verificados y controlados por idioma.
- Publica JSON estable para lectura directa desde la web DDV si el repositorio es público.
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

USER_AGENT = "DDV-Radar-Mundial/0.4 (+https://danieldelavega.com.ar)"
ISSUE_LABEL = "radar-tv-hit"
REVIEW_LABEL = "radar-tv-review"

MOVIE_WORDS = {
    "movie", "movies", "film", "films", "cinema", "cine", "pelicula", "película",
    "feature film", "largometraje", "drama", "thriller", "horror", "terror", "fiction"
}
NON_MOVIE_WORDS = {
    "sports", "sport", "football", "soccer", "baseball", "basketball", "tennis", "cricket", "match",
    "news", "noticias", "reality", "documentary", "documental", "series", "serie", "episode", "episodes",
    "talk", "religion", "children", "kids", "weather", "magazine", "game show", "quiz"
}
MOVIE_CHANNEL_HINTS = {
    "starz", "encore", "hbo", "cinemax", "showtime", "tcm", "film", "films", "movie", "movies",
    "cine", "cinema", "cinéar", "cine.ar", "paramount", "amc", "syfy", "horror", "terror"
}


def norm(s: str) -> str:
    s = s or ""
    repl = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n",
        "Á": "a", "É": "e", "Í": "i", "Ó": "o", "Ú": "u", "Ü": "u", "Ñ": "n",
        "’": "'", "“": '"', "”": '"'
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


def duration_minutes(start: str, stop: str) -> int:
    try:
        a = dt.datetime.strptime(start[:19], "%Y-%m-%d %H:%M:%S")
        b = dt.datetime.strptime(stop[:19], "%Y-%m-%d %H:%M:%S")
        mins = int((b - a).total_seconds() / 60)
        if mins < 0:
            mins += 24 * 60
        return mins
    except Exception:
        return 0


def download_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def elem_texts(parent: ET.Element, name: str) -> list[str]:
    vals = []
    for x in parent.findall(f"./{name}"):
        t = safe_text(x)
        if t:
            vals.append(t)
    return vals


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
                "categories": elem_texts(elem, "category"),
                "start": parse_xmltv_time(elem.attrib.get("start", "")),
                "stop": parse_xmltv_time(elem.attrib.get("stop", "")),
                "channel_id": cid,
                "channel": channel_names.get(cid, cid),
            }
            programme["duration_minutes"] = duration_minutes(programme["start"], programme["stop"])
            yield programme
            elem.clear()


def has_phrase(hay: str, needle: str) -> bool:
    if not needle:
        return False
    return re.search(r"(^|\s)" + re.escape(needle) + r"($|\s)", hay) is not None


def looks_movie_like(programme: dict) -> bool:
    title = norm(programme.get("title", ""))
    channel = norm(programme.get("channel", ""))
    cats = [norm(c) for c in programme.get("categories", [])]
    blob = " ".join([title, channel] + cats)

    if any(w in blob for w in NON_MOVIE_WORDS):
        # Si un canal es claramente de cine, no descartamos automáticamente por categoría débil.
        if not any(w in channel for w in MOVIE_CHANNEL_HINTS):
            return False

    if any(w in blob for w in MOVIE_WORDS):
        return True
    if any(w in channel for w in MOVIE_CHANNEL_HINTS):
        return True
    # Un largometraje suele durar más de una hora. Esto no prueba que sea película, pero ayuda.
    return int(programme.get("duration_minutes") or 0) >= 70


def match_programme(programme: dict, catalog: list[dict]) -> tuple[list[dict], list[dict]]:
    # v002: no usamos descripción para generar hits confiables.
    title_only = norm(programme.get("title", ""))
    sub_only = norm(programme.get("sub_title", ""))
    title_sub = norm(" ".join([programme.get("title", ""), programme.get("sub_title", "")]))
    movie_like = looks_movie_like(programme)
    high: list[dict] = []
    review: list[dict] = []

    for item in catalog:
        aliases = item.get("aliases", [])
        # compatibilidad con v001, por si queda algún alias como string
        aliases = [{"name": a, "mode": "exact_or_subtitle", "generic": False} if isinstance(a, str) else a for a in aliases]
        for alias in aliases:
            name = alias.get("name", "")
            needle = norm(name)
            if not needle:
                continue
            mode = alias.get("mode", "exact_or_subtitle")
            generic = bool(alias.get("generic", False))
            exact_title = needle == title_only
            in_subtitle = has_phrase(sub_only, needle)
            in_title_sub = has_phrase(title_sub, needle)

            accepted = False
            confidence = "low"
            reason = ""

            if mode == "exact_title":
                accepted = exact_title
                confidence = "high" if accepted else "low"
                reason = "título exacto"
            elif mode == "exact_title_movie":
                accepted = exact_title and movie_like
                confidence = "high" if accepted else "low"
                reason = "título exacto + contexto película"
            else:  # exact_or_subtitle
                accepted = exact_title or (in_subtitle and movie_like)
                confidence = "high" if exact_title else ("medium" if accepted else "low")
                reason = "título exacto o subtítulo con contexto película"

            candidate = {
                "slug": item["slug"],
                "work_title": item["title"],
                "matched_alias": name,
                "match_type": "title" if exact_title else ("subtitle" if in_subtitle else "text"),
                "confidence": confidence,
                "match_reason": reason,
                "movie_like": movie_like,
                "generic_alias": generic,
            }

            if accepted and confidence == "high":
                high.append(candidate)
                break
            elif in_title_sub:
                review.append(candidate)
                break

    return high, review


def fingerprint(record: dict) -> str:
    key = "|".join([
        record.get("slug", ""), record.get("country_code", ""), record.get("channel_id", ""),
        record.get("channel", ""), record.get("programme_title", ""), record.get("programme_sub_title", ""),
        record.get("start", ""), record.get("source", ""), record.get("confidence", ""),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def enrich_record(m: dict, programme: dict, country: dict, url: str, source_name: str) -> dict:
    record = {
        **m,
        "country_code": country["code"],
        "country_name": country["name"],
        "region": country.get("region", ""),
        "source": source_name,
        "source_url": url,
        "programme_title": programme.get("title", ""),
        "programme_sub_title": programme.get("sub_title", ""),
        "categories": programme.get("categories", []),
        "channel": programme.get("channel", ""),
        "channel_id": programme.get("channel_id", ""),
        "start": programme.get("start", ""),
        "stop": programme.get("stop", ""),
        "duration_minutes": programme.get("duration_minutes", 0),
        "detected_at_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    record["fingerprint"] = fingerprint(record)
    return record


def scan_country(country: dict, url_template: str, catalog: list[dict]) -> tuple[list[dict], list[dict]]:
    code = country["code"]
    url = url_template.format(code=code)
    print(f"[scan] {code} {url}")
    hits: list[dict] = []
    review_hits: list[dict] = []
    try:
        data = download_bytes(url)
    except urllib.error.HTTPError as e:
        print(f"[skip] {code} HTTP {e.code}")
        return [], []
    except Exception as e:
        print(f"[skip] {code} {type(e).__name__}: {e}")
        return [], []

    try:
        for programme in iter_xmltv_programmes(data):
            high, review = match_programme(programme, catalog)
            for m in high:
                hits.append(enrich_record(m, programme, country, url, "epg.pw XMLTV"))
            for m in review:
                review_hits.append(enrich_record(m, programme, country, url, "epg.pw XMLTV"))
    except Exception as e:
        print(f"[error] parse {code}: {type(e).__name__}: {e}")
        return hits, review_hits
    print(f"[done] {code}: {len(hits)} high-confidence hit(s), {len(review_hits)} review candidate(s)")
    return hits, review_hits


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


def ensure_label(token: str, name: str, color: str, description: str) -> None:
    try:
        github_api("POST", "/labels", token, {"name": name, "color": color, "description": description})
    except urllib.error.HTTPError as e:
        if e.code != 422:
            print(f"[warn] label {name}: HTTP {e.code}")


def existing_fingerprints(token: str, label: str) -> set[str]:
    fps: set[str] = set()
    for page in range(1, 6):
        try:
            issues = github_api("GET", f"/issues?state=all&labels={label}&per_page=100&page={page}", token)
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


def build_issue_body(new_hits: list[dict], title: str) -> str:
    lines = []
    lines.append(f"## {title}")
    lines.append("")
    lines.append(f"Detectado en corrida UTC: `{dt.datetime.utcnow().replace(microsecond=0).isoformat()}Z`")
    lines.append("")
    lines.append("| Obra | País | Región | Canal | Inicio | Fin | Programa | Alias | Confianza |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for h in new_hits:
        prog = h.get("programme_title", "")
        if h.get("programme_sub_title"):
            prog += f" — {h.get('programme_sub_title')}"
        lines.append(
            f"| {h['work_title']} | {h['country_name']} ({h['country_code']}) | {h.get('region','')} | "
            f"{h.get('channel','')} | {h.get('start','')} | {h.get('stop','')} | {prog} | "
            f"{h.get('matched_alias','')} | {h.get('confidence','')} |"
        )
    lines.append("")
    lines.append("### Huellas técnicas")
    lines.append("")
    for h in new_hits:
        lines.append(f"<!-- fingerprint: {h['fingerprint']} -->")
    lines.append("")
    lines.append("Aviso automático generado por GitHub Actions. Las coincidencias débiles quedan separadas como revisión y no deben tomarse como emisión confirmada.")
    return "\n".join(lines)


def create_issue_for_hits(token: str, hits: list[dict], *, label: str, issue_title: str, body_title: str) -> None:
    if not hits:
        print(f"[issue] no hay hits para {label}")
        return
    ensure_label(token, label, "b60205" if label == ISSUE_LABEL else "d4c5f9", "Coincidencias detectadas por el radar DDV")
    github_api("POST", "/issues", token, {
        "title": issue_title,
        "body": build_issue_body(hits, body_title),
        "labels": [label],
    })
    print(f"[issue] creado {label}")



def sort_records(records: list[dict]) -> list[dict]:
    return sorted(records, key=lambda r: (r.get("start", ""), r.get("country_name", ""), r.get("channel", "")), reverse=True)


def summarize_by_region(records: list[dict], sources: dict) -> list[dict]:
    order = sources.get("region_order") or []
    region_index = {name: i for i, name in enumerate(order)}
    grouped: dict[str, dict] = {}
    for r in records:
        region = r.get("region") or "Sin país específico"
        country_key = f"{r.get('country_name','')} ({r.get('country_code','')})"
        if region not in grouped:
            grouped[region] = {"region": region, "hits_total": 0, "countries": {}}
        grouped[region]["hits_total"] += 1
        grouped[region]["countries"].setdefault(country_key, 0)
        grouped[region]["countries"][country_key] += 1
    out = []
    for region, data in grouped.items():
        data["countries"] = [{"country": k, "hits_total": v} for k, v in sorted(data["countries"].items())]
        out.append(data)
    return sorted(out, key=lambda x: region_index.get(x["region"], 999))


def build_web_payload(hits: list[dict], review_hits: list[dict], sources: dict) -> dict:
    safe_hits = sort_records(hits)
    safe_review = sort_records(review_hits)[:100]
    return {
        "ok": True,
        "version": "ddv-radar-mundial-v004-web-json-publico",
        "generated_at_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "regions_order": sources.get("region_order", []),
        "hits_total": len(safe_hits),
        "review_total": len(review_hits),
        "summary_by_region": summarize_by_region(safe_hits, sources),
        "hits": safe_hits,
        "review_hits": safe_review,
        "note": "Payload preparado para futura lectura por la web DDV. Solo hits confiables deben mostrarse como emisiones verificadas."
    }

def main() -> int:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    all_hits: list[dict] = []
    all_review_hits: list[dict] = []
    url_template = sources["sources"]["epg_pw_country_gz"]
    for country in sources["countries"]:
        hits, review = scan_country(country, url_template, catalog)
        all_hits.extend(hits)
        all_review_hits.extend(review)
        time.sleep(0.5)

    all_hits = sort_records(all_hits)
    all_review_hits = sort_records(all_review_hits)
    out = {
        "ok": True,
        "version": "ddv-radar-mundial-v004-catalogo-verificado",
        "generated_at_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "countries_configured": len(sources.get("countries", [])),
        "regions_order": sources.get("region_order", []),
        "hits_total": len(all_hits),
        "review_total": len(all_review_hits),
        "summary_by_region": summarize_by_region(all_hits, sources),
        "hits": all_hits,
        "review_hits": all_review_hits[:100],
        "web_payload": build_web_payload(all_hits, all_review_hits, sources),
    }
    (OUTPUTS_DIR / "latest_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS_DIR / "site_tv_cable_global.json").write_text(json.dumps(out["web_payload"], ensure_ascii=False, indent=2), encoding="utf-8")

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        seen = existing_fingerprints(token, ISSUE_LABEL)
        new_hits = [h for h in all_hits if h.get("fingerprint") not in seen]
        create_issue_for_hits(
            token,
            new_hits,
            label=ISSUE_LABEL,
            issue_title=f"Radar mundial DDV — {len(new_hits)} coincidencia(s) confiable(s)",
            body_title="Radar mundial DDV — coincidencias confiables nuevas",
        )

        # Las de revisión no crean issue por defecto, salvo que se fuerce con una variable.
        if os.environ.get("CREATE_REVIEW_ISSUES", "").lower() in {"1", "true", "yes"}:
            seen_review = existing_fingerprints(token, REVIEW_LABEL)
            new_review = [h for h in all_review_hits if h.get("fingerprint") not in seen_review]
            create_issue_for_hits(
                token,
                new_review[:50],
                label=REVIEW_LABEL,
                issue_title=f"Radar mundial DDV — {len(new_review)} coincidencia(s) para revisar",
                body_title="Radar mundial DDV — coincidencias para revisar",
            )
    else:
        print("[info] GITHUB_TOKEN no disponible; no se crean issues")

    print(json.dumps({"hits_total": len(all_hits), "review_total": len(all_review_hits)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
