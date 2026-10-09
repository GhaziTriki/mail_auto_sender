# Operations

## Logs

```
docker compose logs -f api worker
```

Logs are structured JSON on stdout and include `run_id` / `item_id`. Secrets and email bodies are redacted.

## Restart / stop

```
docker compose restart worker      # safe at any time (see "crashes" below)
docker compose down                # keeps data (volumes mongo_data and data)
docker compose down -v             # DELETES all data
```

## Crashes and restarts

If the worker dies while sending, the item keeps a 120 s lease (`LEASE_S`). When the lease expires the item becomes **unknown** (the message may or may not have left). ApplyMail never resends an unknown item by itself. Check your Sent folder, then use **Mark as sent** or **Rerun** on the run's Unknown tab.

## Backup / restore

```
scripts/backup.sh                       # writes ./backups/<timestamp>/{mongo.archive.gz,data.tar.gz}
scripts/restore.sh ./backups/<timestamp>
```

Back up before upgrading. `SECRET_KEY` is **not** in the backup: keep it safe, because stored passwords/tokens cannot be decrypted without it.

## Upgrading

```
git pull            # or copy the new version over
docker compose up --build -d
```

Indexes are created idempotently on api start. The api and worker use the same image.

## Resetting a stuck run

| Situation | What to do |
|---|---|
| `paused_quota` | Add a sender or wait for the reset time, then **Resume** (409 means still nothing available; the reasons are listed). |
| `paused_llm` | Add a Gemini key and **Resume**, or **Switch to rules**. |
| `paused_errors` | Read the last errors, fix the cause (sender password, network), **Resume**. |
| `preparing` for a long time | Check `docker compose logs worker`. In LLM mode it waits `LLM_MIN_INTERVAL_S` between requests. |
| Items stuck in `sending` | They flip to `unknown` automatically after the lease expires (worker must be running). |
| Wrong contacts prepared | While **ready** and nothing was sent: **Unprepare**, change settings, **Prepare** again. |
| Re-send to someone already emailed | Needs review tab → **Resend** (explicit decision, sends exactly once more). |

## Dev / test without sending real mail

```
docker compose --profile dev up --build
# .env: GMAIL_SMTP_HOST=mailpit GMAIL_SMTP_PORT=1025 GMAIL_SMTP_SECURITY=none GMAIL_SMTP_AUTH=false LLM_FAKE=1
```

Mailpit UI: <http://localhost:8025>. Run the test suite against the real MongoDB with `docker compose --profile test run --rm test`.
