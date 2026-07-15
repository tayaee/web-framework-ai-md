# AI.MD -- AI-powered Markdown Engine

ai.md is a new way of developing simple SPA or REST API application using markdown.
It is human-editable via text editors and directly compiled by the AI.MD engine into
executable applications.

## Use Cases

* SPA (Tetris)

  Write your single-page app requirements in src/tetris.ai.md and access http://localhost:8080/tetris.ai.md. Modifying the file and refreshing the browser triggers on-the-fly re-compilation.

* REST API (Temperature Conversion)

  Define API endpoints in src/convert.ai.md. You can immediately call the compiled backend service via POST requests.

## Quick Start

1. Create an API key from OpenAI, Anthropic (Claude), OpenRouter, MiniMax, or DeepSeek.

2. Build the image:
    ```
    docker compose build
    ```

3. Set the API key and create a Docker container.
  
  * OpenAI
    ```
    export LLM_API_KEY=<OpenAI API Key>
    ./deploy-with-openai.sh
    ```

  * Claude (Anthropic):
    ```
    export LLM_API_KEY=<Anthropic API Key>
    ./deploy-with-sonnet.sh
    ```

  * OpenRouter:
    ```
    export LLM_API_KEY=<OpenRouter API Key>
    ./deploy-with-openrouter.sh
    ```

  * MiniMax:
    ```
    export LLM_API_KEY=<MiniMax API Key>
    ./deploy-with-minimax.sh  
    ```

  * DeepSeek:
    ```
    export LLM_API_KEY=<DeepSeek API Key>
    ./deploy-with-deepseek.sh
    ```

  On Windows (cmd.exe), set the vars first and then run `docker compose up -d`:

  ```
  set LLM_API_KEY=sk-xxxx
  set LLM_BASE_URL=https://api.openai.com/v1
  set LLM_MODEL=gpt-5.4
  set LLM_API_PROTOCOL=openai
  docker compose up -d
  ```

  On Windows (PowerShell):

  ```
  $env:LLM_API_KEY="sk-xxxx"; $env:LLM_BASE_URL="https://api.openai.com/v1"; $env:LLM_MODEL="gpt-5.4"; $env:LLM_API_PROTOCOL="openai"; docker compose up -d
  ```

4. (Optional) Take a look at src/*.md for the demo apps.
5. Use browser to hit http://localhost:8080/ to see the landing page, then click through to the Tetris demo.
6. Try editing src/tetris.ai.md and reload the URL to re-deploy the app.
7. Run the following on terminal: `curl -X POST localhost:8080/convert.ai.md/convert -H 'Content-Type: application/json' -d '{"temperature": 30, "type": "C"}'`
8. Edit src/convert.ai.md to change the contract, and hit the URL again.

## Tested platforms

* Windows (WSL + Docker Desktop) + MiniMax-M3
* Windows (native cmd.exe + Docker Desktop) + MiniMax-M3
