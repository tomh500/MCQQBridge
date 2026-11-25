param(
    [string]$ServerRoot = "$PSScriptRoot/../../..",
    [string]$SpigotJar = "$ServerRoot/core/spigot-1.12.2.jar",
    [string]$BungeeJar = "$ServerRoot/core/BungeeCord.jar",
    [string]$FloodgateJar = "$ServerRoot/proxy/plugins/floodgate-bungee.jar",
    [string]$BedWarsJar = "$ServerRoot/server/bw/plugins/bedwars-plugin-21.11.2-spigot112.jar",
    [ValidateSet('All', 'SpigotMaster-GAL', 'BungeeMaster-GAL', 'MasterGALMenus')]
    [string]$Component = 'All'
)

$ErrorActionPreference = 'Stop'
$classpaths = [ordered]@{}
if ($Component -in 'All', 'SpigotMaster-GAL', 'MasterGALMenus') {
    $classpaths.spigot = (Resolve-Path -LiteralPath $SpigotJar).Path
}
if ($Component -in 'All', 'BungeeMaster-GAL') {
    $classpaths.bungee = @(
        (Resolve-Path -LiteralPath $BungeeJar).Path
        (Resolve-Path -LiteralPath $FloodgateJar).Path
    ) -join [IO.Path]::PathSeparator
}
$hasBedWars = $BedWarsJar -and (Test-Path -LiteralPath $BedWarsJar -PathType Leaf)
if ($Component -eq 'MasterGALMenus' -and !$hasBedWars) {
    throw "MasterGALMenus requires a BedWars compile API at $BedWarsJar"
}
$pathSeparator = [IO.Path]::PathSeparator
$build = (New-Item -ItemType Directory -Force -Path "$PSScriptRoot/build").FullName
$staging = (New-Item -ItemType Directory -Path (Join-Path $build ([Guid]::NewGuid().ToString()))).FullName
$common = @(Get-ChildItem -LiteralPath "$PSScriptRoot/common/src/main/java" -Recurse -Filter '*.java' |
    ForEach-Object { $_.FullName })
$artifactNames = @{ spigot = 'SpigotMasterGAL-0.4.0'; bungee = 'BungeeMasterGAL-0.3.1' }

try {
    foreach ($module in $classpaths.Keys) {
        $source = "$PSScriptRoot/$module/src/main"
        $classes = (New-Item -ItemType Directory -Path "$staging/$module").FullName
        $sources = @(Get-ChildItem -LiteralPath "$source/java" -Recurse -Filter '*.java' |
            ForEach-Object { $_.FullName })
        & javac --release 8 -encoding UTF-8 -classpath $classpaths[$module] -d $classes @common @sources
        if ($LASTEXITCODE) { throw "javac failed for $module" }
        Copy-Item -Path "$source/resources/*" -Destination $classes
        $artifact = "$build/$($artifactNames[$module]).jar"
        & jar --create --file $artifact -C $classes .
        if ($LASTEXITCODE) { throw "jar failed for $module" }
        Write-Output $artifact
    }

    if ($Component -in 'All', 'MasterGALMenus' -and $hasBedWars) {
        $menuSource = "$PSScriptRoot/menus/src/main"
        $menuClasses = (New-Item -ItemType Directory -Path "$staging/menus").FullName
        $menuSources = @(Get-ChildItem -LiteralPath "$menuSource/java" -Recurse -Filter '*.java' |
            ForEach-Object { $_.FullName })
        $bedWars = (Resolve-Path -LiteralPath $BedWarsJar).Path
        $menuClasspath = $classpaths.spigot, $bedWars, "$build/SpigotMasterGAL-0.4.0.jar" -join $pathSeparator
        & javac --release 8 -encoding UTF-8 -classpath $menuClasspath -d $menuClasses @menuSources
        if ($LASTEXITCODE) { throw 'javac failed for MasterGALMenus' }
        Copy-Item -Path "$menuSource/resources/*" -Destination $menuClasses
        $menuArtifact = "$build/MasterGALMenus-0.4.0.jar"
        & jar --create --file $menuArtifact -C $menuClasses .
        if ($LASTEXITCODE) { throw 'jar failed for MasterGALMenus' }
        Write-Output $menuArtifact
    } elseif ($Component -eq 'All') {
        Write-Output "Skipping MasterGALMenus: BedWars compile API not found at $bedWarsJar"
    }
} finally {
    $resolvedStaging = (Resolve-Path -LiteralPath $staging).Path
    if ([IO.Path]::GetDirectoryName($resolvedStaging) -ne $build) { throw 'Unexpected staging directory' }
    Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
}
