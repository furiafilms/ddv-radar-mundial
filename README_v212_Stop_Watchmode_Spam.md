# DDV v212 — Stop Watchmode spam / baseline seguro

Corrige la catarata de mails generada al sumar Watchmode como fuente nueva.

## Qué cambia

- Si el radar detecta una tanda grande de plataformas nuevas, registra el estado como baseline.
- No crea Issues masivos por disponibilidades ya existentes.
- Desde corridas futuras solo debería avisar diferencias reales y acotadas.
- No toca la web, FileZilla, prensa ni TV/Cable.

## Archivos

Subir a GitHub:

- scripts/ddv_radar_cambios.py
- README_v212_Stop_Watchmode_Spam.md

## Importante

No usar "Re-run jobs" de corridas viejas. Después de subir v212, ejecutar desde:

Actions > DDV Radar Cambios > Run workflow

