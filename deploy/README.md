# Putting Movie Recap Tool on the internet (HTTPS, limits, CSP)

`Caddyfile` + `docker-compose.proxy.yml` add an HTTPS reverse proxy in front of the API and serve the two front ends as static files.
Caddy gets and renews the certificates itself (Let's Encrypt), so there is nothing to install on the server except Docker.

```
browser ──HTTPS──> Caddy ──> app.example.com    static files  frontend/dist
                         ──> admin.example.com  static files  admin/dist      (optionally only from your office / VPN)
                         ──> api.example.com    reverse proxy  api:8000  ──> Redis, Postgres, workers
```

## Steps
1. **DNS:** three names (for example `app.`, `admin.`, `api.` + your domain) pointing at the server's public address. Ports 80 and 443 open.
2. **Backend settings** (`backend/.env`, see `backend/.env.example`). These matter for security, none has a safe default for production:
   - `SECRET_KEY` (long random string), `DATABASE_URL` (Postgres), `REDIS_URL` (also shares the login limits between workers), `STORAGE_BACKEND`.
   - `POSTGRES_PASSWORD` and `REDIS_PASSWORD` (shell env or a `.env` next to `docker-compose.yml`): `docker compose up` refuses to start without
     them. Redis has no password in the base image; without `REDIS_PASSWORD` anything on the compose network could read/write the job queue and
     the login rate-limit counters. `mem_limit` is set on every service so one bad upload can't take down the whole host.
   - `TRUSTED_PROXIES`: the compose override sets it for you (`172.16.0.0/12`). Without it every visitor looks like the proxy and shares one login limit.
   - `CORS_ORIGINS` and `ADMIN_ORIGINS`: the override sets them from `APP_DOMAIN` and `ADMIN_DOMAIN`. Logins are **httpOnly cookies** (not a token in
     `localStorage`), and the two apps share the API's cookie jar, so the API accepts admin sessions only from `ADMIN_ORIGINS`. Without that
     variable the admin dashboard cannot sign in.
   - **The three host names must share one registrable domain** (`app.example.com`, `admin.example.com`, `api.example.com`): the cookies are
     `SameSite=Strict`, which browsers only send between hosts of the same site. With unrelated domains (`myapp.com` + `my-api.net`) logins silently
     fail. Cookies are `Secure` automatically because Caddy tells the API the request was HTTPS (`X-Forwarded-Proto`, trusted through `TRUSTED_PROXIES`).
   - `ADMIN_ALLOWED_IPS` (optional): your office / VPN addresses; everyone else gets 404 on `/api/admin/*`.
   - `ALLOW_SIGNUP`, `SIGNUP_*`, `GLOBAL_DAILY_MINUTES` and the admin Settings budget gate: decide how open sign-up is BEFORE you announce the site.
3. **Build the front ends** against the API host (the address is baked into the files):
   ```
   (cd frontend && npm ci && VITE_API_BASE=https://api.example.com npm run build)
   (cd admin && npm ci && VITE_API_BASE=https://api.example.com VITE_APP_URL=https://app.example.com npm run build)
   ```
4. **Start:**
   ```
   export POSTGRES_PASSWORD=... APP_DOMAIN=app.example.com ADMIN_DOMAIN=admin.example.com API_DOMAIN=api.example.com ACME_EMAIL=you@example.com
   docker compose -f docker-compose.yml -f deploy/docker-compose.proxy.yml up -d --build
   ```
   The override also removes the API's own published port (8000), so the only way in is through Caddy.
5. **Create the first admin:** `docker compose exec api python manage.py create-user EMAIL PASSWORD --admin`.

## What is enforced where
| Protection | Proxy (Caddy) | API (`guard.py`, `ratelimit.py`) |
|---|---|---|
| HTTPS, redirect from http | yes (automatic) | no (the proxy terminates TLS) |
| HSTS, nosniff, no framing, no referrer | yes, all three hosts | yes, on `/api/*` answers |
| Body size | login 64 KB, everything else `MAX_UPLOAD_BODY_MB` (1049) | login 64 KB, JSON 4 MB, upload `MAX_UPLOAD_MB` + 25 MB; upload needs a login before its body is read |
| Content-Security-Policy | the two static sites (below) | JSON answers (`default-src 'none'`) |
| Real client address | replaces any `X-Forwarded-For` the client sends | believes it only from `TRUSTED_PROXIES` |
| Admin only from known addresses | optional (commented block) | optional (`ADMIN_ALLOWED_IPS`) |

Keep `MAX_UPLOAD_BODY_MB` equal to `MAX_UPLOAD_MB` + 25 (the API's limit); the proxy limit is only the first wall.

## The Content-Security-Policy for the two apps
```
default-src 'none'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline';
img-src 'self' data: blob: <API>; media-src 'self' blob: <API>; connect-src <API>; font-src 'self';
manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'
```
Why it is this tight: the built apps load one script and one stylesheet from their own host, no CDN, no web fonts, no inline scripts. So a page may run
ONLY its own script (an injected `<script>` or `onclick=` is refused) and may talk ONLY to the API host (stolen data cannot be sent elsewhere).
The login token lives in `localStorage`, so this is the main protection against it being stolen by an injected script.
The two loosenings are on purpose: `blob:` (the preview of the video / logo you picked) and `style-src-attr 'unsafe-inline'` (React sets `style="..."` for the dragged logo and blur boxes).

**If you add something that loads from elsewhere** (a font, an analytics script, an embedded video) the browser will refuse it and print `Refused to ...`
in the console: add exactly that host to the matching directive, never `*` or `'unsafe-inline'` for scripts.

## What was tested, and what was not
Tested on 2026-11-10 with the real Caddy image against a stand-in API (nothing public): the Caddyfile validates, `docker compose config` accepts the override,
a login body over 64 KB and an upload over the limit get `413`, normal requests pass, a forged `X-Forwarded-For` is replaced by the real address,
the headers and CSP are sent, hashed files are cached as immutable, deep links fall back to the app, the admin site is `noindex`.

**The CSP was tested in a real browser** (2026-11-10, `backend/browser_check_csp.py`: headless Chrome against the apps served by this Caddyfile over HTTPS with the
hardened backend image behind it, 25 of 25 checks): normal use of both apps (sign-in, `blob:` video and logo previews, the usage page, all 8 admin pages)
produces **0 policy violations**; 15 injection attempts (inline / external script, `eval`, `new Function`, `onerror`, `javascript:`, and fetch / image /
beacon / WebSocket / stylesheet / iframe / object / form / `<base>` to an attacker's server) are all blocked and the attacker's server received nothing.
A control with the policy switched off in the same page shows the same attacks DO work without it. Re-run it after any change to the policy or the apps
(`python browser_check_csp.py`, see its docstring); `test_frontend_guards.py` fails if the policy is loosened or an XSS-prone code pattern is added.
Not covered: the editor page (needs a finished video, which costs a Gemini run), other browsers, a real domain.

**Not tested:** real certificates (needs public DNS) and the full stack with Postgres / Redis / workers. Note for your own tests: with `--read-only` a root-owned
`tmpfs` mounted on `/app/data`, `/app/uploads` or `/app/outputs` is NOT writable by the app user; use named volumes like `docker-compose.yml` does.

## Other proxies (nginx etc.)
Same rules: `client_max_body_size 1049m;` (and `64k` in `location /api/auth/`), `proxy_set_header X-Forwarded-For $remote_addr;` (REPLACE, do not append
`$proxy_add_x_forwarded_for`, or clients can forge their address), `add_header Content-Security-Policy "..." always;` on the static sites,
and `proxy_request_buffering off;` on `/api/jobs`: nginx otherwise reads the WHOLE upload to disk before the API sees the first byte, which defeats the API's
"log in first, then send the body" check (`guard.py`) and lets anyone fill your disk. Caddy streams request bodies by default, so it needs nothing extra. Set `TRUSTED_PROXIES` to the nginx address.
