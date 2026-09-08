# Clover

A calm, local-first career companion. **Juno** is the assistant inside it — she learns what you're
looking for, tells you honestly what she thinks of a role, and keeps track of everything so you
don't have to. Your profile, documents, conversations, and model inference stay on your machine:
Juno runs Qwen through [LM Studio](https://lmstudio.ai/). When you ask Juno to search or open a
public page, only the search terms or requested URL are sent to those public web services.

## How it works

You meet Juno in conversation rather than filling in a form. She asks what to call you, what your
situation is, and what you're hoping for, then reads your resume if you have one. You can stop
early — she'll fill in the rest as you go.

From there, every role you're considering becomes **one opportunity with one durable thread**. The
posting, Juno's read on the fit, your drafts, your notes, the stage it's at, and the whole
conversation about it all live in that one place, so opening a role feels like Juno already
remembers this specific application.

Home shows the few things actually waiting on you and what you've moved forward lately. Deciding a
role isn't worth pursuing counts as progress too — there are no streaks or missed-target warnings
anywhere in Clover.

## Install

You do not need Python, LM Studio, or developer tools beforehand.

Open the [latest Clover release](https://github.com/ANRC2020/Job-Agent/releases/latest), then
download the installer for your computer.

**Mac**

- Apple Silicon (M1 or newer): **`Clover-macOS-arm64.dmg`**
- Intel Mac: **`Clover-macOS-x64.dmg`**

Open the DMG and drag Clover into Applications. Until the app is code-signed, the first launch may
require right-clicking Clover and choosing **Open**.

**Windows**

Download **`Clover-Windows-Setup.exe`** and double-click it. Until the installer is code-signed,
Windows may require **More info → Run anyway** on the first installation.

The native app sets up LM Studio only if it is missing and opens without waiting for the model
download. Juno finishes downloading in the background with status shown inside Clover. Clover
starts and stops Juno automatically; no terminal remains open.

Developers can still clone the repository and run `./install.command` on Mac or `install.cmd` on
Windows.

## Uninstall

With a native installation:

- **Mac:** move Clover from Applications to the Trash.
- **Windows:** open **Settings → Apps → Installed apps → Clover → Uninstall**.

These standard uninstall actions preserve your profile, conversations, opportunities, and
application history so reinstalling restores them. Users of an older source-based version can
download the latest repository ZIP and run `uninstall.command` or `uninstall.cmd`; it discovers
the older installation automatically and asks separately before permanently deleting personal data.

LM Studio is left installed because other local applications may use it. After uninstalling, the
downloaded Clover folder can be deleted normally.

## Live web and job search

Juno can search the current public web without an account or API key. Job searches prioritize
official company career pages and their public applicant-tracking pages while filtering out job
aggregators. Clover opens and verifies promising source pages, extracts the full description,
requirements, location, workplace type, employment type, compensation, posting date, and direct
application URL when available, then saves readable roles as Suggested opportunities. Source facts
and freshness remain separate from Juno's resume-grounded fit assessment.

Clover bundles the MIT-licensed [DDGS](https://github.com/deedy5/ddgs) metasearch library for this
read-only search layer, then reads supported applicant systems through their official public job
feeds. Web pages are treated as untrusted source material and cannot authorize submissions or
other external actions.

## Guided applications

Clover opens a dedicated, visible Chrome session for an application—there is no extension to
install. Juno reads each step, fills high-confidence answers grounded in your resume and confirmed
profile, attaches your locally stored resume, and navigates unambiguous Next or Continue steps.
Sensitive, uncertain, and protected-trait questions remain manual. Clover pauses at the final page
until you review it and give explicit one-time confirmation, then asks you to verify the employer's
success page.

Each opportunity has an **Apply with Juno** action. Clover opens the verified direct application
link, moves the role into Applying, and keeps the posting, tailored materials, notes, stage history,
and role-specific conversation together.

The application session uses a private browser profile stored with Clover's local data. You can sign
in to employer sites in that window when needed; Clover does not copy credentials into its database.

## Local data

Clover automatically creates and upgrades a private SQLite database when it is installed or opened.
It stores your profile and conversations, each opportunity with its materials and history, and
evidence-backed learnings. Application updates do not overwrite this data.

- New installs on Mac: `~/Library/Application Support/Clover/clover.sqlite3`
- New installs on Windows: `%LOCALAPPDATA%\Clover\clover.sqlite3`

Existing Job Agent installations keep using their original database automatically, so no personal
history is lost during the rename.

The local model can safely describe the schema, list/get records, create and update records, and
search conversations, person memory, jobs, interactions, and learnings. Raw SQL and internal
migration tables are not exposed to the model.

Confirmed learnings and explicitly stated communication preferences are automatically added to
Juno's system context. Unreviewed model guesses are excluded — they show up under **Profile** as
hunches you can confirm or correct. The active personalization is visible under
**Settings → Juno personalization**.

## After install

Opening Clover starts Juno's local Qwen model. Closing it shuts that local model down.

```bash
job-agent launch
job-agent status
job-agent stop
```

## License

[MIT](LICENSE)
