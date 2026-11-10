@echo off
cd /d "%~dp0"
if not exist "..\AgentForge-Runtime\llama\llama-server.exe" (
  echo Local model runtime is missing. See README.md.
  pause
  exit /b 1
)
"..\AgentForge-Runtime\llama\llama-server.exe" -m "..\AgentForge-Runtime\models\qwen2.5-0.5b-instruct-q4_k_m.gguf" --host 127.0.0.1 --port 8081 --alias qwen-local -c 2048 -ngl 99 --threads 6
pause
