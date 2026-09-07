# Clover

A calm, local-first career companion. **Juno** is the assistant inside it — she learns what you're
looking for, tells you honestly what she thinks of a role, and keeps track of everything so you
don't have to. Nothing leaves your machine: Juno runs Qwen through
[LM Studio](https://lmstudio.ai/).

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

You do not need to install Python. The installer downloads a private copy.

```bash
git clone https://github.com/ANRC2020/Job-Agent.git
cd Job-Agent
```

**Mac**

```bash
./install.sh
```

**Windows**

```powershell
.\install.ps1
```

That installs the desktop app, sets up LM Studio only if it is missing, and opens Clover.

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
