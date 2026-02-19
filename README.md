# Diario de Chino — SEO-first Blog CMS

CMS ligero para publicar un diario de aprendizaje de mandarín (desde la perspectiva de un hispanohablante), con panel de administración y automatizaciones SEO.

## Stack
- Python 3 (stdlib)
- SQLite
- HTML/CSS/JS vanilla (SSR con `http.server`)

## Funcionalidades principales
- Sitio público mobile-first con búsqueda, categorías, tags, tiempo de lectura y modo oscuro.
- Panel `/admin` con login, creación/edición de posts, borradores, publicación y autosave local.
- Editor estilo Medium (`contenteditable`) con sugerencias SEO en tiempo real.
- Subida de imagen destacada con conversión a WebP en cliente + naming SEO + ALT sugerido.
- Bloqueo de publicación si faltan elementos SEO obligatorios.
- JSON-LD `BlogPosting`, canonical, `robots.txt`, y `sitemap.xml` automático.
- Integración GA4 opcional (`GA4_ID`) y dashboard básico de métricas.
- Arquitectura preparada para extensiones (newsletter, comentarios, multilenguaje, resúmenes IA).

## Categorías preconfiguradas
- Diario de aprendizaje
- Pronunciación
- Gramática básica
- Cultura china
- Recursos y herramientas

## Credenciales admin por defecto
- Usuario: `admin`
- Contraseña: `admin123`

> Cambia estas credenciales en la tabla `users` de SQLite para producción.

## Ejecutar en local
```bash
python3 app.py
```
Abre: `http://localhost:8000`

## Variables de entorno
- `PORT` (default `8000`)
- `BASE_URL` (default `http://localhost:8000`)
- `GA4_ID` (opcional, ejemplo `G-XXXXXXXXXX`)

## Flujo diario para publicar (no programadores)
1. Entra a `/admin/login`.
2. Crea “Nuevo post”.
3. Rellena título, categoría y contenido (incluyendo H1 + H2).
4. Sube imagen destacada (se convierte a WebP automáticamente).
5. Revisa meta title/meta description/ALT.
6. Selecciona `Published` y guarda.
7. Si falta algo SEO, el sistema bloquea la publicación y muestra qué corregir.

## Guía de despliegue (Vercel preferido)
Este proyecto es compatible con despliegue Python en Vercel usando función serverless + almacenamiento externo.

### Opción recomendada
1. Migrar SQLite a PostgreSQL administrado (Neon/Supabase) para persistencia en serverless.
2. Crear adaptador WSGI/ASGI para Vercel Python runtime.
3. Definir variables `BASE_URL`, `GA4_ID`, credenciales.

### Opción simple (rápida)
Desplegar en Render/Fly.io/Railway como servicio Python continuo (mantiene SQLite local del contenedor).

## Estructura
- `app.py` — servidor SSR + API admin + lógica CMS
- `static/` — estilos y scripts
- `uploads/` — imágenes WebP subidas
- `data/blog.db` — base de datos SQLite autogenerada

