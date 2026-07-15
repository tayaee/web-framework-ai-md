#!/bin/bash
if [ -z "$LLM_API_KEY" ]; then
    if [ -n "$OPENAI_API_KEY" ]; then
        export LLM_API_KEY="$OPENAI_API_KEY"
    fi
fi
if [ -z "$LLM_API_KEY" ]; then
    echo "LLM_API_KEY is not set. Please set it before running this script."
    exit 1
fi
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=${LLM_MODEL:-gpt-5.6-luna}
export LLM_API_PROTOCOL=openai
docker compose up -d
