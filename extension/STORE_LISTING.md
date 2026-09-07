# Chrome Web Store listing

## Product details

**Name:** Clover Browser Companion

**Category:** Productivity

**Language:** English

**Summary (132 characters max):**

Bring Juno into job pages to assess roles, prepare applications, and fill safe fields with your explicit approval.

## Detailed description

Clover Browser Companion brings Juno, your local job-search assistant, into the job and application page you are actively viewing.

Use the side panel to:

- assess a role against the resume stored in Clover;
- ask questions about the current page;
- save a promising opportunity;
- generate and fill safe, empty application fields;
- attach your locally stored resume to a clearly identified resume or CV field; and
- review and approve a final application submission.

Clover is local-first. The extension communicates with the Clover desktop app through a loopback address on your computer. Page access is requested one site at a time. Page captures are temporary unless you explicitly save an opportunity.

Passwords, financial information, government IDs, protected demographic questions, and consent fields are never generated or filled. Application submission requires a fresh, single-use confirmation bound to the paired browser, active tab, and reviewed URL.

The Clover desktop app must be installed and running.

## Single-purpose statement

The extension helps a Clover user understand job pages and prepare applications in the active browser tab through their local Juno assistant.

## Permission justifications

- **sidePanel:** Displays Juno beside the active job or application page.
- **storage:** Stores the local Clover address, revocable pairing token, and short-lived submission tab binding.
- **scripting:** Injects the companion only after the user grants access to the current site.
- **tabs:** Identifies and rechecks the active tab before capture, fill, upload, or approved submission.
- **alarms:** Periodically checks whether the local Clover app is available.
- **127.0.0.1 and localhost:** Communicates with the Clover desktop service running on the user's computer.
- **Optional HTTP/HTTPS site access:** Requested one origin at a time so the user can use the companion on the employer site they choose.

## Data-use disclosures

- Authentication information: a revocable local pairing token is stored in extension storage.
- Website content: visible job text and supported form metadata are sent only to the local Clover service.
- User activity: the active page is inspected only while the user operates the side panel.
- Personal communications, financial information, health information, precise location, and browsing history are not collected.
- Data is not sold, used for advertising, or sent to a hosted Clover service.

Use the public version of `PRIVACY.md` as the listing's privacy-policy URL.

## Required listing assets

- 128 × 128 extension icon: `icons/icon128.png`
- At least one accurate 1280 × 800 or 640 × 400 screenshot
- Optional 440 × 280 small promotional tile

Recommended screenshots:

1. Juno assessing a role in the side panel.
2. Safe application fields prepared with Undo visible.
3. The one-time final submission review.

Do not include real resume data, email addresses, phone numbers, pairing codes, or employer application answers in screenshots.

## Release checklist

1. Update `version` in `manifest.json`.
2. Run `uv run python scripts/package_extension.py`.
3. Run `cd extension && npm test`.
4. Upload `dist/clover-browser-companion-<version>.zip`.
5. Provide a public HTTPS privacy-policy URL.
6. Complete the Chrome Web Store data-use questionnaire using the disclosures above.
7. Upload sanitized screenshots and submit for review.
