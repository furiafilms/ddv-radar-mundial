# DDV v211 — Watchmode baseline sin spam

Corrige el aluvión de Issues/mails generado al sumar Watchmode como segunda fuente.

## Problema

El estado previo de plataformas estaba basado principalmente en TMDb. Al activar Watchmode, el radar interpretó todas las disponibilidades existentes de Watchmode como novedades reales y creó un Issue por cada una.

## Corrección

- Si Watchmode está configurado y todavía no existe `outputs/state_platforms_watchmode_bootstrap_v206.json`, la corrida registra todo lo encontrado como baseline.
- No crea Issues durante ese baseline inicial.
- Actualiza `outputs/state_platforms_seen.json` con fingerprints TMDb + Watchmode.
- Las corridas futuras sí alertan cambios nuevos reales.

## Archivos

Subir a GitHub:

- `scripts/ddv_radar_cambios.py`
- `README_v211_Watchmode_Baseline_Sin_Spam.md`

No tocar hosting ni FileZilla.
