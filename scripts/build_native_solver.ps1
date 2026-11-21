param([string]$DwsimHome = $env:DWSIM_HOME)
$ErrorActionPreference = 'Stop'
if (-not $DwsimHome) { throw 'Specify -DwsimHome or DWSIM_HOME' }
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$destination = Join-Path $projectRoot '.runtime\dwsim'
$sourcePath = Join-Path $projectRoot 'engineering\native\SepMindSolverBridge.cs'
$interfacePath = Join-Path $DwsimHome 'DWSIM.Interfaces.dll'
$compilerPath = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $interfacePath)) { throw 'DWSIM.Interfaces.dll is missing' }
if (-not (Test-Path -LiteralPath $compilerPath)) { throw '.NET Framework C# compiler is missing' }
New-Item -ItemType Directory -Force -Path $destination | Out-Null
$assemblyPath = Join-Path $destination 'SepMindSolverBridge.dll'
& $compilerPath '/nologo' '/target:library' "/out:$assemblyPath" "/reference:$interfacePath" $sourcePath
if ($LASTEXITCODE -ne 0) { throw 'Native bridge compilation failed' }
Write-Output "Built registered numerical adapter: $assemblyPath"
