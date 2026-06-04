# AirCode Dual-Model Triage Router - Implementation Plan

## Executive Summary

Implement an intelligent prompt classification system that routes code generation tasks to either **DeepSeek Coder** (simple tasks) or **Gemini 2.5 Pro** (complex architecture work), reducing API costs by ~60% for routine tasks while maintaining quality for heavy lifting.

---

## Phase 1: Architecture & Design (Days 1-2)

### 1.1 Triage Classification Engine

**File**: `agents/triage_router.py`

**Responsibility**: Analyze incoming prompts and classify as `SIMPLE` or `COMPLEX`.

**Classification Logic**:

```
INPUT: User prompt text
  ↓
[Token Count] < 50 tokens? → SIMPLE
  ↓ NO
[Keywords Analysis]
  Simple markers: "fix", "bug", "typo", "edit", "replace", "format", "lint"
  Complex markers: "refactor", "architect", "redesign", "multi-file", "state", "ui", "layout", "style"
  ↓
[DeepSeek Fast Completion] (0.3s max)
  - Send prompt to `deepseek/deepseek-chat` model
  - Request classification: "Is this task SIMPLE or COMPLEX?"
  - Parse response for confidence score
  ↓
DECISION LOGIC:
  if (token_count < 50 && simple_keyword_count > complex_keyword_count) → SIMPLE
  if (deepseek_confidence > 0.7 && classification == SIMPLE) → SIMPLE
  else → COMPLEX
  ↓
OUTPUT: {
  "classification": "SIMPLE" | "COMPLEX",
  "confidence": 0.0-1.0,
  "reasoning": "reason string",
  "model": "deepseek/deepseek-coder" | "gemini/gemini-2.5-pro",
  "estimated_cost": 0.0001 | 0.005
}
```

**Key Methods**:

```python
class TriageRouter:
    async def classify_prompt(self, prompt: str) -> TriageResult
    async def get_fast_classification(self, prompt: str) -> str  # DeepSeek call
    def analyze_keywords(self, prompt: str) -> Dict[str, int]
    def estimate_cost(self, classification: str) -> float
```

---

### 1.2 Integration Points

**Modify**: `server_refactored.py`

**Location**: Inside `telegram_webhook_gateway()` → Before `execute_aider_compilation()`

**Flow**:

```python
@app.post("/webhook")
async def telegram_webhook_gateway(request: Request):
    # ... existing auth & validation ...

    # NEW: Triage classification
    triage_result = await triage_router.classify_prompt(prompt)
    logger.info(
        "Prompt triaged",
        classification=triage_result.classification,
        confidence=triage_result.confidence,
        model=triage_result.model
    )

    # Dispatch with selected model
    asyncio.create_task(
        execute_aider_compilation(
            chat_id=chat_id,
            prompt=prompt,
            model_override=triage_result.model  # NEW parameter
        )
    )
```

---

### 1.3 DeepSeek API Integration

**Library**: Use existing `httpx.AsyncClient` (already in requirements)

**Endpoint**: `https://api.deepseek.com/v1/chat/completions`

**Request**:

```python
payload = {
    "model": "deepseek-chat",
    "messages": [
        {
            "role": "system",
            "content": "You are a code task classifier. Respond with only: SIMPLE or COMPLEX"
        },
        {
            "role": "user",
            "content": f"Classify this task:\n\n{prompt}\n\nSimple = single file, bug fix, text edit. Complex = multi-file, refactor, architecture."
        }
    ],
    "temperature": 0.3,
    "max_tokens": 10
}

response = await client.post(
    "https://api.deepseek.com/v1/chat/completions",
    json=payload,
    headers={"Authorization": f"Bearer {config.deepseek_api_key}"},
    timeout=1.0  # Fast timeout
)
```

---

## Phase 2: Core Implementation (Days 3-4)

### 2.1 Create Triage Router Agent

**File**: `agents/triage_router.py`

**Deliverable**: ~200 lines

