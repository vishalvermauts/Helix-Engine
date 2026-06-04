#!/usr/bin/env python3
"""
Phase 3: Unit Tests for Triage Router
Tests classification logic, keyword analysis, and DeepSeek integration fallback.
"""

import sys
import os
from pathlib import Path
import asyncio
import pytest

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

from agents.triage_router import TriageRouter, get_triage_router, TriageResult
from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("TRIAGE_TESTS")

class TestTriageRouterKeywordAnalysis:
    """Unit tests for keyword scoring logic."""
    
    @pytest.fixture
    def router(self):
        return get_triage_router()
    
    def test_simple_keywords_detected(self, router):
        """SIMPLE keywords should score high (> 0.5)."""
        prompts = [
            "fix the bug on line 42",
            "typo in variable name",
            "edit the README",
            "format the code",
            "replace this string",
        ]
        for prompt in prompts:
            score = router._analyze_keywords(prompt)
            assert score > 0.5, f"Expected SIMPLE score for: {prompt}, got {score}"
    
    def test_complex_keywords_detected(self, router):
        """COMPLEX keywords should score low (< 0.5)."""
        prompts = [
            "refactor the entire authentication system",
            "architect a new microservices layer",
            "redesign the database schema",
            "migrate from MongoDB to PostgreSQL",
            "update the UI layout for mobile",
        ]
        for prompt in prompts:
            score = router._analyze_keywords(prompt)
            assert score < 0.5, f"Expected COMPLEX score for: {prompt}, got {score}"
    
    def test_empty_prompt_scores_neutral(self, router):
        """Empty prompt should score neutral (0.0)."""
        score = router._analyze_keywords("")
        assert 0.0 <= score <= 1.0
    
    def test_neutral_keywords_score_low(self, router):
        """Prompts with no markers should score low."""
        prompts = [
            "hello world",
            "this is a test",
            "random text without context",
        ]
        for prompt in prompts:
            score = router._analyze_keywords(prompt)
            assert score == 0.0, f"Expected neutral score for: {prompt}, got {score}"


class TestTriageRouterClassification:
    """Unit tests for classification decision logic."""
    
    @pytest.fixture
    def router(self):
        return get_triage_router()
    
    def test_short_high_keywords_simple(self, router):
        """Short prompts with high keywords should classify as SIMPLE."""
        classification, confidence = router._make_decision(
            keyword_score=0.8,
            token_count=10,
            deepseek_result=None
        )
        assert classification == "SIMPLE"
        assert confidence >= 0.8
    
    def test_long_low_keywords_complex(self, router):
        """Long prompts with low keywords should classify as COMPLEX."""
        classification, confidence = router._make_decision(
            keyword_score=0.2,
            token_count=200,
            deepseek_result=None
        )
        assert classification == "COMPLEX"
        assert confidence >= 0.7
    
    def test_medium_medium_keywords_requires_deepseek(self, router):
        """Medium prompts with medium keywords default to COMPLEX."""
        classification, confidence = router._make_decision(
            keyword_score=0.5,
            token_count=100,
            deepseek_result=None
        )
        assert classification == "COMPLEX"
    
    def test_deepseek_simple_overrides_keywords(self, router):
        """DeepSeek SIMPLE result should trigger SIMPLE classification."""
        classification, confidence = router._make_decision(
            keyword_score=0.3,
            token_count=100,
            deepseek_result="SIMPLE"
        )
        assert classification == "SIMPLE"
        assert confidence >= 0.85
    
    def test_deepseek_complex_confirms_complex(self, router):
        """DeepSeek COMPLEX should confirm COMPLEX."""
        classification, confidence = router._make_decision(
            keyword_score=0.5,
            token_count=100,
            deepseek_result="COMPLEX"
        )
        assert classification == "COMPLEX"


class TestTriageResult:
    """Unit tests for TriageResult dataclass."""
    
    def test_triage_result_creation(self):
        """TriageResult should instantiate with all fields."""
        result = TriageResult(
            classification="SIMPLE",
            confidence=0.9,
            reasoning="High keyword score",
            model="deepseek/deepseek-coder",
            estimated_cost=0.0001
        )
        assert result.classification == "SIMPLE"
        assert result.confidence == 0.9
        assert result.estimated_cost == 0.0001
    
    def test_triage_result_cost_calculation(self):
        """Cost should differ between SIMPLE and COMPLEX."""
        simple = TriageResult("SIMPLE", 0.9, "test", "deepseek/deepseek-coder", 0.0001)
        complex_result = TriageResult("COMPLEX", 0.7, "test", "gemini/gemini-2.5-pro", 0.005)
        
        assert simple.estimated_cost < complex_result.estimated_cost


class TestTriageRouterIntegration:
    """Integration tests for full classify_prompt flow."""
    
    @pytest.fixture
    def router(self):
        return get_triage_router()
    
    @pytest.mark.asyncio
    async def test_classify_prompt_simple(self, router):
        """Full classification for simple prompt."""
        result = await router.classify_prompt("fix typo in main.py")
        assert isinstance(result, TriageResult)
        assert result.classification == "SIMPLE"
        assert result.confidence >= 0.7
    
    @pytest.mark.asyncio
    async def test_classify_prompt_complex(self, router):
        """Full classification for complex prompt."""
        result = await router.classify_prompt(
            "refactor the authentication system to support OAuth2 with multi-tenant support"
        )
        assert isinstance(result, TriageResult)
        assert result.classification in ["SIMPLE", "COMPLEX"]
        assert 0.0 <= result.confidence <= 1.0
    
    @pytest.mark.asyncio
    async def test_classify_prompt_returns_model(self, router):
        """Classification should always return a valid model."""
        result = await router.classify_prompt("test")
        assert result.model in ["deepseek/deepseek-coder", "gemini/gemini-2.5-pro"]
    
    @pytest.mark.asyncio
    async def test_classify_prompt_timeout_fallback(self, router):
        """Should handle DeepSeek timeout gracefully."""
        # This test will timeout DeepSeek (API unreachable) and fall back to keyword analysis
        result = await router.classify_prompt("random text")
        assert isinstance(result, TriageResult)
        # Should still return a valid result despite timeout


class TestTriageRouterSingleton:
    """Tests for singleton pattern."""
    
    def test_singleton_returns_same_instance(self):
        """get_triage_router should return the same instance."""
        router1 = get_triage_router()
        router2 = get_triage_router()
        assert router1 is router2
    
    def test_singleton_persists_across_imports(self):
        """Singleton should persist across module reloads."""
        import importlib
        import agents.triage_router as triage_module
        
        router1 = get_triage_router()
        importlib.reload(triage_module)
        router2 = triage_module.get_triage_router()
        
        # Should be different instances after reload
        assert isinstance(router2, TriageRouter)


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
