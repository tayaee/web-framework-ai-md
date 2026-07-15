#!/bin/bash
set +e
if docker compose ps >/dev/null 2>&1; then
    echo "Undeploying..."
    docker compose down >/dev/null 2>&1
else
    echo "No deployment to undeploy; skipping."
fi
exit 0