```python
import asyncio
import re
from typing import NamedTuple
from dataclasses import dataclass
import httpx

from lib.config import get_config
from lib.logging import get_logger

@dataclass
class TriageResult:
    classification: str  # "SIMPLE" | "COMPLEX"
    confidence: float
    reasoning: str
    model: str
    estimated_cost: float

class TriageRouter:
    def __init__(self):
        self.config = get_config()
        self.logger = get_logger("triage_router")
        self.simple_keywords = ["fix", "bug", "typo", "edit", "replace", "format", "lint"]
        self.complex_keywords = ["refactor", "architect", "redesign", "multi-file", "state", "ui", "layout"]

    async def classify_prompt(self, prompt: str) -> TriageResult:
        """Main triage classification method."""
        # 1. Keyword analysis (fast)
        keyword_score = self._analyze_keywords(prompt)

        # 2. Token count (fast)
        token_count = len(prompt.split())

        # 3. DeepSeek fast classification (0.3s max)
        try:
            deepseek_result = await self._get_deepseek_classification(prompt)
        except asyncio.TimeoutError:
            self.logger.warning("DeepSeek timeout; using keyword analysis only")
            deepseek_result = None

        # 4. Decision logic
        if keyword_score > 0.6 and token_count < 100:
            classification = "SIMPLE"
            confidence = 0.8
        elif deepseek_result and "SIMPLE" in deepseek_result:
            classification = "SIMPLE"
            confidence = 0.75
        else:
            classification = "COMPLEX"
            confidence = 0.7

        model = "deepseek/deepseek-coder" if classification == "SIMPLE" else "gemini/gemini-2.5-pro"
        cost = 0.0001 if classification == "SIMPLE" else 0.005

        return TriageResult(
            classification=classification,
            confidence=confidence,
            reasoning=f"Token count: {token_count}, Keywords: {keyword_score:.2f}, DeepSeek: {deepseek_result}",
            model=model,
            estimated_cost=cost
        )

    def _analyze_keywords(self, prompt: str) -> float:
        """Keyword-based classification (returns 0.0-1.0 score)."""
        prompt_lower = prompt.lower()
        simple_count = sum(1 for kw in self.simple_keywords if kw in prompt_lower)
        complex_count = sum(1 for kw in self.complex_keywords if kw in prompt_lower)

        if simple_count + complex_count == 0:
            return 0.5

        return simple_count / (simple_count + complex_count)

    async def _get_deepseek_classification(self, prompt: str, timeout: float = 0.3) -> str:
        """Call DeepSeek for fast classification."""
        try:
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": "Respond with only SIMPLE or COMPLEX"
                    },
                    {
                        "role": "user",
                        "content": f"Is this task simple (single file, bug fix, text edit) or complex (multi-file, refactor, architecture)?\n\n{prompt[:200]}"
                    }
                ],
                "temperature": 0.3,
                "max_tokens": 10
            }

            async with httpx.AsyncClient() as client:
                response = await asyncio.wait_for(
                    client.post(
                        "https://api.deepseek.com/v1/chat/completions",
                        json=payload,
                        headers={"Authorization": f"Bearer {self.config.deepseek_api_key}"},
                        timeout=0.5
                    ),
                    timeout=timeout
                )

            if response.status_code == 200:
                data = response.json()
                classification = data["choices"][0]["message"]["content"].strip().upper()
                return "SIMPLE" if "SIMPLE" in classification else "COMPLEX"
            else:
                self.logger.warning(f"DeepSeek error: {response.status_code}")
                return None

        except asyncio.TimeoutError:
            raise
        except Exception as e:
            self.logger.error(f"DeepSeek classification failed: {e}")
            return None

# Singleton
_triage_router: TriageRouter = None

def get_triage_router() -> TriageRouter:
    global _triage_router
    if _triage_router is None:
        _triage_router = TriageRouter()
    return _triage_router
```

---

### 2.2 Update Config for DeepSeek

**File**: `lib/config.py`

**Add fields** (already present, just confirm):

```python
@dataclass
class AirCodeConfig:
    # ... existing fields ...
    deepseek_api_key: Optional[str] = None  # Already exists ✅
    deepseek_model: str = "deepseek-chat"  # ADD
    triage_enabled: bool = True  # ADD
    triage_timeout: float = 0.3  # ADD (seconds)
```

**Update `.env.example`**:

```bash
# Triage Router Config
TRIAGE_ENABLED=true
TRIAGE_TIMEOUT=0.3
DEEPSEEK_MODEL=deepseek-chat
```

