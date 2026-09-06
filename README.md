# Job Agent

Frictionless job applications — a local desktop app that runs Qwen through [LM Studio](https://lmstudio.ai/) and uses this repo’s tools.

## Install

Clone the repo, then run the installer for your OS. The scripts skip LM Studio if it is already installed.

```bash
git clone https://github.com/ANRC2020/Job-Agent.git
cd Job-Agent
```

### Mac

- Installer: [install.sh](https://github.com/ANRC2020/Job-Agent/blob/main/install.sh)
- Double-click: [install.command](https://github.com/ANRC2020/Job-Agent/blob/main/install.command)

```bash
chmod +x install.sh install.command
./install.sh
```

That puts **Job Agent** in Applications and on the Desktop.

### Windows

- Installer: [install.ps1](https://github.com/ANRC2020/Job-Agent/blob/main/install.ps1)
- Double-click: [install.bat](https://github.com/ANRC2020/Job-Agent/blob/main/install.bat)

```powershell
.\install.ps1
```

That puts **Job Agent** on the Desktop and in the Start Menu.

Python 3 is required. The installer creates a virtualenv, downloads Qwen if needed, and opens the app.

## After install

Opening Job Agent starts the LM Studio daemon, loads Qwen, and starts the local API. Closing the window unloads the model and stops that mapping.

```bash
job-agent launch
job-agent status
job-agent stop
```

## License

[MIT](LICENSE)
