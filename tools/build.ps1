[CmdletBinding()]
param(
    [string]$Version = "8.4"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$sourceDir = Join-Path $projectRoot "src"
$entryPoint = Join-Path $sourceDir "main.py"
$pngIcon = Join-Path $projectRoot "assets\pixel_editor_logo.png"
$icoIcon = Join-Path $projectRoot "assets\pixel_editor_logo.ico"
$buildDir = Join-Path $projectRoot "build"
$workDir = Join-Path $buildDir "pyinstaller"
$specDir = Join-Path $buildDir "spec"
$exeName = "pixel${Version}像素编辑器"
$outputPath = Join-Path $buildDir "${exeName}.exe"

foreach ($requiredPath in @($entryPoint, $pngIcon, $icoIcon)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "缺少构建文件：$requiredPath"
    }
}

New-Item -ItemType Directory -Path $buildDir -Force | Out-Null
New-Item -ItemType Directory -Path $workDir -Force | Out-Null
New-Item -ItemType Directory -Path $specDir -Force | Out-Null

$pyInstallerArgs = @(
    "--clean"
    "--noconfirm"
    "--onefile"
    "--windowed"
    "--hidden-import", "PyQt5.sip"
    "--name", $exeName
    "--icon", $icoIcon
    "--add-data", "${pngIcon};assets"
    "--paths", $sourceDir
    "--distpath", $buildDir
    "--workpath", $workDir
    "--specpath", $specDir
    $entryPoint
)

& pyinstaller @pyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $outputPath)) {
    throw "构建完成但未找到 EXE：$outputPath"
}

Write-Host "构建完成：$outputPath"
