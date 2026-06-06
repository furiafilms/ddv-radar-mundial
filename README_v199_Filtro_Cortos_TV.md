# DDV v199 — Filtro TV/Cable para cortos y títulos genéricos

Este parche corrige falsos positivos del radar TV/Cable antes de generar alertas.

## Caso corregido

- `El Martillo` / `The Hammer` / eMovies Sudáfrica / 95 min.
- Motivo: `El Martillo` es cortometraje; una emisión de 95 minutos no debe considerarse coincidencia confiable.

## Qué cambia

- Agrega reglas de duración para cortometrajes en `data/catalog.json`.
- Marca `The Hammer` como alias de revisión manual para `El Martillo`.
- El script `scripts/ddv_radar_cambios.py` ahora filtra detecciones TV/Cable antes de crear Issues.
- Las detecciones descartadas quedan registradas en:
  - `outputs/site_tv_cable_rejected.json`
  - `outputs/radar_change_log.json`
- También genera una versión filtrada:
  - `outputs/site_tv_cable_global_filtered.json`

## Regla principal

Para obras con `type: short`, si la grilla informa duración mayor a `tv_max_duration_minutes`, no se crea Issue automático.

Valor usado por defecto para cortos: `40` minutos.

## Instalación

Subir estos archivos al repo `furiafilms/ddv-radar-mundial` sobrescribiendo los existentes cuando GitHub lo pida:

```text
.github/workflows/ddv-radar-cambios.yml
scripts/ddv_radar_cambios.py
data/catalog.json
README_v199_Filtro_Cortos_TV.md
```

Después ejecutar manualmente:

```text
Actions > DDV Radar Cambios > Run workflow
```

Resultado esperado con el caso `The Hammer` de eMovies: `tv_items_raw: 2`, `tv_items_alertable: 0`, `tv_items_rejected: 2`.

## Importante

Este parche evita que el flujo `DDV Radar Cambios` genere alertas por ese falso positivo. Si el workflow viejo `DDV Radar Mundial` sigue activo y crea Issues por su cuenta antes del filtro, conviene desactivarlo o integrarle este mismo criterio.
