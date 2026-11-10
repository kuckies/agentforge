@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -Command "$expected=Join-Path (Get-Location).Path '.venv\Scripts\python.exe'; $listeners=Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue; foreach($entry in $listeners){$target=Get-CimInstance Win32_Process -Filter ('ProcessId='+$entry.OwningProcess); $owner=Get-CimInstance Win32_Process -Filter ('ProcessId='+$target.ParentProcessId); if(($target.ExecutablePath -eq $expected -or $owner.ExecutablePath -eq $expected) -and $target.CommandLine -match 'streamlit'){Stop-Process -Id $target.ProcessId; Write-Output 'AgentForge stopped.'}}"
pause
