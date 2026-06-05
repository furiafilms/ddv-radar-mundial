# ddv-radar-mundial

Radar externo para buscar emisiones de obras de Daniel de la Vega en grillas EPG abiertas y dejar resultados listos para la web DDV.

## Versión v004

- Corre en GitHub Actions dos veces por día.
- Consulta XMLTV público por país desde `epg.pw`.
- Usa un catálogo de títulos y alias verificados/controlados por idioma.
- Evita falsos positivos: los alias genéricos solo cuentan con título exacto + contexto de película.
- Genera dos archivos estables:
  - `outputs/latest_results.json`
  - `outputs/site_tv_cable_global.json`
- Si encuentra coincidencias confiables nuevas, crea un Issue en GitHub para generar aviso.
- Si el repositorio es público, la web DDV puede leer directamente el JSON estable desde GitHub.

## Regla de oro

No se traducen títulos automáticamente. Solo se agregan alias realmente usados o razonablemente documentados.

## Próximo paso web

La web DDV debe leer:

```text
https://raw.githubusercontent.com/furiafilms/ddv-radar-mundial/main/outputs/site_tv_cable_global.json
```

y combinarlo con su caché local/verificado.
