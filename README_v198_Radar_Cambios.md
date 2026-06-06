# DDV v198 — Radar de Cambios TV/Cable + Plataformas

Este paquete agrega una capa de control diario para avisar novedades.

## Qué hace

- Consulta plataformas desde TMDb Watch Providers.
- Genera `outputs/site_platforms_global.json` para que la web VIP lo lea.
- Lee `outputs/site_tv_cable_global.json` si ya existe en el repo.
- Compara contra estados guardados:
  - `outputs/state_platforms_seen.json`
  - `outputs/state_tv_seen.json`
- Crea un GitHub Issue cuando aparece una plataforma/territorio nuevo o una emisión TV/Cable nueva.

## Qué NO hace

- No usa FTP.
- No contiene claves.
- No consulta theatrical/salas.
- No garantiza cobertura mundial absoluta.

## Secretos necesarios

En GitHub: `Settings > Secrets and variables > Actions > New repository secret`.

Cargar al menos uno:

- `TMDB_BEARER_TOKEN`, recomendado; o
- `TMDB_API_KEY`.

No pegarlos en ChatGPT ni en archivos públicos.

## Primera corrida

La primera corrida es de arranque: registra lo que ya existe y evita crear Issues masivos por datos viejos.

Desde la segunda corrida, si aparece algo nuevo, crea Issue.

## Notificación por mail

Para recibir email:

1. En el repo `furiafilms/ddv-radar-mundial`, activar `Watch > All Activity`.
2. En la cuenta de GitHub, revisar `Settings > Notifications` y confirmar email activo para Issues.

## Archivo que consume la web

La web VIP intentará leer:

`https://raw.githubusercontent.com/furiafilms/ddv-radar-mundial/main/outputs/site_platforms_global.json`

Si el repo está privado, esa URL no funcionará. En ese caso hay que mantener repo público o usar otra publicación pública del JSON.
