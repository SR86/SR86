$ErrorActionPreference = 'Stop'
$logDir = Join-Path $env:LOCALAPPDATA 'AutomationServer\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile = Join-Path $logDir ('startup-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')
function Log([string]$message) {
    Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ((Get-Date -Format o) + ' ' + $message)
}
$mutex = [Threading.Mutex]::new($false, 'Local\AutomationServerRemainingStartup')
$locked = $false
try {
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { exit 0 }
    Log 'startup_started'
    # Direct HTTPS with normal certificate validation; never send campus credentials.
    Add-Type -AssemblyName System.Net.Http
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $handler.AllowAutoRedirect = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(5)
    $online = $false
    try {
        for ($attempt = 1; $attempt -le 12; $attempt++) {
            foreach ($url in @('https://www.msftconnecttest.com/connecttest.txt', 'https://www.baidu.com/')) {
                try {
                    $response = $client.GetAsync($url).GetAwaiter().GetResult()
                    try {
                        if ([int]$response.StatusCode -eq 200) {
                            $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                            if (($url -like '*connecttest.txt' -and $body.Trim() -eq 'Microsoft Connect Test') -or
                                ($url -like '*baidu.com/*' -and $body -match '(?i)<html')) {
                                $online = $true
                            }
                        }
                    } finally { $response.Dispose() }
                } catch { }
                if ($online) { break }
            }
            if ($online) { break }
            Log 'network_not_ready'
            if ($attempt -lt 12) { Start-Sleep -Seconds 5 }
        }
    } finally { $client.Dispose(); $handler.Dispose() }
    if (-not $online) { Log 'network_check_failed'; exit 2 }
    Log 'network_check_passed'
    if (-not (Get-Process -Name 'clash-verge' -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath 'D:\Clash Verge\clash-verge.exe' -WindowStyle Hidden | Out-Null
        Log 'clash_start_requested'
    } else { Log 'clash_already_running' }
    Start-Sleep -Seconds 5
    if (Get-Process -Name 'verge-mihomo' -ErrorAction SilentlyContinue) { Log 'clash_core_running' }
    else { Log 'clash_core_not_running' }
    foreach ($name in @('Tailscale', 'RustDesk')) {
        $service = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($service -and $service.Status -eq 'Running') { Log ($name + '_service_running') }
        else { Log ($name + '_service_not_running') }
    }
    $raw = & 'C:\Program Files\Tailscale\tailscale.exe' status --json 2>$null
    if ($LASTEXITCODE -eq 0) {
        $status = $raw | ConvertFrom-Json
        if ($status.BackendState -eq 'Running' -and $status.Self.Online) { Log 'tailscale_online' }
        else { Log 'tailscale_not_online' }
    } else { Log 'tailscale_status_unavailable' }
    Log 'startup_completed'
} catch { Log ('error_type=' + $_.Exception.GetType().Name); exit 1 }
finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
