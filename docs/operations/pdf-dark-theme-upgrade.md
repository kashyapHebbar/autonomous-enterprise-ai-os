# UI Upgrade 4 — PDF export and theme-aware intelligence reports

## Prerequisites

- Existing React/FastAPI one-URL integration (`/app`)
- Upgrade 1 (Async and Live)
- Report Design V2
- Upgrade 3 (Grouped Artifacts and Execution Explorer)

## What's new

1. HTML executive reports, dashboards, and individual HTML charts default to dark mode in standalone view and match the AI OS dark palette.
2. When previewed within React, the HTML follows the app's current dark/light theme. Toggle the app theme to see it change live.
3. Each HTML artifact row has a **PDF** shortcut. In its Preview, **Save as PDF** opens the browser print dialog, where you select **Save as PDF** and save the file. This is a browser export, **not** a new server-generated or registered PDF artifact.
4. Print media rules always use readable white-paper cards and dark text, even if the UI is dark. The executive banner can retain its dark branded design.
5. PDF export runs in an iframe with scripts still disabled; the sandbox permits same-origin parent printing and modal dialogs but not scripts, forms or navigation.
6. Existing Markdown and raw HTML downloads remain available. No change to analytics, agent workflow, API, or app.py.

## Installation and testing

Stop `make dev` and run from the project root:

```bash
python3 ~/Downloads/AEAI-Upgrade4-PDF-Dark-Apply.py
source .venv/bin/activate
python -m pytest -q tests/test_report_pdf_dark_upgrade.py
cd frontend
npm run build
cd ..
make dev
```

On Apple Silicon Macs where `npm` resolves to an Intel executable, first run:

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
rehash
```

Then run a **new workflow** to regenerate the report/dashboard/chart HTML with upgraded styling. Old HTML artifacts are unchanged by design.

Go to **Reports & Artifacts**, select an HTML report, choose **Preview**, and click **Save as PDF**. In the browser dialog choose **Save as PDF** (and enable background graphics if desired). The resulting PDF is stored on your computer, not in the AI OS artifact registry. For Safari's native dialog, select the PDF option.

If the browser blocks iframe printing, use **Open** followed by `Command+P` on a Mac or `Ctrl+P` elsewhere.

## Limitations

- PDF output uses the user's browser print engine, not a server-side PDF conversion service. Rendering and the print-dialog UI may vary by browser. There is no headless PDF download API or automatic PDF artifact record in this upgrade.
- Previously generated HTML reports will not be recolored automatically. Generate a new run after upgrading.
- This does not install any new JavaScript or Python dependencies.
