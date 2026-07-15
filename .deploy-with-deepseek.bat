@echo off
if "%LLM_API_KEY%"=="" (
    if not "%DEEPSEEK_API_KEY%"=="" (
        set LLM_API_KEY=%DEEPSEEK_API_KEY%
    )
)
if "%LLM_API_KEY%"=="" (
    echo LLM_API_KEY is not set. Please set it before running this script.
    exit /b 1
)
set LLM_NAME=deepseek
set LLM_BASE_URL=https://api.deepseek.com/v1
set LLM_MODEL=deepseek-v4-flash
set LLM_API_PROTOCOL=openai
docker compose up -d
