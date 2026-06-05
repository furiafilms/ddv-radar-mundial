# ddv-radar-mundial

Radar externo experimental para buscar emisiones de obras de Daniel de la Vega en grillas EPG abiertas.

## Qué hace la versión v003

- Corre en GitHub Actions.
- Consulta XMLTV público por país desde epg.pw.
- Mantiene filtros estrictos: no usa descripciones largas para confirmar emisiones.
- Separa coincidencias confiables (`hits`) de coincidencias dudosas (`review_hits`).
- Amplía cobertura territorial por bloques:
  - Estados Unidos
  - Norteamérica
  - Latinoamérica
  - Europa
  - Resto del mundo
- Genera un payload preparado para futura integración con la web: `web_payload` dentro de `latest_results.json`.
- También escribe `outputs/site_tv_cable_global.json`, útil para la futura conexión web.
- No toca Neolo.
- No usa FTP todavía.
- No usa claves TMDb todavía.

## Criterio

La v003 prefiere no detectar nada antes que crear falsos positivos. Una coincidencia confiable exige título exacto o subtítulo con contexto claro de película.

## Cómo correrlo manualmente

1. Entrar en la pestaña **Actions**.
2. Elegir **DDV Radar Mundial**.
3. Botón **Run workflow**.
4. Esperar la corrida.
5. Descargar el artefacto `ddv-radar-results` y revisar `latest_results.json`.

## Cuándo se pasa a la web

Después de validar v003/v004. La web no debe investigar: solo debe leer JSON ya generado por GitHub. El paso web será una integración pasiva: GitHub produce JSON, la web DDV lo muestra dentro de TV/Cable.

Para conectar automáticamente con la web hará falta una de estas dos opciones:

1. FTP restringido a `/public_html/vip/cache/radar-tv/`.
2. Otra vía de publicación JSON controlada.

No conviene usar la clave principal de cPanel/FTP.

## Países iniciales

Estados Unidos, Canadá, México, Argentina, Uruguay, Chile, Colombia, Perú, Brasil, Bolivia, Paraguay, Ecuador, Venezuela, Costa Rica, Panamá, República Dominicana, Guatemala, El Salvador, Honduras, Nicaragua, España, Reino Unido, Francia, Alemania, Italia, Portugal, Países Bajos, Bélgica, Suiza, Austria, Irlanda, Polonia, Suecia, Noruega, Dinamarca, Finlandia, Australia, Nueva Zelanda y Sudáfrica.
