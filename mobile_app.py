"""Installable-app support (PWA) for the APlus dashboard: web manifest, service worker and the snippet that wires them into every page.

On Android (Chrome) over HTTPS the page can be installed with "Add to Home screen / Install app": own icon, full screen, no browser bar.
The service worker never caches live data (/api/*) - a stale price or P&L is worse than none. If the PC cannot be reached the app shows a
plain "not connected" page instead of old numbers.
"""

from __future__ import annotations

import json

MANIFEST = {
    "name": "APlus Trading Terminal", "short_name": "APlus", "description": "APlus F&O paper-trading terminal",
    "start_url": "/", "scope": "/", "display": "standalone", "orientation": "any",
    "background_color": "#0b1020", "theme_color": "#0b1020",
    "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
              {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}],
}

SERVICE_WORKER = r"""
const CACHE = 'aplus-shell-v1';
const OFFLINE = '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><body style="background:#0b1020;color:#e7eefc;font:16px system-ui;padding:32px;text-align:center"><h2>Not connected</h2><p>The phone cannot reach the APlus PC. Check that Tailscale is connected on this phone, then pull down to retry.</p><p><a style="color:#4c8dff" href="/">Retry</a></p></body>';
self.addEventListener('install', e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then(c => c.addAll(['/static/icon-192.png', '/static/icon-512.png', '/static/lightweight-charts.js']).catch(() => {}))); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  if (u.pathname.startsWith('/api/')) return;                         // live data: always straight from the PC, never cached
  if (u.pathname.startsWith('/static/')) { e.respondWith(caches.match(e.request).then(r => r || fetch(e.request))); return; }
  if (e.request.mode === 'navigate') { e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, {headers: {'Content-Type': 'text/html; charset=utf-8'}}))); }
});
"""

PWA_SNIPPET = """<script>(function(){try{var h=document.head;if(!document.querySelector('link[rel=manifest]')){var l=document.createElement('link');l.rel='manifest';l.href='/manifest.webmanifest';h.appendChild(l);
var t=document.createElement('meta');t.name='theme-color';t.content='#0b1020';h.appendChild(t);var a=document.createElement('link');a.rel='apple-touch-icon';a.href='/static/icon-192.png';h.appendChild(a)}
if('serviceWorker' in navigator&&(location.protocol==='https:'||location.hostname==='localhost'))navigator.serviceWorker.register('/sw.js').catch(function(){})}catch(e){}})();</script>"""


def effective_remote(headers, client_ip: str) -> str:
    """The address to treat the caller as. A reverse proxy such as `tailscale serve` connects from 127.0.0.1 on behalf of a remote
    phone; those requests carry proxy headers, so they must never count as 'this PC' (LIVE can only be armed from this PC)."""
    for name in ("Tailscale-User-Login", "X-Forwarded-For", "Forwarded"):
        if headers.get(name):
            return "proxied-remote"
    return client_ip


def manifest_json() -> bytes:
    return json.dumps(MANIFEST).encode("utf-8")


def make_icons(static_dir) -> None:
    """Draws the two app icons (dark tile, white 'A+', green underline). Needs Pillow; the PNGs are committed so this is only for regeneration."""
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFont

    static_dir = Path(static_dir)
    for size in (192, 512):
        img = Image.new("RGB", (size, size), "#0b1020")
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([size * 0.06, size * 0.06, size * 0.94, size * 0.94], radius=size * 0.18, fill="#121a2d", outline="#27334d", width=max(2, size // 100))
        font = None
        for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(name, int(size * 0.46))
                break
            except OSError:
                continue
        font = font or ImageFont.load_default()
        text = "A+"
        box = d.textbbox((0, 0), text, font=font)
        w, h = box[2] - box[0], box[3] - box[1]
        d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1] - size * 0.03), text, fill="#e7eefc", font=font)
        d.rounded_rectangle([size * 0.28, size * 0.74, size * 0.72, size * 0.78], radius=size * 0.02, fill="#2ecc71")
        img.save(static_dir / f"icon-{size}.png")
