# AirCode Autonomous Developer Engine 🚀

An automated, self-healing rapid prototyping platform running a headless AI agent loop to build, refactor, and host full-stack web applications dynamically via a cloud pipeline.

## 🛠️ Platform Architecture & Upgrades

### 1. Robust Backend Infrastructure (`server.py`)
*   **Modern Lifespan Architecture:** Upgraded the core FastAPI application to utilize the modern `asynccontextmanager` lifespan event handler, completely removing legacy deprecated event loops.
*   **Static Asset Delivery Pipeline:** Implemented directory-wide static mounting using `FastAPI.staticfiles` along with explicit root routing fallbacks to serve companion files (`style.css`, `script.js`) cleanly to the browser.
*   **Asynchronous Processing Loop:** Engineered a background task worker system that intercepts incoming webhooks, spawns headless subprocesses, and safely executes isolated file operations.

### 2. Automated Network Tunneling & Security
*   **Silent Public Port Lock:** Integrated a background automation routine utilizing the GitHub CLI (`gh`). The server automatically detects its current container environment string (`$CODESPACE_NAME`) upon binding to port 8000 and configures the cloud router visibility to `PUBLIC` without requiring interactive manual selections.
*   **Self-Healing Port Management:** Embedded proactive terminal port-clearing scripts (`fuser -k`) to drop ghost connections seamlessly before startup.

### 3. AI Agent Upgrades (Gemini Migration)
*   **Provider Optimization:** Migrated the core Aider code-refactoring loop from DeepSeek to Gemini via LiteLLM.
*   **Extended Reasoning Engine:** Leveraged Gemini's massive context window to process complex multi-file directories, layout styling rules, and state-machine inputs simultaneously without experiencing token cutoffs.

---

## 🏆 Completed Milestone Projects

The following applications have been successfully scaffolded, tested, and archived using this engine:

### 🏙️ Milestone 1: Isometric City Building Sandbox
*   **Simulation Ticker Loop:** Implemented a synchronized Delta-Time logic engine running on a background interval loop to dynamically compute multi-variable economic yields (Gold generation, Population capacity, and Power grid requirements).
*   **Affine Coordinate Viewport:** Rendered an 8x8 grass map grid utilizing a rotated spatial projection layout (`rotateX(60deg) rotateZ(-45deg)`) supporting dynamic hover styling and item coordinate placement.

---

## 🚀 Quick Start & Deployment

### Run the Server Engine
To boot the automated developer engine, clear the active network socket and initialize the script:
```bash
fuser -k 8000/tcp
python server.py