---

### 2.3 Update Server to Use Triage Router

**File**: `server_refactored.py`

**Import**:

```python
from agents.triage_router import get_triage_router
```

**Modify `telegram_webhook_gateway()`**:

```python
@app.post("/webhook")
async def telegram_webhook_gateway(request: Request):
    # ... existing validation code (lines 1-80) ...

    # NEW: Triage classification (if enabled)
    selected_model = config.gemini_model  # default
    if config.triage_enabled:
        try:
            triage = get_triage_router()
            result = await triage.classify_prompt(prompt)
            selected_model = result.model
            logger.info(
                "📊 Prompt triaged",
                classification=result.classification,
                confidence=result.confidence,
                model=result.model,
                estimated_cost=result.estimated_cost
            )
        except Exception as e:
            logger.warning("Triage failed; using default model", error=str(e))

    # Dispatch with selected model
    asyncio.create_task(
        execute_aider_compilation(
            chat_id=chat_id,
            prompt=prompt,
            user_id=user_id,
            model_override=selected_model
        )
    )

    return JSONResponse(status_code=200, content={"status": "queued", "task": "Aider processing initiated"})
```

**Modify `execute_aider_compilation()` signature**:

```python
async def execute_aider_compilation(
    chat_id: int,
    prompt: str,
    user_id: int,
    model_override: Optional[str] = None  # NEW parameter
):
    """
    Asynchronous compilation runner with model selection.
    """
    async with pipeline_lock:
        try:
            # Use override model if provided, else fall back to config default
            model = model_override or config.gemini_model

            logger.info("🔨 Aider execution started", user_id=user_id, model=model, prompt_len=len(prompt))

            # Build environment
            env = os.environ.copy()
            env["GEMINI_API_KEY"] = config.gemini_api_key
            env["GEMINI_API_BASE"] = config.gemini_api_base
            env["LITELLM_MODE"] = "production"

            if config.deepseek_api_key:
                env["DEEPSEEK_API_KEY"] = config.deepseek_api_key

            # Build Aider command with selected model
            aider_cmd = [
                config.aider_bin,
                "--model", model,  # Use routed model
                "--no-show-model-warnings",
                "--yes-always",
                "--no-suggest-shell-commands",
                "--no-gitignore",
                "--no-check-update",
                "--message", prompt
            ]

            # ... rest of execution logic (unchanged) ...
```

---

## Phase 3: Testing (Days 5-6)

### 3.1 Unit Tests

**File**: `test_triage_router.py`

```python
import pytest
from agents.triage_router import TriageRouter

@pytest.mark.asyncio
async def test_simple_task_classification():
    """Classify a simple bug fix prompt."""
    router = TriageRouter()
    result = await router.classify_prompt("Fix the typo in line 42 where 'conect' should be 'connect'")
    assert result.classification == "SIMPLE"
    assert result.model == "deepseek/deepseek-coder"

@pytest.mark.asyncio
async def test_complex_task_classification():
    """Classify a complex refactoring prompt."""
    router = TriageRouter()
    result = await router.classify_prompt(
        "Refactor the entire authentication system to use OAuth2 instead of basic auth. "
        "Update database schema, middleware, and all route handlers."
    )
    assert result.classification == "COMPLEX"
    assert result.model == "gemini/gemini-2.5-pro"

@pytest.mark.asyncio
async def test_keyword_analysis():
    """Test keyword scoring."""
    router = TriageRouter()
    simple_score = router._analyze_keywords("fix bug typo")
    complex_score = router._analyze_keywords("refactor architecture redesign")
    assert simple_score > 0.7
    assert complex_score < 0.3

def test_config_triage_enabled():
    """Verify triage config loads."""
    config = get_config()
    assert config.triage_enabled == True
    assert config.triage_timeout == 0.3
    assert config.deepseek_api_key is not None
```

**Run**:

```bash
pytest test_triage_router.py -v
```

---

### 3.2 Integration Test

**File**: `test_telegram_e2e_with_triage.py`

