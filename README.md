# ApplyMail

A Dockerized web app that sends personalized internship-application emails (with your CV attached) in controlled, resumable runs. Each person runs their own instance on their own machine.

You create a **run**: upload a contacts file (CSV/XLSX) and a CV (PDF), filter the rows, pick the email and name columns, choose how greetings are produced (Gemini or fixed rules), write a subject/body template, choose one or more sender accounts, preview and edit every email, then send manually (approve each) or automatically, with pause/resume, quota handling, retries and duplicate protection across runs.

**Not included (v1):** login/multi-user, deployment automation, bounce/reply tracking, HTML emails, follow-ups, time-of-day scheduling, Outlook via SMTP, translations.

## Screenshots (placeholders)

Add images to `docs/screenshots/` and link them here: `dashboard.png`, `wizard-filters.png`, `wizard-greeting.png`, `run-queue.png`, `send-window.png`, `needs-review.png`, `settings-senders.png`.

## Requirements

- **Docker** with Compose v2 (`docker compose`). On Windows and macOS install **Docker Desktop**; on Windows use the WSL2 backend (Linux containers).
- Nothing else: Python and Node are not needed on your machine, everything builds inside Docker.

## Quick start

Pick your system. All variants end with the app on <http://localhost:8000>.

### Windows (PowerShell)

```powershell
Copy-Item .env.example .env
# generate a key (uses Docker, no Python needed) and copy the printed line:
docker run --rm python:3.12-slim python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
notepad .env        # paste it after SECRET_KEY= (no quotes, no spaces), save
docker compose up --build -d
```

Command Prompt (cmd.exe): use `copy .env.example .env` instead of `Copy-Item`.

### macOS / Linux / WSL / Git Bash

```bash
cp .env.example .env
scripts/gen-secret-key.sh          # prints a key
# paste it into .env as SECRET_KEY=...
docker compose up --build -d
```

If `scripts/*.sh` fail with `bad interpreter` or `\r` errors, the files got Windows line endings. The repo ships a `.gitattributes` that prevents this; otherwise run `dos2unix scripts/*.sh`.

### Check it works

```
docker compose ps                  # api, worker, mongo should be "running" / "healthy"
docker compose logs -f api worker  # Ctrl+C to stop following
```

Then open <http://localhost:8000>. If the `api` container exits immediately, `SECRET_KEY` is missing or not a valid key (see Troubleshooting).

The app refuses to start without a valid `SECRET_KEY`. Keep that key: stored passwords and tokens cannot be decrypted without it. The app is published on `127.0.0.1` only. If port 8000 is already in use, change the left side of `"127.0.0.1:8000:8000"` in `docker-compose.yml` (and `APP_BASE_URL` / `OUTLOOK_REDIRECT_URI` if you use them).

### First-run checklist

1. **Settings → Senders → Gmail → Add account** (needs a Google app password, see [docs/providers/gmail.md](docs/providers/gmail.md)), then **Check login**.
2. *(Optional)* **Settings → LLM keys → Add key** for Gemini greetings ([docs/llm/gemini.md](docs/llm/gemini.md)). Rules mode needs none.
3. **New run** → walk through the wizard → **Prepare** → review → **Start**.
4. Try it first without real mail: `docker compose --profile dev up --build` with the Mailpit settings in [docs/operations.md](docs/operations.md).

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | – (required) | Fernet key that encrypts stored secrets |
| `MONGO_URL` | `mongodb://mongo:27017/applymail` | MongoDB connection |
| `DATA_DIR` | `/data` | Uploaded files per run |
| `APP_BASE_URL` | `http://localhost:8000` | Public URL of the app |
| `GMAIL_SMTP_HOST` / `GMAIL_SMTP_PORT` | `smtp.gmail.com` / `587` | Gmail SMTP endpoint |
| `GMAIL_SMTP_SECURITY` | `starttls` | `starttls`, `ssl` or `none` |
| `GMAIL_SMTP_AUTH` | `true` | `false` only for Mailpit/dev |
| `DEFAULT_GMAIL_DAILY_CAP` / `MAX_GMAIL_DAILY_CAP` | `100` / `400` | Per-account daily cap default / ceiling |
| `OUTLOOK_CLIENT_ID` | empty | Empty = Outlook disabled |
| `OUTLOOK_REDIRECT_URI` | `http://localhost:8000/api/oauth/outlook/callback` | Must match the Azure registration |
| `DEFAULT_OUTLOOK_DAILY_CAP` / `MAX_OUTLOOK_DAILY_CAP` | `100` / `250` | Outlook caps |
| `GEMINI_MODEL` | `gemini-flash-latest` | Model name |
| `DEFAULT_LLM_DAILY_CAP` | `200` | Requests/day per key |
| `LLM_MIN_INTERVAL_S` | `6` | Minimum seconds between Gemini requests |
| `LLM_BATCH_SIZE` | `20` | Contacts per Gemini request |
| `LLM_FAKE` | `0` | `1` = deterministic fake LLM (dev/test) |
| `SEND_DELAY_MIN_S` / `SEND_DELAY_MAX_S` | `30` / `90` | Random pause between automatic sends |
| `MAX_RETRIES` | `3` | Attempts per email for transient errors |
| `RETRY_DELAYS_S` | `60,300,900` | Wait before retry 1, 2, 3 |
| `BREAKER_THRESHOLD` | `10` | Consecutive failures that pause a run |
| `LEASE_S` | `120` | Time an in-flight send is considered alive |
| `WORKER_TICK_S` | `2` | Worker polling interval |
| `MAX_ROWS` / `MAX_SOURCE_MB` / `MAX_CV_MB` | `20000` / `10` / `3` | Upload limits |

