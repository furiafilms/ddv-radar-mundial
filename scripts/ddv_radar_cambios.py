#!/usr/bin/env python3
"""
DDV Radar de Cambios v212
- Plataformas: consulta TMDb Watch Providers + Watchmode y genera outputs/site_platforms_global.json.
- TV/Cable: lee outputs/site_tv_cable_global.json si existe y detecta novedades contra estado previo.
- Alertas: crea Issues de GitHub cuando aparecen fingerprints nuevos.

No contiene claves. Usa secretos de GitHub:
- TMDB_BEARER_TOKEN o TMDB_API_KEY para plataformas.
- GITHUB_TOKEN lo provee GitHub Actions.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
CATALOG_FILE = DATA_DIR / "catalog.json"
PLATFORMS_OUT = OUTPUTS_DIR / "site_platforms_global.json"
PLATFORMS_STATE = OUTPUTS_DIR / "state_platforms_seen.json"
TV_OUT = OUTPUTS_DIR / "site_tv_cable_global.json"
TV_STATE = OUTPUTS_DIR / "state_tv_seen.json"
CHANGE_LOG = OUTPUTS_DIR / "radar_change_log.json"
TV_FILTERED_OUT = OUTPUTS_DIR / "site_tv_cable_global_filtered.json"
TV_REJECTED_OUT = OUTPUTS_DIR / "site_tv_cable_rejected.json"
TV_REVIEW_OUT = OUTPUTS_DIR / "site_tv_cable_review.json"
TV_EPG_BOOTSTRAP_STATE = OUTPUTS_DIR / "state_tv_epg_bootstrap_v205.json"
PLATFORMS_WATCHMODE_BOOTSTRAP_STATE = OUTPUTS_DIR / "state_platforms_watchmode_bootstrap_v206.json"
TV_SOURCES_FILE = DATA_DIR / "tv_sources.json"
TV_VERIFIED_FILE = DATA_DIR / "tv_verified_records.json"

TMDB_BEARER_TOKEN = os.environ.get("TMDB_BEARER_TOKEN", "").strip()
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
WATCHMODE_API_KEY = os.environ.get("WATCHMODE_API_KEY", "").strip()
WATCHMODE_REGIONS = os.environ.get("WATCHMODE_REGIONS", "AR,US,ES,MX,BR,CL,CO,UY,PE,GB,CA,FR,DE,IT,PT,AU").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "").strip()
CREATE_ISSUES = os.environ.get("CREATE_ISSUES", "1").strip() not in {"0", "false", "FALSE", "no"}

PRIORITY_COUNTRIES = [
    "AR", "US", "ES", "MX", "BR", "CL", "CO", "UY", "PE", "GB", "CA", "FR", "DE", "IT", "PT", "AU"
]

TYPE_LABELS = {
    "flatrate": "suscripción",
    "free": "gratis",
    "ads": "gratis con publicidad",
    "rent": "alquiler",
    "buy": "compra",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def http_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 20) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} {url}", file=sys.stderr)
    except Exception as exc:
        print(f"ERROR {url}: {exc}", file=sys.stderr)
    return None


def tmdb_headers() -> Dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "DDV-Radar-Cambios/212"}
    if TMDB_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {TMDB_BEARER_TOKEN}"
    return headers


def tmdb_url(path: str, params: Dict[str, Any]) -> str:
    params = {k: v for k, v in params.items() if v is not None and v != ""}
    if not TMDB_BEARER_TOKEN and TMDB_API_KEY:
        params["api_key"] = TMDB_API_KEY
    return "https://api.themoviedb.org/3" + path + "?" + urllib.parse.urlencode(params)


def tmdb_ready() -> bool:
    return bool(TMDB_BEARER_TOKEN or TMDB_API_KEY)


def pick_best_tmdb(results: Dict[str, Any], expected_year: Optional[int]) -> Optional[Dict[str, Any]]:
    items = results.get("results") if isinstance(results, dict) else None
    if not isinstance(items, list):
        return None
    exact_year = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        release_date = str(item.get("release_date") or "")
        year = int(release_date[:4]) if release_date[:4].isdigit() else None
        if expected_year and year == int(expected_year):
            exact_year.append(item)
    if exact_year:
        return exact_year[0]
    # Para títulos genéricos preferimos no tomar un resultado sin año exacto.
    return None


def platform_fingerprint(slug: str, item: Dict[str, Any]) -> str:
    raw = "|".join([
        slug,
        str(item.get("name") or "").strip().lower(),
        str(item.get("region_code") or item.get("country") or item.get("region") or "").strip().upper(),
        str(item.get("type") or "").strip().lower(),
        str(item.get("source") or "").strip().lower(),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def normalize_tmdb_providers(work: Dict[str, Any], provider_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = provider_data.get("results") if isinstance(provider_data, dict) else None
    if not isinstance(results, dict):
        return []
    countries = list(results.keys())
    ordered = [c for c in PRIORITY_COUNTRIES if c in results] + sorted([c for c in countries if c not in PRIORITY_COUNTRIES])
    out: List[Dict[str, Any]] = []
    seen = set()
    detected_at = now_iso()

    for country in ordered:
        country_data = results.get(country) or {}
        if not isinstance(country_data, dict):
            continue
        link = str(country_data.get("link") or "")
        for raw_type in ["flatrate", "free", "ads", "rent", "buy"]:
            providers = country_data.get(raw_type)
            if not isinstance(providers, list):
                continue
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                name = str(provider.get("provider_name") or "").strip()
                if not name or name.lower() == "eventive":
                    continue
                key = (country, name.lower(), raw_type)
                if key in seen:
                    continue
                seen.add(key)
                item = {
                    "slug": work["slug"],
                    "work_title": work["title"],
                    "name": name,
                    "provider_id": provider.get("provider_id"),
                    "region": country,
                    "region_code": country,
                    "country": country,
                    "type": TYPE_LABELS.get(raw_type, raw_type),
                    "raw_type": raw_type,
                    "url": link,
                    "source": "TMDb Watch Providers",
                    "detected_at": detected_at,
                }
                item["fingerprint"] = platform_fingerprint(work["slug"], item)
                out.append(item)
    return out


def fetch_platforms_for_work(work: Dict[str, Any]) -> Dict[str, Any]:
    slug = work["slug"]
    title = work["title"]
    base = {
        "slug": slug,
        "title": title,
        "year": work.get("year"),
        "type": work.get("type"),
        "current": [],
        "current_status": "not_configured" if not tmdb_ready() else "not_found",
        "message": None,
        "tmdb_id": work.get("tmdb_id"),
        "tmdb_title": None,
        "updated_at": now_iso(),
    }
    if not tmdb_ready():
        base["message"] = "TMDb no configurado. Cargar TMDB_BEARER_TOKEN o TMDB_API_KEY como GitHub Secret."
        return base

    tmdb_id = work.get("tmdb_id")
    tmdb_title = None
    if not tmdb_id:
        query = work.get("platform_search") or title
        search = http_json(tmdb_url("/search/movie", {
            "query": query,
            "include_adult": "false",
            "language": "en-US",
            "year": work.get("year"),
            "page": 1,
        }), tmdb_headers())
        picked = pick_best_tmdb(search or {}, work.get("year"))
        if picked:
            tmdb_id = picked.get("id")
            tmdb_title = {
                "name": picked.get("title") or picked.get("original_title") or query,
                "release_date": picked.get("release_date"),
            }

    if not tmdb_id:
        base["current_status"] = "not_found"
        base["message"] = "No se pudo verificar TMDb ID por título/año. Completar tmdb_id en data/catalog.json si corresponde."
        return base

    providers = http_json(tmdb_url(f"/movie/{int(tmdb_id)}/watch/providers", {}), tmdb_headers())
    current = normalize_tmdb_providers(work, providers or {})
    base["tmdb_id"] = int(tmdb_id)
    base["tmdb_title"] = tmdb_title
    base["current"] = current
    base["current_status"] = "found" if current else "no_sources"
    base["message"] = None if current else "Sin proveedores actuales registrados en TMDb."
    return base




def watchmode_ready() -> bool:
    return bool(WATCHMODE_API_KEY)


def watchmode_url(path: str, params: Optional[Dict[str, Any]] = None) -> str:
    params = dict(params or {})
    params["apiKey"] = WATCHMODE_API_KEY
    return "https://api.watchmode.com/v1" + path + "?" + urllib.parse.urlencode(params)


def watchmode_allowed_regions() -> set:
    return {x.strip().upper() for x in WATCHMODE_REGIONS.split(",") if x.strip()}


def pick_best_watchmode_title(results: Any, expected_year: Optional[int]) -> Optional[Dict[str, Any]]:
    if not isinstance(results, dict):
        return None
    items = results.get("title_results") or results.get("results") or []
    if not isinstance(items, list):
        return None
    fallback = None
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        typ = str(item.get("type") or item.get("result_type") or "").lower()
        if typ and "movie" not in typ and typ not in {"film"}:
            continue
        year = item.get("year")
        try:
            year_int = int(year) if year is not None and str(year).strip() else None
        except Exception:
            year_int = None
        if expected_year and year_int == int(expected_year):
            return item
        if fallback is None:
            fallback = item
    # Para títulos genéricos, igual que TMDb: sin año exacto preferimos no adivinar.
    return fallback if expected_year is None else None


def watchmode_type(raw_type: Any) -> Tuple[str, str]:
    raw = str(raw_type or "").strip().lower()
    mapping = {
        "sub": ("flatrate", "suscripción"),
        "subscription": ("flatrate", "suscripción"),
        "free": ("free", "gratis"),
        "rent": ("rent", "alquiler"),
        "buy": ("buy", "compra"),
        "tve": ("tve", "TV Everywhere"),
        "ads": ("ads", "gratis con publicidad"),
        "addon": ("addon", "addon"),
    }
    return mapping.get(raw, (raw or "unknown", TYPE_LABELS.get(raw, raw or "desconocido")))


def platform_identity_fingerprint(slug: str, item: Dict[str, Any]) -> str:
    """Identidad lógica sin fuente, para evitar duplicar alertas TMDb/Watchmode."""
    raw_type = str(item.get("raw_type") or item.get("type") or "").strip().lower()
    region = str(item.get("region_code") or item.get("country") or item.get("region") or "").strip().upper()
    name = norm_match(item.get("name"))
    raw = "|".join([slug, name, region, raw_type])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def normalize_watchmode_sources(work: Dict[str, Any], sources: Any, watchmode_id: Optional[int]) -> List[Dict[str, Any]]:
    if not isinstance(sources, list):
        return []
    allowed = watchmode_allowed_regions()
    out: List[Dict[str, Any]] = []
    seen = set()
    detected_at = now_iso()
    for source in sources:
        if not isinstance(source, dict):
            continue
        region = str(source.get("region") or source.get("country") or "").upper().strip()
        if allowed and region and region not in allowed:
            continue
        name = str(source.get("name") or source.get("source_name") or source.get("provider_name") or "").strip()
        if not name or name.lower() == "eventive":
            continue
        raw_type, label = watchmode_type(source.get("type") or source.get("monetization_type"))
        url = str(source.get("web_url") or source.get("url") or "").strip()
        key = (region, name.lower(), raw_type, url)
        if key in seen:
            continue
        seen.add(key)
        item = {
            "slug": work["slug"],
            "work_title": work["title"],
            "name": name,
            "provider_id": source.get("source_id") or source.get("id"),
            "watchmode_id": watchmode_id,
            "region": region,
            "region_code": region,
            "country": region,
            "type": label,
            "raw_type": raw_type,
            "url": url,
            "source": "Watchmode",
            "detected_at": detected_at,
        }
        item["fingerprint"] = platform_fingerprint(work["slug"], item)
        item["identity_fingerprint"] = platform_identity_fingerprint(work["slug"], item)
        out.append(item)
    return out


def fetch_watchmode_for_work(work: Dict[str, Any]) -> Dict[str, Any]:
    base = {
        "slug": work.get("slug"),
        "title": work.get("title"),
        "year": work.get("year"),
        "current": [],
        "current_status": "not_configured" if not watchmode_ready() else "not_found",
        "message": None,
        "watchmode_id": work.get("watchmode_id"),
        "updated_at": now_iso(),
    }
    if not watchmode_ready():
        base["message"] = "Watchmode no configurado. Cargar WATCHMODE_API_KEY como GitHub Secret si se desea usar esta segunda fuente."
        return base

    watchmode_id = work.get("watchmode_id")
    if not watchmode_id:
        query = work.get("watchmode_search") or work.get("platform_search") or work.get("title")
        search = http_json(watchmode_url("/search/", {"search_field": "name", "search_value": query}), {"Accept": "application/json", "User-Agent": "DDV-Radar-Cambios/212"})
        picked = pick_best_watchmode_title(search or {}, work.get("year"))
        if picked:
            watchmode_id = picked.get("id")

    if not watchmode_id:
        base["current_status"] = "not_found"
        base["message"] = "No se pudo verificar Watchmode ID por título/año. Completar watchmode_id en data/catalog.json si corresponde."
        return base

    sources = http_json(watchmode_url(f"/title/{int(watchmode_id)}/sources/", {}), {"Accept": "application/json", "User-Agent": "DDV-Radar-Cambios/212"})
    # http_json espera dict; algunas respuestas de sources pueden ser lista. Reintento liviano para listas.
    if sources is None:
        req = urllib.request.Request(watchmode_url(f"/title/{int(watchmode_id)}/sources/", {}), headers={"Accept": "application/json", "User-Agent": "DDV-Radar-Cambios/212"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw)
        except Exception as exc:
            print(f"ERROR Watchmode sources {work.get('slug')}: {exc}", file=sys.stderr)
            parsed = None
    else:
        parsed = sources

    current = normalize_watchmode_sources(work, parsed, int(watchmode_id))
    base["watchmode_id"] = int(watchmode_id)
    base["current"] = current
    base["current_status"] = "found" if current else "no_sources"
    base["message"] = None if current else "Sin proveedores actuales registrados en Watchmode para las regiones monitoreadas."
    return base


def merge_platform_results(tmdb_result: Dict[str, Any], watchmode_result: Dict[str, Any]) -> Dict[str, Any]:
    """Combina fuentes sin perder detalle. Mantiene items por fuente, deduplica por identidad lógica."""
    combined: List[Dict[str, Any]] = []
    seen_identity = set()
    for item in (tmdb_result.get("current") or []):
        copy = dict(item)
        copy.setdefault("identity_fingerprint", platform_identity_fingerprint(str(copy.get("slug") or tmdb_result.get("slug") or ""), copy))
        ident = copy["identity_fingerprint"]
        seen_identity.add(ident)
        combined.append(copy)
    for item in (watchmode_result.get("current") or []):
        copy = dict(item)
        copy.setdefault("identity_fingerprint", platform_identity_fingerprint(str(copy.get("slug") or watchmode_result.get("slug") or ""), copy))
        # Si TMDb ya tenía el mismo proveedor/territorio/tipo, no duplicamos en current,
        # pero dejamos a Watchmode en source_status para trazabilidad.
        if copy["identity_fingerprint"] in seen_identity:
            continue
        seen_identity.add(copy["identity_fingerprint"])
        combined.append(copy)

    result = dict(tmdb_result)
    result["current"] = combined
    result["current_status"] = "found" if combined else "no_sources"
    result["source_status"] = {
        "tmdb": {
            "configured": tmdb_ready(),
            "status": tmdb_result.get("current_status"),
            "items": len(tmdb_result.get("current") or []),
            "tmdb_id": tmdb_result.get("tmdb_id"),
        },
        "watchmode": {
            "configured": watchmode_ready(),
            "status": watchmode_result.get("current_status"),
            "items": len(watchmode_result.get("current") or []),
            "watchmode_id": watchmode_result.get("watchmode_id"),
            "regions": sorted(watchmode_allowed_regions()),
        },
    }
    if not combined:
        result["message"] = "Sin proveedores actuales registrados en TMDb/Watchmode."
    else:
        result["message"] = None
    return result

def extract_tv_hits(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("web_payload"), dict):
        payload = payload["web_payload"]
    for key in ["hits", "current", "items", "results"]:
        if isinstance(payload.get(key), list):
            return [x for x in payload[key] if isinstance(x, dict)]
    return []


def tv_fingerprint(item: Dict[str, Any]) -> str:
    if item.get("fingerprint"):
        return str(item["fingerprint"])
    raw = "|".join([
        str(item.get("slug") or item.get("work_slug") or "").lower(),
        str(item.get("work_title") or item.get("title") or item.get("matched_term") or "").lower(),
        str(item.get("channel") or "").lower(),
        str(item.get("country_code") or item.get("country") or "").upper(),
        str(item.get("start") or item.get("start_iso") or item.get("date_iso") or ""),
        str(item.get("start_time") or ""),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def strip_accents_basic(s: str) -> str:
    table = str.maketrans({
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n",
        "Á": "a", "É": "e", "Í": "i", "Ó": "o", "Ú": "u", "Ü": "u", "Ñ": "n",
        "’": "'", "‘": "'", "´": "'", "`": "'",
    })
    return s.translate(table)


def norm_match(value: Any) -> str:
    s = strip_accents_basic(str(value or "").lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_alias_index(works: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = {}
    for work in works:
        if not isinstance(work, dict) or not work.get("slug"):
            continue
        aliases = [work.get("title"), work.get("platform_search")] + list(work.get("aliases") or [])
        for alias in aliases:
            n = norm_match(alias)
            if not n or len(n) < 3:
                continue
            entry = {"slug": work.get("slug"), "alias": str(alias), "work": work}
            index.setdefault(n, []).append(entry)
    return index


def parse_xmltv_datetime(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    m = re.match(r"^(\d{14})(?:\s*([+-]\d{4}))?", raw)
    if not m:
        return None
    base, off = m.group(1), m.group(2)
    try:
        dt = datetime.strptime(base, "%Y%m%d%H%M%S")
        if off:
            sign = 1 if off[0] == "+" else -1
            hh = int(off[1:3])
            mm = int(off[3:5])
            tz = timezone(sign * timedelta(hours=hh, minutes=mm))
            return dt.replace(tzinfo=tz).astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def xml_text_first(elem: Any, tag: str) -> str:
    try:
        child = elem.find(tag)
        return "" if child is None or child.text is None else str(child.text).strip()
    except Exception:
        return ""


def http_bytes(url: str, timeout: int = 45, max_bytes: int = 35000000) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "DDV-Radar-Cambios/212"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes + 1)
            if len(raw) > max_bytes:
                print(f"TV source skipped, too large > {max_bytes} bytes: {url}", file=sys.stderr)
                return None
            return raw
    except Exception as exc:
        print(f"TV source error {url}: {exc}", file=sys.stderr)
        return None


def maybe_decompress(raw: bytes, url: str) -> bytes:
    if url.endswith(".gz") or raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    return raw


def safe_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def epg_hit_fingerprint(item: Dict[str, Any]) -> str:
    raw = "|".join([
        str(item.get("slug") or ""),
        str(item.get("programme_title") or item.get("title") or "").lower(),
        str(item.get("channel") or "").lower(),
        str(item.get("country_code") or item.get("country") or "").upper(),
        str(item.get("start") or item.get("start_iso") or item.get("date_iso") or ""),
        str(item.get("start_time") or ""),
        str(item.get("source") or "").lower(),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def source_country_name(code: str) -> str:
    names = {
        "AR": "Argentina", "US": "Estados Unidos", "CA": "Canadá", "GB": "Reino Unido",
        "BR": "Brasil", "DE": "Alemania", "FR": "Francia", "AU": "Australia", "ZA": "Sudáfrica",
        "ES": "España", "MX": "México", "CL": "Chile", "CO": "Colombia", "UY": "Uruguay", "PE": "Perú",
        "IT": "Italia", "PT": "Portugal",
    }
    return names.get(str(code or "").upper(), str(code or "").upper())


def scan_xmltv_source(source: Dict[str, Any], works: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Escanea una fuente XMLTV con coincidencia conservadora: título exacto normalizado."""
    url = str(source.get("url") or "").strip()
    provider = str(source.get("provider") or source.get("id") or "XMLTV").strip()
    country_code = str(source.get("country_code") or "").upper()
    max_bytes = safe_int(source.get("max_bytes"), safe_int(os.environ.get("DDV_TV_SOURCE_MAX_BYTES"), 35000000))
    if not url:
        return [], [], {"id": source.get("id"), "ok": False, "reason": "sin url"}

    raw = http_bytes(url, timeout=safe_int(source.get("timeout"), 45), max_bytes=max_bytes)
    if raw is None:
        return [], [], {"id": source.get("id"), "ok": False, "reason": "no se pudo descargar"}
    try:
        xml = maybe_decompress(raw, url)
    except Exception as exc:
        return [], [], {"id": source.get("id"), "ok": False, "reason": f"no se pudo descomprimir: {exc}"}

    alias_index = build_alias_index(works)
    now = datetime.now(timezone.utc)
    past_days = safe_int(source.get("past_days"), safe_int(os.environ.get("DDV_TV_EPG_PAST_DAYS"), 1))
    future_days = safe_int(source.get("future_days"), safe_int(os.environ.get("DDV_TV_EPG_FUTURE_DAYS"), 14))
    window_start = now - timedelta(days=past_days)
    window_end = now + timedelta(days=future_days)
    channels: Dict[str, str] = {}
    hits: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    parsed_programmes = 0

    try:
        context = ET.iterparse(io.BytesIO(xml), events=("end",))
        for _event, elem in context:
            tag = elem.tag.split("}")[-1]
            if tag == "channel":
                cid = str(elem.attrib.get("id") or "").strip()
                name = xml_text_first(elem, "display-name")
                if cid:
                    channels[cid] = name or cid
                elem.clear()
                continue
            if tag != "programme":
                elem.clear()
                continue
            parsed_programmes += 1
            start = parse_xmltv_datetime(elem.attrib.get("start"))
            stop = parse_xmltv_datetime(elem.attrib.get("stop"))
            if start and (start < window_start or start > window_end):
                elem.clear()
                continue
            title = xml_text_first(elem, "title")
            title_norm = norm_match(title)
            if not title_norm or title_norm not in alias_index:
                elem.clear()
                continue
            duration = None
            if start and stop:
                duration = int(round((stop - start).total_seconds() / 60))
            channel_id = str(elem.attrib.get("channel") or "").strip()
            channel_name = channels.get(channel_id, channel_id)
            desc = xml_text_first(elem, "desc")
            for match in alias_index[title_norm]:
                work = match["work"]
                item = {
                    "slug": work.get("slug"),
                    "work_slug": work.get("slug"),
                    "work_title": work.get("title"),
                    "title": work.get("title"),
                    "programme_title": title,
                    "matched_term": match.get("alias"),
                    "matched_alias": match.get("alias"),
                    "channel": channel_name,
                    "channel_id": channel_id,
                    "channel_number": channel_name,
                    "country": country_code,
                    "country_code": country_code,
                    "country_name": str(source.get("country_name") or source_country_name(country_code)),
                    "start": start.isoformat().replace("+00:00", "Z") if start else "",
                    "start_iso": start.isoformat().replace("+00:00", "Z") if start else "",
                    "stop": stop.isoformat().replace("+00:00", "Z") if stop else "",
                    "end_iso": stop.isoformat().replace("+00:00", "Z") if stop else "",
                    "date_iso": start.date().isoformat() if start else "",
                    "start_time": start.strftime("%H:%M") if start else "",
                    "end_time": stop.strftime("%H:%M") if stop else "",
                    "duration_minutes": duration,
                    "description_sample": desc[:240] if desc else "",
                    "source": provider,
                    "source_url": url,
                    "detection_type": "xmltv_exact_title",
                    "confidence": "medium",
                    "detected_at": now_iso(),
                }
                item["fingerprint"] = epg_hit_fingerprint(item)
                ok, reason = classify_tv_hit(item, work)
                if ok:
                    hits.append(item)
                else:
                    item["review_required"] = True
                    item["review_reason"] = reason
                    review.append(item)
            elem.clear()
    except Exception as exc:
        return hits, review, {"id": source.get("id"), "ok": False, "reason": f"xml parse error: {exc}", "bytes": len(raw)}

    return hits, review, {
        "id": source.get("id"), "ok": True, "provider": provider, "country_code": country_code,
        "url": url, "hits": len(hits), "review": len(review), "channels": len(channels),
        "programmes_parsed": parsed_programmes, "bytes": len(raw), "window_days": {"past": past_days, "future": future_days},
    }


