# OpenShop MCP — tools reference (for this agent)

This documents the **open-shop-mcp** server: remote MCP tools exposed over **Streamable HTTP** with **OAuth 2.1** when the server runs in OAuth mode. The agent discovers these at runtime via MCP `tools/list`; this file is a **static reference** for prompts and debugging.

**Upstream project:** `open-shop-mcp` (OpenShop Admin API as MCP tools). All tools use the `oshop_` prefix and are **read-only**.

## Choosing tools: list vs get

- **`oshop_list_*`** — browse with pagination / sort / filter; **no** resource id required.
- **`oshop_get_*`** (and similar) — one resource or child data; **requires** the id(s) in the tool schema.

For example, use `oshop_list_orders` to discover order ids, then `oshop_get_order` or `oshop_get_order_items` for details.

## MCP endpoints (HTTP)

| Path | Environment |
|------|-------------|
| `POST /mcp` | Production |
| `POST /sandbox/mcp` | Sandbox |

Point **`MCP_URL`** in `.env` at the full URL for one of these (e.g. `https://<host>/sandbox/mcp`).

## Tools

| Tool | Description |
|------|-------------|
| `oshop_get_store_info` | Store settings and configuration (no arguments) |
| `oshop_list_products` | List products with pagination, sorting, and filtering |
| `oshop_get_product` | Full product details by **product id** |
| `oshop_get_product_variants` | Variants for a **product id** |
| `oshop_list_orders` | List orders with pagination, sorting, and filtering |
| `oshop_get_order` | Full order details by **order id** |
| `oshop_get_order_items` | Line items for an **order id** |
| `oshop_list_customers` | List customers with pagination, sorting, and filtering |
| `oshop_get_customer` | Full customer details by **customer / user id** |
| `oshop_get_customer_orders` | Orders for a **customer id** (with pagination, etc.) |

### Typical list-tool parameters

List tools generally accept optional: **`page`**, **`perPage`**, **`sortBy`**, **`sortOrder`** (`ASC` / `DESC`), **`filter`** (OpenShop filter string). Defaults vary by tool; see MCP tool descriptions in the server.

## Authentication (OAuth mode)

- **`MCP_BEARER_TOKEN`** — OAuth **access token** from `POST /oauth/token` (not the raw Admin API key).
- Access tokens expire (about **1 hour**); refresh via refresh token or re-run OAuth — see [README](../README.md) OpenShop section.

**Discovery (same host as MCP):**

- `GET /.well-known/oauth-authorization-server`
- `GET /.well-known/oauth-protected-resource`

Pre-registered clients (no Dynamic Client Registration): **`openshop-claude`**, **`openshop-cursor`**.

Use [`scripts/openshop_oauth_login.py`](../scripts/openshop_oauth_login.py) to obtain tokens for local testing when your redirect URI is registered for the chosen `client_id`.
