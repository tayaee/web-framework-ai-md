@echo off
if "%LLM_API_KEY%"=="" (
    if not "%OPENROUTER_API_KEY%"=="" (
        set LLM_API_KEY=%OPENROUTER_API_KEY%
    )
)
if "%LLM_API_KEY%"=="" (
    echo LLM_API_KEY is not set. Please set it before running this script.
    exit /b 1
)
set LLM_NAME=openrouter
set LLM_BASE_URL=https://openrouter.ai/api/v1
set LLM_MODEL=openrouter/free
set LLM_API_PROTOCOL=openai
docker compose up -d