## Concepts

| Term | Meaning |
|---|---|
| **Run** | A named batch with all its choices saved (files, filters, columns, template, senders). |
| **Item** | One email to one contact within a run. |
| **Sender** | A Gmail or Outlook account you send from. Shared across runs. |
| **Exhausted** | A sender whose rolling-24 h cap is reached, or that the provider blocked. Derived, never stored. |
| **Idle** | You switched a sender/key off. It is never reactivated automatically. |
| **Sender pool (fill-first)** | The first available sender is used until exhausted, then the next. |
| **Send-once lock** | Every address can be emailed once across **all** runs. Re-sending needs an explicit action. |
| **Needs review** | The contact was already emailed in another run. Not sent unless you choose Resend. |
| **Unknown** | The connection dropped while sending, so the email may or may not have gone. Never resent automatically. |

### Run statuses

| Status | Meaning |
|---|---|
| `draft` | Wizard in progress |
| `preparing` | Classifying contacts and rendering emails |
| `ready` | Prepared; waiting for Start |
| `running` | Worker is sending |
| `paused_user` | You paused it |
| `paused_quota` | No sender available; stays paused until you click Resume |
| `paused_llm` | No usable Gemini key: add a key, wait, or switch to rules |
| `paused_errors` | Too many consecutive failures |
| `completed` | Nothing pending or sending |

### Item statuses

| Status | Meaning |
|---|---|
| `pending` | Waiting to be sent (or approved) |
| `sending` | In flight |
| `sent` | Delivered to the provider |
| `failed` | Failed after retries; use Rerun |
| `no_contact` | No valid email address in the cell |
| `needs_review` | Already emailed in another run |
| `skipped_duplicate` | Duplicate in this run, or skipped from Needs review |
| `skipped_user` | You skipped it |
| `unknown` | Outcome uncertain |

## Day-to-day workflow

1. Create a run and prepare it. Emails appear in **Preview/Queue**; click one to see the contact line used, the greeting decision, the sender, and to edit it. **Send me a test** mails the first sender's own address.
2. **Manual approval:** use the **Send window** (Send / Skip / Approve all remaining). **Automatic:** Start and let it run with delays.
3. If the run pauses, the banner tells you why and what to do.
4. Handle **Failed** (Rerun selected), **Unknown** (Mark as sent / Rerun) and **Needs review** (Resend / Skip).
5. The **Dashboard** shows totals, sent-per-day and each sender's quota.

## Troubleshooting

| Message / symptom | Meaning and fix |
|---|---|
| `534-5.7.9 Application-specific password required` | Normal Google password used. Create an app password. |
| `535` (SMTP auth) | Wrong address/password or 2-Step Verification off. Regenerate; sender shows `auth_failed` until fixed. |
| `5.4.5`, "Daily user sending", "sending limit" | Gmail daily limit hit. Sender blocked for 24 h; add another sender or Resume after the reset time. |
| SMTP `421`, other `4xx`, connect/TLS error before sending | Transient: retried after 60 s, 5 min, 15 min, then Failed. |
| SMTP `550/551/553` or `5.1.x` at RCPT | Bad recipient. Item fails; does not count toward the breaker. |
| Other `5xx` | Permanent failure; counts toward the breaker. |
| Disconnect/timeout after DATA started | Item becomes **Unknown**. Check your Sent folder, then Mark as sent or Rerun. |
| Graph `401` | Token refreshed once and retried; if it still fails the sender is `auth_failed`: Reconnect. |
| Graph `invalid_grant` | Refresh token expired/revoked. Reconnect the Outlook account. |
| Graph `429` | Transient; `Retry-After` is honoured. |
| Graph `503`/`504` | Transient. |
| Graph `403`/`400` with "quota" | Outlook limit reached; sender blocked 24 h. |
| Other Graph `4xx` | Permanent failure. |
| "Outlook is not activated" | Set `OUTLOOK_CLIENT_ID` ([docs/providers/outlook.md](docs/providers/outlook.md)). |
| Gemini `429` / RESOURCE_EXHAUSTED | Key exhausted until midnight Pacific. Next key is tried, else `paused_llm`. |
| Gemini `400/401/403` | Invalid key → `auth_failed`. |
| Gemini "model not found" | Set `GEMINI_MODEL`. |
| `409 config_locked` | A run's settings cannot change after its first send. |
| `409 no_sender_available` on Resume | Still no sender; reasons and the earliest reset time are shown. |
| `409 needs_review_unresolved` on Start | Manual runs need every duplicate resolved first. |
| `422` on Prepare | A required setting is missing; the message names the field. |
| App exits at startup with "SECRET_KEY is required" | Generate a key (see Quick start) and put it in `.env`. |
| "SECRET_KEY is not a valid Fernet key" | The value must be exactly the printed 44-character key, no quotes or spaces. |
| `docker: command not found` / daemon not running (Windows) | Start Docker Desktop and wait until it says it is running. |
| `bad interpreter` / `\r` error running `scripts/*.sh` | Windows line endings: `dos2unix scripts/*.sh`, or use the PowerShell commands. |
| Port 8000 already in use | Change the host port in `docker-compose.yml`. |

