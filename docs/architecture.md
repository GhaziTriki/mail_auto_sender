# ApplyMail architecture

```
api (FastAPI + static React build :8000) ─┐
worker (python -m app.worker)             ─┼─► mongo (volume mongo_data)
mailpit (profile "dev")                    │   data volume /data  (runs/<id>/source.*, parsed.jsonl, cv.pdf)
```

`api` and `worker` are the same image with different commands. They never call each other: run/item `status` fields in MongoDB are the only channel. All claims are single-document atomic operations (`find_one_and_update`); there are no transactions. All datetimes are tz-aware UTC and every "now" goes through `app.clock.now()` so tests can freeze and advance time. Every query is scoped by `current_user_id()` (always `"local"`).

## 1. Collections (database `applymail`)

| Collection | Purpose | Key fields / indexes |
|---|---|---|
| `senders` | Sender accounts, shared across runs | `provider`, `address`, `secret_enc` (Fernet), `daily_cap`, `status` (`active`/`idle`/`auth_failed`), `blocked_until`, soft delete via `deleted_at`. Unique `(user_id, provider, address)`. |
| `send_log` | Makes quota survive run deletion | `sender_id`, `item_id`, `at`. Index `(sender_id, at)`, TTL 3 days on `at`. Inserted before each provider call; kept only for `sent`/`unknown`, deleted otherwise. |
| `llm_keys` | Gemini key pool | `secret_enc`, `daily_cap`, `used_today`, `day_key` (America/Los_Angeles), `status`, `blocked_until`. |
| `contacts` | Global identity, one per address | Unique `(user_id, email_norm)`. `sent_item_id` is the **send-lock**; `sent_info` survives run deletion. |
| `runs` | A batch and everything the user chose | See spec §5.5; unique `name_lower`. Counts are aggregated from `run_items`, never stored. |
| `run_items` | One per contact per run = the email | Row snapshot, classification, rendered subject/body, `status`, attempts. Indexes `(run_id,status,row_index)`, `(run_id,email_norm)`, `(contact_id)`, `(status,lease_until)`. |
| `oauth_states` | Outlook sign-in handshake | `state` (unique), `code_verifier`; TTL 10 minutes. |

**Derived sender quota** (`services/quota.py`, never stored): `used = count(send_log, sender, at >= now-24h)`; exhausted if `used >= daily_cap` or `blocked_until > now`; `resets_at = max(blocked_until, sorted_at[used-cap] + 24h)`. Gemini keys use a Pacific-day counter that resets lazily when `day_key` changes.

## 2. Status machines

**Run:** `draft → preparing → ready → running ⇄ paused_user`; `preparing → paused_llm → preparing`; `running → paused_quota → running` (Resume only, never automatic); `running → paused_errors → running`; `running → completed`; `completed → running` when Rerun / Resend / Approve creates new `pending` items; `ready → draft` (Unprepare, only if nothing was sent).

**Item:** `pending → sending → sent | failed | unknown | pending` (retry / sender problem / quota). `failed → pending` (Rerun). `needs_review → pending` (Resend, `override_duplicate=true`) or `→ skipped_duplicate`. `unknown → sent` (Mark as sent) or `→ pending` (Rerun, releases the lock first). `pending|failed → skipped_user`. Created as `pending`, `no_contact`, `needs_review` or `skipped_duplicate` at Prepare.

## 3. Send-once lock (`services/locking.py`)

Before a provider call the worker runs `contacts.find_one_and_update({_id, sent_item_id: None}, {$set: {sent_item_id: item_id}})`. If nothing is returned and the holder is another item, the item becomes `needs_review` (`duplicate_reason="already_sent"`) and nothing is sent. The lock is **kept** on `sent` and `unknown` (with `sent_info`, `uncertain=true` for unknown) and **released** on every other outcome. `override_duplicate=true` skips acquisition. Deleting a run never clears locks.

## 4. Worker algorithm

Every `WORKER_TICK_S` (2 s):

