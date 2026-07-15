@echo off
if "%LLM_API_KEY%"=="" (
    if not "%ANTHROPIC_API_KEY%"=="" (
        set LLM_API_KEY=%ANTHROPIC_API_KEY%
    )
)
if "%LLM_API_KEY%"=="" (
    echo LLM_API_KEY is not set. Please set it before running this script.
    exit /b 1
)
set LLM_NAME=sonnet
set LLM_BASE_URL=https://api.anthropic.com/v1
set LLM_MODEL=claude-sonnet-5
set LLM_API_PROTOCOL=anthropic
docker compose up -d