## Backup / restore

**macOS / Linux / WSL / Git Bash**

```bash
scripts/backup.sh                          # → ./backups/<timestamp>/
scripts/restore.sh ./backups/<timestamp>
```

**Windows (PowerShell)**, binary-safe (avoids `>` redirection, which corrupts binary data in PowerShell 5):

```powershell
$ts = Get-Date -Format "yyyyMMddTHHmmss"
New-Item -ItemType Directory -Force "backups\$ts" | Out-Null
docker compose exec -T mongo mongodump --archive=/tmp/mongo.archive.gz --gzip --db applymail
docker compose cp mongo:/tmp/mongo.archive.gz "backups\$ts\mongo.archive.gz"
docker compose exec -T api tar -C /data -czf /tmp/data.tar.gz .
docker compose cp api:/tmp/data.tar.gz "backups\$ts\data.tar.gz"
```

Restore (replace `<ts>`):

```powershell
docker compose cp "backups\<ts>\mongo.archive.gz" mongo:/tmp/mongo.archive.gz
docker compose exec -T mongo mongorestore --archive=/tmp/mongo.archive.gz --gzip --drop
docker compose cp "backups\<ts>\data.tar.gz" api:/tmp/data.tar.gz
docker compose exec -T api sh -c "rm -rf /data/* && tar -C /data -xzf /tmp/data.tar.gz"
docker compose restart api worker
```

More in [docs/operations.md](docs/operations.md). The `SECRET_KEY` is not part of the backup: store it somewhere safe.

## FAQ

**Why no login?** Each person runs their own instance, bound to `127.0.0.1`. There is nobody to log in as.

**Why app passwords?** Google removed password-only SMTP (May 2025). An app password is the simplest supported way for a personal tool.

**Why is Outlook off by default?** It needs OAuth2 and your own free Azure app registration; Gmail works out of the box. See the Outlook guide.

**What does "unknown" mean?** The connection died after sending the message body, so the server may have accepted it. ApplyMail will not guess: you decide.

**Can I email the same person twice?** Not by accident. Use Needs review → Resend.

## Limits and facts

**[V]** verified on 2026-10-07 from the cited source; **[U]** from memory, unverified: kept configurable.

- **[V]** Gmail SMTP `smtp.gmail.com` 587 STARTTLS / 465 SSL; app password or OAuth required; personal 500 / rolling 24 h, Workspace 2,000 / day, 100 recipients per message. ([Nylas guide](https://developer.nylas.com/docs/cookbook/email/gmail-smtp-settings.md), secondary source)
- **[V]** Gemini limits apply per project, not per key; daily quota resets at midnight Pacific; exact numbers are in AI Studio. ApplyMail defaults to 200 requests/day. ([Google docs](https://ai.google.dev/gemini-api/docs/rate-limits))
- **[V]** Outlook should use OAuth2/Graph; Basic-auth SMTP AUTH is planned to be disabled by default at the end of December 2026 (Exchange Online). ([Nylas](https://developer.nylas.com/docs/cookbook/email/outlook-smtp-settings/), [Microsoft Q&A](https://learn.microsoft.com/en-sg/answers/questions/2125483/send-email-via-microsoft-graph-with-personal-accou))
- **[U]** Outlook free personal daily send limit (defaults 100/day, max 250).
- **[U]** Graph inline attachment ≤ 3 MB per `sendMail`, hence the 3 MB CV cap.
- **[U]** Public-client refresh tokens expire after about 90 days of inactivity.
- **[U]** Gmail daily-limit error text contains `5.4.5` / "Daily user sending".
- **[U]** Free-tier Gemini prompts may be used by Google to improve products.
- **[U]** `gemini-flash-latest` is a valid model alias (otherwise set `GEMINI_MODEL`).

See [docs/architecture.md](docs/architecture.md) for the data model, state machines, locking and worker algorithm.