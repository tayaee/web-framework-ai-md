#!/bin/bash
set +e
: "${LLM_API_KEY:=noop-for-teardown}"
export LLM_API_KEY
if docker compose ps >/dev/null 2>&1; then
    export LLM_NAME="${LLM_NAME:-openai}"
    echo "Undeploying project ai-md-${LLM_NAME}..."
    docker compose down >/dev/null 2>&1
else
    echo "No deployment to undeploy; skipping."
fi
exit 0
