# DDV v205 — TV/Cable EPG.PW + fuentes oficiales verificadas

## Objetivo

Reactivar el radar TV/Cable mundial de forma controlada, sin volver a los falsos positivos del workflow viejo.

## Qué agrega

- Escaneo diario de fuentes XMLTV/EPG.PW configuradas en `data/tv_sources.json`.
- Conservación de registros oficiales/verificados en `data/tv_verified_records.json`.
- Filtros v200/v203 conservados:
  - cortometrajes máximo 20 minutos;
  - duración obligatoria para cortos;
  - alias peligrosos no generan alerta automática;
  - `The Hammer` no alerta por `El Martillo`;
  - `Dead End` no alerta por `Punto Muerto`;
  - `On the 3rd Day` no alerta por `Al 3er Día`.
- Salida nueva de revisión manual:
  - `outputs/site_tv_cable_review.json`

## Archivos

- `.github/workflows/ddv-radar-cambios.yml`
- `scripts/ddv_radar_cambios.py`
- `data/catalog.json`
- `data/tv_sources.json`
- `data/tv_verified_records.json`

## Funcionamiento

El workflow `DDV Radar Cambios` sigue corriendo todos los días a las 08:10 Argentina.

En TV/Cable, ahora:

1. Lee registros verificados/manuales.
2. Descarga fuentes XMLTV habilitadas.
3. Busca coincidencias exactas de título/alias.
4. Filtra falsos positivos.
5. Escribe:
   - `outputs/site_tv_cable_global.json`
   - `outputs/site_tv_cable_global_filtered.json`
   - `outputs/site_tv_cable_rejected.json`
   - `outputs/site_tv_cable_review.json`
6. Crea Issue/mail solo para detecciones nuevas filtradas como alertables.

## Primera corrida

La primera corrida con v205 registra el nuevo universo de fuentes como estado inicial y evita mandar alertas viejas de golpe. Las alertas reales empiezan desde las corridas siguientes.

## Cobertura

Fuentes EPG.PW iniciales:

- US
- GB
- CA
- BR
- DE
- FR
- AU
- ZA

Esto es radar de indicios, no cobertura profesional garantizada. Para cobertura total haría falta proveedor pago tipo Gracenote/TMS.
