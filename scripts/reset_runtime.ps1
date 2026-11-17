<#
.SYNOPSIS
Preview confirmed SimAssist runtime files, or remove them with -Execute.
.DESCRIPTION
Run with the API and worker stopped. Git-tracked files, .gitkeep files,
unrecognized content, and links are preserved. No data root is removed recursively.
#>
[CmdletBinding()]
param([switch]$Execute)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeRoots = @(
    (Join-Path $repositoryRoot 'data'),
    (Join-Path $repositoryRoot 'backend\data')
)
$uuid = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
$runtimePatterns = @(
    '^jobs\.db(?:-(?:wal|shm|journal))?$',
    '^artifacts/artifacts\.db(?:-(?:wal|shm|journal))?$',
    "^uploads/$uuid/$uuid\.(?:step|part)$",
    "^artifacts/files/$uuid/$uuid/(?:geometry\.step|mesh\.msh|preview\.json|$uuid\.step)(?:\.tmp)?$",
    "^artifacts/files/$uuid/$uuid/\.simassist-preview-cache/(?:(?:$uuid-)?v\d+(?:\.meta)?\.json|p-[0-9a-f]{12}\.tmp)$",
    "^workspaces/$uuid/geometry/$uuid/geometry\.step$",
    "^workspaces/$uuid/meshing/$uuid/mesh\.msh$",
    "^workspaces/$uuid/previews/$uuid/preview\.json$"
)
$directoryPattern = "^(?:cache|artifacts(?:/files(?:/$uuid(?:/$uuid(?:/\.simassist-preview-cache)?)?)?)?|uploads(?:/$uuid)?|workspaces(?:/$uuid(?:/(?:geometry|meshing|previews)(?:/$uuid)?)?)?)$"

function Assert-SafePath([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    if (-not $absolute.StartsWith($repositoryRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside the repository: $absolute"
    }
    # Inspect ancestors as well, so a junction cannot redirect a validated path.
    $ancestor = $absolute
    while ($ancestor) {
        if (Test-Path -LiteralPath $ancestor) {
            $item = Get-Item -LiteralPath $ancestor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Linked path is protected: $ancestor"
            }
        }
        $ancestor = [IO.Path]::GetDirectoryName($ancestor)
    }
}

function Get-TrackedPaths {
    $topLevel = & git -C $repositoryRoot rev-parse --show-toplevel
    if ($LASTEXITCODE -ne 0 -or [IO.Path]::GetFullPath($topLevel) -ne $repositoryRoot) {
        throw 'Cannot verify this repository with Git. Cleanup is refused.'
    }
    $tracked = & git -C $repositoryRoot -c core.quotepath=false ls-files -- data backend/data
    if ($LASTEXITCODE -ne 0) {
        throw 'Cannot inspect Git-tracked runtime paths. Cleanup is refused.'
    }
    foreach ($relative in $tracked) {
        [IO.Path]::GetFullPath((Join-Path $repositoryRoot $relative))
    }
}

function Assert-ProcessesStopped {
    try {
        $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        if ($processes.Count -eq 0) {
            throw 'Process enumeration returned no processes.'
        }
    }
    catch {
        throw "Cannot verify that API and worker are stopped. Cleanup is refused. $($_.Exception.Message)"
    }
    # Conservatively block all Python/uv/ASGI hosts, including script-based launches
    # whose command lines do not identify SimAssist. No process is stopped here.
    $active = @($processes | Where-Object {
        $_.Name -match '^(python.*|pypy.*|py|uvx?|uvicorn|gunicorn|hypercorn|fastapi|simassist[^.]*)\.exe$' -or
        $_.CommandLine -match 'simassist\.(main|workers\.runner)'
    })
    if ($active.Count) {
        $identifiers = ($active | ForEach-Object { "$($_.Name) PID=$($_.ProcessId)" }) -join ', '
        throw "Stop API, worker, and Python/uv/ASGI hosts before cleanup: $identifiers"
    }
}

$trackedPaths = @(Get-TrackedPaths)
$targets = [Collections.Generic.List[string]]::new()
$directories = [Collections.Generic.List[string]]::new()
$protected = [Collections.Generic.List[string]]::new()

foreach ($root in $runtimeRoots) {
    Write-Output "INSPECT $root"
    Assert-SafePath $root
    if (-not (Test-Path -LiteralPath $root)) { continue }
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "Runtime root is not a directory: $root"
    }
    if ($trackedPaths -contains $root) { throw "Git-tracked root is protected: $root" }
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push($root)
    while ($pending.Count) {
        $directory = $pending.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $trackedPaths -contains $item.FullName) {
                $protected.Add($item.FullName)
                continue
            }
            $relative = $item.FullName.Substring($root.Length + 1).Replace('\', '/')
            if ($item.PSIsContainer) {
                # Traverse for inspection, but only prune known runtime directories.
                if ($relative -match $directoryPattern) {
                    $directories.Add($item.FullName)
                }
                else { $protected.Add($item.FullName) }
                $pending.Push($item.FullName)
                continue
            }
            $recognized = @($runtimePatterns | Where-Object { $relative -match $_ }).Count -gt 0
            if ($item.Name -eq '.gitkeep' -or $trackedPaths -contains $item.FullName -or -not $recognized) {
                $protected.Add($item.FullName)
            }
            else {
                $targets.Add($item.FullName)
            }
        }
    }
}

# Print every file individually. Directory pruning is empty-only and nonrecursive.
foreach ($target in ($targets | Sort-Object)) { Write-Output "DELETE FILE $target" }
foreach ($directory in ($directories | Sort-Object Length -Descending)) {
    Write-Output "PRUNE IF EMPTY $directory"
}
foreach ($path in ($protected | Sort-Object)) { Write-Output "PRESERVE $path" }
Write-Output "Planned files: $($targets.Count). Protected entries: $($protected.Count)."

if (-not $Execute) {
    try {
        Assert-ProcessesStopped
        Write-Output 'Process check passed.'
    }
    catch { Write-Warning $_.Exception.Message }
    Write-Output 'Dry run only. Review targets, stop API and worker, then rerun with -Execute.'
    return
}

# Complete all preflight checks before the first deletion.
Assert-ProcessesStopped
$trackedPaths = @(Get-TrackedPaths)
foreach ($target in $targets) {
    Assert-SafePath $target
    if ($trackedPaths -contains $target) { throw "File became Git-tracked: $target" }
}
foreach ($target in $targets) {
    Assert-SafePath $target
    Remove-Item -LiteralPath $target -Force
}
foreach ($directory in ($directories | Sort-Object Length -Descending)) {
    Assert-SafePath $directory
    $trackedChildren = @($trackedPaths | Where-Object { $_.StartsWith($directory + '\', [StringComparison]::OrdinalIgnoreCase) })
    if (-not $trackedChildren.Count -and -not @(Get-ChildItem -LiteralPath $directory -Force).Count) {
        [IO.Directory]::Delete($directory, $false)
    }
}
Write-Output 'Runtime cleanup completed. Preserved entries are listed above.'
Write-Output "Select the canonical root in both launch shells: `$env:SIMASSIST_DATA_DIR = '$($runtimeRoots[0])'"
