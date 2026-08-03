# MongoDB Atlas Storage — Operations Guide

Operational procedures for optional MongoDB Atlas persistence. Local SQLite
remains the default. Use placeholders only; never paste production credentials
into shared shells or tickets.

## 1. Local default

Fresh clone with no Mongo environment variables:

- `DEPLOYMENT_MODE` defaults to `local`
- App data and LangGraph checkpoints use SQLite on disk
- Browser settings (provider keys, web search toggles) stay in `localStorage`
- Storage Settings panel can connect to Atlas on demand

No Atlas account is required for local development.

## 2. Atlas provisioning

1. Create a dedicated cluster (or reuse a non-production cluster).
2. Create database user `a2ui_app` with password stored in a secret manager.
3. Grant `readWrite` on **one** application database only (for example `a2ui`).
4. Do not grant `atlasAdmin`, `readWriteAnyDatabase`, or cluster-wide roles.
5. Prefer a disposable database name for smoke tests.

## 3. Network Access

- Allowlist developer workstation public IP for local Settings connect.
- Allowlist deployment egress IP/CIDR for cloud mode.
- Avoid `0.0.0.0/0` except short-lived break-glass debugging; remove immediately.
- If Atlas temporarily blocks auth failures, wait for unlock and rotate password.

## 4. URI password encoding and TLS/SRV

- Use `mongodb+srv://` for Atlas SRV + TLS (default for modern clusters).
- URL-encode special characters in passwords (`@` → `%40`, `/` → `%2F`, etc.).
- Example shape (placeholders only):

```text
mongodb+srv://a2ui_app:<password>@<cluster-host>/?retryWrites=true&w=majority
```

- Server forces TLS via driver defaults for SRV URIs; do not disable TLS.

## 5. Local connect

1. Open Settings → Storage in the UI (preferred over curl).
2. Paste URI + database name; submit Connect.
3. URI is stored in browser storage and held in **server process memory only**.
4. Last successful connect wins; previous Mongo client is closed after swap.
5. While Mongo is active, all app repositories and the graph checkpointer use Mongo.
6. Local SQLite files remain on disk as an untouched backup until you migrate or
   write new local data after disconnect.

## 6. Migration

Before migrate:

1. Cancel or wait for active generation jobs (API returns `409` if busy).
2. Confirm Connect succeeded (`activeBackend: mongo`).
3. Ensure local SQLite still has the data you intend to copy.

Then:

1. Call migrate with browser provider/web-search snapshots in the payload.
2. Server copies domain tables in batches with idempotent upserts.
3. Checkpoints copy through saver APIs (`checkpoints`, `checkpoint_writes`).
4. Response includes per-collection row/matched/upserted/modified counts.
5. Safe to retry: second migrate should keep document totals stable
   (matched/modified may rise; upserted may fall toward zero).

## 7. Checkpoints

- LangGraph checkpoints migrate via saver APIs, not raw collection dumps.
- Paused or cancelled generations can resume after migrate when thread IDs match.
- Cloud and local Mongo use fixed collection names:
  `checkpoints`, `checkpoint_writes`.

## 8. Disconnect

- Local-only endpoint; cloud mode returns `403`.
- Restores SQLite repositories and SQLite checkpointer.
- Pre-migration SQLite data reappears; Atlas data is **not** deleted.
- Active generation must be idle (`409` otherwise).

## 9. Cloud deploy

Set three environment variables (no Settings UI connect):

```dotenv
DEPLOYMENT_MODE=cloud
MONGO_URI=mongodb+srv://a2ui_app:<password>@<cluster-host>/?retryWrites=true&w=majority
MONGO_DB=a2ui
```

Behavior:

- Startup fails fast if `MONGO_URI` or `MONGO_DB` missing.
- Process connects to Mongo **before** serving traffic.
- No SQLite checkpointer control path in cloud mode.
- `POST /settings/storage/connect|disconnect|migrate` return `403`.
- `GET/PUT /settings/storage/app-settings` remain available when Mongo is active.
- Shutdown stops generation runtime, then closes the shared Mongo client.

## 10. Plaintext keys

- Provider API keys and web-search settings may be stored as documents in Atlas.
- Atlas provides at-rest encryption and TLS in transit.
- Anyone with the URI (or Atlas UI access to that DB) can read those documents.
- Treat URI like a root password for application data; rotate on leak.

## 11. Rotation

**Local mode**

1. Update URI in Settings (or browser storage).
2. Disconnect if needed, then Connect with the new URI.
3. Restart server if process memory still holds a stale client after crash.

**Cloud mode**

1. Update deployment secret (`MONGO_URI` / password).
2. Restart all server instances so lifespan reconnects.
3. Revoke the old Atlas user password after cutover.

## 12. Recovery

| Situation | Action |
|-----------|--------|
| Migration failed mid-run | Fix root cause; retry migrate (idempotent) |
| Mongo unreachable locally | Disconnect to SQLite backup; keep working offline |
| Bad cloud config | Fix env; restart — process will not serve until connect works |
| Suspected data loss on Atlas | **Never delete local SQLite backup first** |
| Auth lockout | Unlock IP/user in Atlas; rotate password; reconnect |

## 13. Monitoring

Watch for:

- Authentication failures and IP not allowlisted errors
- Connection / server selection timeouts
- Storage and connection quotas approaching limits
- Index creation failures at connect time
- Elevated generation job failures after backend switch

Logs must never include full URIs, passwords, or app settings payloads. Errors
log operation name and exception **type** only.

## 14. Non-goals

This storage mode intentionally does **not** provide:

- Multi-tenant authentication or per-user Atlas isolation
- Dual-write to SQLite and Mongo
- Bidirectional continuous sync
- Application-level encryption of provider keys beyond Atlas TLS/at-rest

## API examples (placeholders only)

Prefer the Settings UI. Shell history can retain URIs.

```bash
curl http://localhost:8000/settings/storage/status

curl -X POST http://localhost:8000/settings/storage/connect \
  -H "Content-Type: application/json" \
  -d '{"uri":"mongodb+srv://<user>:<password>@<host>","dbName":"a2ui"}'

curl -X POST http://localhost:8000/settings/storage/migrate \
  -H "Content-Type: application/json" \
  -d '{"providerSettings":{},"webSearchSettings":{}}'

curl -X POST http://localhost:8000/settings/storage/disconnect
```

Cloud mode status should show `deploymentMode: cloud`, `connected: true`, and
`canConnect` / `canDisconnect` / `canMigrate` false.
