# DDV v200 — Filtro estricto de cortometrajes TV/Cable + nota prensa

Este parche reemplaza la regla v199 de 40 minutos por una regla estricta de 20 minutos para los tres cortometrajes:

- Sueño Profundo
- La Última Cena
- El Martillo

## Regla nueva

Para obras `type: short`, el radar solo puede generar alerta TV/Cable si la duración de grilla es verificable y no supera `tv_max_duration_minutes`.

En el catálogo, los tres cortos quedan con:

```json
"tv_max_duration_minutes": 20
```

Si una detección de corto no trae duración calculable, no se avisa automáticamente: queda descartada/revisión manual para evitar falsos positivos.

## El Martillo / The Hammer

`The Hammer` sigue marcado como alias de revisión manual para El Martillo. No debe disparar alertas automáticas.

## Prensa

Este parche no agrega monitor de prensa. El workflow actual `DDV Radar Cambios` cubre plataformas y TV/Cable. Si el monitor de prensa existe en otro workflow viejo, hay que revisarlo aparte o integrarlo en una v201.

## Instalación

Subir al repo `furiafilms/ddv-radar-mundial` sobrescribiendo:

```text
.github/workflows/ddv-radar-cambios.yml
scripts/ddv_radar_cambios.py
data/catalog.json
README_v200_Filtro_Cortos_Max20_y_Prensa.md
```

Luego ejecutar:

```text
Actions > DDV Radar Cambios > Run workflow
```
