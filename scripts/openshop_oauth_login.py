#!/usr/bin/env python3
"""
OpenShop MCP — same OAuth pattern as Claude Desktop: authorization code + PKCE (RFC 7636).

OpenShop pre-registers clients (no DCR): e.g. openshop-claude (Claude redirect),
openshop-cursor (Cursor). Each client_id is tied to specific redirect URIs at deploy time.
For YOUR redirect URL you need OpenShop to register it (or add a new client_id).

On success, prints access_token for MCP_BEARER_TOKEN.

Defaults match the pre-registered openshop-claude redirect (same as Claude Desktop):
  client_id=openshop-claude, redirect_uri=http://localhost:6274/oauth/callback

  export OPENSHOP_CLIENT_ID=openshop-claude   # optional; this is the default
  export OPENSHOP_REDIRECT_URI=http://localhost:6274/oauth/callback
  export OPENSHOP_RESOURCE=https://mcp.openshopgo.com/sandbox/mcp
  python scripts/openshop_oauth_login.py
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTH = "https://mcp.openshopgo.com/oauth/authorize"
TOKEN_URL = "https://mcp.openshopgo.com/oauth/token"
DEFAULT_SCOPES = "read:store read:orders read:customers read:products"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _parse_redirect(redirect_uri: str) -> tuple[str, int, str]:
    p = urlparse(redirect_uri)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise SystemExit(f"Invalid OPENSHOP_REDIRECT_URI: {redirect_uri}")
    port = p.port or (443 if p.scheme == "https" else 80)
    path = p.path or "/"
    return p.hostname or "127.0.0.1", port, path


def main() -> None:
    client_id = os.environ.get("OPENSHOP_CLIENT_ID", "openshop-claude")
    redirect_uri = os.environ.get(
        "OPENSHOP_REDIRECT_URI",
        "http://localhost:6274/oauth/callback",
    )
    resource = os.environ.get(
        "OPENSHOP_RESOURCE",
        "https://mcp.openshopgo.com/sandbox/mcp",
    )
    scopes = os.environ.get("OPENSHOP_SCOPES", DEFAULT_SCOPES)

    host, port, callback_path = _parse_redirect(redirect_uri)
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": scopes,
        "resource": resource,
    }
    auth_url = f"{AUTH}?{urlencode(params)}"

    print(
        "\nSame flow as Claude Desktop: OAuth authorize + PKCE, then POST /oauth/token.\n"
        f"  client_id={client_id}\n"
        f"  redirect_uri={redirect_uri}\n\n"
        "Listening for the redirect on this machine. If you changed OPENSHOP_REDIRECT_URI, "
        "it must be registered for that client_id on the server.\n"
    )

    result: dict[str, str | None] = {}
    done = threading.Event()
    server_holder: list[HTTPServer | None] = [None]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            req_path = parsed.path.rstrip("/") or "/"
            want = callback_path.rstrip("/") or "/"
            if req_path != want:
                self.send_error(404)
                return
            q = parse_qs(parsed.query)
            if "error" in q:
                result["error"] = q.get("error", ["unknown"])[0]
                result["error_description"] = (q.get("error_description") or [None])[0]
            if "code" in q:
                result["code"] = q["code"][0]
            if "state" in q:
                result["state"] = q["state"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><p>Callback OK. You can close this tab.</p></body></html>"
            )
            done.set()
            if server_holder[0]:
                threading.Thread(target=server_holder[0].shutdown, daemon=True).start()

    server = HTTPServer((host, port), Handler)
    server_holder[0] = server

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.4)

    print("Opening browser. If it does not open, paste this URL:\n")
    print(auth_url, "\n")
    webbrowser.open(auth_url)

    if not done.wait(timeout=600):
        print("Timed out waiting for OAuth redirect (10 min).", file=sys.stderr)
        server.shutdown()
        sys.exit(1)

    server.shutdown()
    t.join(timeout=5)

    if result.get("error"):
        err = result["error"]
        desc = result.get("error_description") or ""
        print(f"OAuth error: {err} {desc}", file=sys.stderr)
        if err == "invalid_redirect_uri":
            print(
                "\nOpenShop only allows redirect URIs registered for this client_id.\n"
                "Default is http://localhost:6274/oauth/callback for openshop-claude (Claude Desktop).\n"
                "Ask OpenShop to register your redirect or issue a client_id if you use a different URI.\n",
                file=sys.stderr,
            )
        sys.exit(1)
    code = result.get("code")
    if not code:
        print("No authorization code in callback.", file=sys.stderr)
        sys.exit(1)
    if result.get("state") != state:
        print("State mismatch — aborting.", file=sys.stderr)
        sys.exit(1)

    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    resp = httpx.post(TOKEN_URL, data=body, timeout=60.0)
    if resp.is_error:
        print(resp.text, file=sys.stderr)
        resp.raise_for_status()
    data = resp.json()
    at = data.get("access_token", "")
    rt = data.get("refresh_token")
    print("\nSuccess. Put in .env (do not commit):\n")
    print(f"MCP_BEARER_TOKEN={at}")
    if rt:
        print(f"# OPENSHOP_REFRESH_TOKEN={rt}  # keep secret; use for refresh scripts")


if __name__ == "__main__":
    main()
