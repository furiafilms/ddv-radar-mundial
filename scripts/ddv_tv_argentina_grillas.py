#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DDV TV Argentina Grillas v213

Objetivo:
- escanear grillas argentinas vivas, no cargar registros manuales;
- detectar apariciones futuras de la filmografía DDV en CINE.AR / Canal á / grillas abiertas;
- actualizar los JSON que ya consume el sitio;
- dejar trazabilidad cuando una fuente falla, para no confundir "sin registros" con "no escaneado".

No usa claves. Solo urllib + stdlib.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)

CATALOG_PATHS = [DATA_DIR / "catalogo.json", DATA_DIR / "catalog.json"]
SOURCES_FILE = DATA_DIR / "tv_argentina_grillas_sources.json"
SITE_TV_GLOBAL = OUTPUTS_DIR / "site_tv_cable_global.json"
SITE_TV_FILTERED = OUTPUTS_DIR / "site_tv_cable_global_filtered.json"
SITE_TV_REVIEW = OUTPUTS_DIR / "site_tv_cable_review.json"
LAST_RUN = OUTPUTS_DIR / "tv_argentina_grillas_last_run.json"

TZ_NAME = os.getenv("DDV_TV_ARG_TIMEZONE", "America/Argentina/Buenos_Aires")
TZ = ZoneInfo(TZ_NAME)
NOW_LOCAL = datetime.now(TZ)
NOW_UTC = datetime.now(timezone.utc)
CURRENT_YEAR = NOW_LOCAL.year
USER_AGENT = "Mozilla/5.0 (compatible; DDV-TV-Argentina-Grillas/213; +https://danieldelavega.com.ar)"

SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
TARGET_CHANNEL_ALIASES = {
    "cine.ar": "CINE.AR",
    "cinear": "CINE.AR",
    "canal a": "Canal á",
    "canal á": "Canal á",
    "volver": "VOLVER",
    "canal volver": "VOLVER",
    "film arts": "Film & Arts",
    "film & arts": "Film & Arts",
    "america tv": "América TV",
    "américa tv": "América TV",
}


def now_iso() -> str:
    return NOW_UTC.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm(s: Any) -> str:
    text = str(s or "").lower()
    table = str.maketrans({
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n",
        "Á": "a", "É": "e", "Í": "i", "Ó": "o", "Ú": "u", "Ü": "u", "Ñ": "n",
        "’": "'", "´": "'", "`": "'", "“": '"', "”": '"',
    })
    text = text.translate(table)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def read_json(path: Path, default: Any) -> Any:
    try:
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "section", "article"}:
            self.parts.append("\n")
    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "section", "article"}:
            self.parts.append("\n")
    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)
    def text(self) -> str:
        raw = "".join(self.parts)
        raw = html.unescape(raw).replace("\xa0", " ")
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n", raw)
        return raw.strip()


def html_to_text(raw: str) -> str:
    p = TextExtractor()
    try:
        p.feed(raw)
        return p.text()
    except Exception:
        return compact_spaces(re.sub(r"<[^>]+>", " ", raw))


def http_text(url: str, timeout: int = 45, retries: int = 1) -> Tuple[Optional[str], Optional[str], int]:
    last_err = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace"), None, len(raw)
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(2 + attempt)
    return None, last_err, 0


def parse_dmy(s: str) -> Optional[date]:
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", s)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_dmy_no_year(s: str) -> Optional[date]:
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", s)
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    y = CURRENT_YEAR
    try:
        out = date(y, mo, d)
        # Si estamos en diciembre y aparece enero, asumir año siguiente.
        if NOW_LOCAL.month == 12 and mo == 1:
            out = date(y + 1, mo, d)
        return out
    except ValueError:
        return None


def parse_spanish_date(text: str) -> Optional[date]:
    n = norm(text)
    m = re.search(r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo)?\s*(\d{1,2})\s+de\s+([a-z]+)(?:\s+de\s+(\d{4}))?\b", n)
    if not m:
        return None
    d = int(m.group(2))
    mo = SPANISH_MONTHS.get(m.group(3))
    y = int(m.group(4)) if m.group(4) else CURRENT_YEAR
    if not mo:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_time_hhmm(text: str) -> Optional[str]:
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", str(text or ""))
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"


def iso_week_urls(template: str, past_weeks: int = 1, future_weeks: int = 8) -> list[str]:
    urls = []
    today = NOW_LOCAL.date()
    for delta in range(-past_weeks, future_weeks + 1):
        target = today + timedelta(days=delta * 7)
        iso = target.isocalendar()
        urls.append(template.format(year=iso.year, week=iso.week))
    return list(dict.fromkeys(urls))


