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

## After install

Opening the app starts Qwen. Closing it shuts that local model down.

```bash
job-agent launch
job-agent status
job-agent stop
```

## License

[MIT](LICENSE)
