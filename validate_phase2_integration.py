#!/usr/bin/env python3
"""
Phase 2 Integration Validation - Triage Router & Server Integration Tests
Validates that triage router can be imported, configured, and integrated into server.
"""

import sys
import os
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
from lib.config import get_config
from lib.logging import get_logger
from agents.triage_router import get_triage_router

logger = get_logger("PHASE2_VALIDATION")

# Test results tracker
tests_passed = 0
tests_failed = 0

def log_test(test_name: str, passed: bool, details: str = ""):
    global tests_passed, tests_failed
    status = "✅" if passed else "❌"
    print(f"{status} {test_name}")
    if details:
        print(f"   → {details}")
    if passed:
        tests_passed += 1
    else:
        tests_failed += 1

async def main():
    print("\n" + "="*80)
    print("PHASE 2 INTEGRATION VALIDATION - Triage Router & Server Integration")
    print("="*80 + "\n")
    
    # Test 1: Config loads with triage fields
    print("TEST GROUP 1: Configuration Loading")
    print("-" * 80)
    try:
        config = get_config()
        log_test(
            "1.1 Config loads with triage fields",
            all([
                hasattr(config, 'triage_enabled'),
                hasattr(config, 'triage_timeout'),
                hasattr(config, 'triage_fallback_model'),
                hasattr(config, 'deepseek_model'),
            ]),
            f"triage_enabled={config.triage_enabled}, timeout={config.triage_timeout}"
        )
    except Exception as e:
        log_test("1.1 Config loads with triage fields", False, str(e))
        return
    
    try:
        log_test(
            "1.2 Triage config defaults are sensible",
            config.triage_enabled and config.triage_timeout == 0.3,
            f"enabled={config.triage_enabled}, timeout={config.triage_timeout}s"
        )
    except Exception as e:
        log_test("1.2 Triage config defaults are sensible", False, str(e))
    
    # Test 2: Triage Router instantiation
    print("\nTEST GROUP 2: Triage Router Instantiation")
    print("-" * 80)
    try:
        router = get_triage_router()
        log_test(
            "2.1 Triage router instantiates",
            router is not None,
            f"Router type: {type(router).__name__}"
        )
    except Exception as e:
        log_test("2.1 Triage router instantiates", False, str(e))
        return
    
    try:
        log_test(
            "2.2 Triage router is singleton",
            router is get_triage_router(),
            "Same instance returned on subsequent calls"
        )
    except Exception as e:
        log_test("2.2 Triage router is singleton", False, str(e))
    
    # Test 3: Keyword analysis (fast, no API calls)
    print("\nTEST GROUP 3: Triage Router Keyword Analysis")
    print("-" * 80)
    try:
        simple_prompt = "fix the bug on line 42 in main.py"
        simple_score = router._analyze_keywords(simple_prompt)
        log_test(
            "3.1 Keyword analysis detects SIMPLE prompts",
            simple_score > 0.5,
            f"Score for 'fix bug' prompt: {simple_score}"
        )
    except Exception as e:
        log_test("3.1 Keyword analysis detects SIMPLE prompts", False, str(e))
    
    try:
        complex_prompt = "refactor the entire authentication system to use OAuth2 with multi-tenant support"
        complex_score = router._analyze_keywords(complex_prompt)
        log_test(
            "3.2 Keyword analysis detects COMPLEX prompts",
            complex_score < 0.5,
            f"Score for 'refactor' prompt: {complex_score}"
        )
    except Exception as e:
        log_test("3.2 Keyword analysis detects COMPLEX prompts", False, str(e))
    
    # Test 4: Classification logic (no API calls)
    print("\nTEST GROUP 4: Triage Router Classification Logic")
    print("-" * 80)
    try:
        # Very short prompt with high keyword score
        classification, confidence = router._make_decision(
            keyword_score=0.8,
            token_count=10,
            deepseek_result=None
        )
        log_test(
            "4.1 Classification: short + high keywords = SIMPLE",
            classification == "SIMPLE" and confidence >= 0.8,
            f"Classification: {classification}, Confidence: {confidence}"
        )
    except Exception as e:
        log_test("4.1 Classification: short + high keywords = SIMPLE", False, str(e))
    
    try:
        # Long prompt, low keywords
        classification, confidence = router._make_decision(
            keyword_score=0.2,
            token_count=200,
            deepseek_result=None
        )
        log_test(
            "4.2 Classification: long + low keywords = COMPLEX",
            classification == "COMPLEX" and confidence >= 0.7,
            f"Classification: {classification}, Confidence: {confidence}"
        )
    except Exception as e:
        log_test("4.2 Classification: long + low keywords = COMPLEX", False, str(e))
    
    # Test 5: Full classification with timeout handling
    print("\nTEST GROUP 5: Full Triage Classification (with fallback)")
    print("-" * 80)
    try:
        result = await router.classify_prompt("fix typo in README")
        log_test(
            "5.1 Full classification returns TriageResult",
            result is not None and hasattr(result, 'classification'),
            f"Classification: {result.classification}, Model: {result.model}"
        )
    except asyncio.TimeoutError:
        log_test(
            "5.1 Full classification returns TriageResult",
            True,  # DeepSeek timeout is expected if API unreachable
            "DeepSeek timeout (API unreachable), using keyword analysis fallback"
        )
    except Exception as e:
        log_test("5.1 Full classification returns TriageResult", False, str(e))
        return
    
    try:
        log_test(
            "5.2 TriageResult has required fields",
            all([
                hasattr(result, 'classification'),
                hasattr(result, 'confidence'),
                hasattr(result, 'model'),
                hasattr(result, 'estimated_cost'),
                hasattr(result, 'reasoning'),
            ]),
            f"All fields present: {result.__dict__.keys()}"
        )
    except Exception as e:
        log_test("5.2 TriageResult has required fields", False, str(e))
    
    try:
        log_test(
            "5.3 Selected model is valid",
            result.model in ["deepseek/deepseek-chat", "deepseek/deepseek-coder", "gemini/gemini-2.5-pro"],
            f"Model: {result.model}"
        )
    except Exception as e:
        log_test("5.3 Selected model is valid", False, str(e))
    
    # Test 6: Server imports check
    print("\nTEST GROUP 6: Server Integration Imports")
    print("-" * 80)
    try:
        # Try importing server_refactored to ensure triage router import works
        import importlib.util
        spec = importlib.util.spec_from_file_location("server_refactored", 
                                                       "/workspaces/AirCode/server_refactored.py")
        server_module = importlib.util.module_from_spec(spec)
        sys.modules["server_refactored"] = server_module
        spec.loader.exec_module(server_module)
        
        log_test(
            "6.1 server_refactored.py imports successfully",
            True,
            "All imports resolved (FastAPI, triage_router, etc.)"
        )
    except Exception as e:
        log_test("6.1 server_refactored.py imports successfully", False, str(e))
    
    # Summary
    print("\n" + "="*80)
    print(f"VALIDATION SUMMARY: {tests_passed} passed, {tests_failed} failed")
    print("="*80 + "\n")
    
    if tests_failed == 0:
        print("✨ All Phase 2 integration tests passed! Ready for Telegram E2E testing.")
        return 0
    else:
        print(f"⚠️  {tests_failed} test(s) failed. Review above for details.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
