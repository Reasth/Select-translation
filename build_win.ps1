# 一键构建 Windows 安装包。用法：在项目目录执行  ./build_win.ps1
# 产物只有一个：installer\TranslatePopup-Setup.exe（dist\TranslatePopup.exe 仅是中间产物）。
# 需要先装 Inno Setup 6（https://jrsoftware.org/isdl.php）。
$ErrorActionPreference = "Stop"

Write-Host "[1/4] 安装/更新打包依赖..." -ForegroundColor Cyan
python -m pip install -q --upgrade pyinstaller

Write-Host "[2/4] 清理旧产物..." -ForegroundColor Cyan
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist)  { Remove-Item dist  -Recurse -Force }

Write-Host "[3/4] 打包 exe（首次较慢）..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm TranslatePopup.spec
if (-not (Test-Path "dist/TranslatePopup.exe")) {
    Write-Host "打包失败，请检查上面的输出。" -ForegroundColor Red
    exit 1
}

Write-Host "[4/4] 编译安装包..." -ForegroundColor Cyan
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if ($null -eq $iscc) {
    $fallback = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $fallback) { $iscc = $fallback }
}
if ($null -eq $iscc) {
    Write-Host "未找到 Inno Setup（iscc）。请先安装：https://jrsoftware.org/isdl.php" -ForegroundColor Red
    exit 1
}
& $iscc TranslatePopup.iss | Select-Object -Last 3

$setup = "installer/TranslatePopup-Setup.exe"
if (Test-Path $setup) {
    $mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host "`n完成：$setup （$mb MB）" -ForegroundColor Green
} else {
    Write-Host "安装包编译失败，请检查上面的输出。" -ForegroundColor Red
    exit 1
}
