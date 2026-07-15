#!/bin/bash
if [ -z "$LLM_API_KEY" ]; then
    if [ -n "$OPENROUTER_API_KEY" ]; then
        export LLM_API_KEY="$OPENROUTER_API_KEY"
    fi
fi
if [ -z "$LLM_API_KEY" ]; then
    echo "LLM_API_KEY is not set. Please set it before running this script."
    exit 1
fi
export LLM_NAME=openrouter
export LLM_BASE_URL=https://openrouter.ai/api/v1
export LLM_MODEL=${LLM_MODEL:-openrouter/free}
export LLM_API_PROTOCOL=openai
docker compose up -d
