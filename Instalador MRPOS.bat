@echo off
CHCP 65001 >NUL
title Instalador MRPOS Chile
color 0B

echo.
echo ========================================================
echo        INSTALANDO MRPOS - PUNTO DE VENTA NUBE
echo ========================================================
echo.
echo Creando acceso directo en su escritorio...
echo.

PowerShell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$WshShell = New-Object -comObject WScript.Shell; ^
    $DesktopPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop); ^
    if (-not $DesktopPath) { $DesktopPath = \"$env:USERPROFILE\Desktop\" }; ^
    $Shortcut = $WshShell.CreateShortcut(\"$DesktopPath\MRPOS.lnk\"); ^
    $ChromePath = \"C:\Program Files\Google\Chrome\Application\chrome.exe\"; ^
    if (-not (Test-Path $ChromePath)) { $ChromePath = \"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe\" }; ^
    if (-not (Test-Path $ChromePath)) { $ChromePath = \"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe\" }; ^
    $Shortcut.TargetPath = $ChromePath; ^
    $Shortcut.Arguments = \"--app=https://mrpos-chile.onrender.com/\"; ^
    $Shortcut.Description = \"MRPOS Punto de Venta\"; ^
    $Shortcut.IconLocation = \"C:\Windows\System32\imageres.dll, 109\"; ^
    $Shortcut.Save(); ^
    Write-Host 'Icono creado en: ' $DesktopPath"

echo.
echo [LISTO] El proceso ha terminado.
echo Si no ve el icono, intente click derecho e "Ir a Escritorio" o "Actualizar".
echo.
pause
