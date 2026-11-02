# Operations Center — focused visual refresh (Upgrade 12.5 UI)

This is a frontend-only replacement for the Operations Center delivered by Upgrade 12.5. It changes:

- `frontend/src/pages/Operations.tsx`
- `frontend/src/operations.css`

It also includes offline UI contract tests. **No backend routes, workflows, schedules, credentials, data or reports are modified.**

## Improvements

- Compact mission-control hero showing real backend health, worker and monitoring status.
- Four KPI cards: waiting, running, completed and jobs needing review.
- Connected services with heartbeat age and persistence status.
- Queue distribution view based on actual queue counters (not dummy figures).
- Workflow queue filters, local search, per-run links and preserved audited dead-letter retry.
- Quick navigation to investigations, monitoring, sources and AI spending.
- Expandable technical diagnostics, rather than a wall of deployment text.
- Responsive light/dark styling, keyboard-accessible inputs and reduced-motion support.

## Install

Stop the development server, download `AEAI-Operations-UI-Refresh-Apply.py` to `~/Downloads`, and run from the project root:

```bash
python3 ~/Downloads/AEAI-Operations-UI-Refresh-Apply.py --check
python3 ~/Downloads/AEAI-Operations-UI-Refresh-Apply.py
python -m pytest -q tests/test_upgrade125_operations_ui.py
```

Build with native Node on Apple Silicon:

```zsh
eval "$(/opt/homebrew/bin/brew shellenv)"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
rehash
npm --prefix frontend run build
```

Start the backend with `make dev` and open `/app/operations`. Reload the page (Cmd+Shift+R) if assets were cached. **No Hugging Face calls are required** to test this UI.

## Safety

The installer accepts exactly the two Upgrade 12.5 UI file hashes and refuses unexpected edits. It creates `.operations-ui-backup-<timestamp>` at the project root. Use `--restore .operations-ui-backup-<timestamp>` to roll back, provided the installed files have not been edited since installation. The original Operations Banner styles used by the homepage are preserved.

The UI does not manage OS processes or execute shell commands. Operations remain governed by the existing FastAPI routes.
