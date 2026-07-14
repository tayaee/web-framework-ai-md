# AI.MD -- AI-powered Markdown Engine

ai.md is a new way of developing simple SPA or REST API application using markdown.
It is human-editable via text editors and directly compiled by the AI.MD engine into
executable applications.

## Use Cases

* SPA (Tetris)

Write your single-page app requirements in src/tetris.ai.md and access
http://localhost:8080/tetris.ai.md. Modifying the file and refreshing the browser
triggers on-the-fly re-compilation.

* REST API (Temperature Conversion)

Define API endpoints in src/convert.ai.md. You can immediately call the compiled
backend service via POST requests.

## Quick Start

1. Create an API key from OpenAI, Anthropic, MiniMax, DeepSeek or OpenRouter.

  ./setup-dotenv.sh
  ./deploy-to-docker.sh

2. (Optional) Take a look at src/*.md for the demo apps.
3. Use browser to hit http://localhost:8080/tetris.ai.md to create and run the Tetris game.
4. Try editing src/tetris.ai.md and reload the URL to re-deploy the app.
5. Run the following on terminal: `curl -X POST localhost:8080/convert.ai.md/convert -H 'Content-Type: application/json' -d '{"temperature": 30, "type": "C"}'`
6. Edit src/convert.ai.md to change the contract, and hit the URL again.

## Tested platforms

* Windows (WSL + Docker Desktop) + MiniMax-M3
