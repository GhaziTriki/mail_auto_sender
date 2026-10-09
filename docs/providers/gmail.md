# Gmail sender setup

**What you need:** a Gmail/Google account you will send from, with 2-Step Verification.

1. Sign in to the account and open <https://myaccount.google.com/security>.
2. Under "How you sign in to Google", turn on **2-Step Verification** (app passwords are unavailable without it; some work/school accounts may block them by admin policy).
3. Open <https://myaccount.google.com/apppasswords>. Name it `ApplyMail` → **Create**.
4. Copy the **16-character password** (shown once; spaces optional). Do not use your normal Google password.
5. In ApplyMail: **Settings → Senders → Gmail → Add account**: address, display name, app password, daily cap → **Add**, then **Check login**.
6. To revoke: delete the app password on the same Google page and switch the sender to idle/delete it in ApplyMail.

## Limits [V]

Personal accounts: 500 messages per rolling 24 h. Workspace: 2,000/day. 100 recipients per message (ApplyMail sends one recipient per message).
ApplyMail defaults to **100/day (max 400)** to stay well below the limit and avoid spam flags; raise it in the sender's settings (`DEFAULT_GMAIL_DAILY_CAP`, `MAX_GMAIL_DAILY_CAP`).

Password-only SMTP access was removed in May 2025, so an app password (or OAuth) is required. Source (secondary): Nylas Gmail SMTP guide, <https://developer.nylas.com/docs/cookbook/email/gmail-smtp-settings.md>.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `534-5.7.9 Application-specific password required` | You used your normal password. Create an app password. |
| `535` | Wrong address/password, or 2-Step Verification is off. Regenerate the app password. |
| Status `auth_failed` | Fix the password via **Edit**, then **Check login**. |
| Quota reached (`5.4.5` / "Daily user sending" / "sending limit") | The sender is blocked for 24 h; the run pauses as `paused_quota`. Add another sender, or click **Resume** after the reset time shown. |
| Connection or TLS errors | Treated as transient and retried (60 s, 5 min, 15 min). Check `GMAIL_SMTP_HOST`/`PORT`/`SECURITY` if it persists. |

[U] The quota error text containing `5.4.5` / "Daily user sending" is from memory; the matching is case-insensitive and also catches "sending limit".
