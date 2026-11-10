"""Browser check of the cookie sessions: drives a real (headless) Chrome over the DevTools protocol against the REAL running apps and checks what only a
browser enforces (httpOnly / SameSite / CORS with credentials / what JavaScript can see). The unit tests (test_cookie_sessions.py) cannot check these.

Needs the normal development setup running: the API on :8000, the user app on :3000, the admin app on :3001, Chrome installed, and one normal and one
admin account of YOUR dev database. Run it from backend/ :
    CHECK_USER_EMAIL=... CHECK_USER_PW=... CHECK_ADMIN_EMAIL=... CHECK_ADMIN_PW=... python browser_check_cookies.py
It starts its own tiny web server on a free port as the "other site" and its own headless Chrome (with a throw-away profile); it logs in and out
with the accounts you give it. Exit code 0 = every check passed. Last run 2026-11-10: 31 of 31."""
import http.server
import json
import os
import tempfile
import threading
import subprocess
import sys
import time
import urllib.request

from websockets.sync.client import connect

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = tempfile.mkdtemp(prefix="chrome-profile-")
PORT = 9333
USER = (os.environ["CHECK_USER_EMAIL"], os.environ["CHECK_USER_PW"])
ADMIN = (os.environ["CHECK_ADMIN_EMAIL"], os.environ["CHECK_ADMIN_PW"])
results = []


class _Other(http.server.BaseHTTPRequestHandler):   # the "other site": a different origin AND a different site (127.0.0.1 is not localhost)
    def do_GET(self):
        body = b"<html><body>other site</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


_srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Other)   # port 0 = any free port (a fixed one may already be in use)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
OTHER = f"http://127.0.0.1:{_srv.server_address[1]}/"


def check(cond, msg):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg, flush=True)


proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check",
                         "--disable-gpu", "--disable-extensions", "--window-size=1280,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    def call(method, params=None):
        seq[0] += 1
        ws.send(json.dumps({"id": seq[0], "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv(timeout=60))
            if msg.get("id") == seq[0]:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg["result"]

    def js(expr):
        r = call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
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
            time.sleep(0.4)
        return False

    def go(url):
        call("Page.navigate", {"url": url})
        time.sleep(1.0)

    def cookies():
        return {c["name"]: c for c in call("Network.getAllCookies")["cookies"]}

    def sign_in(email, password):
        assert wait("!!document.querySelector('input[type=password]')"), "login form did not appear"
        js("""(async () => {
          const set = (el, v) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true})); };
          set(document.querySelector('input[type=email]'), %s); set(document.querySelector('input[type=password]'), %s);
          document.querySelector('form').requestSubmit(); return true; })()""" % (json.dumps(email), json.dumps(password)))

    call("Network.enable")
    call("Page.enable")

    # ---------------- 1. the user app ----------------
    go("http://localhost:3000/")
    js("localStorage.clear()")
    go("http://localhost:3000/")
    check(wait("!!document.querySelector('input[type=password]')"), "user app: the sign-in screen appears when there is no session")
    sign_in(*USER)
    check(wait("document.body.innerText.includes('testuser@example.com') || !!document.querySelector('nav, aside')", 30), "user app: signed in through the real form (cookie mode)")
    time.sleep(1.5)
    ck = cookies()
    s = ck.get("session")
    check(s is not None, "the browser stored a 'session' cookie")
    if s:
        check(s["httpOnly"] is True, f"cookie is HttpOnly (httpOnly={s['httpOnly']})")
        check(s["sameSite"] == "Strict", f"cookie is SameSite=Strict (sameSite={s['sameSite']})")
        check(s["path"] == "/api", f"cookie path is /api ({s['path']})")
    check("session" not in (js("document.cookie") or ""), "JavaScript cannot see the session cookie (document.cookie has no 'session')")
    ls = js("JSON.stringify(Object.assign({}, localStorage))")
    check("token" not in (ls or "").lower() and "eyJ" not in (ls or ""), f"nothing token-like in localStorage ({ls})")
    check("eyJ" not in (js("document.documentElement.outerHTML") or ""), "no JWT anywhere in the page's HTML")

    # a page reload keeps the user signed in (cookie survives, csrf recovered through /me)
    go("http://localhost:3000/")
    check(wait("!document.querySelector('input[type=password]') && document.body.innerText.length > 50", 30), "after a page reload the user is still signed in")

    # what a script running in the user's page can and cannot do
    r = js("fetch('http://localhost:8000/api/auth/me', {credentials: 'include'}).then(async r => [r.status, (await r.json()).email])")
    check(r == [200, USER[0]], f"the page itself can call the API with the cookie ({r})")
    r = js("fetch('http://localhost:8000/api/jobs/nope/cancel', {method: 'POST', credentials: 'include'}).then(r => r.status)")
    check(r == 403, f"a state-changing call without the CSRF token is refused ({r})")
    r = js("fetch('http://localhost:8000/api/admin/overview', {credentials: 'include', headers: {'X-Audience': 'admin'}}).then(r => r.status)")
    check(r in (401, 403), f"a script in the USER app cannot use the admin API, even asking for the admin audience ({r})")
    r = js("fetch('http://localhost:8000/api/admin/overview', {credentials: 'include'}).then(r => r.status)")
    check(r in (401, 403), f"... nor without it ({r})")

    # the app's own renewal (what the 10-minute timer does) rotates the cookie
    before = cookies()["session"]["value"]
    js("document.dispatchEvent(new Event('visibilitychange'))")
    time.sleep(2.0)
    after = cookies()["session"]["value"]
    check(before != after, "the app's renewal replaced the session cookie with a fresh one")
    check(wait("!document.querySelector('input[type=password]')", 5), "... and the user stayed signed in")

    # ---------------- 2. a different site cannot use the session ----------------
    go(OTHER)
    r = js("fetch('http://localhost:8000/api/auth/me', {credentials: 'include'}).then(r => 'status ' + r.status).catch(e => 'blocked: ' + e.message)")
    check(str(r).startswith("blocked"), f"another site (127.0.0.1) cannot read the answer with the user's cookie ({r})")
    r = js("fetch('http://localhost:8000/api/jobs/nope/cancel', {method: 'POST', credentials: 'include', headers: {'X-CSRF-Token': 'guess'}}).then(r => 'status ' + r.status).catch(e => 'blocked: ' + e.message)")
    check(str(r).startswith("blocked"), f"... nor change anything ({r})")
    r = js("fetch('http://localhost:8000/api/auth/me').then(r => 'status ' + r.status).catch(e => 'blocked: ' + e.message)")
    check(str(r).startswith("blocked"), f"... and a plain request without cookies gets no CORS permission either ({r})")

    # ---------------- 3. log out (the server must delete the httpOnly cookie) ----------------
    go("http://localhost:3000/")
    wait("!document.querySelector('input[type=password]') && document.body.innerText.length > 50", 30)
    clicked = js("""(() => { const b = [...document.querySelectorAll('button')].find(x => /log ?out|ထွက်/i.test(x.innerText)); if (b) { b.click(); return true } return false })()""")
    if not clicked:   # on a narrow layout the log-out button lives in the drawer
        js("(() => { const b = document.querySelector('button[aria-label], header button'); if (b) b.click() })()")
        time.sleep(0.5)
        clicked = js("""(() => { const b = [...document.querySelectorAll('button')].find(x => /log ?out|ထွက်/i.test(x.innerText)); if (b) { b.click(); return true } return false })()""")
    check(clicked, "found the log-out button")
    time.sleep(1.5)
    check("session" not in cookies(), "after log-out the browser no longer has the session cookie (the server deleted it)")
    check(wait("!!document.querySelector('input[type=password]')", 10), "... and the sign-in screen is back")

    # ---------------- 4. the admin dashboard ----------------
    go("http://localhost:3001/")
    sign_in(*ADMIN)
    check(wait("!document.querySelector('input[type=password]') && document.body.innerText.length > 100", 30), "admin app: signed in through the real form")
    time.sleep(1.5)
    ck = cookies()
    a = ck.get("admin_session")
    check(a is not None and a["httpOnly"] and a["sameSite"] == "Strict", f"admin_session cookie: httpOnly + SameSite=Strict ({a and (a['httpOnly'], a['sameSite'])})")
    check("session" not in ck or ck["session"]["name"] == "session" and "admin_session" in ck, "(the normal-app cookie is separate)")
    check("admin_session" not in (js("document.cookie") or ""), "JavaScript cannot see the admin cookie")
    ls = js("JSON.stringify(Object.assign({}, localStorage))")
    check("admin_token" not in (ls or "") and "eyJ" not in (ls or ""), f"nothing token-like in the admin app's localStorage ({ls})")
    check(wait("/overview|users|jobs/i.test(document.body.innerText)", 15), "admin pages load (data fetched with the cookie)")
    r = js("fetch('http://localhost:8000/api/admin/overview', {credentials: 'include', headers: {'X-Audience': 'admin'}}).then(r => r.status)")
    check(r == 200, f"the dashboard's own calls work ({r})")

    # the same admin cookie used from the USER app's origin
    go("http://localhost:3000/")
    time.sleep(1.0)
    r = js("fetch('http://localhost:8000/api/admin/overview', {credentials: 'include', headers: {'X-Audience': 'admin'}}).then(async r => [r.status, (await r.json()).detail])")
    check(isinstance(r, list) and r[0] == 403, f"a script in the USER app cannot ride the admin's cookie: {r}")

    # admin log-out
    go("http://localhost:3001/")
    wait("document.body.innerText.length > 100", 20)
    clicked = js("""(() => { const b = [...document.querySelectorAll('button')].find(x => /log ?out|ထွက်/i.test(x.innerText)); if (b) { b.click(); return true } return false })()""")
    time.sleep(1.5)
    check(clicked and "admin_session" not in cookies(), "admin log-out: the cookie is gone")
finally:
    try:
        ws.close()
    except Exception:
        pass
    proc.terminate()
    _srv.shutdown()

print(f"\n{sum(results)} of {len(results)} browser checks passed")
sys.exit(0 if all(results) else 1)
