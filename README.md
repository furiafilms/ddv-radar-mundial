# ddv-radar-mundial

Radar externo experimental para buscar emisiones de obras de Daniel de la Vega en grillas EPG abiertas.

## Qué hace esta versión v002

- Corre en GitHub Actions.
- Consulta XMLTV público por país desde epg.pw.
- Busca coincidencias por títulos y alias configurados en `data/catalogo.json`.
- Filtra falsos positivos: no usa descripciones largas para confirmar emisiones.
- Separa `hits` confiables de `review_hits` débiles.
- No crea Issues por coincidencias débiles.
- No toca Neolo.
- No usa FTP.
- No usa claves TMDb.
- No modifica la web pública.

## Importante

La v001 detectó falsos positivos por alias genéricos como `Dead End` y `On the 3rd Day` dentro de descripciones o episodios de otros programas. La v002 es más conservadora: mejor perder una coincidencia dudosa que avisar una emisión falsa.

## Cómo correrlo manualmente

1. Entrar en la pestaña **Actions**.
2. Elegir **DDV Radar Mundial**.
3. Botón **Run workflow**.
4. Esperar la corrida.
5. Revisar si se creó un Issue o descargar el artefacto `ddv-radar-results`.

## Países iniciales

Estados Unidos, Canadá, México, Argentina, Uruguay, Chile, Colombia, Perú, Brasil, España, Reino Unido, Francia, Alemania e Italia.
