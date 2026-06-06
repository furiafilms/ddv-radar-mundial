# DDV v206 — Plataformas: TMDb + Watchmode

## Objetivo

Sumar Watchmode al radar diario de plataformas sin romper el circuito ya funcionando con TMDb.

## Qué cambia

- El workflow `DDV Radar Cambios` sigue corriendo todos los días a las 08:10 de Argentina.
- TMDb sigue siendo la fuente base.
- Watchmode se suma como segunda fuente cuando existe el secret `WATCHMODE_API_KEY`.
- JustWatch queda como verificación manual / link de consulta, no como API automática.
- No se agrega Streaming Availability API.

## Secret requerido

En GitHub > Settings > Secrets and variables > Actions crear o actualizar:

`WATCHMODE_API_KEY`

Pegar ahí la clave de Watchmode. No ponerla en el chat ni en archivos públicos.

## Primer corrida

La primera corrida con Watchmode activo registra el estado inicial de Watchmode y evita disparar avisos viejos de golpe.

Crea este archivo de control:

`outputs/state_platforms_watchmode_bootstrap_v206.json`

Desde las corridas siguientes, si Watchmode detecta una plataforma/territorio nuevo que no estaba en el estado previo, el workflow puede crear Issue y avisar por mail vía GitHub.

## Outputs

El output principal sigue siendo:

`outputs/site_platforms_global.json`

Ahora queda con:

`version: v206-radar-platforms-tmdb-watchmode-daily`

Incluye estado por fuente:

- `sources.tmdb`
- `sources.watchmode`
- `by_slug.<slug>.source_status.tmdb`
- `by_slug.<slug>.source_status.watchmode`

## Regiones Watchmode monitoreadas

Por defecto:

`AR,US,ES,MX,BR,CL,CO,UY,PE,GB,CA,FR,DE,IT,PT,AU`

Se puede cambiar desde el workflow en `WATCHMODE_REGIONS`.

## Seguridad

No contiene claves. Watchmode se usa solo desde GitHub Secrets.
