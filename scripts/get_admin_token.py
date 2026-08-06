#!/usr/bin/env python3
"""
Obtain an Admin API access token for a Dev Dashboard app, with no hosting.

Shopify has retired legacy custom apps on newer stores, so there is no
"reveal token" button any more — a Dev Dashboard app only gives you a client
ID and secret, and the token is issued through OAuth to the app's backend.
This script *is* that backend, briefly: it serves a redirect URL on localhost,
captures the authorisation code, and exchanges it for a permanent offline
access token.

Setup, once, in the Dev Dashboard for the app:
  1. Add this exact redirect URL:  http://localhost:3456/callback
  2. Copy the client ID and client secret.
  3. Put them in .env.live (git-ignored):

       SHOPIFY_STORE_DOMAIN=kinetic-motorcycles.myshopify.com
       SHOPIFY_CLIENT_ID=...
       SHOPIFY_CLIENT_SECRET=...

Then:  python3 scripts/get_admin_token.py --env .env.live

It prints a URL to open, waits for you to approve, then writes
SHOPIFY_ADMIN_TOKEN back into the same file. The token is never printed in
full and never leaves this machine.
"""
import argparse, hashlib, hmac, http.server, json, os, secrets, ssl
import urllib.error, urllib.parse, urllib.request, webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Only what the migration actually needs. Deliberately no customer, order,
# discount or financial scopes — a live store holds real personal data.
SCOPES = ",".join([
    "read_products", "write_products",
    "read_inventory", "write_inventory",
    "read_locations",
    "read_publications", "write_publications",
    "read_content", "write_content",
    "read_online_store_navigation", "write_online_store_navigation",
    "read_themes", "write_themes",
])


def ssl_context():
    for p in ('/etc/ssl/cert.pem', '/opt/homebrew/etc/openssl@3/cert.pem'):
        if os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    return ssl.create_default_context()


def load_env(path):
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def write_env_value(path, key, value):
    lines, found = [], False
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            if line.strip().startswith(key + '='):
                lines.append(f'{key}={value}\n')
                found = True
            else:
                lines.append(line)
    if not found:
        if lines and not lines[-1].endswith('\n'):
            lines.append('\n')
        lines.append(f'{key}={value}\n')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.writelines(lines)


def normalize(domain):
    d = domain.strip().rstrip('/')
    for p in ('https://', 'http://'):
        if d.startswith(p):
            d = d[len(p):]
    return d.split('/')[0]


def verify_hmac(params, secret):
    """Shopify signs the callback; reject anything we cannot verify."""
    supplied = params.get('hmac', [''])[0]
    if not supplied:
        return False
    rest = {k: v[0] for k, v in params.items() if k not in ('hmac', 'signature')}
    msg = '&'.join(f'{k}={rest[k]}' for k in sorted(rest))
    digest = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, supplied)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default=os.path.join(ROOT, '.env.live'))
    ap.add_argument('--port', type=int, default=3456)
    args = ap.parse_args()

    env = load_env(args.env)
    shop = normalize(env.get('SHOPIFY_STORE_DOMAIN', ''))
    cid = env.get('SHOPIFY_CLIENT_ID', '')
    csec = env.get('SHOPIFY_CLIENT_SECRET', '')
    missing = [k for k, v in (('SHOPIFY_STORE_DOMAIN', shop),
                              ('SHOPIFY_CLIENT_ID', cid),
                              ('SHOPIFY_CLIENT_SECRET', csec)) if not v]
    if missing:
        raise SystemExit(f"missing in {args.env}: {', '.join(missing)}\n"
                         f"See the header of this file for setup.")

    redirect = f"http://localhost:{args.port}/callback"
    state = secrets.token_urlsafe(24)
    auth_url = (f"https://{shop}/admin/oauth/authorize?"
                + urllib.parse.urlencode({
                    "client_id": cid, "scope": SCOPES,
                    "redirect_uri": redirect, "state": state,
                    "grant_options[]": "",           # empty = offline, permanent
                }))

    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != '/callback':
                self.send_response(404); self.end_headers(); return
            q = urllib.parse.parse_qs(parsed.query)
            if q.get('state', [''])[0] != state:
                # A callback from an earlier attempt, still queued in the
                # browser. Ignore it and keep waiting rather than aborting —
                # `result` stays empty so the serve loop continues.
                print("  (ignored a callback from a previous attempt)")
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b"<h2>Stale callback ignored.</h2>"
                                 b"<p>Open the newest URL from the terminal.</p>")
                return
            if not verify_hmac(q, csec):
                result['error'] = 'HMAC verification failed — callback not from Shopify'
            elif not q.get('code'):
                result['error'] = f"no code in callback: {parsed.query[:200]}"
            else:
                result['code'] = q['code'][0]
            ok = 'error' not in result
            body = (b"<h2>Authorised.</h2><p>Token captured. You can close this tab.</p>"
                    if ok else
                    b"<h2>Failed.</h2><p>Check the terminal.</p>")
            self.send_response(200 if ok else 400)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.HTTPServer(('localhost', args.port), Handler)
    print(f"store    : {shop}")
    print(f"redirect : {redirect}")
    print(f"scopes   : {SCOPES.count(',') + 1} requested (no customer/order access)\n")
    print("Open this URL in a browser signed in as the store owner:\n")
    print(f"  {auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    print("waiting for the callback ... (Ctrl-C to abort)")
    # Serve until the callback actually lands. A single handle_request() would
    # be consumed by the browser's favicon probe and exit empty-handed.
    srv.timeout = 300
    while not result:
        srv.handle_request()
        if not result:
            print("  (ignored a non-callback request, still waiting)")
    srv.server_close()

    if 'error' in result:
        raise SystemExit("FAILED: " + result['error'])

    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": csec, "code": result['code'],
    }).encode()
    req = urllib.request.Request(f"https://{shop}/admin/oauth/access_token",
                                 data=body, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=45, context=ssl_context()) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"token exchange failed HTTP {e.code}: "
                         f"{e.read().decode(errors='replace')[:300]}")

    token = payload.get('access_token')
    if not token:
        raise SystemExit(f"no access_token in response: {json.dumps(payload)[:200]}")

    write_env_value(args.env, 'SHOPIFY_ADMIN_TOKEN', token)
    granted = payload.get('scope', '')
    print(f"\ntoken written to {args.env}")
    print(f"  prefix  : {token[:6]}…{token[-4:]}  (len {len(token)})")
    print(f"  granted : {granted}")
    missing_scopes = [s for s in SCOPES.split(',') if s not in granted.split(',')]
    if missing_scopes:
        print(f"  WARNING : not granted -> {', '.join(missing_scopes)}")


if __name__ == '__main__':
    main()
