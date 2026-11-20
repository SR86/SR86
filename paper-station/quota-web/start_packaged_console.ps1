[CmdletBinding()]
param([ValidateSet('console','probe','inspect')][string]$Action='console')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$package=Get-AppxPackage -Name 'OpenAI.Codex'
if (@($package).Count -ne 1) { throw 'CodexPackageUnavailableOrAmbiguous' }
$manifest=$package | Get-AppxPackageManifest
$application=$manifest.Package.Applications.Application | Where-Object Id -eq 'App'
if (@($application).Count -ne 1) { throw 'CodexApplicationUnavailable' }
$python=Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
switch($Action) {
    'console' { $entry=Join-Path $PSScriptRoot 'console_server.py'; $entryArgs='"'+$entry+'"' }
    'probe' {
        $entry=Join-Path $PSScriptRoot 'repair_windows_sandbox.py'
        $output=Join-Path $projectRoot 'backups\sandbox-package-probe.txt'
        $entryArgs='"'+$entry+'" probe --output "'+$output+'"'
    }
    'inspect' {
        $entry=Join-Path $PSScriptRoot 'repair_windows_sandbox.py'
        $output=Join-Path $projectRoot 'backups\sandbox-package-inspect.txt'
        $entryArgs='"'+$entry+'" inspect --output "'+$output+'"'
    }
}
Invoke-CommandInDesktopPackage -PackageFamilyName $package.PackageFamilyName -AppId $application.Id -Command $python -Args $entryArgs -PreventBreakaway -ErrorAction Stop
