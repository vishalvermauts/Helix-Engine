# 🧬 Helix Engine

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python Version](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)
![Architecture](https://img.shields.io/badge/Architecture-Three--Tier%20Defensive-orange)

The **Helix Engine** is a state-of-the-art, autonomous agent generation and orchestration backend. It leverages a rigorous **Three-Tier Defensive Architecture** to write, execute, and self-heal Python and Node.js agents dynamically on the fly based on webhook payloads.

---

## 🏗️ The Three-Tier Architecture

To achieve production-grade reliability when LLMs write code, the Helix Engine relies on three synchronized layers of defense:

### Tier 1: Prevention (Dynamic Skill RAG)
Located in `core_memory/skills/`, the engine maintains a localized "Brain" of strict guidelines. When a user requests a specific type of agent (e.g., a "GitHub Security Scanner"), the **Triage Router** dynamically injects the relevant `.md` memory files into the LLM context. This enforces domain knowledge *before* a single line of code is written (e.g., forcing the use of `gitleaks` over `git grep`, or enforcing `-f json` for Bandit).

### Tier 2: Enforcement (Staff Linter Prompting)
The `Planner Agent` acts as a Staff Engineer, intercepting the user's raw prompt and explicitly injecting architectural constraints. It ensures every generated agent:
1. Implements strict `try/except` subprocess exception handling.
2. Only operates within a controlled execution sandbox (e.g., `/workspaces/AirCode/workspace/`).
3. Outputs clear, unified markdown reports (`report.md`).

### Tier 3: Correction (The Self-Healing Loop)
If an agent compiles with a syntax error, the `Swarm Orchestrator` catches the traceback and automatically feeds the error *back* into the LLM for a self-correction loop (up to 3 retries). This guarantees that any syntax typos or module import errors are fixed silently without human intervention.

---

## 🚀 Engine Capabilities

- **Autonomous Agent Generation:** Request complex agents (Scrapers, Documenters, Security Scanners) and the engine will scaffold, write, test, and save them directly to the `workspace/custom_agents/` directory.
- **Webhook Orchestration:** Fully decoupled HTTP design. Expose the `/webhook` endpoint via Ngrok or Cloudflare Tunnels, and integrate it with messaging platforms (like Telegram or Discord) or frontend dashboards.
- **Dynamic Semantic Routing:** The `Triage Router` automatically classifies inbound requests as `SIMPLE`, `AGENT_GENERATION`, `QA_TESTING`, or `COMPLEX`, assigning the optimal model size and context length for cost-efficiency.

---

## 📂 Repository Structure

```text
HelixEngine/
├── agents/                     # Core system agents
│   ├── orchestrator.py         # Tier 3: Executes agents & handles self-healing
│   ├── planner_agent.py        # Tier 2: Staff Linter blueprint generation
│   └── triage_router.py        # Tier 1: Semantic router & RAG injection
├── core_memory/                # The Brain: Long-term storage & RAG skills
│   └── skills/                 # Domain-specific constraints (Security, Routing)
├── workspace/                  # Execution Sandbox
│   └── custom_agents/          # Output directory for successfully generated agents
├── server.py                   # FastAPI application & Webhook receiver
└── .env.example                # Template for LLM API keys
```

---

## 🛠️ Setup & Installation

We provide a magical, 1-click interactive setup script that automatically handles Python dependencies, `.env` generation, and auto-tunneling.

1. **Clone the Engine:**
   ```bash
   git clone https://github.com/vishalvermauts/Helix-Engine.git
   cd Helix-Engine
   ```

2. **Run the Interactive Wizard:**
   ```bash
   bash setup.sh
   ```
   *The wizard will ask for your API keys, build your virtual environment, and instantly launch the engine with a secure PyNgrok HTTPS tunnel!*

---

## 🔬 Connecting to the Helix Brain Diagnostic Lab

The Helix Engine is designed to run completely headlessly in the background. To interface with it, you will need the **Helix Brain Diagnostic Lab** frontend.

1. **Clone the Diagnostic Lab Repository:**
   *(The dashboard is maintained in a separate repository)*
   ```bash
   git clone https://github.com/vishalvermauts/Helix-Brain-Diagnostic-Lab.git
   ```

2. **Establish the Backend Webhook Tunnel:**
   The frontend (which typically runs on port `3000` or `5173`) needs to communicate with this backend engine by dispatching requests to the `/webhook` endpoint. 
   Because you used `bash setup.sh`, the Helix Engine already automatically spawned a secure PyNgrok HTTPS tunnel for you! Look at your terminal output to find your live Ngrok URL.
   
3. **Configure the Lab Frontend:**
   Take the resulting Ngrok URL (e.g., `https://abc-123.ngrok-free.app`) and place it in the Lab frontend's `.env` or configuration file. This allows your local React/Vue dashboard on port `3000` to seamlessly POST webhook events to the remote Helix Engine.

---

## 🔀 Connecting to HelixFlow Gateway (New)

For enterprise-grade API multiplexing, failover, and ultra-low-latency traffic routing, the Helix Engine is designed to pair perfectly with the **HelixFlow Gateway**. 

Instead of connecting the Helix Engine directly to OpenAI or DeepSeek, you can route all internal LLM traffic from the Engine through the Gateway. The Gateway will automatically manage rate limits, PII scrubbing, and cost optimization.

1. **Deploy HelixFlow:** [https://github.com/vishalvermauts/HelixFlow](https://github.com/vishalvermauts/HelixFlow)
2. **Configure Helix Engine:** Update your `.env` to point the base URL to your HelixFlow instance (e.g., `http://localhost:8000/v1`).

---

*This codebase was meticulously crafted and continuously refined using advanced agentic pair-programming.*
