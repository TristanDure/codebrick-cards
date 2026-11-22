[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$Port = 8765,
    [switch]$Check,
    [switch]$NoBrowser
)

# Separate the browser operation so readiness can be tested without opening a browser.
function Open-StudyBrowser {
    param([string]$Url)
    Start-Process -FilePath $Url
}

function Get-StudyHttpIndexHash {
    param([string]$Url)
    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.Proxy = $null
    $request.Timeout = 500
    $request.ReadWriteTimeout = 500
    $request.KeepAlive = $false
    $response = $null
    $buffer = New-Object System.IO.MemoryStream
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $response = $request.GetResponse()
        $response.GetResponseStream().CopyTo($buffer)
        return [BitConverter]::ToString($sha.ComputeHash($buffer.ToArray())).Replace('-', '').ToLowerInvariant()
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        $buffer.Dispose()
        $sha.Dispose()
    }
}

function Start-StudyServer {
    [CmdletBinding()]
    param(
        [string]$Python,
        [string]$Root,
        [int]$Port,
        [string]$ExpectedIndexHash,
        [switch]$NoBrowser,
        [int]$ReadyTimeoutMilliseconds = 10000
    )
    # This private pipe signal is emitted only after this child binds its socket.
    # An unrelated service, including one serving identical data, cannot satisfy it.
    $token = [Guid]::NewGuid().ToString('N')
    $bootstrap = @'
import base64
import functools
import http.server
import socket
import sys
root = base64.b64decode(sys.argv[2]).decode("utf-8")
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
with http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), handler, bind_and_activate=False) as server:
    server.allow_reuse_address = False
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    server.server_bind()
    server.server_activate()
    print("codebrick-study-ready:" + sys.argv[3], flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
'@
    $bootstrap64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($bootstrap))
    $root64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Root))
    $server = New-Object System.Diagnostics.Process
    $server.StartInfo.FileName = $Python
    $server.StartInfo.Arguments = "-u -c `"import base64;exec(base64.b64decode('$bootstrap64'))`" $Port $root64 $token"
    $server.StartInfo.WorkingDirectory = $Root
    $server.StartInfo.UseShellExecute = $false
    $server.StartInfo.CreateNoWindow = $true
    $server.StartInfo.RedirectStandardOutput = $true
    $server.StartInfo.RedirectStandardError = $true
    $started = $false
    try {
        $started = $server.Start()
        if (-not $started) { throw 'The study server process could not be started.' }
        Write-Verbose "Study server process: $($server.Id)"
        # Drain stderr while waiting, so even a long error/request log cannot block the child.
        $stderr = $server.StandardError.ReadToEndAsync()
        $readyLine = $server.StandardOutput.ReadLineAsync()
        $deadline = [DateTime]::UtcNow.AddMilliseconds($ReadyTimeoutMilliseconds)
        while (-not $readyLine.IsCompleted -and [DateTime]::UtcNow -lt $deadline) {
            Start-Sleep -Milliseconds 50
        }
        if (-not $readyLine.IsCompleted) { throw "Study server startup timed out on port $Port. No browser was opened." }
        if ($readyLine.GetAwaiter().GetResult() -ne "codebrick-study-ready:$token") {
            $details = if ($stderr.IsCompleted) { $stderr.GetAwaiter().GetResult().Trim() } else { '' }
            throw "Study server exited before becoming ready on port $Port. If the port is in use, rerun with -Port and a different free port. No browser was opened. $details"
        }
        $stdout = $server.StandardOutput.ReadToEndAsync()
        $url = "http://127.0.0.1:$Port/web/workbench.html"
        $verified = $false
        while ([DateTime]::UtcNow -lt $deadline) {
            if ($server.HasExited) { throw 'Study server exited before HTTP verification. No browser was opened.' }
            $actualHash = $null
            try {
                $actualHash = Get-StudyHttpIndexHash -Url "http://127.0.0.1:$Port/data/study/index.json"
            } catch [System.Net.WebException] {
                Start-Sleep -Milliseconds 50
                continue
            }
            if ($actualHash -ne $ExpectedIndexHash) {
                throw 'The served study index does not match the local snapshot. No browser was opened.'
            }
            if ($server.HasExited) { throw 'Study server exited during HTTP verification. No browser was opened.' }
            $verified = $true
            break
        }
        if (-not $verified) { throw "Study server HTTP readiness timed out on port $Port. No browser was opened." }
        Write-Host "CodeBrick Cards ready: $url"
        Write-Host 'Content is still under review. Use Ctrl+C to stop this local-only server.'
        if (-not $NoBrowser) { Open-StudyBrowser -Url $url }
        # Keep the launcher in the foreground. Pipeline cancellation (Ctrl+C) runs finally.
        while (-not $server.WaitForExit(200)) { Start-Sleep -Milliseconds 50 }
        $exitCode = $server.ExitCode
        if ($exitCode -ne 0) {
            $details = $stderr.GetAwaiter().GetResult().Trim()
            Write-Warning "Study server exited with code ${exitCode}. $details"
        }
        return $exitCode
    } finally {
        try {
            if ($started) {
                try {
                    if (-not $server.HasExited) { $server.Kill() }
                } catch [System.InvalidOperationException] {
                    if (-not $server.HasExited) { throw }
                }
                if (-not $server.WaitForExit(5000)) {
                    throw 'The study server process did not stop within five seconds.'
                }
            }
        } finally {
            $server.Dispose()
        }
    }
}

# Dot-sourcing exposes the small test seam without starting a server or exiting the host.
if ($MyInvocation.InvocationName -eq '.') { return }

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$indexPath = Join-Path $root 'data\study\index.json'
if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) {
    throw 'Study data is missing. Run python scripts/prepare_workspace.py --demo for an offline demo, or --sync to fetch sources, then start again.'
}
$index = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($index.schema -ne 'codebrick-article-workspace') {
    throw 'Unexpected study index. No server was started.'
}

$candidates = @()
$projectPython = Join-Path $root '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $projectPython) { $candidates += $projectPython }
$candidates += @(Get-Command python.exe -All -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
if ($env:LOCALAPPDATA) {
    $pythonHome = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path -LiteralPath $pythonHome) {
        $candidates += @(Get-ChildItem -LiteralPath $pythonHome -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName 'python.exe' })
    }
}
if ($env:USERPROFILE) {
    $candidates += Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
$python = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
        $probe = & $candidate -c "import sys; print('codebrick-python-ok' if sys.version_info >= (3, 8) else 'too-old')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $probe -eq 'codebrick-python-ok') {
            $python = $candidate
            break
        }
    } catch { continue }
}
if (-not $python) {
    throw 'Python 3.8+ was not found. Install Python or create .venv/Scripts/python.exe in this project.'
}
$url = "http://127.0.0.1:$Port/web/workbench.html"
if ($Check) {
    [pscustomobject]@{
        python = $python
        project = $root
        url = $url
        articles = $index.summary.articles
        curatedCards = $index.summary.curatedCandidates
        contentApproved = $index.contentApproved
        serverStarted = $false
    } | ConvertTo-Json
    exit 0
}
Write-Host "Articles: $($index.summary.articles); curated candidates: $($index.summary.curatedCandidates)"
$indexHasher = [System.Security.Cryptography.SHA256]::Create()
try {
    $expectedIndexHash = [BitConverter]::ToString($indexHasher.ComputeHash([IO.File]::ReadAllBytes($indexPath))).Replace('-', '').ToLowerInvariant()
} finally {
    $indexHasher.Dispose()
}
exit (Start-StudyServer -Python $python -Root $root -Port $Port -ExpectedIndexHash $expectedIndexHash -NoBrowser:$NoBrowser)

