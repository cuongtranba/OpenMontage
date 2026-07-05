"""Probe script for the TikTok Content Posting API (sandbox-friendly).

Validates the full auth + publish loop before we build the real
tools/publishers/tiktok_publisher.py tool:

    python3 scripts/tiktok_probe.py login          # one-time browser OAuth
    python3 scripts/tiktok_probe.py creator-info   # verify token + privacy options
    python3 scripts/tiktok_probe.py post VIDEO.mp4 --title "test"   # SELF_ONLY post
    python3 scripts/tiktok_probe.py status PUBLISH_ID

Requires TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in .env or .env.local.
The redirect URI (default http://localhost:8917/callback/) must be registered
in the app's Login Kit settings. Tokens are stored at
~/.config/openmontage/tiktok_tokens.json (chmod 600).
"""

from __future__ import annotations

import argparse
import http.server
import json
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import tools.base_tool  # noqa: E402,F401  (importing runs _load_dotenv)

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API_BASE = "https://open.tiktokapis.com/v2"
TOKEN_PATH = Path.home() / ".config" / "openmontage" / "tiktok_tokens.json"
STATE_PATH = Path.home() / ".config" / "openmontage" / "tiktok_oauth_state.json"
SCOPES = "user.info.basic,video.publish"
DEFAULT_REDIRECT = "http://localhost:8917/callback/"
CHUNK_SIZE = 10 * 1024 * 1024  # single-chunk uploads for files <= 64MB


@dataclass
class AppCreds:
    client_key: str
    client_secret: str
    redirect_uri: str


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    open_id: str
    expires_at: float  # unix time

    def save(self) -> None:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(json.dumps(self.__dict__, indent=2))
        TOKEN_PATH.chmod(0o600)

    @staticmethod
    def load() -> "Tokens":
        if not TOKEN_PATH.exists():
            sys.exit(f"No tokens at {TOKEN_PATH}. Run: python3 scripts/tiktok_probe.py login")
        return Tokens(**json.loads(TOKEN_PATH.read_text()))


def load_creds() -> AppCreds:
    import os

    # main's base_tool only loads .env; also honor gitignored .env.local overrides
    local_env = REPO_ROOT / ".env.local"
    if local_env.is_file():
        for line in local_env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not key or not secret:
        sys.exit("TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET missing from .env / .env.local")
    return AppCreds(key, secret, os.environ.get("TIKTOK_REDIRECT_URI", DEFAULT_REDIRECT))


def _token_request(creds: AppCreds, form: dict[str, str]) -> Tokens:
    form |= {"client_key": creds.client_key, "client_secret": creds.client_secret}
    resp = requests.post(
        TOKEN_URL,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    body = resp.json()
    if "access_token" not in body:
        sys.exit(f"Token request failed ({resp.status_code}): {json.dumps(body, indent=2)}")
    tokens = Tokens(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        open_id=body.get("open_id", ""),
        expires_at=time.time() + float(body.get("expires_in", 86400)),
    )
    tokens.save()
    return tokens


def cmd_login(creds: AppCreds) -> None:
    state = secrets.token_urlsafe(16)
    # Local bind port; a tunnel may front the redirect URI on 443.
    port = urllib.parse.urlparse(creds.redirect_uri).port or 8917
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
                self.wfile.write(b"<h2>OpenMontage: TikTok auth received. You can close this tab.</h2>")

        def do_HEAD(self) -> None:  # noqa: N802
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    query = urllib.parse.urlencode(
        {
            "client_key": creds.client_key,
            "scope": SCOPES,
            "response_type": "code",
            "redirect_uri": creds.redirect_uri,
            "state": state,
        }
    )
    url = f"{AUTH_URL}?{query}"
    print("Open this URL in your browser (trying to auto-open):\n\n  " + url + "\n")
    webbrowser.open(url)

    deadline = time.time() + 300
    while "code" not in result and time.time() < deadline:
        time.sleep(0.5)
    server.server_close()

    if result.get("error"):
        sys.exit(f"Authorization denied: {result['error']}")
    if not result.get("code"):
        sys.exit("Timed out waiting for OAuth callback (5 min).")
    if result.get("state") != state:
        sys.exit("State mismatch — aborting (possible CSRF).")

    tokens = _token_request(
        creds,
        {
            "code": urllib.parse.unquote(result["code"]),
            "grant_type": "authorization_code",
            "redirect_uri": creds.redirect_uri,
        },
    )
    print(f"Login OK. open_id={tokens.open_id}\nTokens saved to {TOKEN_PATH}")


def cmd_auth_url(creds: AppCreds) -> None:
    """Print the authorize URL for a manual-paste flow (no local server)."""
    state = secrets.token_urlsafe(16)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"state": state, "redirect_uri": creds.redirect_uri}))
    STATE_PATH.chmod(0o600)
    query = urllib.parse.urlencode(
        {
            "client_key": creds.client_key,
            "scope": SCOPES,
            "response_type": "code",
            "redirect_uri": creds.redirect_uri,
            "state": state,
        }
    )
    print(f"{AUTH_URL}?{query}")
    print(
        "\nAfter authorizing, the browser will land on a page that fails to load.\n"
        "Copy the FULL URL from the address bar, then run:\n"
        '  python3 scripts/tiktok_probe.py exchange "<pasted-url>"'
    )


