@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_local_stack.ps1" %*
exit /b %ERRORLEVEL%