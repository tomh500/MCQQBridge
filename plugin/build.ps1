param(
    [string]$ServerRoot = "$PSScriptRoot/../../..",
    [string]$BungeeJar = "",
    [string]$ChatJar = ""
)
if (-not $BungeeJar) { $BungeeJar = Join-Path $ServerRoot "core/BungeeCord.jar" }
$ErrorActionPreference = 'Stop'
$outputDir = Join-Path $PSScriptRoot 'target/classes'
if (Test-Path -LiteralPath $outputDir) {
    $resolvedOutput = (Resolve-Path -LiteralPath $outputDir).Path
    if (-not $resolvedOutput.StartsWith((Resolve-Path -LiteralPath $PSScriptRoot).Path + [IO.Path]::DirectorySeparatorChar)) { throw 'Unexpected output directory' }
    Remove-Item -LiteralPath $resolvedOutput -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$sources = @(Get-ChildItem -LiteralPath "$PSScriptRoot/src/main/java" -Recurse -Filter '*.java' | ForEach-Object { $_.FullName })
if (-not $ChatJar) {
    $ChatJar = (Get-ChildItem (Join-Path $ServerRoot "proxy/plugins") -Filter '*Chat*.jar' |
        Select-Object -First 1).FullName
}
$classpath = @($BungeeJar, $ChatJar) | ForEach-Object { (Resolve-Path -LiteralPath $_).Path }
& javac --release 8 -encoding UTF-8 -classpath ($classpath -join [IO.Path]::PathSeparator) -d $outputDir @sources
if ($LASTEXITCODE -ne 0) { throw 'javac failed' }
Copy-Item -Path "$PSScriptRoot/src/main/resources/*" -Destination $outputDir -Force
& jar --create --file "$PSScriptRoot/target/mcqq-bridge-2.0.0.jar" -C $outputDir .
if ($LASTEXITCODE -ne 0) { throw 'jar failed' }
Write-Output "$PSScriptRoot/target/mcqq-bridge-2.0.0.jar"