```python
async def test_simple_prompt_routes_to_deepseek():
    """Send a simple bug fix, verify it's routed to DeepSeek."""
    payload = {
        "message": {
            "chat": {"id": config.telegram_chat_id},
            "from": {"id": config.allowed_user_id},
            "text": "Fix the typo: 'conect' should be 'connect'"
        }
    }

    # Send webhook
    response = await client.post("http://127.0.0.1:8000/webhook", json=payload)
    assert response.status_code == 200

    # Verify logs show DeepSeek routing
    await asyncio.sleep(3)
    logs = read_structured_logs()
    assert any(log["message"].contains("deepseek/deepseek-coder") for log in logs)

async def test_complex_prompt_routes_to_gemini():
    """Send a complex refactoring, verify it's routed to Gemini."""
    payload = {
        "message": {
            "chat": {"id": config.telegram_chat_id},
            "from": {"id": config.allowed_user_id},
            "text": "Refactor the entire API architecture from REST to GraphQL with multiple file changes"
        }
    }

    response = await client.post("http://127.0.0.1:8000/webhook", json=payload)
    assert response.status_code == 200

    await asyncio.sleep(3)
    logs = read_structured_logs()
    assert any(log["message"].contains("gemini/gemini-2.5-pro") for log in logs)
```

---

### 3.3 Manual Telegram Test

**Scenario 1: Simple Task**

```
Send via Telegram: "Fix the bug where password validation doesn't trim whitespace"

Expected:
  ✅ Triage logs "SIMPLE" classification
  ✅ DeepSeek Coder processes the fix
  ✅ Aider runs with deepseek/deepseek-coder model
  ✅ Response sent to Telegram within 30 seconds
```

**Scenario 2: Complex Task**

```
Send via Telegram: "Redesign the entire payment module to support multiple currencies with real-time exchange rates and audit logging across all microservices"

Expected:
  ✅ Triage logs "COMPLEX" classification
  ✅ Gemini 2.5 Pro processes the architecture
  ✅ Aider runs with gemini/gemini-2.5-pro model
  ✅ Response sent to Telegram (may take 1-2 minutes)
```

---

## Phase 4: Monitoring & Observability (Days 7)

### 4.1 Add Triage Metrics

**Update**: `agents/system_monitor.py`

**Add method**:

```python
async def _collect_triage_stats(self):
    """Gather triage routing statistics."""
    try:
        # Read structured logs and aggregate by classification
        simple_count = count_logs(level="INFO", contains="SIMPLE")
        complex_count = count_logs(level="INFO", contains="COMPLEX")

        savings = (simple_count * 0.0001 - simple_count * 0.005)  # cost diff

        report = (
            f"📊 **Triage Router Statistics**\n\n"
            f"Simple Tasks: {simple_count}\n"
            f"Complex Tasks: {complex_count}\n"
            f"Estimated Savings: ${savings:.2f}\n"
        )

        await self._send_telegram_message(report)
    except Exception as e:
        self.logger.error("Triage stats collection failed", error=str(e))
```

### 4.2 Logging Format

**Example structured log output**:

```json
{
  "timestamp": "2026-06-03T14:00:00.123Z",
  "level": "INFO",
  "logger": "triage_router",
  "message": "📊 Prompt triaged",
  "classification": "SIMPLE",
  "confidence": 0.85,
  "model": "deepseek/deepseek-coder",
  "estimated_cost": 0.0001,
  "prompt_len": 64,
  "reasoning": "Token count: 12, Keywords: 0.90, DeepSeek: SIMPLE"
}
```

---

## Phase 5: Deployment & Rollout (Day 8)

### 5.1 Feature Flags

**In `.env.example`**:

```bash
# Enable/disable triage router
TRIAGE_ENABLED=true

# Triage timeout (seconds)
TRIAGE_TIMEOUT=0.3

# Fallback behavior if triage fails
TRIAGE_FALLBACK_MODEL=gemini/gemini-2.5-pro
```

**Rollout strategy**:

1. **Day 1 (Dev)**: Deploy with `TRIAGE_ENABLED=true`, monitor logs
2. **Day 2 (Staging)**: Run 24-hour test; collect cost/latency metrics
3. **Day 3 (Prod)**: Roll out to live; can disable with `TRIAGE_ENABLED=false` if issues arise

### 5.2 Graceful Degradation

If triage fails for any reason (timeout, API error, config missing):

