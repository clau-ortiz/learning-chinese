import html
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "blog.db"
SESSIONS = {}
APP_NAME = "Diario de Chino"
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
GA4_ID = os.getenv("GA4_ID", "")

DEFAULT_CATEGORIES = [
    "Diario de aprendizaje",
    "Pronunciación",
    "Gramática básica",
    "Cultura china",
    "Recursos y herramientas",
]


def ensure_dirs():
    DATA_DIR.mkdir(exist_ok=True)
    UPLOADS_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            slug TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            slug TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            excerpt TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            category_id INTEGER,
            featured_image TEXT,
            featured_image_alt TEXT,
            meta_title TEXT,
            meta_description TEXT,
            canonical_url TEXT,
            seo_keyword TEXT,
            read_time INTEGER DEFAULT 1,
            author_name TEXT DEFAULT 'Admin',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            published_at TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );
        CREATE TABLE IF NOT EXISTS post_tags (
            post_id INTEGER,
            tag_id INTEGER,
            PRIMARY KEY(post_id, tag_id),
            FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            path TEXT,
            event_type TEXT,
            value INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        """
    )
    c.execute("SELECT id FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users(username, password) VALUES (?, ?)", ("admin", "admin123"))
    for cat in DEFAULT_CATEGORIES:
        slug = slugify(cat)
        c.execute("INSERT OR IGNORE INTO categories(name, slug) VALUES (?, ?)", (cat, slug))
    conn.commit()
    conn.close()


def slugify(value: str):
    v = value.lower().strip()
    v = re.sub(r"[^a-z0-9áéíóúñ\s-]", "", v)
    v = v.replace("ñ", "n")
    v = re.sub(r"\s+", "-", v)
    return re.sub(r"-+", "-", v).strip("-") or "post"


def strip_html(s: str):
    return re.sub(r"<[^>]*>", "", s)


def reading_time_minutes(content: str):
    words = max(1, len(strip_html(content).split()))
    return max(1, round(words / 220))


def excerpt_from(content: str):
    text = strip_html(content).strip()
    return (text[:157] + "...") if len(text) > 160 else text


def validate_headings(content: str):
    return bool(re.search(r"<h1[\s>]", content, re.I)) and bool(re.search(r"<h2[\s>]", content, re.I))


def seo_guard(payload):
    missing = []
    if not payload.get("title"):
        missing.append("title")
    if not payload.get("content"):
        missing.append("content")
    if not payload.get("meta_title"):
        missing.append("meta_title")
    if not payload.get("meta_description"):
        missing.append("meta_description")
    if not payload.get("featured_image_alt"):
        missing.append("featured_image_alt")
    if not validate_headings(payload.get("content", "")):
        missing.append("headings(H1/H2)")
    return missing


def base_layout(title, body, description="", canonical="", extra_head="", ga=True):
    theme_script = """
<script>
(() => {
  const mode = localStorage.getItem('theme') || 'light';
  document.documentElement.dataset.theme = mode;
})();
</script>
"""
    ga_script = f"""
<script async src=\"https://www.googletagmanager.com/gtag/js?id={GA4_ID}\"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());
gtag('config', '{GA4_ID}');
</script>
""" if ga and GA4_ID else ""
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>
<title>{html.escape(title)}</title><meta name='description' content='{html.escape(description)}'/>{f"<link rel='canonical' href='{canonical}'/>" if canonical else ''}
<link rel='stylesheet' href='/static/style.css'/>{extra_head}{theme_script}{ga_script}</head><body>
<header class='site-header'><a href='/' class='logo'>{APP_NAME}</a><nav><a href='/'>Inicio</a><a href='/about'>Autor</a><a href='/admin'>Admin</a><button id='themeToggle'>🌓</button></nav></header>
<main>{body}</main><footer>Aprender chino, un día a la vez.</footer>
<script src='/static/app.js'></script></body></html>"""


def json_ld(post):
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["title"],
        "description": post["meta_description"] or excerpt_from(post["content"]),
        "datePublished": post["published_at"],
        "dateModified": post["updated_at"],
        "author": {"@type": "Person", "name": post["author_name"]},
        "image": f"{BASE_URL}/uploads/{post['featured_image']}" if post["featured_image"] else None,
        "mainEntityOfPage": f"{BASE_URL}/post/{post['slug']}"
    })


