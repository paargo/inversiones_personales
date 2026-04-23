@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0bootstrap_env.ps1" %*
endlocal
