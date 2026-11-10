@echo off
cd /d "%~dp0"
if not exist "..\AgentForge-Runtime\models\qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf" goto missing
if not exist "..\AgentForge-Runtime\models\qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf" goto missing
"..\AgentForge-Runtime\llama\llama-server.exe" -m "..\AgentForge-Runtime\models\qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf" --host 127.0.0.1 --port 8084 --alias qwen-7b -c 2048 -ngl 99 --threads 6
pause
exit /b 0
:missing
echo Both Qwen 7B model files are required. See README.md.
pause
exit /b 1
