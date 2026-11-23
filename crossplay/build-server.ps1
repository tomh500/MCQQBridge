param(
    [string]$ServerRoot = "$PSScriptRoot/../../..",
    [string]$SpigotJar = "$ServerRoot/core/spigot-1.12.2.jar",
    [string]$BungeeJar = "$ServerRoot/core/BungeeCord.jar",
    [string]$FloodgateJar = "$ServerRoot/proxy/plugins/floodgate-bungee.jar",
    [string]$BedWarsJar = "$ServerRoot/server/bw/plugins/bedwars-plugin-21.11.2-spigot112.jar"
)

$ErrorActionPreference = 'Stop'
$spigot = (Resolve-Path -LiteralPath $SpigotJar).Path
$bungee = (Resolve-Path -LiteralPath $BungeeJar).Path
$floodgate = (Resolve-Path -LiteralPath $FloodgateJar).Path
$pathSeparator = [IO.Path]::PathSeparator
$build = (New-Item -ItemType Directory -Force -Path "$PSScriptRoot/build").FullName
$staging = (New-Item -ItemType Directory -Path (Join-Path $build ([Guid]::NewGuid().ToString()))).FullName
$common = @(Get-ChildItem -LiteralPath "$PSScriptRoot/common/src/main/java" -Recurse -Filter '*.java' |
    ForEach-Object { $_.FullName })
$classpaths = @{
    spigot = $spigot
    bungee = $bungee, $floodgate -join $pathSeparator
}
$artifactNames = @{ spigot = 'SpigotMasterGAL-0.3.0'; bungee = 'BungeeMasterGAL-0.2.0' }

try {
    foreach ($component in 'spigot', 'bungee') {
        $source = "$PSScriptRoot/$component/src/main"
        $classes = (New-Item -ItemType Directory -Path "$staging/$component").FullName
        $sources = @(Get-ChildItem -LiteralPath "$source/java" -Recurse -Filter '*.java' |
            ForEach-Object { $_.FullName })
        & javac --release 8 -encoding UTF-8 -classpath $classpaths[$component] -d $classes @common @sources
        if ($LASTEXITCODE) { throw "javac failed for $component" }
        Copy-Item -Path "$source/resources/*" -Destination $classes
        $artifact = "$build/$($artifactNames[$component]).jar"
        & jar --create --file $artifact -C $classes .
        if ($LASTEXITCODE) { throw "jar failed for $component" }
        Write-Output $artifact
    }

    if ($BedWarsJar -and (Test-Path -LiteralPath $BedWarsJar -PathType Leaf)) {
        $menuSource = "$PSScriptRoot/menus/src/main"
        $menuClasses = (New-Item -ItemType Directory -Path "$staging/menus").FullName
        $menuSources = @(Get-ChildItem -LiteralPath "$menuSource/java" -Recurse -Filter '*.java' |
            ForEach-Object { $_.FullName })
        $bedWars = (Resolve-Path -LiteralPath $BedWarsJar).Path
        $menuClasspath = $spigot, $bedWars, "$build/SpigotMasterGAL-0.3.0.jar" -join $pathSeparator
        & javac --release 8 -encoding UTF-8 -classpath $menuClasspath -d $menuClasses @menuSources
        if ($LASTEXITCODE) { throw 'javac failed for MasterGALMenus' }
        Copy-Item -Path "$menuSource/resources/*" -Destination $menuClasses
        $menuArtifact = "$build/MasterGALMenus-0.3.0.jar"
        & jar --create --file $menuArtifact -C $menuClasses .
        if ($LASTEXITCODE) { throw 'jar failed for MasterGALMenus' }
        Write-Output $menuArtifact
    } else {
        Write-Output "Skipping MasterGALMenus: BedWars compile API not found at $bedWarsJar"
    }
} finally {
    $resolvedStaging = (Resolve-Path -LiteralPath $staging).Path
    if ([IO.Path]::GetDirectoryName($resolvedStaging) -ne $build) { throw 'Unexpected staging directory' }
    Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
}
