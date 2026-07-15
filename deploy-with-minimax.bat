@echo off
if "%LLM_API_KEY%"=="" (
    if not "%MINIMAX_API_KEY%"=="" (
        set LLM_API_KEY=%MINIMAX_API_KEY%
    )
)
if "%LLM_API_KEY%"=="" (
    echo LLM_API_KEY is not set. Please set it before running this script.
    exit /b 1
)
set LLM_BASE_URL=https://api.minimax.io/v1
set LLM_MODEL=MiniMax-M3
set LLM_API_PROTOCOL=openai
docker compose up -d