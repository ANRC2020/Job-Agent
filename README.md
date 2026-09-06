# Job Agent

Frictionless job applications — a local desktop app that runs Qwen through [LM Studio](https://lmstudio.ai/).

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

That installs the desktop app, sets up LM Studio only if it is missing, and opens Job Agent.

## Local data

Job Agent automatically creates and upgrades a private SQLite database when it is installed or opened.
It stores the person's profile and conversations, job processes and materials, and evidence-backed
learnings. Application updates do not overwrite this data.

- Mac: `~/Library/Application Support/Job Agent/job-agent.sqlite3`
- Windows: `%LOCALAPPDATA%\Job Agent\job-agent.sqlite3`

## After install

Opening the app starts Qwen. Closing it shuts that local model down.

```bash
job-agent launch
job-agent status
job-agent stop
```

## License

[MIT](LICENSE)