class Handler(BaseHTTPRequestHandler):
    def send_html(self, content, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def send_json(self, payload, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def parse_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length).decode("utf-8")
        return parse_qs(data)

    def current_user(self):
        raw = self.headers.get("Cookie", "")
        c = cookies.SimpleCookie(); c.load(raw)
        token = c.get("session")
        if token and token.value in SESSIONS:
            return SESSIONS[token.value]
        return None

    def require_auth(self):
        if not self.current_user():
            self.redirect("/admin/login")
            return False
        return True

    def redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.end_headers()

    def track(self, path, event_type, post_id=None, value=0):
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO analytics(post_id,path,event_type,value,created_at) VALUES(?,?,?,?,?)", (post_id, path, event_type, value, datetime.utcnow().isoformat()))
        conn.commit(); conn.close()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith('/static/'):
            fp = STATIC_DIR / path.replace('/static/', '')
            if fp.exists():
                ct = 'text/css' if fp.suffix == '.css' else 'application/javascript'
                self.send_response(200); self.send_header('Content-Type', ct); self.end_headers(); self.wfile.write(fp.read_bytes()); return
        if path.startswith('/uploads/'):
            fp = UPLOADS_DIR / path.replace('/uploads/', '')
            if fp.exists():
                ct = 'image/webp' if fp.suffix == '.webp' else 'application/octet-stream'
                self.send_response(200); self.send_header('Content-Type', ct); self.end_headers(); self.wfile.write(fp.read_bytes()); return

        if path == '/robots.txt':
            self.send_response(200); self.send_header('Content-Type', 'text/plain'); self.end_headers(); self.wfile.write(f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n".encode()); return
        if path == '/sitemap.xml':
            conn = db(); posts = conn.execute("SELECT slug, updated_at FROM posts WHERE status='published'").fetchall(); conn.close()
            items = "".join([f"<url><loc>{BASE_URL}/post/{p['slug']}</loc><lastmod>{p['updated_at']}</lastmod></url>" for p in posts])
            xml = f"<?xml version='1.0' encoding='UTF-8'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>{BASE_URL}/</loc></url>{items}</urlset>"
            self.send_response(200); self.send_header('Content-Type', 'application/xml'); self.end_headers(); self.wfile.write(xml.encode()); return

        if path == '/':
            conn = db()
            q = query.get('q', [''])[0].strip()
            sql = "SELECT p.*, c.name AS category_name FROM posts p LEFT JOIN categories c ON c.id=p.category_id WHERE p.status='published'"
            args = []
            if q:
                sql += " AND (p.title LIKE ? OR p.content LIKE ?)"
                args.extend([f"%{q}%", f"%{q}%"])
            posts = conn.execute(sql + " ORDER BY datetime(p.published_at) DESC", args).fetchall()
            cats = conn.execute("SELECT * FROM categories ORDER BY name").fetchall(); conn.close()
            cards = "".join([f"<article class='card'><a href='/post/{p['slug']}'><h2>{html.escape(p['title'])}</h2></a><p>{html.escape(p['excerpt'] or '')}</p><small>{p['category_name'] or ''} · {p['read_time']} min</small></article>" for p in posts]) or "<p>No hay publicaciones aún.</p>"
            cats_html = " ".join([f"<a class='chip' href='/category/{c['slug']}'>{c['name']}</a>" for c in cats])
            body = f"<section><h1>Diario de aprendizaje de chino</h1><form><input name='q' placeholder='Buscar posts...' value='{html.escape(q)}'/><button>Buscar</button></form><div>{cats_html}</div><div class='grid'>{cards}</div></section>"
            self.track('/', 'pageview')
            self.send_html(base_layout(APP_NAME, body, 'Blog para aprender mandarín desde cero en español.', f"{BASE_URL}/")); return

        if path.startswith('/post/'):
            slug = unquote(path.split('/post/', 1)[1])
            conn = db()
            post = conn.execute("SELECT p.*, c.name category_name FROM posts p LEFT JOIN categories c ON c.id=p.category_id WHERE p.slug=? AND p.status='published'", (slug,)).fetchone()
            tags = conn.execute("SELECT t.* FROM tags t JOIN post_tags pt ON pt.tag_id=t.id WHERE pt.post_id=?", (post['id'],)).fetchall() if post else []
            conn.close()
            if not post:
                self.send_html(base_layout("No encontrado", "<h1>Post no encontrado</h1>"), 404); return
            tag_html = " ".join([f"<a class='chip' href='/tag/{t['slug']}'>#{t['name']}</a>" for t in tags])
            img = f"<img src='/uploads/{post['featured_image']}' alt='{html.escape(post['featured_image_alt'] or post['title'])}' class='featured'/>" if post['featured_image'] else ''
            schema = f"<script type='application/ld+json'>{json_ld(post)}</script>"
            body = f"<article><h1>{html.escape(post['title'])}</h1><p class='meta'>{post['category_name'] or ''} · {post['read_time']} min · {post['published_at'][:10]}</p>{img}<div class='content'>{post['content']}</div><div>{tag_html}</div><section class='author'><h3>Sobre el autor</h3><p>Aprendiz hispanohablante construyendo hábitos de estudio de mandarín.</p></section></article>"
            self.track(path, 'pageview', post['id'])
            self.send_html(base_layout(post['meta_title'] or post['title'], body, post['meta_description'] or '', post['canonical_url'] or f"{BASE_URL}{path}", schema)); return

        if path.startswith('/category/') or path.startswith('/tag/'):
            kind = 'category' if path.startswith('/category/') else 'tag'
            slug = path.split(f'/{kind}/',1)[1]
            conn = db()
            if kind == 'category':
                entity = conn.execute("SELECT * FROM categories WHERE slug=?", (slug,)).fetchone()
                posts = conn.execute("SELECT * FROM posts WHERE status='published' AND category_id=?", (entity['id'],)).fetchall() if entity else []
            else:
                entity = conn.execute("SELECT * FROM tags WHERE slug=?", (slug,)).fetchone()
                posts = conn.execute("SELECT p.* FROM posts p JOIN post_tags pt ON pt.post_id=p.id WHERE p.status='published' AND pt.tag_id=?", (entity['id'],)).fetchall() if entity else []
            conn.close()
            cards = "".join([f"<article class='card'><a href='/post/{p['slug']}'><h2>{p['title']}</h2></a><p>{p['excerpt'] or ''}</p></article>" for p in posts]) or "<p>Sin resultados.</p>"
            self.send_html(base_layout(entity['name'] if entity else 'No encontrado', f"<h1>{entity['name'] if entity else 'No encontrado'}</h1>{cards}")); return

        if path == '/about':
            self.send_html(base_layout("Sobre el autor", "<h1>Hola, soy un estudiante de chino desde cero</h1><p>Este blog documenta estrategias prácticas para hispanohablantes.</p>")); return

        if path == '/admin/login':
            body = """<section class='admin'><h1>Admin Login</h1><form method='post' action='/admin/login'><input name='username' placeholder='Usuario'/><input type='password' name='password' placeholder='Contraseña'/><button>Entrar</button></form></section>"""
            self.send_html(base_layout('Login', body, ga=False)); return

        if path == '/admin/logout':
            raw = self.headers.get("Cookie", "")
            c = cookies.SimpleCookie(); c.load(raw)
            token = c.get("session")
            if token and token.value in SESSIONS: SESSIONS.pop(token.value)
            self.send_response(302); self.send_header('Location', '/admin/login'); self.send_header('Set-Cookie', 'session=; Path=/; Max-Age=0'); self.end_headers(); return

        if path == '/admin' or path == '/admin/posts':
            if not self.require_auth(): return
            conn = db(); posts = conn.execute("SELECT p.*, c.name category_name FROM posts p LEFT JOIN categories c ON c.id=p.category_id ORDER BY datetime(updated_at) DESC").fetchall(); conn.close()
            rows = ''.join([f"<tr><td>{p['title']}</td><td>{p['status']}</td><td>{p['category_name'] or ''}</td><td><a href='/admin/edit/{p['id']}'>Editar</a></td></tr>" for p in posts])
            body = f"<section class='admin'><h1>Panel</h1><a href='/admin/new'>+ Nuevo post</a> | <a href='/admin/analytics'>Analytics</a> | <a href='/admin/categories'>Categorías/Tags</a> | <a href='/admin/logout'>Salir</a><table><tr><th>Título</th><th>Estado</th><th>Categoría</th><th></th></tr>{rows}</table></section>"
            self.send_html(base_layout('Admin', body, ga=False)); return

        if path == '/admin/new' or path.startswith('/admin/edit/'):
            if not self.require_auth(): return
            post = None
            conn = db(); cats = conn.execute("SELECT * FROM categories ORDER BY name").fetchall(); tags = conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
            selected = []
            if path.startswith('/admin/edit/'):
                pid = int(path.split('/admin/edit/')[1]); post = conn.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone();
                selected = [r['tag_id'] for r in conn.execute('SELECT tag_id FROM post_tags WHERE post_id=?', (pid,)).fetchall()]
            conn.close()
            opts = ''.join([f"<option value='{c['id']}' {'selected' if post and post['category_id']==c['id'] else ''}>{c['name']}</option>" for c in cats])
            tag_checks = ''.join([f"<label><input type='checkbox' name='tags' value='{t['id']}' {'checked' if t['id'] in selected else ''}/> {t['name']}</label>" for t in tags])
            body = f"""<section class='admin'><h1>{'Editar' if post else 'Nuevo'} post</h1>
<form method='post' action='/admin/save' id='postForm'>
<input type='hidden' name='id' value='{post['id'] if post else ''}'/>
<label>Título<input name='title' value='{html.escape(post['title'] if post else '')}'/></label>
<label>Slug<input name='slug' value='{html.escape(post['slug'] if post else '')}'/></label>
<label>Keyword SEO<input name='seo_keyword' value='{html.escape(post['seo_keyword'] if post else '')}'/></label>
<label>Categoría<select name='category_id'>{opts}</select></label>
<label>Tags<div class='tag-grid'>{tag_checks}</div></label>
<label>Meta title<input name='meta_title' value='{html.escape(post['meta_title'] if post else '')}'/></label>
<label>Meta description<textarea name='meta_description'>{html.escape(post['meta_description'] if post and post['meta_description'] else '')}</textarea></label>
<label>Canonical URL<input name='canonical_url' value='{html.escape(post['canonical_url'] if post and post['canonical_url'] else '')}'/></label>
<label>Excerpt<textarea name='excerpt'>{html.escape(post['excerpt'] if post and post['excerpt'] else '')}</textarea></label>
<label>Imagen destacada WebP<input type='file' id='featuredImage' accept='image/*'/><input type='hidden' name='featured_image'/></label>
<label>ALT de imagen<input name='featured_image_alt' value='{html.escape(post['featured_image_alt'] if post and post['featured_image_alt'] else '')}'/></label>
<label>Contenido</label><div id='editor' contenteditable='true' class='editor'>{post['content'] if post else '<h1>Título del artículo</h1><h2>Introducción</h2><p>Empieza aquí...</p>'}</div>
<textarea name='content' id='contentInput' hidden></textarea>
<label>Estado<select name='status'><option value='draft' {'selected' if not post or post['status']=='draft' else ''}>Draft</option><option value='published' {'selected' if post and post['status']=='published' else ''}>Published</option></select></label>
<button type='submit'>Guardar</button><button type='button' id='autosave'>Autosave</button>
</form><div id='seoTips'></div></section>"""
            self.send_html(base_layout('Editor', body, ga=False, extra_head="<script src='/static/editor.js'></script>")); return

        if path == '/admin/categories':
            if not self.require_auth(): return
            conn = db(); cats = conn.execute("SELECT * FROM categories").fetchall(); tags = conn.execute("SELECT * FROM tags").fetchall(); conn.close()
            chtml = ''.join([f"<li>{c['name']}</li>" for c in cats]); thtml = ''.join([f"<li>{t['name']}</li>" for t in tags])
            body = f"<section class='admin'><h1>Categorías y tags</h1><form method='post' action='/admin/category/add'><input name='name' placeholder='Nueva categoría'/><button>Agregar</button></form><ul>{chtml}</ul><form method='post' action='/admin/tag/add'><input name='name' placeholder='Nuevo tag'/><button>Agregar</button></form><ul>{thtml}</ul></section>"
            self.send_html(base_layout('Categorías', body, ga=False)); return

        if path == '/admin/analytics':
            if not self.require_auth(): return
            conn = db()
            top = conn.execute("SELECT p.title, COUNT(a.id) views FROM analytics a JOIN posts p ON p.id=a.post_id WHERE a.event_type='pageview' GROUP BY p.title ORDER BY views DESC LIMIT 10").fetchall()
            total = conn.execute("SELECT COUNT(*) c FROM analytics WHERE event_type='pageview'").fetchone()['c']
            conn.close()
            rows = ''.join([f"<tr><td>{r['title']}</td><td>{r['views']}</td></tr>" for r in top])
            body = f"<section class='admin'><h1>Analytics</h1><p>Visitas totales: {total}</p><table><tr><th>Post</th><th>Visitas</th></tr>{rows}</table></section>"
            self.send_html(base_layout('Analytics', body, ga=False)); return

        self.send_html(base_layout('404', '<h1>No encontrado</h1>'), 404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/admin/login':
            form = self.parse_body()
            username = form.get('username', [''])[0]
            password = form.get('password', [''])[0]
            conn = db(); user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone(); conn.close()
            if not user:
                self.send_html(base_layout('Login', '<p>Credenciales inválidas</p><a href="/admin/login">Volver</a>', ga=False), 401); return
            token = secrets.token_hex(24); SESSIONS[token] = username
            self.send_response(302); self.send_header('Location', '/admin'); self.send_header('Set-Cookie', f'session={token}; Path=/; HttpOnly'); self.end_headers(); return

        if path in ['/admin/category/add', '/admin/tag/add']:
            if not self.require_auth(): return
            form = self.parse_body(); name = form.get('name', [''])[0].strip()
            table = 'categories' if 'category' in path else 'tags'
            conn = db(); conn.execute(f"INSERT OR IGNORE INTO {table}(name, slug) VALUES(?,?)", (name, slugify(name))); conn.commit(); conn.close()
            self.redirect('/admin/categories'); return

        if path == '/admin/save':
            if not self.require_auth(): return
            form = self.parse_body()
            data = {k: v[0] for k, v in form.items() if k != 'tags'}
            tags = [int(x) for x in form.get('tags', [])]
            title = data.get('title', '').strip()
            slug = slugify(data.get('slug') or title)
            content = data.get('content', '')
            status = data.get('status', 'draft')
            now = datetime.utcnow().isoformat()
            payload = {
                'title': title, 'content': content, 'meta_title': data.get('meta_title') or title,
                'meta_description': data.get('meta_description') or excerpt_from(content),
                'featured_image_alt': data.get('featured_image_alt') or f"{title} aprendizaje chino",
            }
            if status == 'published':
                missing = seo_guard(payload)
                if missing:
                    self.send_html(base_layout('SEO bloqueado', f"<h1>No se puede publicar</h1><p>Faltan: {', '.join(missing)}</p>", ga=False), 422); return
            conn = db(); c = conn.cursor()
            if data.get('id'):
                pid = int(data['id'])
                c.execute("""UPDATE posts SET title=?, slug=?, content=?, excerpt=?, status=?, category_id=?, featured_image=?, featured_image_alt=?,
                           meta_title=?, meta_description=?, canonical_url=?, seo_keyword=?, read_time=?, updated_at=?, published_at=COALESCE(published_at,?) WHERE id=?""",
                          (title, slug, content, data.get('excerpt') or excerpt_from(content), status, data.get('category_id') or None, data.get('featured_image') or None,
                           payload['featured_image_alt'], payload['meta_title'], payload['meta_description'], data.get('canonical_url') or f"{BASE_URL}/post/{slug}",
                           data.get('seo_keyword') or '', reading_time_minutes(content), now, now if status == 'published' else None, pid))
                c.execute('DELETE FROM post_tags WHERE post_id=?', (pid,))
            else:
                c.execute("""INSERT INTO posts(title,slug,content,excerpt,status,category_id,featured_image,featured_image_alt,meta_title,meta_description,canonical_url,seo_keyword,read_time,created_at,updated_at,published_at)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (title, slug, content, data.get('excerpt') or excerpt_from(content), status, data.get('category_id') or None, data.get('featured_image') or None,
                           payload['featured_image_alt'], payload['meta_title'], payload['meta_description'], data.get('canonical_url') or f"{BASE_URL}/post/{slug}",
                           data.get('seo_keyword') or '', reading_time_minutes(content), now, now, now if status == 'published' else None))
                pid = c.lastrowid
            for tid in tags:
                c.execute('INSERT OR IGNORE INTO post_tags(post_id, tag_id) VALUES(?,?)', (pid, tid))
            conn.commit(); conn.close()
            self.redirect('/admin/posts'); return

        if path == '/admin/upload-image':
            if not self.require_auth(): return
            length = int(self.headers.get('Content-Length', '0'))
            raw = self.rfile.read(length)
            name = self.headers.get('X-File-Name', f'image-{int(time.time())}.webp')
            safe = slugify(Path(name).stem) + '.webp'
            (UPLOADS_DIR / safe).write_bytes(raw)
            self.send_json({'filename': safe}); return

        self.send_json({'error': 'Not found'}, 404)


def write_static():
    (STATIC_DIR / 'style.css').write_text("""
:root{--bg:#f7f7f5;--fg:#1f2428;--muted:#666;--card:#fff;--accent:#2d5a88}html[data-theme='dark']{--bg:#17191c;--fg:#eceff1;--muted:#a5aab0;--card:#202329;--accent:#8ab4f8}
*{box-sizing:border-box}body{font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0;line-height:1.7}.site-header{position:sticky;top:0;display:flex;justify-content:space-between;padding:1rem 1.5rem;background:var(--bg);border-bottom:1px solid #ddd}.logo{text-decoration:none;color:var(--fg);font-weight:700}
main{max-width:860px;margin:0 auto;padding:1rem}footer{text-align:center;color:var(--muted);padding:2rem}.grid{display:grid;gap:1rem}.card{background:var(--card);padding:1rem;border-radius:12px}.chip{display:inline-block;padding:.2rem .6rem;background:var(--card);border-radius:999px;text-decoration:none;color:var(--accent);margin:.25rem 0}
input,textarea,select,button{width:100%;padding:.7rem;margin:.3rem 0;border-radius:8px;border:1px solid #ccc;background:var(--card);color:var(--fg)}button{cursor:pointer}.admin label{display:block}.tag-grid{display:flex;gap:.8rem;flex-wrap:wrap}.editor{min-height:260px;border:1px solid #ccc;border-radius:8px;padding:1rem;background:var(--card)}table{width:100%;border-collapse:collapse}td,th{border:1px solid #ccc;padding:.5rem}.featured{width:100%;border-radius:12px}
@media(max-width:700px){.site-header nav{display:flex;gap:.5rem;align-items:center}.site-header{padding:.75rem}}
""")
    (STATIC_DIR / 'app.js').write_text("""
document.getElementById('themeToggle')?.addEventListener('click',()=>{const c=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=c;localStorage.setItem('theme',c)});
""")
    (STATIC_DIR / 'editor.js').write_text("""
const form=document.getElementById('postForm');
const editor=document.getElementById('editor');
const contentInput=document.getElementById('contentInput');
const titleInput=form?.querySelector('input[name="title"]');
const slugInput=form?.querySelector('input[name="slug"]');
const excerptInput=form?.querySelector('textarea[name="excerpt"]');
const seoTips=document.getElementById('seoTips');
const featured=document.getElementById('featuredImage');
const hiddenImage=form?.querySelector('input[name="featured_image"]');

if(form){
  titleInput?.addEventListener('input',()=>{ if(!slugInput.value){ slugInput.value=titleInput.value.toLowerCase().normalize('NFD').replace(/[^\w\s-]/g,'').replace(/\s+/g,'-'); }});
  form.addEventListener('submit',()=>{contentInput.value=editor.innerHTML; if(!excerptInput.value){excerptInput.value=editor.innerText.slice(0,160);} });
  const suggest=()=>{const txt=editor.innerText; const words=txt.split(/\s+/).filter(Boolean); const heads=editor.querySelectorAll('h2').length; let msg=`Palabras: ${words.length}. `; if(heads<2) msg+='Añade más H2 para SEO. '; if(!editor.querySelector('h1')) msg+='Falta H1. '; msg+='Sugerencia enlaces internos: /category/diario-de-aprendizaje'; seoTips.innerText=msg;};
  editor.addEventListener('input', suggest); suggest();
  document.getElementById('autosave')?.addEventListener('click',()=>{contentInput.value=editor.innerHTML; localStorage.setItem('draft_'+(slugInput.value||'new'), JSON.stringify(Object.fromEntries(new FormData(form)))); alert('Borrador guardado en navegador');});
  const key='draft_'+(slugInput.value||'new'); const draft=localStorage.getItem(key); if(draft && !form.querySelector('input[name="id"]').value){const d=JSON.parse(draft); for(const [k,v] of Object.entries(d)){const el=form.querySelector(`[name="${k}"]`); if(el) el.value=v;} if(d.content) editor.innerHTML=d.content;}
  featured?.addEventListener('change', async (e)=>{const file=e.target.files[0]; if(!file) return; const img=await createImageBitmap(file); const canvas=document.createElement('canvas'); canvas.width=img.width; canvas.height=img.height; const ctx=canvas.getContext('2d'); ctx.drawImage(img,0,0); canvas.toBlob(async(blob)=>{const seoName=(slugInput.value||titleInput.value||'image').toLowerCase().replace(/\s+/g,'-')+'.webp'; const res=await fetch('/admin/upload-image',{method:'POST',headers:{'X-File-Name':seoName},body:blob}); const j=await res.json(); hiddenImage.value=j.filename; const alt=form.querySelector('input[name="featured_image_alt"]'); if(!alt.value){alt.value='Imagen destacada: '+(titleInput.value||'aprendizaje de chino');} }, 'image/webp', 0.8);
  });
}
""")


if __name__ == '__main__':
    ensure_dirs()
    write_static()
    init_db()
    port = int(os.getenv('PORT', '8000'))
    print(f"Running on http://localhost:{port}")
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
