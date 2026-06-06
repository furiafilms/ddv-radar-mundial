#!/usr/bin/env python3
"""
DDV Radar de Cambios v198
- Plataformas: consulta TMDb Watch Providers y genera outputs/site_platforms_global.json.
- TV/Cable: lee outputs/site_tv_cable_global.json si existe y detecta novedades contra estado previo.
- Alertas: crea Issues de GitHub cuando aparecen fingerprints nuevos.

No contiene claves. Usa secretos de GitHub:
- TMDB_BEARER_TOKEN o TMDB_API_KEY para plataformas.
- GITHUB_TOKEN lo provee GitHub Actions.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
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

TMDB_BEARER_TOKEN = os.environ.get("TMDB_BEARER_TOKEN", "").strip()
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
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
    headers = {"Accept": "application/json", "User-Agent": "DDV-Radar-Cambios/198"}
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
            "User-Agent": "DDV-Radar-Cambios/198",
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
        "Revisar manualmente antes de difundir comercialmente. TMDb puede variar por país y fecha.",
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
    changes = {"generated_at": now_iso(), "platforms": [], "tv_cable": [], "bootstrap": {"platforms": platform_bootstrap, "tv_cable": tv_bootstrap}}

    by_slug: Dict[str, Any] = {}
    all_platform_items: List[Dict[str, Any]] = []
    for work in works:
        if not isinstance(work, dict) or not work.get("slug"):
            continue
        result = fetch_platforms_for_work(work)
        by_slug[result["slug"]] = result
        all_platform_items.extend(result.get("current") or [])
        time.sleep(0.25)

    current_platform_fps = {str(item.get("fingerprint") or platform_fingerprint(str(item.get("slug") or ""), item)) for item in all_platform_items}
    new_platform_items = [item for item in all_platform_items if str(item.get("fingerprint") or "") not in platform_seen]

    if not platform_bootstrap:
        for item in new_platform_items:
            changes["platforms"].append(item)
            issue_platform(item)
    elif new_platform_items:
        print(f"Bootstrap plataformas: se registran {len(new_platform_items)} detecciones existentes sin crear Issues.")

    platform_seen.update(current_platform_fps)
    save_state(PLATFORMS_STATE, platform_seen)

    write_json(PLATFORMS_OUT, {
        "ok": True,
        "version": "v198-radar-platforms-daily",
        "generated_at": now_iso(),
        "source": "TMDb Watch Providers",
        "by_slug": by_slug,
        "items_count": len(all_platform_items),
        "note": "Disponibilidad sujeta a variación por territorio y fecha. Verificar antes de difundir.",
    })

    tv_payload = read_json(TV_OUT, {})
    tv_hits = extract_tv_hits(tv_payload)
    new_tv = []
    current_tv_fps = set()
    for hit in tv_hits:
        fp = tv_fingerprint(hit)
        current_tv_fps.add(fp)
        if fp not in tv_seen:
            new_tv.append((hit, fp))

    if not tv_bootstrap:
        for hit, fp in new_tv:
            changes["tv_cable"].append({"fingerprint": fp, "item": hit})
            issue_tv(hit, fp)
    elif new_tv:
        print(f"Bootstrap TV/Cable: se registran {len(new_tv)} detecciones existentes sin crear Issues.")

    tv_seen.update(current_tv_fps)
    save_state(TV_STATE, tv_seen)
    write_json(CHANGE_LOG, changes)

    print(json.dumps({
        "ok": True,
        "platform_items": len(all_platform_items),
        "platform_changes": len(changes["platforms"]),
        "tv_items": len(tv_hits),
        "tv_changes": len(changes["tv_cable"]),
        "tmdb_configured": tmdb_ready(),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
