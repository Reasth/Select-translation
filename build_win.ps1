# 一键打包 Windows 单文件 exe。用法：在项目目录执行  ./build_win.ps1
$ErrorActionPreference = "Stop"

Write-Host "[1/3] 安装/更新打包依赖..." -ForegroundColor Cyan
python -m pip install -q --upgrade pyinstaller

Write-Host "[2/3] 清理旧产物..." -ForegroundColor Cyan
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist)  { Remove-Item dist  -Recurse -Force }

Write-Host "[3/3] 打包中（首次较慢）..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm TranslatePopup.spec

$exe = "dist/TranslatePopup.exe"
if (Test-Path $exe) {
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "`n完成：$exe （$mb MB）" -ForegroundColor Green
    Write-Host "提示：装了 upx 后重打约可再省 10%（onefile 已二次压缩，增益有限）。" -ForegroundColor DarkGray
} else {
    Write-Host "打包失败，请检查上面的输出。" -ForegroundColor Red
    exit 1
}
