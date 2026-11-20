"""Launch one local worker with Windows-assigned Codex package identity."""
from pathlib import Path
import subprocess


def command(project):
    project=Path(project).resolve()
    python=project/'.venv'/'Scripts'/'pythonw.exe'
    entry=project/'quota-web'/'console_server.py'
    def literal(value):return "'"+str(value).replace("'","''")+"'"
    # Invoke the Windows cmdlet directly. Do not change script execution policy.
    statement=('Invoke-CommandInDesktopPackage -PackageFamilyName '
        "'OpenAI.Codex_2p2nqsd0c76g0' -AppId 'App' -Command "+literal(python)
        +' -Args '+literal(subprocess.list2cmdline([str(entry)]))+' -PreventBreakaway -ErrorAction Stop')
    return ['powershell.exe','-NoProfile','-NonInteractive','-Command',statement]


def start(project):
    subprocess.run(command(project),check=True,timeout=25,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
