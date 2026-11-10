"""Static guard: the two front ends contain no code patterns that make script injection (XSS) possible, and the Content-Security-Policy in deploy/Caddyfile
has not been loosened. A change that adds such a pattern or loosens the policy fails this test and must be argued for in review.
(What the policy does in a real browser is checked by browser_check_csp.py.)
Run: python test_frontend_guards.py"""
import os
import re

ROOT = os.path.join("..")
SRC_DIRS = [os.path.join(ROOT, "frontend", "src"), os.path.join(ROOT, "admin", "src")]


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


files = []
for d in SRC_DIRS:
    for dirpath, _dirs, names in os.walk(d):
        files += [os.path.join(dirpath, n) for n in names if n.endswith((".js", ".jsx", ".ts", ".tsx", ".html"))]
for extra in ("frontend/index.html", "admin/index.html"):
    files.append(os.path.join(ROOT, *extra.split("/")))
ok(len(files) > 20, f"scanning {len(files)} front-end source files")

# patterns that turn text into code or markup (each one is how XSS happens)
BANNED = {
    "dangerouslySetInnerHTML": r"dangerouslySetInnerHTML",
    "innerHTML / outerHTML": r"\b(inner|outer)HTML\b",
    "insertAdjacentHTML": r"insertAdjacentHTML",
    "document.write": r"document\s*\.\s*write",
    "eval()": r"(?<![\w.])eval\s*\(",
    "new Function()": r"new\s+Function\s*\(",
    "string timers (setTimeout('code'))": r"set(Timeout|Interval)\s*\(\s*['\"`]",
    "iframe srcdoc": r"srcdoc",
    "javascript: URLs": r"javascript\s*:",
    "createContextualFragment": r"createContextualFragment",
    "inline event handler attributes in HTML": r"<[a-zA-Z][^>]*\son[a-z]+\s*=\s*[\"']",
    "external script / stylesheet tags": r"<(script|link)[^>]+(src|href)\s*=\s*[\"']https?://",
    "target=_blank without noopener": r"target=\"_blank\"(?![^>]*noopener)",
}
for label, pattern in BANNED.items():
    found = []
    for path in files:
        for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
            if re.search(pattern, line):
                found.append(f"{os.path.relpath(path, ROOT)}:{n}: {line.strip()[:80]}")
    ok(not found, f"no {label}" + ("" if not found else "\n   " + "\n   ".join(found)))

# the policy itself
caddy = open(os.path.join(ROOT, "deploy", "Caddyfile"), encoding="utf-8").read()
m = re.search(r'header Content-Security-Policy "([^"]+)"', caddy)
ok(m is not None, "deploy/Caddyfile sets a Content-Security-Policy for the static sites")
policy = {}
for part in m.group(1).split(";"):
    bits = part.strip().split()
    if bits:
        policy[bits[0]] = bits[1:]
ok(policy.get("default-src") == ["'none'"], "default-src is 'none' (everything not listed is forbidden)")
ok(policy.get("script-src") == ["'self'"], f"script-src is exactly 'self' ({policy.get('script-src')}): no inline scripts, no eval, no other host")
ok(all("'unsafe-eval'" not in v and "'unsafe-inline'" not in v and "*" not in v for k, v in policy.items() if k not in ("style-src-attr",)),
   "no 'unsafe-inline' / 'unsafe-eval' / wildcard anywhere (only style-src-attr may allow inline STYLE attributes)")
ok(policy.get("style-src-attr") == ["'unsafe-inline'"] and policy.get("style-src") == ["'self'"], "inline styles are allowed only as style=\"\" attributes, never <style> blocks")
ok(all(h.startswith(("'self'", "data:", "blob:", "https://{$API_DOMAIN}")) for k in ("connect-src", "img-src", "media-src") for h in policy.get(k, [])),
   f"connect / img / media sources are only self, data:, blob: and the API host (connect-src: {policy.get('connect-src')})")
ok(policy.get("connect-src") == ["https://{$API_DOMAIN}"], "scripts may talk ONLY to the API host (stolen data cannot be sent anywhere else)")
for directive, value in (("base-uri", ["'none'"]), ("form-action", ["'none'"]), ("frame-ancestors", ["'none'"]), ("object-src", ["'none'"])):
    ok(policy.get(directive) == value, f"{directive} is {value[0]}")

print("ALL OK")
