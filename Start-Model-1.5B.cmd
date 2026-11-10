@echo off
cd /d "%~dp0"
if not exist "..\AgentForge-Runtime\models\qwen2.5-1.5b-instruct-q4_k_m.gguf" (
  echo Qwen 1.5B model is missing. See README.md.
  pause
  exit /b 1
)
"..\AgentForge-Runtime\llama\llama-server.exe" -m "..\AgentForge-Runtime\models\qwen2.5-1.5b-instruct-q4_k_m.gguf" --host 127.0.0.1 --port 8082 --alias qwen-1.5b -c 2048 -ngl 99 --threads 6
pause
