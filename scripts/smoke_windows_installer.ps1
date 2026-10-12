param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath
)

$ErrorActionPreference = 'Stop'
$installer = (Resolve-Path $InstallerPath).Path
$installDir = Join-Path $env:TEMP "vplayer-installer-smoke-$PID"
$markerKey = 'HKCU:\Software\VPlayer'
$environmentKey = 'HKCU:\Environment'
$originalProcessPath = $env:Path
$registry = Get-Item $environmentKey
$originalUserPath = $registry.GetValue('Path', $null, 'DoNotExpandEnvironmentNames')
$originalPathKind = if ($null -ne $originalUserPath) { $registry.GetValueKind('Path') }

if (Test-Path $markerKey) {
    throw 'VPlayer PATH marker already exists; refusing to modify an existing installation.'
}
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'
if ((Test-Path $uninstallKey) -and
    (Get-ChildItem $uninstallKey | Get-ItemProperty | Where-Object DisplayName -eq 'VPlayer')) {
    throw 'VPlayer is already installed; refusing to replace it.'
}

function Assert-PathState([bool]$expectedEntry, [bool]$expectedMarker) {
    $key = Get-Item $environmentKey
    $path = $key.GetValue('Path', $null, 'DoNotExpandEnvironmentNames')
    $entries = @(($path -split ';') | Where-Object { $_.TrimEnd('\') -ieq $installDir.TrimEnd('\') })
    if ($entries.Count -ne [int]$expectedEntry) {
        throw "Expected $([int]$expectedEntry) installer PATH entries, found $($entries.Count)."
    }
    if ((Test-Path "$markerKey") -and
        (Get-ItemProperty $markerKey -Name PathAdded -ErrorAction SilentlyContinue).PathAdded -eq '1') {
        $marker = $true
    } else {
        $marker = $false
    }
    if ($marker -ne $expectedMarker) {
        throw "Unexpected VPlayer PATH marker: $marker."
    }
    if ($expectedEntry -and $key.GetValueKind('Path') -ne [Microsoft.Win32.RegistryValueKind]::ExpandString) {
        throw 'Installer PATH must be REG_EXPAND_SZ.'
    }
}

function Install([string[]]$options) {
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$installDir") + $options
    $process = Start-Process $installer -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Installer exited with $($process.ExitCode)." }
    if (-not (Test-Path (Join-Path $installDir 'vplayer.exe'))) {
        throw 'Installed executable is missing.'
    }
}

function Uninstall {
    $uninstaller = Join-Path $installDir 'unins000.exe'
    if (Test-Path $uninstaller) {
        $process = Start-Process $uninstaller -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Uninstaller exited with $($process.ExitCode)." }
    }
}

try {
    Install @()
    Assert-PathState $true $true
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path', 'User')
    $pythonScripts = Join-Path (Split-Path (Get-Command python.exe -CommandType Application).Source) 'Scripts'
    $env:Path = (($env:Path -split ';') |
        Where-Object { $_.TrimEnd('\') -ine $pythonScripts.TrimEnd('\') }) -join ';'
    $resolved = (Get-Command vplayer.exe -ErrorAction Stop).Source
    if ($resolved -ine (Join-Path $installDir 'vplayer.exe')) {
        throw "Fresh PATH resolved the wrong executable: $resolved"
    }
    & vplayer.exe --version
    if ($LASTEXITCODE -ne 0) {
        throw "Installed vplayer --version exited with $LASTEXITCODE."
    }
    Uninstall
    Assert-PathState $false $false

    Install @('/MERGETASKS=!addtopath')
    Assert-PathState $false $false
    Uninstall
    Assert-PathState $false $false

    Install @()
    Assert-PathState $true $true
    Install @('/MERGETASKS=!addtopath')
    Assert-PathState $false $false
    Uninstall
    Assert-PathState $false $false

    $currentUserPath = (Get-Item $environmentKey).GetValue('Path', $null, 'DoNotExpandEnvironmentNames')
    if ($currentUserPath -cne $originalUserPath -or
        ($null -ne $originalUserPath -and (Get-Item $environmentKey).GetValueKind('Path') -ne $originalPathKind)) {
        throw 'Uninstall did not restore the original user PATH and value type.'
    }
    Write-Host 'Fresh install PATH on/off, upgrade PATH on to off, and uninstall passed.'
} finally {
    Uninstall
    $env:Path = $originalProcessPath
}