def load_verified_tv_records(works_by_slug: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    data = read_json(TV_VERIFIED_FILE, {"items": []})
    items = data.get("items") if isinstance(data, dict) else []
    out: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or item.get("work_slug") or "")
        work = works_by_slug.get(slug, {})
        copy = dict(item)
        copy.setdefault("work_slug", slug)
        copy.setdefault("work_title", work.get("title") or item.get("title"))
        copy.setdefault("title", work.get("title") or item.get("title"))
        copy.setdefault("source", "Registro verificado DDV")
        copy.setdefault("detected_at", now_iso())
        copy.setdefault("confidence", "high")
        copy.setdefault("fingerprint", tv_fingerprint(copy))
        out.append(copy)
    return out


def scan_tv_sources(works: List[Dict[str, Any]], works_by_slug: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    sources_config = read_json(TV_SOURCES_FILE, {"xmltv_sources": []})
    source_reports: List[Dict[str, Any]] = []
    hits: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []

    hits.extend(load_verified_tv_records(works_by_slug))

    xml_sources = []
    if isinstance(sources_config, dict) and isinstance(sources_config.get("xmltv_sources"), list):
        xml_sources = sources_config["xmltv_sources"]
    enabled_sources = [s for s in xml_sources if isinstance(s, dict) and s.get("enabled", True)]

    countries_env = os.environ.get("DDV_TV_EPG_COUNTRIES", "").strip()
    if countries_env:
        allowed = {x.strip().upper() for x in countries_env.split(",") if x.strip()}
        enabled_sources = [s for s in enabled_sources if str(s.get("country_code") or "").upper() in allowed]

    for src in enabled_sources:
        src_hits, src_review, report = scan_xmltv_source(src, works)
        hits.extend(src_hits)
        review.extend(src_review)
        source_reports.append(report)
        time.sleep(float(os.environ.get("DDV_TV_SOURCE_SLEEP", "0.25")))
    return hits, review, source_reports


def dedupe_tv_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        fp = tv_fingerprint(item)
        if fp in seen:
            continue
        seen.add(fp)
        copy = dict(item)
        copy.setdefault("fingerprint", fp)
        out.append(copy)
    return out


def duration_from_hit(item: Dict[str, Any]) -> Optional[int]:
    raw = item.get("duration_minutes")
    try:
        if raw is not None and str(raw).strip() != "":
            return int(round(float(raw)))
    except Exception:
        pass
    # Si no viene duration_minutes, intentamos calcular con start/stop ISO simple.
    start = str(item.get("start") or item.get("start_iso") or "").replace("Z", "+00:00")
    stop = str(item.get("stop") or item.get("end_iso") or "").replace("Z", "+00:00")
    try:
        if start and stop:
            a = datetime.fromisoformat(start)
            b = datetime.fromisoformat(stop)
            mins = int(round((b - a).total_seconds() / 60))
            return mins if mins > 0 else None
    except Exception:
        return None
    return None


def catalog_map(works: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(w.get("slug")): w for w in works if isinstance(w, dict) and w.get("slug")}


def classify_tv_hit(item: Dict[str, Any], work: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Devuelve (alertable, motivo).

    Regla v200: los cortos solo generan alertas automáticas si la grilla permite
    verificar que la duración no supera el máximo del catálogo. Para Sueño
    Profundo, La Última Cena y El Martillo el máximo es 20 minutos.
    """
    if not isinstance(item, dict):
        return False, "item inválido"
    if not work:
        return True, "sin regla específica de catálogo"

    slug = str(work.get("slug") or item.get("slug") or "")
    work_type = str(work.get("type") or "").lower()
    dur = duration_from_hit(item)
    alias = norm_text(item.get("matched_alias") or item.get("alias") or "")
    title = norm_text(item.get("programme_title") or item.get("program") or item.get("title") or "")
    channel = norm_text(item.get("channel") or "")
    country = norm_text(item.get("country_code") or item.get("country_name") or item.get("country") or "")

    blocked_patterns = [norm_text(x) for x in work.get("blocked_tv_title_patterns") or [] if norm_text(x)]
    for pattern in blocked_patterns:
        if pattern and pattern in title:
            return False, f"patrón bloqueado para {slug}: {pattern}"

    manual_aliases = {norm_text(x) for x in work.get("manual_only_aliases") or [] if norm_text(x)}
    if alias in manual_aliases or title in manual_aliases:
        return False, f"alias de revisión manual para {slug}: {item.get('matched_alias') or item.get('programme_title')}"

    if work_type == "short":
        max_minutes = int(work.get("tv_max_duration_minutes") or 20)
        if dur is None:
            return False, f"cortometraje sin duración verificable; requiere revisión manual <= {max_minutes} min"
        if dur > max_minutes:
            return False, f"cortometraje con duración de grilla incompatible: {dur} min > {max_minutes} min"

    # Bloqueos puntuales defensivos por falsos positivos ya detectados.
    if slug == "el-martillo" and "hammer" in title and dur is not None and dur > 20:
        return False, f"falso positivo probable: El Martillo no coincide con emisión The Hammer de {dur} min ({channel}/{country})"

    if slug == "soy-toxico" and norm_match(title) == "toxic":
        return False, f"falso positivo probable: Soy Tóxico no debe alertar por programa genérico titulado Toxic ({channel}/{country})"

    return True, "alertable"


def filter_tv_hits_for_alerts(tv_hits: List[Dict[str, Any]], works_by_slug: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for hit in tv_hits:
        slug = str(hit.get("slug") or hit.get("work_slug") or "")
        ok, reason = classify_tv_hit(hit, works_by_slug.get(slug))
        if ok:
            accepted.append(hit)
        else:
            copy = dict(hit)
            copy["rejected_by_v199"] = True
            copy["rejection_reason"] = reason
            copy["rejected_at"] = now_iso()
            rejected.append(copy)
    return accepted, rejected


def load_state(path: Path) -> Tuple[set, bool]:
    data = read_json(path, {})
    if isinstance(data, dict) and isinstance(data.get("seen"), list):
        return set(map(str, data["seen"])), False
    return set(), True


def save_state(path: Path, seen: Iterable[str]) -> None:
    write_json(path, {"updated_at": now_iso(), "seen": sorted(set(seen))})


def github_issue(title: str, body: str) -> bool:
    if not (CREATE_ISSUES and GITHUB_TOKEN and GITHUB_REPOSITORY):
        print(f"ISSUE OMITIDO: {title}")
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues"
    payload = json.dumps({"title": title[:240], "body": body}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "DDV-Radar-Cambios/212",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        print(f"No pude crear Issue: {title} / {exc}", file=sys.stderr)
        return False


def issue_platform(item: Dict[str, Any]) -> None:
    title = f"[Radar Plataformas] {item.get('work_title')}: {item.get('name')} — {item.get('country') or item.get('region_code') or item.get('region')}"
    body = "\n".join([
        "Nueva disponibilidad detectada por el radar de plataformas DDV.",
        "",
        f"- Obra: {item.get('work_title')} (`{item.get('slug')}`)",
        f"- Plataforma: {item.get('name')}",
        f"- País/Territorio: {item.get('country') or item.get('region_code') or item.get('region')}",
        f"- Tipo: {item.get('type')}",
        f"- Fuente: {item.get('source')}",
        f"- URL: {item.get('url') or 'sin enlace'}",
        f"- Detectado: {item.get('detected_at') or now_iso()}",
        f"- Fingerprint: `{item.get('fingerprint')}`",
        "",
        "Revisar manualmente antes de difundir comercialmente. TMDb/Watchmode pueden variar por país y fecha.",
    ])
    github_issue(title, body)


def issue_tv(item: Dict[str, Any], fp: str) -> None:
    work_title = item.get("work_title") or item.get("title") or item.get("matched_term") or "Obra DDV"
    channel = item.get("channel") or "TV/Cable"
    country = item.get("country_name") or item.get("country_code") or item.get("country") or ""
    start = item.get("start") or item.get("start_iso") or item.get("date_iso") or ""
    time_label = item.get("start_time") or ""
    title = f"[Radar TV/Cable] {work_title}: {channel} — {country} {start} {time_label}".strip()
    body = "\n".join([
        "Nueva emisión detectada por el radar TV/Cable DDV.",
        "",
        f"- Obra: {work_title} (`{item.get('slug') or item.get('work_slug') or ''}`)",
        f"- Canal/señal: {channel}",
        f"- País/Territorio: {country}",
        f"- Inicio: {start} {time_label}",
        f"- Fin: {item.get('stop') or item.get('end_iso') or item.get('end_time') or ''}",
        f"- Fuente: {item.get('source') or item.get('source_url') or 'sin fuente'}",
        f"- URL: {item.get('source_url') or 'sin enlace'}",
        f"- Fingerprint: `{fp}`",
        "",
        "Revisar la fuente antes de difundir. Si es falso positivo, cerrar el Issue como descartado.",
    ])
    github_issue(title, body)


def main() -> int:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    catalog = read_json(CATALOG_FILE, {"works": []})
    works = catalog.get("works") if isinstance(catalog, dict) else []
    if not isinstance(works, list):
        works = []

    platform_seen, platform_bootstrap = load_state(PLATFORMS_STATE)
    tv_seen, tv_bootstrap = load_state(TV_STATE)
    changes = {"generated_at": now_iso(), "platforms": [], "tv_cable": [], "tv_rejected": [], "bootstrap": {"platforms": platform_bootstrap, "tv_cable": tv_bootstrap}}
    works_by_slug = catalog_map(works)

    by_slug: Dict[str, Any] = {}
    all_platform_items: List[Dict[str, Any]] = []
    watchmode_bootstrap = watchmode_ready() and not PLATFORMS_WATCHMODE_BOOTSTRAP_STATE.is_file()
    watchmode_items_count = 0
    tmdb_items_count = 0

    for work in works:
        if not isinstance(work, dict) or not work.get("slug"):
            continue
        tmdb_result = fetch_platforms_for_work(work)
        watchmode_result = fetch_watchmode_for_work(work)
        result = merge_platform_results(tmdb_result, watchmode_result)
        by_slug[result["slug"]] = result
        current_items = result.get("current") or []
        all_platform_items.extend(current_items)
        tmdb_items_count += len(tmdb_result.get("current") or [])
        watchmode_items_count += len(watchmode_result.get("current") or [])
        time.sleep(0.25)

    current_platform_fps = set()
    for item in all_platform_items:
        slug_for_fp = str(item.get("slug") or "")
        current_platform_fps.add(str(item.get("fingerprint") or platform_fingerprint(slug_for_fp, item)))
        current_platform_fps.add(str(item.get("identity_fingerprint") or platform_identity_fingerprint(slug_for_fp, item)))

    new_platform_items = []
    for item in all_platform_items:
        fp = str(item.get("fingerprint") or platform_fingerprint(str(item.get("slug") or ""), item))
        ident = str(item.get("identity_fingerprint") or platform_identity_fingerprint(str(item.get("slug") or ""), item))
        if fp not in platform_seen and ident not in platform_seen:
            new_platform_items.append(item)

    # v212: seguro anti-spam. Si hay una tanda grande de plataformas nuevas
    # se considera baseline, no novedad comercial. Esto evita cataratas de Issues
    # al sumar Watchmode o al cambiar fingerprints por ajuste interno.
    large_platform_batch = len(new_platform_items) > int(os.environ.get("DDV_PLATFORM_ALERT_BATCH_LIMIT", "5"))
    watchmode_new_batch = any(str(item.get("source") or "").lower() == "watchmode" for item in new_platform_items)
    force_platform_baseline = os.environ.get("DDV_FORCE_PLATFORM_BASELINE", "0").strip().lower() in {"1", "true", "yes", "si", "sí"}

    if platform_bootstrap or watchmode_bootstrap or large_platform_batch or force_platform_baseline:
        if new_platform_items:
            print(f"Baseline plataformas v212: se registran {len(new_platform_items)} detecciones sin crear Issues.")
        write_json(PLATFORMS_WATCHMODE_BOOTSTRAP_STATE, {
            "bootstrapped_at": now_iso(),
            "items_registered": len(new_platform_items),
            "reason": "Baseline/failsafe anti-spam: alta cantidad de plataformas nuevas o Watchmode agregado",
            "platform_bootstrap": platform_bootstrap,
            "watchmode_bootstrap": watchmode_bootstrap,
            "large_platform_batch": large_platform_batch,
            "watchmode_new_batch": watchmode_new_batch,
            "batch_limit": int(os.environ.get("DDV_PLATFORM_ALERT_BATCH_LIMIT", "5")),
        })
    else:
        for item in new_platform_items:
            changes["platforms"].append(item)
            issue_platform(item)

    platform_seen.update(current_platform_fps)
    save_state(PLATFORMS_STATE, platform_seen)

    write_json(PLATFORMS_OUT, {
        "ok": True,
        "version": "v212-radar-platforms-tmdb-watchmode-failsafe-baseline",
        "generated_at": now_iso(),
        "source": "TMDb Watch Providers + Watchmode",
        "sources": {
            "tmdb": {"configured": tmdb_ready(), "items_count": tmdb_items_count},
            "watchmode": {"configured": watchmode_ready(), "items_count": watchmode_items_count, "regions": sorted(watchmode_allowed_regions())},
        },
        "by_slug": by_slug,
        "items_count": len(all_platform_items),
        "note": "Disponibilidad sujeta a variación por territorio y fecha. Verificar antes de difundir. Watchmode se usa como segunda fuente gratuita/práctica cuando el secret está configurado.",
    })

    tv_payload = read_json(TV_OUT, {})
    tv_hits_existing = extract_tv_hits(tv_payload)
    tv_source_hits, tv_source_review, tv_source_reports = scan_tv_sources(works, works_by_slug)
    tv_hits_raw = dedupe_tv_items(tv_hits_existing + tv_source_hits)
    tv_hits, tv_rejected = filter_tv_hits_for_alerts(tv_hits_raw, works_by_slug)
    tv_review = dedupe_tv_items(tv_source_review)
    changes["tv_rejected"] = tv_rejected
    changes["tv_review"] = tv_review

    generated_tv_payload = {
        "ok": True,
        "version": "v212-tv-cable-epgpw-official-sources",
        "generated_at_utc": now_iso(),
        "source": "DDV Radar Cambios v205 + fuentes XMLTV/EPG.PW + registros oficiales verificados",
        "hits_total": len(tv_hits_raw),
        "review_total": len(tv_review),
        "hits": tv_hits_raw,
        "review_hits": tv_review,
        "source_reports": tv_source_reports,
        "note": "Radar de indicios TV/Cable. Las alertas se emiten solo para coincidencias filtradas; las dudosas quedan en revisión.",
    }
    write_json(TV_OUT, generated_tv_payload)

    filtered_payload = dict(generated_tv_payload)
    filtered_payload["hits"] = tv_hits
    filtered_payload["hits_total"] = len(tv_hits)
    filtered_payload["rejected_by_v205"] = tv_rejected
    filtered_payload["version_filter"] = "v205-tv-short-max-20-generic-title-filter"
    filtered_payload["filtered_at"] = now_iso()
    write_json(TV_FILTERED_OUT, filtered_payload)

    write_json(TV_REJECTED_OUT, {
        "ok": True,
        "version": "v212-tv-rejected",
        "generated_at": now_iso(),
        "items": tv_rejected,
        "items_count": len(tv_rejected),
    })
    write_json(TV_REVIEW_OUT, {
        "ok": True,
        "version": "v212-tv-review",
        "generated_at": now_iso(),
        "items": tv_review,
        "items_count": len(tv_review),
    })

    new_tv = []
    current_tv_fps = set()
    for hit in tv_hits:
        fp = tv_fingerprint(hit)
        current_tv_fps.add(fp)
        if fp not in tv_seen:
            new_tv.append((hit, fp))

    epg_bootstrap = not TV_EPG_BOOTSTRAP_STATE.is_file()
    if not tv_bootstrap and not epg_bootstrap:
        for hit, fp in new_tv:
            changes["tv_cable"].append({"fingerprint": fp, "item": hit})
            issue_tv(hit, fp)
    elif new_tv:
        print(f"Bootstrap TV/Cable v205: se registran {len(new_tv)} detecciones existentes sin crear Issues.")
        write_json(TV_EPG_BOOTSTRAP_STATE, {"bootstrapped_at": now_iso(), "items_registered": len(new_tv)})

    tv_seen.update(current_tv_fps)
    save_state(TV_STATE, tv_seen)
    write_json(CHANGE_LOG, changes)

    print(json.dumps({
        "ok": True,
        "platform_items": len(all_platform_items),
        "platform_changes": len(changes["platforms"]),
        "tv_items_raw": len(tv_hits_raw),
        "tv_items_alertable": len(tv_hits),
        "tv_items_rejected": len(tv_rejected),
        "tv_changes": len(changes["tv_cable"]),
        "tmdb_configured": tmdb_ready(),
        "watchmode_configured": watchmode_ready(),
        "watchmode_items": watchmode_items_count,
        "tv_source_reports": len(tv_source_reports),
        "tv_review": len(tv_review),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
