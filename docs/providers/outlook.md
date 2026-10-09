# Outlook sender setup

Outlook is **off by default**. Gmail needs none of this. ApplyMail sends through **Microsoft Graph** with OAuth2 because Microsoft is retiring password-based SMTP [V] (Basic-auth SMTP AUTH is planned to be disabled by default at the end of December 2026 for Exchange Online).

1. Go to <https://portal.azure.com> and sign in with your Microsoft account (Microsoft may ask you to create a free directory first; no payment is needed for app registrations).
2. Search **App registrations** → **New registration**.
3. Name: `ApplyMail`. Supported account types: **Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant) and personal Microsoft accounts**.
4. Redirect URI: platform **Public client/native (mobile & desktop)**, value `http://localhost:8000/api/oauth/outlook/callback` (must match `OUTLOOK_REDIRECT_URI` exactly; change both if you change the port). **Register**.
5. On the Overview page copy the **Application (client) ID**.
6. **Authentication** → under Advanced settings set **Allow public client flows = Yes** → Save.
7. **API permissions → Add a permission → Microsoft Graph → Delegated permissions** → add `Mail.Send`, `User.Read`, `offline_access`. For personal accounts you consent when you sign in; no admin consent step.
8. In `.env` set `OUTLOOK_CLIENT_ID=<the id>`, then `docker compose up -d` (restarts api and worker).
9. In ApplyMail: **Settings → Senders → Outlook → Connect Outlook account**, sign in and accept the permissions.

No client secret is used or stored. Tokens are stored encrypted. If sending later fails with `auth_failed` (for example after months of inactivity [U]), click **Reconnect**.

## Limits

Personal-account daily limits are not documented for free accounts [U]; ApplyMail defaults to **100/day (max 250)** (`DEFAULT_OUTLOOK_DAILY_CAP`, `MAX_OUTLOOK_DAILY_CAP`). The attachment limit for an inline Graph `sendMail` request is about 3 MB [U], which is why the CV is capped at 3 MB. Work/school accounts may be blocked by tenant policy.

Sources: <https://developer.nylas.com/docs/cookbook/email/outlook-smtp-settings/> and <https://learn.microsoft.com/en-sg/answers/questions/2125483/send-email-via-microsoft-graph-with-personal-accou>.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Outlook tab says "Not activated" | `OUTLOOK_CLIENT_ID` is empty. Follow steps 1–8. |
| Sign-in page error about the redirect URI | The URI in Azure differs from `OUTLOOK_REDIRECT_URI`. They must match exactly. |
| `invalid_grant` / status `auth_failed` | The refresh token expired or was revoked. Click **Reconnect**. |
| 429 | Treated as transient; the `Retry-After` header is honoured by the retry schedule. |
| 403/400 mentioning quota | The sender is blocked for 24 h; the run pauses as `paused_quota` if no other sender is available. |
