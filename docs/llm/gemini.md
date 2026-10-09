# Gemini API keys (optional)

Only needed for **LLM greeting mode**. Rules mode needs no key.

1. Open <https://aistudio.google.com/apikey> → **Create API key**.
2. Choose an existing Google Cloud project or **create a new one**; copy the key.
3. In ApplyMail: **Settings → LLM keys → Add key** (label, key, daily cap) → **Check**.
4. Quotas apply **per project, not per key** [V]: two keys from the same project share one quota. To add capacity, create each key in a **separate project**.
5. View your real limits at <https://aistudio.google.com/rate-limit>. ApplyMail defaults to **200 requests/day** (editable; `DEFAULT_LLM_DAILY_CAP`).
6. The daily quota resets at **midnight Pacific time** [V], about 08:00 (summer) or 09:00 (winter) in Tunis. ApplyMail shows the reset time in your local time.
7. Privacy: in LLM mode, contact names and email addresses are sent to Gemini; free-tier prompts may be used by Google to improve its products. Use rules mode if that is not acceptable.

Source: <https://ai.google.dev/gemini-api/docs/rate-limits>.

## How ApplyMail uses it

- 20 contacts per request (`LLM_BATCH_SIZE`), at least 6 s apart (`LLM_MIN_INTERVAL_S`), JSON output, `temperature=0`.
- The model only decides human vs company, cleaned name/company and an optional honorific. It never writes the email body.
- Results are cached on each email, so Resume never re-calls the model for finished items.
- Invalid or missing answers are retried (smaller batch, up to 2 times), then rules decide and tag the email `decided_by=rules` with warning `llm_failed`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| 429 / RESOURCE_EXHAUSTED | Key exhausted until the next midnight Pacific. ApplyMail moves to the next key or pauses the run as `paused_llm`. |
| 400/401/403 invalid key | The key becomes `auth_failed`. Replace it and click **Check**. |
| Model not found | Set `GEMINI_MODEL` in `.env` (default `gemini-flash-latest` [U]). |
| Run in `paused_llm` | Add a key and **Resume**, wait for the reset, or **Switch to rules** and continue. |
