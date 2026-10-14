# Private operation diagnostics (development capability)

The authenticated `GET /api/diagnostics/support` endpoint returns support bundle v1.
Health checks offers **View support bundle** when `/api/health` advertises
`diagnostics.support_bundle_version: 1`. Collection uses retained operation metadata and
cached health samples; it does not scan logs, run providers, probe accounts or interrupt playback.
Missing samples mean unavailable, not healthy. Nothing is uploaded automatically.

## Operation contract v1

API envelopes keep their existing `ok`, `data` and `error` fields. They add `operation`,
`history_recorded` and `next_step`. Older clients can continue reading `data`.
`X-Correlation-ID` accepts a 32-character lowercase hexadecimal opaque ID; missing or
invalid IDs are replaced. Credentials must never be used as correlation IDs.

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `operation_id` | Unique opaque reference for this operation record |
| `correlation_id` | Groups a caller operation and its Manager requests |
| `operation` | Fixed handler/tool name; never a URL, profile, argument or target |
| `decision` | `allow` or `refuse` |
| `reason_code` | Allowlisted stable code; unrecognized codes become `unknown` in retained records |
| `duration_ms`, `recorded_at` | Bounded elapsed milliseconds and UTC Unix timestamp |
| `outcome` | `succeeded`, `refused`, `failed`, `partial` or `unknown` |
| `backup_refs`, `recovery_refs` | Existing opaque backup IDs, including undo IDs; no paths or profile/add-on map keys |

Refusal, authentication, incompatible/missing APIs, connection failures and invalid responses
remain distinguishable through codes such as `write_disabled`, `unauthorized`, `unsupported`,
`unreachable` and `invalid_response`. API errors retain their existing original `error.code`.
An `allow` decision does not imply success. A successful response to a queued job confirms
acceptance, not completion of its background work. A returned nonempty `failed` list is partial.

An error after a write handler has run, or a profile/service change after it returns, can have
`outcome: unknown`. Check current state and recovery references before retrying. Clients never
automatically resend writes. Correlation IDs are diagnostic references, **not idempotency keys**;
sending the same request again can repeat the operation.

`ManagerClient.request(..., correlation_id=...)` forwards an optional correlation ID.
`last_operation` exposes compatible response metadata; `ManagerError` exposes the service code,
outcome, correlation ID and a next step. Missing metadata from older services is supported.
Only a route-not-found 404 identifies an unsupported API; a missing resource remains a resource error.

## Privacy, bounds and recovery

Each Manager profile has its own `operations/history.sqlite3` under its add-on data directory.
The directory is private (0700), the database 0600 on POSIX; other platforms also need their normal
user/account filesystem permissions. SQLite transactions serialize threads and processes.
The database is capped at 1 MiB and 256 records; records expire after seven days, and each bundle
selects at most 20. Outcome/code counts describe at most the latest 50 retained records.
Cached metric input is capped at 256 KiB and projected onto numeric memory/row fields.

Arguments, settings, credentials, URLs, file paths, profiles, titles, media items and raw logs are
excluded through field projection. Bundles still contain operational timestamps and opaque
recovery references: keep them private and review before sharing. No export or network upload
happens when viewing the bundle.

Recording failures never turn a completed action into a retryable error: `history_recorded: false`
reports missing bookkeeping separately. History availability appears in the bundle. Corrupt or
oversized history is reported unavailable and left intact. This is diagnostic history, not an
exactly-once execution journal; process termination can prevent a final record. Existing backups,
checksums, token ownership, write allowlists and playback/profile protections remain authoritative.

The stdlib contract/store in `src/kodi_manager/operation_records.py` is canonical and vendored
unchanged in nvidia-MCP, preserving independent packages and Kodi's Python 3.8 runtime. Coordinated
changes must update both copies; the sibling integration test checks byte parity. No runtime
dependency on nvidia-MCP is added.
