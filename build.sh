#!/bin/bash
mkdir -p logs > /dev/null 2>&1
echo [DEBUG] docker compose build
docker compose build | tee logs/build.log
