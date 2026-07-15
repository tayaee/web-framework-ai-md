@echo off
if "%LLM_API_KEY%"=="" (
    if not "%OPENAI_API_KEY%"=="" (
        set LLM_API_KEY=%OPENAI_API_KEY%
    ) else (
        echo LLM_API_KEY is not set. Please set it before running this script.
        exit /b 1
    )
)
set LLM_BASE_URL=https://api.openai.com/v1
set LLM_MODEL=gpt-5.4-mini
set LLM_API_PROTOCOL=openai
docker compose up -d
