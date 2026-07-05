"""One-time interactive TikTok login for OpenMontage.

Prereqs (user-managed — this script runs NO tunnel):
  1. TikTok developer app with Login Kit + Content Posting API, scope video.publish.
  2. TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in .env / .env.local.
  3. TIKTOK_REDIRECT_URI in .env.local — an HTTPS URL registered in the app's
     Login Kit settings (TikTok rejects localhost). Point that domain at this
     machine's callback port yourself (reverse proxy, tunnel, etc.).
  4. Optional TIKTOK_CALLBACK_PORT (default 8917) — the local port this script
     listens on and your domain forwards to.

Usage:
  python3 scripts/tiktok_login.py            # browser OAuth, saves tokens
  python3 scripts/tiktok_login.py --status   # show connected account + expiry
  python3 scripts/tiktok_login.py --refresh  # force a token refresh
"""

from __future__ import annotations

import argparse
import http.server
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tools.base_tool  # noqa: E402,F401  (importing runs the dotenv loader)
from tools.publishers.tiktok_client import (  # noqa: E402
    AUTH_URL,
    DEFAULT_TOKEN_PATH,
    SCOPES,
    TikTokClient,
    TikTokTokens,
    TokenStore,
    exchange_code,
    refresh_tokens,
)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"{name} is not set — add it to .env.local")
    return value


def _login(client_key: str, client_secret: str) -> None:
    redirect_uri = _require_env("TIKTOK_REDIRECT_URI")
    port = int(os.environ.get("TIKTOK_CALLBACK_PORT", "8917"))
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            is_callback = parsed.path.rstrip("/").endswith("callback") and "code" in params
            if is_callback:
                result["code"] = params.get("code", [""])[0]
                result["state"] = params.get("state", [""])[0]
                result["error"] = params.get("error", [""])[0]
            self.send_response(200 if is_callback else 404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if is_callback:
                self.wfile.write(
                    b"<h2>OpenMontage: TikTok auth received. You can close this tab.</h2>"
                )

        def do_HEAD(self) -> None:  # noqa: N802
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    query = urllib.parse.urlencode(
        {
            "client_key": client_key,
            "scope": SCOPES,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    url = f"{AUTH_URL}?{query}"
    print(
        f"Listening on 127.0.0.1:{port} — make sure {redirect_uri} forwards here.\n"
        f"Open this URL in your browser (trying to auto-open):\n\n  {url}\n"
    )
    webbrowser.open(url)

    deadline = time.time() + 300
    while "code" not in result and time.time() < deadline:
        time.sleep(0.5)
    server.shutdown()

    if result.get("error"):
        sys.exit(f"Authorization denied: {result['error']}")
    if not result.get("code"):
        sys.exit("Timed out waiting for OAuth callback (5 min).")
    if result.get("state") != state:
        sys.exit("State mismatch — aborting (possible CSRF).")

    tokens = exchange_code(
        client_key, client_secret, urllib.parse.unquote(result["code"]), redirect_uri
    )
    tokens.save()
    creator = TikTokClient(tokens).creator_info()
    print(f"Connected as @{creator.username}. Tokens saved to {DEFAULT_TOKEN_PATH}")


def _status() -> None:
    store = TokenStore()
    if not store.exists():
        sys.exit(f"Not connected — no tokens at {DEFAULT_TOKEN_PATH}")
    tokens = TikTokTokens.load(store.path)
    remaining = tokens.expires_at - time.time()
    creator = TikTokClient(tokens).creator_info() if remaining > 0 else None
    who = f"@{creator.username}" if creator else "(access token expired — run --refresh)"
    print(f"Connected: {who}\nAccess token expires in {remaining / 3600:.1f}h")


def _refresh(client_key: str, client_secret: str) -> None:
    store = TokenStore()
    if not store.exists():
        sys.exit(f"Not connected — no tokens at {DEFAULT_TOKEN_PATH}")
    tokens = refresh_tokens(
        client_key, client_secret, TikTokTokens.load(store.path).refresh_token
    )
    tokens.save(store.path)
    print(f"Refreshed. New access token valid until {time.ctime(tokens.expires_at)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="One-time TikTok login for OpenMontage")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    if args.status:
        _status()
        return

    client_key = _require_env("TIKTOK_CLIENT_KEY")
    client_secret = _require_env("TIKTOK_CLIENT_SECRET")
    if args.refresh:
        _refresh(client_key, client_secret)
    else:
        _login(client_key, client_secret)


if __name__ == "__main__":
    main()
