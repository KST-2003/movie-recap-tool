# Recat Studio website (marketing site)

Its own small app (Vite + React + Tailwind), separate from `frontend/` (the app people log in to) and `admin/` (owner dashboard).
Pages: Home (hero with animated phone demo, how it works, features, stats, price teaser, FAQ), Pricing, About, Contact, Privacy, Terms, 404.
English + Burmese (switch in the header, or a link like `/?lang=my`). The Burmese text is AI-written: have a native speaker read it.
Privacy and Terms are English only on purpose and describe how the service works today: have a lawyer review them (and add a governing law).

## Run
```
cd website && npm install && npm run dev      # http://localhost:3002
npm run build                                 # dist/
```

## Before launch: edit `src/site.config.js`
- `contact` (email, Telegram, Facebook, phone, hours): empty values are hidden. With no email the Contact page shows "details coming soon" and no form.
  With an email, the form opens the visitor's email app addressed to it (no backend, nothing is stored).
- `appUrl` (where "Log in" / "Open Recat Studio" go), `pricePerMinuteTHB` and `packs` (keep equal to admin Settings -> Pricing), `updated` (date on Privacy / Terms).
- Text lives in `src/content.js` (both languages). Mascot art is copied from `frontend/public/` (`recat*.webp`, `recat-icon.png`).

## Deploy (static files + one Nginx rule)
Build, copy `dist/` to the server, and let every path fall back to `index.html` (the site uses real URLs like `/pricing`):
```
location / { root /var/www/recat-site; try_files $uri $uri/ /index.html; }
```
Use its own domain / sub-domain and certificate (certbot) like the other two apps.
