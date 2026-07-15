# AI.MD -- Translate Markdown Into Web Application Directly.

ai.md is a new way of developing simple SPA (single page application) or REST API application using markdown.
It is human-editable via text editors and directly compiled by the AI.MD engine into executable applications.

## Demo Use Cases

* SPA (Tetris)

  Write your single-page app requirements in `src/tetris.ai.md` and access http://localhost:8080/tetris.ai.md. Modifying the file and refreshing the browser triggers on-the-fly re-compilation.

* REST API (Temperature Conversion)

  Define API endpoints in `src/convert.ai.md`. You can immediately call the compiled backend service via POST requests.

## Quick Start

### Prerequisites
* Linux or WSL
* Docker
* API Key from OpenAI or MiniMax 

### Instruction
* Clone the repo
    ```
    git clone https://github.com/tayaee/web-framework-ai-md.git
    cd web-framework-ai-md
    ```
* First time deployment to Docker
  #### Linux
    
    ```
    export LLM_API_KEY=$OPENAI_API_KEY
    ./build.sh
    ./undeploy-openai.sh
    ./deploy-with-openai.sh
    ```
  #### Windows
    
    ```
    set LLM_API_KEY=%OPENAI_API_KEY%
    .\build.bat
    .\undeploy-openai.bat
    .\deploy-with-openai.bat
    ```
* Open http://localhost:8080/ and try out the demo app Tetris
* Edit `src\tetris.ai.md` with additional requirements and save it.
* Reload the URL to rebuild the app live.
* Find your app cache at dist/. Those will be re-used during the next container runs.

## Verified Configurations

* Windows + Docker Desktop + OpenAI
* WSL2 + Docker Desktop + Minimax
