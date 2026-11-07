param([string]$FloodgateJar = "$PSScriptRoot/../../../proxy/plugins/floodgate-bungee.jar")
$ErrorActionPreference = 'Stop'
$outputDir = Join-Path $PSScriptRoot 'target/classes'
if (Test-Path -LiteralPath $outputDir) {
    $resolvedOutput = (Resolve-Path -LiteralPath $outputDir).Path
    if (-not $resolvedOutput.StartsWith((Resolve-Path -LiteralPath $PSScriptRoot).Path + [IO.Path]::DirectorySeparatorChar)) { throw 'Unexpected output directory' }
    Remove-Item -LiteralPath $resolvedOutput -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$sourceFiles = @(Get-ChildItem -LiteralPath "$PSScriptRoot/src" -Recurse -Filter '*.java' | ForEach-Object { $_.FullName })
& javac --release 8 -encoding UTF-8 -classpath $FloodgateJar -d $outputDir @sourceFiles
if ($LASTEXITCODE -ne 0) { throw 'javac failed' }
Copy-Item -LiteralPath "$PSScriptRoot/init.json" -Destination $outputDir -Force
& jar --create --file "$PSScriptRoot/target/floodgate-mcqq-database.jar" -C $outputDir .
if ($LASTEXITCODE -ne 0) { throw 'jar failed' }
Write-Output "$PSScriptRoot/target/floodgate-mcqq-database.jar"