def cmd_exchange(creds: AppCreds, callback_url: str) -> None:
    saved = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    params = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url).query)
    code = params.get("code", [""])[0]
    state = params.get("state", [""])[0]
    if params.get("error", [""])[0]:
        sys.exit(f"Authorization denied: {params['error'][0]}")
    if not code:
        sys.exit("No ?code= found in the pasted URL.")
    if saved.get("state") and state != saved["state"]:
        sys.exit("State mismatch — re-run auth-url and use the fresh link.")
    tokens = _token_request(
        creds,
        {
            "code": urllib.parse.unquote(code),
            "grant_type": "authorization_code",
            "redirect_uri": str(saved.get("redirect_uri", creds.redirect_uri)),
        },
    )
    print(f"Login OK. open_id={tokens.open_id}\nTokens saved to {TOKEN_PATH}")


def fresh_tokens(creds: AppCreds) -> Tokens:
    tokens = Tokens.load()
    if time.time() < tokens.expires_at - 300:
        return tokens
    print("Access token expired — refreshing...")
    return _token_request(
        creds, {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token}
    )


def _api_post(tokens: Tokens, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    resp = requests.post(
        f"{API_BASE}{path}",
        json=payload if payload is not None else {},
        headers={
            "Authorization": f"Bearer {tokens.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        timeout=30,
    )
    body: dict[str, object] = resp.json()
    print(f"POST {path} -> {resp.status_code}\n{json.dumps(body, indent=2)}")
    error = body.get("error")
    if isinstance(error, dict) and error.get("code") not in ("ok", None):
        sys.exit(f"API error: {error.get('code')}: {error.get('message')}")
    return body


def cmd_creator_info(creds: AppCreds) -> None:
    _api_post(fresh_tokens(creds), "/post/publish/creator_info/query/")


def cmd_post(creds: AppCreds, video: Path, title: str) -> None:
    if not video.exists():
        sys.exit(f"No such file: {video}")
    size = video.stat().st_size
    if size > 64 * 1024 * 1024:
        sys.exit("Probe supports videos up to 64MB (single chunk). Use a smaller test clip.")

    tokens = fresh_tokens(creds)
    init = _api_post(
        tokens,
        "/post/publish/video/init/",
        {
            "post_info": {
                "title": title,
                "privacy_level": "SELF_ONLY",
                "is_aigc": True,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": size,
                "total_chunk_count": 1,
            },
        },
    )
    data = init["data"]
    assert isinstance(data, dict)
    publish_id, upload_url = str(data["publish_id"]), str(data["upload_url"])

    print(f"Uploading {size} bytes...")
    up = requests.put(
        upload_url,
        data=video.read_bytes(),
        headers={
            "Content-Type": "video/mp4",
            "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}",
        },
        timeout=300,
    )
    print(f"PUT upload -> {up.status_code}")
    if up.status_code not in (200, 201):
        sys.exit(f"Upload failed: {up.text[:500]}")

    print(f"Polling status for publish_id={publish_id} ...")
    for _ in range(30):
        body = _api_post(tokens, "/post/publish/status/fetch/", {"publish_id": publish_id})
        data = body["data"]
        assert isinstance(data, dict)
        status = str(data.get("status", ""))
        if status in ("PUBLISH_COMPLETE", "FAILED"):
            print(f"\nFinal status: {status}")
            return
        time.sleep(5)
    print("Gave up polling after 150s — check status manually:")
    print(f"  python3 scripts/tiktok_probe.py status {publish_id}")


def cmd_status(creds: AppCreds, publish_id: str) -> None:
    _api_post(fresh_tokens(creds), "/post/publish/status/fetch/", {"publish_id": publish_id})


def main() -> None:
    parser = argparse.ArgumentParser(description="TikTok Content Posting API probe")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    sub.add_parser("auth-url")
    exchange = sub.add_parser("exchange")
    exchange.add_argument("callback_url")
    sub.add_parser("creator-info")
    post = sub.add_parser("post")
    post.add_argument("video", type=Path)
    post.add_argument("--title", default="OpenMontage probe post")
    status = sub.add_parser("status")
    status.add_argument("publish_id")
    args = parser.parse_args()

    creds = load_creds()
    if args.cmd == "login":
        cmd_login(creds)
    elif args.cmd == "auth-url":
        cmd_auth_url(creds)
    elif args.cmd == "exchange":
        cmd_exchange(creds, args.callback_url)
    elif args.cmd == "creator-info":
        cmd_creator_info(creds)
    elif args.cmd == "post":
        cmd_post(creds, args.video, args.title)
    elif args.cmd == "status":
        cmd_status(creds, args.publish_id)


if __name__ == "__main__":
    main()
