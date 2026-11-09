# Movie Recap Tool · Admin

Separate app (own build, own sub-domain, e.g. `admin.example.com`) for the owner: overview, users, videos (jobs), voice
models (Gemini quotas), audit log, settings. It talks to the same backend as the main app (`/api/admin/*`, admin accounts only).

## Run (dev)
```bash
cd admin
cp .env.example .env     # VITE_API_BASE, optional VITE_APP_URL
npm install
npm run dev              # http://localhost:3001
```
Sign in with an admin account: `cd backend && python manage.py create-user EMAIL PASSWORD --admin`.

## Deploy
`npm run build` -> static files in `dist/`; serve them on the admin sub-domain (any static host, behind HTTPS).
Build with `VITE_API_BASE=https://api.example.com`. The backend must allow the origin:
`CORS_ORIGINS=https://app.example.com,https://admin.example.com`. Optional hardening: restrict the admin sub-domain
(IP allow-list / VPN / basic auth at the proxy); the API already refuses non-admins.

## Layout
`src/App.jsx` sign-in gate · `src/Admin.jsx` shell (sidebar / phone drawer) · `src/*Page.jsx` one file per page ·
`src/ui.jsx` shared pieces + data hook · `src/i18n.jsx` + `src/strings.js` Myanmar/English (AI-written Burmese, needs native review).
