#!/bin/bash
if [ -z "$LLM_API_KEY" ]; then
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        export LLM_API_KEY="$ANTHROPIC_API_KEY"
    fi
fi
if [ -z "$LLM_API_KEY" ]; then
    echo "LLM_API_KEY is not set. Please set it before running this script."
    exit 1
fi
export LLM_NAME=sonnet
export LLM_BASE_URL=https://api.anthropic.com/v1
export LLM_MODEL=${LLM_MODEL:-claude-sonnet-5}
export LLM_API_PROTOCOL=anthropic
docker compose up -d
