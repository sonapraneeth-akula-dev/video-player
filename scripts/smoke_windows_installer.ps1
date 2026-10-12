param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath
)

$ErrorActionPreference = 'Stop'
$installer = (Resolve-Path $InstallerPath).Path
$installDir = Join-Path $env:TEMP "vplayer-installer-smoke-$PID"
$markerKey = 'HKCU:\Software\VPlayer'
$environmentKey = 'HKCU:\Environment'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'VPlayer\VPlayer.lnk'
$originalProcessPath = $env:Path
$registry = Get-Item $environmentKey
$originalUserPath = $registry.GetValue('Path', $null, 'DoNotExpandEnvironmentNames')
$originalPathKind = if ($null -ne $originalUserPath) { $registry.GetValueKind('Path') }
$extensions = 'mp4', 'mkv', 'webm', 'mov', 'avi', 'ts', 'm4v', 'wmv', 'flv', 'mpg', 'mpeg'
$originalDefaults = @{}
foreach ($extension in $extensions) {
    $class = "HKCU:\Software\Classes\.$extension"
    $choice = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.$extension\UserChoice"
    $originalDefaults[$extension] = @{
        Class = if (Test-Path $class) { (Get-Item $class).GetValue('') } else { $null }
        Choice = if (Test-Path $choice) { (Get-Item $choice).GetValue('ProgId') } else { $null }
    }
}

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

function Assert-Associations([bool]$installed) {
    $classes = 'HKCU:\Software\Classes'
    $progId = Join-Path $classes 'VPlayer.Media'
    if ((Test-Path $progId) -ne $installed) { throw "Unexpected VPlayer.Media registration." }
    if ($installed) {
        $command = (Get-Item (Join-Path $progId 'shell\open\command')).GetValue('')
        if ($command -cne ('"{0}" "%1"' -f (Join-Path $installDir 'vplayer.exe'))) {
            throw "Incorrect VPlayer.Media open command: $command"
        }
    }
    foreach ($extension in $extensions) {
        $openWith = Join-Path $classes ".$extension\OpenWithProgids"
        $registered = (Test-Path $openWith) -and (
            (Get-Item $openWith).GetValueNames() -contains 'VPlayer.Media'
        )
        if ($registered -ne $installed) { throw "Unexpected Open With registration for .$extension." }
        $class = Join-Path $classes ".$extension"
        $choice = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.$extension\UserChoice"
        $classDefault = if (Test-Path $class) { (Get-Item $class).GetValue('') } else { $null }
        $userChoice = if (Test-Path $choice) { (Get-Item $choice).GetValue('ProgId') } else { $null }
        if ($classDefault -cne $originalDefaults[$extension].Class -or
            $userChoice -cne $originalDefaults[$extension].Choice) {
            throw "Installer changed the default app for .$extension."
        }
        $verb = Join-Path $classes "SystemFileAssociations\.$extension\shell\VPlayer.NewWindow"
        if ((Test-Path $verb) -ne $installed) { throw "Unexpected new-window verb for .$extension." }
        if ($installed) {
            $command = (Get-Item (Join-Path $verb 'command')).GetValue('')
            if ($command -cne ('"{0}" --new-window "%1"' -f (Join-Path $installDir 'vplayer.exe'))) {
                throw "Incorrect new-window command for .$extension`: $command"
            }
        }
    }
}

function Assert-InstallArtifacts([bool]$installed) {
    if ((Test-Path $shortcut) -ne $installed) { throw 'Unexpected VPlayer Start menu shortcut.' }
    if ((Test-Path (Join-Path $installDir 'vplayer.exe')) -ne $installed) {
        throw 'Unexpected installed executable state.'
    }
    if (-not $installed -and (Test-Path $markerKey)) {
        throw 'Uninstall left the VPlayer registry key behind.'
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
    Assert-Associations $true
    Assert-InstallArtifacts $true
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path', 'User')
    $pythonDirectory = if ($env:pythonLocation) {
        $env:pythonLocation
    } else {
        Split-Path (Get-Command python.exe -CommandType Application | Select-Object -First 1).Source
    }
    $pythonScripts = Join-Path $pythonDirectory 'Scripts'
    $env:Path = (($env:Path -split ';') |
        Where-Object { $_.TrimEnd('\') -ine $pythonScripts.TrimEnd('\') }) -join ';'
    $resolved = & pwsh.exe -NoProfile -Command '(Get-Command vplayer.exe -CommandType Application | Select-Object -First 1).Source'
    if ($LASTEXITCODE -ne 0) { throw 'Fresh shell could not resolve vplayer.exe.' }
    $resolved = $resolved.Trim()
    if ($resolved -ine (Join-Path $installDir 'vplayer.exe')) {
        throw "Fresh PATH resolved the wrong executable: $resolved (excluded $pythonScripts)"
    }
    & $resolved --version
    if ($LASTEXITCODE -ne 0) {
        throw "Installed vplayer --version exited with $LASTEXITCODE."
    }
    Uninstall
    Assert-PathState $false $false
    Assert-Associations $false
    Assert-InstallArtifacts $false

    Install @('/MERGETASKS=!addtopath')
    Assert-PathState $false $false
    Assert-Associations $true
    Assert-InstallArtifacts $true
    Uninstall
    Assert-PathState $false $false
    Assert-Associations $false
    Assert-InstallArtifacts $false

    Install @()
    Assert-PathState $true $true
    Install @('/MERGETASKS=!addtopath')
    Assert-PathState $false $false
    Uninstall
    Assert-PathState $false $false
    Assert-InstallArtifacts $false

    $preexisting = if ($originalUserPath -and -not $originalUserPath.EndsWith(';')) {
        "$originalUserPath;$installDir"
    } else {
        "$originalUserPath$installDir"
    }
    New-ItemProperty $environmentKey -Name Path -Value $preexisting -PropertyType ExpandString -Force |
        Out-Null
    try {
        Install @()
        Assert-PathState $true $false
        Assert-Associations $true
        Uninstall
        Assert-PathState $true $false
        Assert-Associations $false
        Assert-InstallArtifacts $false
    } finally {
        if ($null -eq $originalUserPath) {
            Remove-ItemProperty $environmentKey -Name Path
        } else {
            New-ItemProperty $environmentKey -Name Path -Value $originalUserPath `
                -PropertyType $originalPathKind -Force | Out-Null
        }
    }

    $currentUserPath = (Get-Item $environmentKey).GetValue('Path', $null, 'DoNotExpandEnvironmentNames')
    if ($currentUserPath -cne $originalUserPath -or
        ($null -ne $originalUserPath -and (Get-Item $environmentKey).GetValueKind('Path') -ne $originalPathKind)) {
        $currentPathKind = if ($null -ne $currentUserPath) { (Get-Item $environmentKey).GetValueKind('Path') }
        throw "Uninstall changed user PATH: before present=$($null -ne $originalUserPath) kind=$originalPathKind length=$($originalUserPath.Length); after present=$($null -ne $currentUserPath) kind=$currentPathKind length=$($currentUserPath.Length)"
    }
    Write-Host 'Fresh install PATH on/off, associations, upgrade, and clean uninstall passed.'
} finally {
    Uninstall
    $env:Path = $originalProcessPath
}
