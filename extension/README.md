# Clover Browser Companion

The Chromium companion lets Juno inspect the job or application page you are actively viewing,
answer questions about it, fill safe empty form fields, and attach your stored resume. It can click
one unambiguous final submission button only after you review the live page and explicitly confirm.

## Install

For a normal release, install Clover Browser Companion from its Chrome Web Store page. The browser
installs it once and delivers future updates automatically. Clover still uses a one-time local
pairing step so a website cannot connect to the desktop app.

Until the store listing is published, use the development steps below.

## Load it for development in Chrome, Edge, Brave, or Arc

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

The store upload is `dist/clover-browser-companion-<version>.zip`; the script also writes
`dist/clover-browser-companion.zip` for local release tooling. A ZIP must be uploaded to the browser
store; for **Load unpacked**, select the `extension` folder directly.

Store copy, permission justifications, disclosures, and the submission checklist live in
[`STORE_LISTING.md`](STORE_LISTING.md).

## Safety boundaries

- Captured page text and form values stay in memory for the current request and are not added to
  Clover's database.
- Saving a role requires clicking **Save opportunity**.
- Passwords, payment details, government IDs, protected demographic fields, consent checkboxes,
  hidden fields, and submit controls are excluded from generated answers.
- A resume is attached only to a clearly identified resume or CV file field.
- Autofill changes only empty supported fields, highlights each change, and offers Undo.
- Multi-page forms are prepared one page at a time; you control when to continue.
- Final submission requires a fresh one-time approval, is bound to the reviewed URL, and stops when
  required fields are incomplete or the submit control is ambiguous. Confirm receipt on the
  employer's success page.

See [PRIVACY.md](PRIVACY.md) for the complete data-handling summary.

## Test

```bash
cd extension
npm install
npm test
```
