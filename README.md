# Ollama + remote MCP agent

Runs a small HTTP service that answers `POST /chat` using a local **Ollama** model (OpenAI-compatible API) and tools from a **remote MCP** server (streamable HTTP or SSE).

## Quick start

1. Copy `.env.example` to `.env` and set `MCP_URL` and auth per your ecommerce provider.
2. Install: `pip install -e .` (Python 3.11+).
3. Ensure Ollama is running and the model exists: `ollama pull $OLLAMA_MODEL`.
4. Run: `python -m agent_service` or `ollama-mcp-agent`.

## Configuration

See `.env.example`. `MCP_TRANSPORT` is `streamable-http` (default) or `sse`.

### OpenShop (sandbox MCP)

Point `MCP_URL` at your MCP URL (for example `https://mcp.openshopgo.com/sandbox/mcp`).

**Tool names and endpoints:** see [docs/OPENSHOP_MCP_TOOLS.md](docs/OPENSHOP_MCP_TOOLS.md).

#### OpenShop OAuth 2.1 (how the MCP server auth works)

When OAuth is enabled, OpenShop implements **OAuth 2.1 with PKCE (S256)**. There is **no Dynamic Client Registration**—OAuth clients are **pre-registered at deploy time**.

**Discovery endpoints** (same host as the MCP server, e.g. `https://mcp.openshopgo.com`):

- `GET /.well-known/oauth-authorization-server`
- `GET /.well-known/oauth-protected-resource`

**Auth flow:**

1. Client redirects to **`GET /oauth/authorize`** with a PKCE `code_challenge` (S256).
2. Store owner enters **API key** and **store slug** on the login page.
3. Server validates credentials, encrypts the API key, and redirects back with an **authorization code**.
4. Client exchanges the code at **`POST /oauth/token`** for **access** and **refresh** tokens.
5. **Access tokens expire after 1 hour.** **Refresh tokens last 30 days** with rotation.

**Pre-registered `client_id` values:** `openshop-claude`, `openshop-cursor` (each is tied to specific redirect URIs at deploy time—your own app needs a **new** pre-registered client or you must use **refresh tokens** from a completed login).

For this agent, set **`MCP_BEARER_TOKEN`** to the current **access token** and plan to **refresh before 1 hour** (e.g. store **`OPENSHOP_REFRESH_TOKEN`** and call `POST /oauth/token` with `grant_type=refresh_token`—not implemented in the agent yet, but required for production).

### How Claude authenticates remote MCP (official reference)

Anthropic’s guide describes how **Claude** (web, Cowork, Desktop) uses **remote MCP** over the internet: you add the MCP **server URL** under **Settings → Connectors**, and when you **Connect**, you typically go through **OAuth** so Claude can act on your behalf without seeing your password. Team and Enterprise **owners** can optionally set **OAuth Client ID** and **OAuth Client Secret** under **Advanced settings** when registering the connector for the organization.

**This project is not Claude:** our agent runs **headless** (e.g. on a VPS). It does not run Claude’s connector UI or OAuth callback to `claude.ai`. You must supply whatever the **HTTP MCP server** accepts—usually **`Authorization: Bearer <access_token>`** and any headers OpenShop documents—obtained via your own OAuth flow, refresh token, or credentials OpenShop gives you for server use.

See: [Get started with custom connectors using remote MCP | Claude Help Center](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

**Why raw API keys still get 401 on MCP:** The MCP HTTP API expects **`Authorization: Bearer <access_token>`** from **`POST /oauth/token`**, not the login API key alone. The key + slug are entered on the **authorize** page; the server then issues **OAuth tokens** (see above).

**What to put in `.env`:** **`MCP_BEARER_TOKEN`** = current **access token** (expires **1 hour**). For a **custom redirect** (e.g. your VPS or ngrok), you need a **pre-registered client** at deploy time—ask OpenShop to add one. **`openshop-claude`** and **`openshop-cursor`** only work with their registered redirects; use [`scripts/openshop_oauth_login.py`](scripts/openshop_oauth_login.py) with `OPENSHOP_CLIENT_ID` / `OPENSHOP_REDIRECT_URI` **only** if OpenShop has registered that pair.

**If you see `invalid_redirect_uri`:** Your `redirect_uri` is not registered for that `client_id`. With a fixed set of clients, OpenShop must **register** your redirect URI or give you a **new `client_id`** for your integration.

**Debug:** `python scripts/probe_mcp_auth.py` tries header patterns and shows HTTP status (not secrets).

The server exposes tools such as `oshop_list_orders`, `oshop_get_order`, `oshop_list_products`, …—the agent discovers them via MCP `tools/list`.

## Deploy

- **Docker:** from `deploy/`, run `docker compose up -d --build` (requires `.env` in the repo root). See [deploy/OPERATIONS.txt](deploy/OPERATIONS.txt).
- **systemd:** unit file in [deploy/systemd/ollama-mcp-agent.service](deploy/systemd/ollama-mcp-agent.service).
- **TLS:** example [deploy/Caddyfile.example](deploy/Caddyfile.example) (reverse-proxy to `127.0.0.1:8080`).