1. **Recovery:** `sending` items with an expired lease become `unknown` (lock kept, `uncertain=true`). Never auto-resent.
2. **Classification** for each `preparing` run: rules mode classifies instantly; LLM mode sends one batch of 20 (honouring `next_llm_at`), validates the JSON, retries only missing ids with smaller batches (up to 2 retries), then falls back to rules with `llm_failed`. No usable key → `paused_llm`.
3. **Send unit** for each `running` run whose `next_send_at` is due: pick the first available sender (fill-first) → claim the lowest pending item (must be `approved` in manual runs, and past its `next_attempt_at`) → acquire the lock → insert `send_log` → provider call → outcome table → breaker → `next_send_at = now + random(delay)` (skipped in manual runs).

### Outcome table

| outcome | item | lock | sender | extras |
|---|---|---|---|---|
| `sent` | `sent` | keep, set `sent_info` | – | keep `send_log`; `consecutive_failures=0` |
| `unknown` | `unknown` | keep (`uncertain`) | – | keep `send_log`; breaker unchanged |
| `transient` | `pending` with `next_attempt_at = now + retry_delays_s[n-1]`, or `failed` after `max_retries` | release | – | delete `send_log`; breaker +1 when it becomes `failed` |
| `permanent` | `failed` | release | – | delete `send_log`; breaker +1 unless `recipient_specific` |
| `auth` | back to `pending` (no attempt increment) | release | `auth_failed` | delete `send_log` |
| `quota` | back to `pending` (no attempt increment) | release | `blocked_until = now+24h` (or `retry_after`) | delete `send_log` |

## 5. Provider mapping

**Gmail SMTP** (phase tracked as `connect|auth|rcpt|data`):

| Condition | Outcome |
|---|---|
| `SMTPAuthenticationError` (535, 534) | `auth` |
| RCPT 550/551/553 or enhanced `5.1.x` | `permanent`, `recipient_specific` |
| other 5xx | `permanent` |
| reply text contains `5.4.5`, `Daily user sending` or `sending limit` (case-insensitive) | `quota` |
| 4xx anywhere (incl. 421); connect/TLS errors before `data` | `transient` |
| disconnect/timeout/reset after the `data` phase started | `unknown` |
| accepted | `sent` |

**Outlook / Graph:**

| Condition | Outcome |
|---|---|
| 202 | `sent` |
| 401 | refresh once and retry, else `auth`; `invalid_grant` on refresh → `auth` |
| 429 | `transient` with `retry_after_s` from `Retry-After` |
| 503 / 504 | `transient` |
| 403/400 with `quota` in the body | `quota` |
| other 4xx | `permanent` |
| connection failure before sending | `transient` |
| connection error/timeout after the request was sent | `unknown` |

## 6. Implementation notes

Choices made where the spec was ambiguous (simplest option consistent with the guarantees):

- **Completed beats paused_quota.** If every sender is unavailable but no item is `pending`/`sending`, the run becomes `completed` instead of pausing.
- **Rerun / Resend in manual runs** also set `approved=true`: the user's explicit action is the approval, otherwise the item would sit unsent.
- **Unknown → Rerun** releases the lock and clears `contacts.sent_info`, so the next send writes fresh info.
- **`first_send_at`** is set right before the first provider call of a run, so the configuration lock applies even if that first attempt fails.
- **Items that are not sendable** (`no_contact`, `skipped_duplicate`) are stored with `classified=true`; `needs_review` items are classified like pending ones so a later Resend has a rendered email.
- **LLM bookkeeping:** `llm_attempts` is a per-item counter. Transient Gemini errors (5xx/network) change no key or item state; the batch is retried on the next tick. Every request that reached Google increments `used_today`.
- **Sender/key lists** return `quota` objects computed on read; `blocked_until` is not exposed.
- **API additions** beyond the spec list: `POST /api/runs/{id}/approve-all` ("Approve all remaining" switches the run to auto), `GET /api/oauth/outlook/start` returns `{url}` as JSON (the browser then navigates to it), `POST /api/senders` is a thin alias of `/api/senders/gmail`.
- **Wizard autosave** happens when you leave a step (Next) and on blur of the run name, not on every keystroke.
- **Frontend types** are hand-written in `src/api/types.ts`. The `npm run gen:api` script (openapi-typescript) is provided and writes `src/api/schema.d.ts`, but the app does not import the generated file yet.
- **Dashboard dates** are local days converted to UTC bounds in the browser; the daily chart buckets by the browser's time zone (`tz` parameter).
- **Tests** run on `mongomock` by default (fast, no services) and on a real MongoDB when `USE_REAL_MONGO=1` (the compose `test` profile sets it).