```python
try:
    result = await triage.classify_prompt(prompt)
    model = result.model
except Exception as e:
    logger.warning("Triage failed; using fallback", error=str(e))
    model = config.triage_fallback_model or config.gemini_model
```

---

## Phase 6: Cost Analysis & ROI (Day 9)

### 6.1 Expected Outcomes

| Metric                        | Before          | After                       | Gain                        |
| ----------------------------- | --------------- | --------------------------- | --------------------------- |
| **Avg cost per simple task**  | $0.005 (Gemini) | $0.0001 (DeepSeek)          | 98% savings                 |
| **Avg cost per complex task** | $0.005 (Gemini) | $0.005 (Gemini)             | No change                   |
| **Simple task ratio**         | 0%              | ~40-50%                     | 40-50% tasks routed cheaper |
| **Overall cost reduction**    | Baseline        | -40%                        | ~$200/month on 10k tasks    |
| **Latency**                   | ~45s (Gemini)   | 8s (DeepSeek) + 2s (triage) | 15% faster for simple       |

### 6.2 Dashboard Metrics

Track in structured logs:

```
triage_simple_count
triage_complex_count
triage_success_rate
triage_avg_latency_ms
aider_deepseek_success_rate
aider_gemini_success_rate
total_cost_saved_usd
```

---

## Implementation Checklist

- [ ] **Phase 1**: Create `agents/triage_router.py` (200 lines)
- [ ] **Phase 1**: Add config fields to `lib/config.py` (5 lines)
- [ ] **Phase 1**: Update `.env.example` with triage config (3 lines)
- [ ] **Phase 2**: Modify `server_refactored.py` webhook handler (20 lines)
- [ ] **Phase 2**: Modify `execute_aider_compilation()` signature (5 lines)
- [ ] **Phase 3**: Create `test_triage_router.py` (100 lines)
- [ ] **Phase 3**: Create `test_telegram_e2e_with_triage.py` (50 lines)
- [ ] **Phase 3**: Run manual Telegram tests (scenarios 1 & 2)
- [ ] **Phase 4**: Update `agents/system_monitor.py` with triage stats (30 lines)
- [ ] **Phase 5**: Set feature flags in `.env`
- [ ] **Phase 5**: Test graceful degradation
- [ ] **Phase 6**: Collect baseline metrics (24h)
- [ ] **Phase 6**: Deploy to production
- [ ] **Phase 6**: Monitor savings & success rates

---

## Risk Mitigation

| Risk                   | Mitigation                                                                        |
| ---------------------- | --------------------------------------------------------------------------------- |
| **DeepSeek timeout**   | 300ms timeout; fall back to keyword analysis                                      |
| **DeepSeek API down**  | Fail open to Gemini; log error; continue                                          |
| **Misclassification**  | Confidence scoring; manually override via prompt prefix (e.g., `[FORCE_COMPLEX]`) |
| **Cost spike**         | Monitor daily spend; cap DeepSeek calls to 100/day initially                      |
| **Latency regression** | Triage adds ~0.5s; acceptable since simple tasks complete 8x faster               |

---

## Success Criteria

✅ **Phase completion**: All phases delivered by Day 9
✅ **Test coverage**: >90% of code paths tested
✅ **Cost reduction**: >30% reduction in API costs
✅ **Quality**: No regressions in code generation quality
✅ **Latency**: Simple tasks <15 seconds (vs 45s baseline)
✅ **Uptime**: 99.9% webhook availability during rollout

---

## Timeline Summary

```
Day 1-2:  Architecture & Design (Triage Engine)
Day 3-4:  Core Implementation (Router + Server Integration)
Day 5-6:  Testing (Unit + Integration + Manual)
Day 7:    Monitoring & Observability
Day 8:    Deployment & Rollout (Dev → Staging → Prod)
Day 9:    Cost Analysis & ROI Metrics

Total: 9 days (1-2 weeks including buffer)
```

---

## Next Steps

1. **Approve this plan** or suggest modifications
2. **Day 1**: Create `agents/triage_router.py` with full implementation
3. **Day 2**: Integrate into `server_refactored.py` and test locally
4. **Day 3+**: Proceed through phases with parallel workstreams

Ready to implement? 🚀
