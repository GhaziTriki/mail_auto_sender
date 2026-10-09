# Security audit snapshots

Reports produced while hardening v1, kept for reference. They describe the dependency
trees of that moment, not the current lockfiles; rerun the tools for a fresh picture.

| File | Tool | When |
|---|---|---|
| `npm_audit_before.json` | `npm audit --json` in `frontend/` | before the dependency update |
| `npm_audit_after.json`, `npm_audit_after.txt` | `npm audit` | after the first fixes |
| `sca_python_before.json` | `pip-audit --format json` in `backend/` | before the dependency update |
| `bandit_before.html`, `bandit_after.html` | `bandit -r app -f html` | before and after the first fixes |

To rerun them: `cd frontend && npm audit`, `cd backend && uvx pip-audit`, `cd backend && uvx bandit -r app`.
