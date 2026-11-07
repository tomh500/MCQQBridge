$ErrorActionPreference = 'Stop'
$mavenCommand = Get-Command mvn -ErrorAction SilentlyContinue
if (-not $mavenCommand) { throw 'Install Maven 3.9+ and put mvn on PATH.' }
& $mavenCommand.Source -B -f "$PSScriptRoot/pom.xml" package
if ($LASTEXITCODE) { throw 'Maven build failed' }
