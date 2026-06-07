# DDV v209 — Radar: falso positivo Soy Tóxico + web plataformas

Cambios incluidos:

1. Neutraliza el workflow viejo `radar-mundial.yml` para que no vuelva a crear Issues con el formato anterior.
2. Bloquea el falso positivo `Soy Tóxico / Toxic / Discovery ID` como alerta automática.
3. Actualiza `data/catalog.json` para que `Toxic` quede como alias de revisión/bloqueo, no como coincidencia confiable.
4. Actualiza `distribucion-plataformas.js` para que la web VIP lea primero `api/radar-platforms.php`, que consume el JSON global de GitHub.
5. Cambia el rótulo de TV/Cable de “Lugares registrados” a “Fuentes de este registro”, para evitar confundir fuentes usadas en una ficha con todas las fuentes monitoreadas.

Subir a GitHub:
- `.github/workflows/radar-mundial.yml`
- `scripts/ddv_radar_cambios.py`
- `data/catalog.json`
- `README_v209_Falsos_Positivos_Plataformas_Web.md`

Subir al hosting:
- `public_html/vip/js/distribucion-plataformas.js` → `/public_html/vip/js/distribucion-plataformas.js`