def load_catalog() -> list[dict]:
    for path in CATALOG_PATHS:
        data = read_json(path, None)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
    raise SystemExit("No encontré data/catalogo.json ni data/catalog.json")


def build_aliases(catalog: list[dict]) -> list[dict]:
    out = []
    for item in catalog:
        if not isinstance(item, dict):
            continue
        aliases = item.get("aliases") or []
        for raw in aliases:
            if isinstance(raw, str):
                raw = {"name": raw, "generic": False, "mode": "exact_or_subtitle"}
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            out.append({
                "slug": item.get("slug", ""),
                "work_title": item.get("title", name),
                "year": item.get("year"),
                "type": item.get("type"),
                "alias": name,
                "alias_norm": norm(name),
                "generic": bool(raw.get("generic")),
                "mode": raw.get("mode") or "exact_or_subtitle",
            })
    # Preferir alias más largos para evitar que un alias corto gane antes.
    return sorted(out, key=lambda x: len(x["alias_norm"]), reverse=True)


def clean_program_title(title: str) -> str:
    t = compact_spaces(title)
    t = re.sub(r"^[|•*\-–]+\s*", "", t)
    t = re.sub(r"\s*,\s*(19|20)\d{2}\b", "", t)
    t = re.sub(r"\s+\((19|20)\d{2}\)\b", "", t)
    t = re.sub(r"^FICCIONARTE\s*[-–:]\s*", "", t, flags=re.I)
    t = re.sub(r"^Pel[ií]cula\s*[:\-–]\s*", "", t, flags=re.I)
    return compact_spaces(t)


def looks_like_series_episode(title: str) -> bool:
    n = norm(title)
    if re.search(r"\bs\d{1,2}\s*e\d{1,3}\b", n):
        return True
    if any(x in n for x in ["temporada", "episodio", "capitulo", "capitulo", "csi miami", "the rookie", "la brea"]):
        return True
    # "CSI: Miami - Punto muerto" no debe entrar como película DDV.
    if " - " in title or " – " in title:
        left = re.split(r"\s[-–]\s", title, maxsplit=1)[0]
        leftn = norm(left)
        if not any(ok in leftn for ok in ["pelicula", "ficcionarte", "cine", "film", "largometraje"]):
            return True
    return False


def match_ddv_title(raw_title: str, aliases: list[dict], source_hint: str = "") -> Tuple[Optional[dict], Optional[dict]]:
    title = clean_program_title(raw_title)
    tn = norm(title)
    rawn = norm(raw_title)
    srcn = norm(source_hint)
    if not tn:
        return None, None

    for a in aliases:
        an = a["alias_norm"]
        if not an:
            continue
        exact = tn == an or rawn == an
        official_context = any(x in rawn for x in ["pelicula", "ficcionarte"]) or any(x in srcn for x in ["canal a", "canal á", "cine ar", "cinear", "telered", "america tvguide"])
        contains = re.search(r"(^|\b)" + re.escape(an) + r"($|\b)", rawn) is not None

        if exact and not looks_like_series_episode(raw_title):
            return {
                **a,
                "matched_term": a["alias"],
                "match_reason": "título exacto en grilla",
                "confidence": "high",
            }, None

        # Caso típico: "FICCIONARTE - Película: PUNTO MUERTO".
        if contains and official_context and not looks_like_series_episode(raw_title):
            # Para alias genéricos, exigimos que el título limpio termine siendo exacto.
            if a.get("generic") and tn != an:
                return None, {**a, "programme_title": raw_title, "reason": "alias genérico dentro de texto; requiere revisión"}
            return {
                **a,
                "matched_term": a["alias"],
                "match_reason": "alias en contexto de película/grilla argentina",
                "confidence": "high",
            }, None

        if contains:
            return None, {**a, "programme_title": raw_title, "reason": "coincidencia textual no exacta; revisión para evitar falsos positivos"}
    return None, None


