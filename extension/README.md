# Clover Browser Companion

The Chromium companion lets Juno inspect the job or application page you are actively viewing,
answer questions about it, and fill safe empty form fields. It never submits an application.

## Load it in Chrome, Edge, Brave, or Arc

1. Open Clover and leave it running.
2. In the browser, open the extensions page and enable **Developer mode**.
3. Choose **Load unpacked** and select this `extension` folder.
4. Open **Clover → Settings → Browser companion** and choose **Pair a browser**.
5. Click the Clover toolbar icon and enter the eight-digit code.
6. When prompted, allow access to the current job site. Permission is requested one site at a time.

Pin Clover's icon for quick access. Clicking it opens the side panel.

## Build a ZIP

From the repository root, run Clover's managed Python:

```bash
uv run python scripts/package_extension.py
```

The result is `dist/clover-browser-companion.zip`. Unzip it before using **Load unpacked**.

## Safety boundaries

- Captured page text and form values stay in memory for the current request and are not added to
  Clover's database.
- Saving a role requires clicking **Save opportunity**.
- Passwords, payment details, government IDs, protected demographic fields, file inputs, consent
  checkboxes, hidden fields, and submit controls are excluded.
- Autofill changes only empty supported fields, highlights each change, and offers Undo.
- Juno cannot click or trigger submit.

See [PRIVACY.md](PRIVACY.md) for the complete data-handling summary.

## Test

```bash
cd extension
npm install
npm test
```
