# DDV v210 — Push seguro del radar

Corrige el fallo de GitHub Actions `failed to push some refs` / `fetch first`.

El radar sí corría bien, pero fallaba al guardar resultados si el repositorio recibía otro commit mientras el workflow estaba ejecutándose.

Esta versión modifica solamente:

- `.github/workflows/ddv-radar-cambios.yml`

Cambio aplicado:

- antes de guardar outputs, el workflow copia los JSON generados a una carpeta temporal;
- sincroniza el repo con `origin/main`;
- restaura los outputs generados;
- hace commit y push sobre la última versión remota.

No cambia lógica de detección, catálogo, filtros ni web.
