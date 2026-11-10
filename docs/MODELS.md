# Локальные модели

Демо и автоматические тесты работают без моделей. Для настоящей генерации используются отдельно установленные llama.cpp и GGUF-файлы. Эта сборка проверена с llama.cpp b12110 для Windows x64 Vulkan и Qwen2.5-Instruct Q4_K_M.

Положите распакованный движок в соседнюю папку `AgentForge-Runtime/llama`, а модели — в `AgentForge-Runtime/models`. Все DLL из архива движка должны оставаться рядом с llama-server.exe. Установка драйверов, CUDA или WSL для запуска демо не требуется.

## Проверенные источники

- [llama.cpp b12110](https://github.com/ggml-org/llama.cpp/releases/tag/b12110), архив `llama-b12110-bin-win-vulkan-x64.zip`, SHA-256 `9732a5e48887ca54d0bfe4af4324dc85fd56cd8cda19b52df3542fa6ebe6874f`.
- [Qwen 0.5B](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF), файл `qwen2.5-0.5b-instruct-q4_k_m.gguf`, SHA-256 `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`.
- [Qwen 1.5B](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/tree/91cad51170dc346986eccefdc2dd33a9da36ead9), файл `qwen2.5-1.5b-instruct-q4_k_m.gguf`, SHA-256 `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`.
- [Qwen 7B](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/tree/bb5d59e06d9551d752d08b292a50eb208b07ab1f), две части `qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf` и `qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf`. Обе должны быть рядом. SHA-256: `dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db` и `539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a`.

0.5B занимает около 0,49 ГБ, 1.5B — 1,12 ГБ, 7B — 4,68 ГБ на диске. Загрузка моделей выполняется пользователем отдельно; приложение не скачивает их автоматически. Требования к памяти зависят от модели, контекста и движка. Проверенная конфигурация разработчика: 16 ГБ RAM, Radeon RX 7700 XT с 12 ГБ VRAM, Windows 11. Другие GPU и компьютеры не подтверждены этой проверкой.

Скрипты Start-Model.cmd, Start-Model-1.5B.cmd и Start-Model-7B.cmd запускают модели вручную. В режиме локальной модели интерфейс может запустить установленные файлы сам. Для Ollama используется отдельная установка; приложение работает с уже установленной там моделью через локальный API. Условия использования моделей и движка смотрите у их издателей.
