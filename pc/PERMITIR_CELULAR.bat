@echo off
chcp 65001 >nul
title MATRIX - permitir que el celular entre a la PC
:: Abre el puerto 8782 del Firewall de Windows SOLO en redes privadas (el wifi de tu casa),
:: para que la app del celular lea los partidos directo de esta PC. Hace falta una sola vez.
net session >nul 2>&1
if errorlevel 1 (
    echo Pidiendo permiso de administrador...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
netsh advfirewall firewall delete rule name="MATRIX Alertas (celular)" >nul 2>&1
netsh advfirewall firewall add rule name="MATRIX Alertas (celular)" dir=in action=allow protocol=TCP localport=8782 profile=private,domain
if errorlevel 1 (
    echo.
    echo  No se pudo agregar la regla del firewall.
) else (
    echo.
    echo  Listo: el celular ya puede entrar a esta PC por el wifi de la casa ^(puerto 8782^).
    echo  Si tu wifi esta marcado como red PUBLICA en Windows, cambialo a PRIVADA:
    echo  Configuracion ^> Red e Internet ^> Wi-Fi ^> tu red ^> Tipo de perfil: Privada.
)
echo.
pause
