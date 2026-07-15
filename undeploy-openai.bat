@echo off
setlocal
set "PROJNAME=%LLM_NAME%"
if "%PROJNAME%"=="" set "PROJNAME=openai"
if "%LLM_API_KEY%"=="" set "LLM_API_KEY=noop-for-teardown"
docker compose ps >nul 2>&1
if errorlevel 1 (
    echo No deployment to undeploy; skipping.
) else (
    echo Undeploying project ai-md-%PROJNAME%...
    docker compose down >nul 2>&1
)
endlocal
exit /b 0