def fingerprint(rec: dict) -> str:
    raw = "|".join([
        str(rec.get("slug") or rec.get("work_slug") or ""),
        str(rec.get("programme_title") or rec.get("title") or ""),
        str(rec.get("channel") or ""),
        str(rec.get("date_iso") or rec.get("start") or ""),
        str(rec.get("start_time") or ""),
        str(rec.get("source") or ""),
        str(rec.get("source_url") or ""),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class SourceReport:
    id: str
    ok: bool
    provider: str
    url: str
    channel: str = ""
    bytes: int = 0
    programmes_parsed: int = 0
    hits: int = 0
    review: int = 0
    error: str = ""
    scanned_at: str = ""


def make_hit(match: dict, *, title: str, channel: str, channel_number: str, when: date, hhmm: str, source: str, source_url: str, detection_type: str) -> dict:
    rec = {
        "slug": match["slug"],
        "title": match["work_title"],
        "programme_title": clean_program_title(title) or title,
        "raw_programme_title": title,
        "matched_term": match.get("matched_term") or match.get("alias"),
        "match_reason": match.get("match_reason", "grilla argentina"),
        "channel": channel,
        "channel_number": channel_number,
        "country": "AR",
        "country_code": "AR",
        "country_name": "Argentina",
        "date_iso": when.isoformat(),
        "start_time": hhmm,
        "end_time": "",
        "source": source,
        "source_url": source_url,
        "detection_type": detection_type,
        "confidence": match.get("confidence", "high"),
        "source_labels": [source],
        "work_slug": match["slug"],
        "work_title": match["work_title"],
        "detected_at": now_iso(),
    }
    rec["fingerprint"] = fingerprint(rec)
    return rec


def parse_america_tvguide(src: dict, raw_html: str, aliases: list[dict]) -> Tuple[list[dict], list[dict], int]:
    text = html_to_text(raw_html)
    lines = [compact_spaces(x) for x in text.splitlines() if compact_spaces(x)]
    channel = src.get("channel") or src.get("label") or "TV Argentina"
    channel_number = src.get("channel_number", "")
    current_date: Optional[date] = None
    hits, review = [], []
    parsed = 0

    for line in lines:
        # Ej: ##### Hoy - 16/7/26 - Jueves
        d = parse_dmy(line)
        if d and ("hoy" in norm(line) or "manana" in norm(line) or re.search(r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b", norm(line))):
            current_date = d
            continue
        if current_date is None:
            # Algunas páginas no separan bien; capturamos fecha suelta si aparece.
            d2 = parse_dmy(line)
            if d2:
                current_date = d2
            continue
        m = re.match(r"^\|?\s*([01]?\d|2[0-3]):([0-5]\d)\s+(.+)$", line)
        if not m:
            continue
        hhmm = f"{int(m.group(1)):02d}:{m.group(2)}"
        title = compact_spaces(m.group(3))
        # Cortar posibles separadores de navegación que no son programación.
        if not title or len(title) > 180:
            continue
        parsed += 1
        match, review_match = match_ddv_title(title, aliases, f"{src.get('provider','')} {channel}")
        if match:
            hits.append(make_hit(match, title=title, channel=channel, channel_number=channel_number, when=current_date, hhmm=hhmm, source=src.get("provider", "AmericaTVGuide"), source_url=src["url"], detection_type="grilla argentina viva / AmericaTVGuide"))
        elif review_match:
            review.append({
                "source": src.get("provider", "AmericaTVGuide"),
                "source_url": src["url"],
                "channel": channel,
                "date_iso": current_date.isoformat(),
                "start_time": hhmm,
                "programme_title": title,
                "matched_term": review_match.get("alias"),
                "work_slug": review_match.get("slug"),
                "work_title": review_match.get("work_title"),
                "reason": review_match.get("reason", "revisión"),
                "detected_at": now_iso(),
            })
    return hits, review, parsed


def parse_telered(src: dict, raw_html: str, aliases: list[dict]) -> Tuple[list[dict], list[dict], int]:
    text = html_to_text(raw_html)
    lines = [compact_spaces(x) for x in text.splitlines() if compact_spaces(x)]
    joined = "\n".join(lines)
    # Default de TeleRed: grilla de hoy. Se toma la primera fecha del selector "hoy dd/mm".
    today = None
    for m in re.finditer(r"\b(?:hoy|domingo|lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado)\s+(\d{1,2}/\d{1,2})\b", joined, flags=re.I):
        today = parse_dmy_no_year(m.group(1))
        if today:
            break
    if not today:
        today = NOW_LOCAL.date()

    hits, review = [], []
    parsed = 0
    current_channel = ""
    channel_number = ""
    target_norms = set(TARGET_CHANNEL_ALIASES.keys())

    for line in lines:
        n = norm(line)
        if re.fullmatch(r"\d{1,4}", line):
            channel_number = line
            continue
        if n in target_norms or any(n == norm(x) for x in src.get("channels", [])):
            current_channel = TARGET_CHANNEL_ALIASES.get(n, line)
            continue
        m = re.match(r"^[*•\-–]?\s*(.+?)\s+([01]?\d|2[0-3]):([0-5]\d)\s*hs\b", line, flags=re.I)
        if not m or not current_channel:
            continue
        title = compact_spaces(m.group(1))
        hhmm = f"{int(m.group(2)):02d}:{m.group(3)}"
        if not title or norm(title) == norm(current_channel):
            continue
        parsed += 1
        match, review_match = match_ddv_title(title, aliases, f"TeleRed {current_channel}")
        if match:
            hits.append(make_hit(match, title=title, channel=current_channel, channel_number=(f"TeleRed {channel_number}" if channel_number else "TeleRed"), when=today, hhmm=hhmm, source=src.get("provider", "TeleRed / grilla de programación"), source_url=src["url"], detection_type="grilla argentina viva / TeleRed"))
        elif review_match:
            review.append({
                "source": src.get("provider", "TeleRed / grilla de programación"),
                "source_url": src["url"],
                "channel": current_channel,
                "date_iso": today.isoformat(),
                "start_time": hhmm,
                "programme_title": title,
                "matched_term": review_match.get("alias"),
                "work_slug": review_match.get("slug"),
                "work_title": review_match.get("work_title"),
                "reason": review_match.get("reason", "revisión"),
                "detected_at": now_iso(),
            })
    return hits, review, parsed


def parse_artear_week(src: dict, raw_html: str, aliases: list[dict], url: str) -> Tuple[list[dict], list[dict], int]:
    text = html_to_text(raw_html)
    lines = [compact_spaces(x) for x in text.splitlines() if compact_spaces(x)]
    text_join = "\n".join(lines)
    hits, review = [], []
    parsed = 0

    # Recorremos líneas buscando alias. Si hay fecha y hora cerca, se genera hit.
    for idx, line in enumerate(lines):
        maybe_match, maybe_review = match_ddv_title(line, aliases, "Artear Canal A Ficcionarte Película")
        if not maybe_match and not maybe_review:
            continue
        window_lines = lines[max(0, idx - 18): min(len(lines), idx + 18)]
        window = "\n".join(window_lines)
        d = parse_dmy(window) or parse_spanish_date(window)
        hhmm = parse_time_hhmm(window) or parse_time_hhmm(line)
        parsed += 1
        if maybe_match and d and hhmm:
            hits.append(make_hit(maybe_match, title=line, channel=src.get("channel", "Canal á"), channel_number=src.get("channel_number", "Canal á · Artear"), when=d, hhmm=hhmm, source=src.get("provider", "Artear / grilla comercial Canal A"), source_url=url, detection_type="grilla argentina viva / Artear Canal A"))
        else:
            rm = maybe_review or maybe_match
            review.append({
                "source": src.get("provider", "Artear / grilla comercial Canal A"),
                "source_url": url,
                "channel": src.get("channel", "Canal á"),
                "date_iso": d.isoformat() if d else "",
                "start_time": hhmm or "",
                "programme_title": line,
                "matched_term": rm.get("alias") or rm.get("matched_term"),
                "work_slug": rm.get("slug"),
                "work_title": rm.get("work_title"),
                "reason": "coincidencia en grilla Artear, pero falta fecha/hora confiable" if not (d and hhmm) else rm.get("reason", "revisión"),
                "detected_at": now_iso(),
            })
    return hits, review, parsed


def merge_hits(existing_payload: dict, new_hits: list[dict], source_reports: list[dict], review_hits: list[dict]) -> dict:
    existing_hits = []
    if isinstance(existing_payload, dict) and isinstance(existing_payload.get("hits"), list):
        existing_hits = [h for h in existing_payload.get("hits", []) if isinstance(h, dict)]
    by_fp: Dict[str, dict] = {}
    for h in existing_hits + new_hits:
        fp = h.get("fingerprint") or fingerprint(h)
        h["fingerprint"] = fp
        # El nuevo dato pisa el viejo si es el mismo fingerprint.
        by_fp[fp] = h
    hits = sorted(by_fp.values(), key=lambda r: (str(r.get("date_iso", "")), str(r.get("start_time", "")), str(r.get("channel", ""))), reverse=True)
    payload = {
        "ok": True,
        "version": "v213-tv-argentina-grillas-activas",
        "generated_at_utc": now_iso(),
        "source": "DDV TV Argentina Grillas v213 + outputs previos",
        "hits_total": len(hits),
        "review_total": len(review_hits),
        "hits": hits,
        "review_hits": review_hits,
        "source_reports": source_reports,
        "argentina_sources_ok": all(r.get("ok") for r in source_reports if r.get("critical")),
        "note": "El radar diferencia ausencia real de registros de fuentes no escaneadas. Si una fuente crítica falla, no debe mostrarse como ausencia confirmada.",
        "filtered_at": now_iso(),
        "version_filter": "v213-tv-argentina-active-grid-scanner",
    }
    return payload


def main() -> int:
    catalog = load_catalog()
    aliases = build_aliases(catalog)
    sources = read_json(SOURCES_FILE, {})
    if not sources:
        raise SystemExit("Falta data/tv_argentina_grillas_sources.json")

    all_hits: list[dict] = []
    all_review: list[dict] = []
    reports: list[dict] = []

    for src in sources.get("sources", []):
        if not src.get("enabled", True):
            continue
        stype = src.get("type")
        urls = []
        if stype == "artear_weekly":
            urls = iso_week_urls(src["url_template"], int(src.get("past_weeks", 1)), int(src.get("future_weeks", 8)))
        else:
            urls = [src["url"]]
        for url in urls:
            report = SourceReport(id=src.get("id", url), ok=False, provider=src.get("provider", ""), url=url, channel=src.get("channel", ""), scanned_at=now_iso())
            raw, err, size = http_text(url, timeout=int(src.get("timeout", 45)), retries=int(src.get("retries", 1)))
            report.bytes = size
            if raw is None:
                report.error = err or "fetch error"
                d = asdict(report)
                d["critical"] = bool(src.get("critical"))
                reports.append(d)
                print(f"[fuente ERROR] {report.id}: {report.error}", file=sys.stderr)
                continue
            try:
                if stype == "america_tvguide_channel":
                    hits, review, parsed = parse_america_tvguide(src, raw, aliases)
                elif stype == "telered_grid":
                    hits, review, parsed = parse_telered(src, raw, aliases)
                elif stype == "artear_weekly":
                    hits, review, parsed = parse_artear_week(src, raw, aliases, url)
                else:
                    hits, review, parsed = [], [], 0
                    report.error = f"tipo no soportado: {stype}"
                report.ok = True
                report.programmes_parsed = parsed
                report.hits = len(hits)
                report.review = len(review)
                all_hits.extend(hits)
                all_review.extend(review)
                print(f"[fuente OK] {report.id}: programas={parsed} hits={len(hits)} review={len(review)}")
            except Exception as exc:
                report.error = f"parse error: {type(exc).__name__}: {exc}"
                print(f"[fuente ERROR] {report.id}: {report.error}", file=sys.stderr)
            d = asdict(report)
            d["critical"] = bool(src.get("critical"))
            reports.append(d)
            time.sleep(float(src.get("delay_seconds", 0.2)))

    existing = read_json(SITE_TV_FILTERED, read_json(SITE_TV_GLOBAL, {}))
    payload = merge_hits(existing, all_hits, reports, all_review[:200])
    write_json(SITE_TV_FILTERED, payload)
    write_json(SITE_TV_GLOBAL, payload)
    write_json(SITE_TV_REVIEW, {"ok": True, "version": "v213-tv-argentina-review", "generated_at_utc": now_iso(), "review_total": len(all_review), "review_hits": all_review[:500], "source_reports": reports})
    last = {
        "ok": True,
        "version": "v213-tv-argentina-grillas-activas",
        "ran_at_utc": now_iso(),
        "ran_at_local": NOW_LOCAL.replace(microsecond=0).isoformat(),
        "timezone": TZ_NAME,
        "new_hits_total": len(all_hits),
        "review_total": len(all_review),
        "sources_total": len(reports),
        "sources_ok": sum(1 for r in reports if r.get("ok")),
        "critical_sources_failed": [r for r in reports if r.get("critical") and not r.get("ok")],
        "hits": all_hits,
        "source_reports": reports,
    }
    write_json(LAST_RUN, last)

    # Si todas las fuentes críticas fallan, el workflow debe fallar: mejor mail de error que falso silencio.
    critical = [r for r in reports if r.get("critical")]
    if critical and not any(r.get("ok") for r in critical):
        print("ERROR: todas las fuentes críticas argentinas fallaron. No se puede afirmar 'sin registros'.", file=sys.stderr)
        return 2
    print(json.dumps({"new_hits_total": len(all_hits), "review_total": len(all_review), "sources_ok": last["sources_ok"], "sources_total": last["sources_total"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
