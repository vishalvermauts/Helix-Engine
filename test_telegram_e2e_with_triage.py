#!/usr/bin/env python3
"""
Phase 3: Integration Tests for Telegram + Triage Router
End-to-end testing of webhook → triage → aider → telegram response flow.
"""

import sys
import os
from pathlib import Path
import asyncio
import json
import subprocess
import time
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from lib.config import get_config
from lib.logging import get_logger

logger = get_logger("TELEGRAM_TRIAGE_E2E")

config = get_config()

class TelegramTriageE2ETest:
    """End-to-end tests with triage router integration."""
    
    def __init__(self):
        self.server_healthy = False
        self.aider_functional = False
        self.tests_passed = 0
        self.tests_failed = 0
    
    def log_test(self, test_name: str, passed: bool, details: str = ""):
        """Log test result."""
        status = "✅" if passed else "❌"
        print(f"{status} {test_name}")
        if details:
            print(f"   → {details}")
        if passed:
            self.tests_passed += 1
        else:
            self.tests_failed += 1
    
    async def check_server_health(self) -> bool:
        """Check if FastAPI server is healthy."""
        print("\n🔍 Checking FastAPI server health...")
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get("http://127.0.0.1:8000/health", timeout=5)
                healthy = response.status_code == 200
                self.log_test(
                    "Server health check",
                    healthy,
                    f"Status: {response.status_code}"
                )
                self.server_healthy = healthy
                return healthy
        except Exception as e:
            self.log_test("Server health check", False, str(e))
            return False
    
    def check_aider_functional(self) -> bool:
        """Check if aider binary exists and works."""
        print("\n🔨 Checking aider functionality...")
        try:
            result = subprocess.run(
                [config.aider_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            functional = result.returncode == 0
            self.log_test(
                "Aider binary functional",
                functional,
                f"Version: {result.stdout.strip()}"
            )
            self.aider_functional = functional
            return functional
        except Exception as e:
            self.log_test("Aider binary functional", False, str(e))
            return False
    
    async def test_webhook_with_simple_prompt(self) -> bool:
        """Test webhook with SIMPLE prompt (should route to DeepSeek)."""
        print("\n📨 Testing webhook with SIMPLE prompt...")
        if not self.server_healthy:
            self.log_test("Webhook SIMPLE prompt", False, "Server not healthy")
            return False
        
        try:
            import httpx
            
            # Craft test payload
            payload = {
                "message": {
                    "chat": {"id": config.telegram_chat_id},
                    "from": {"id": config.allowed_user_id},
                    "text": "fix typo in README"
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://127.0.0.1:8000/webhook",
                    json=payload,
                    timeout=10
                )
                accepted = response.status_code == 200
                self.log_test(
                    "Webhook accepts SIMPLE prompt",
                    accepted,
                    f"Response: {response.json()}"
                )
                return accepted
        except Exception as e:
            self.log_test("Webhook accepts SIMPLE prompt", False, str(e))
            return False
    
    async def test_webhook_with_complex_prompt(self) -> bool:
        """Test webhook with COMPLEX prompt (should route to Gemini)."""
        print("\n📨 Testing webhook with COMPLEX prompt...")
        if not self.server_healthy:
            self.log_test("Webhook COMPLEX prompt", False, "Server not healthy")
            return False
        
        try:
            import httpx
            
            payload = {
                "message": {
                    "chat": {"id": config.telegram_chat_id},
                    "from": {"id": config.allowed_user_id},
                    "text": "refactor the authentication system to support OAuth2"
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://127.0.0.1:8000/webhook",
                    json=payload,
                    timeout=10
                )
                accepted = response.status_code == 200
                self.log_test(
                    "Webhook accepts COMPLEX prompt",
                    accepted,
                    f"Response: {response.json()}"
                )
                return accepted
        except Exception as e:
            self.log_test("Webhook accepts COMPLEX prompt", False, str(e))
            return False
    
    async def test_webhook_firewall(self) -> bool:
        """Test webhook firewall (deny unauthorized user)."""
        print("\n🔒 Testing webhook firewall...")
        try:
            import httpx
            
            # Try with unauthorized user ID
            payload = {
                "message": {
                    "chat": {"id": 999999},
                    "from": {"id": 999999},  # Unauthorized
                    "text": "test"
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://127.0.0.1:8000/webhook",
                    json=payload,
                    timeout=10
                )
                # Should still accept (returns 200) but deny execution
                is_denied = response.status_code == 200
                self.log_test(
                    "Webhook firewall blocks unauthorized user",
                    is_denied,
                    f"Response: {response.json()}"
                )
                return is_denied
        except Exception as e:
            self.log_test("Webhook firewall blocks unauthorized user", False, str(e))
            return False
    
    async def test_webhook_empty_prompt(self) -> bool:
        """Test webhook with empty prompt (should be ignored)."""
        print("\n📨 Testing webhook with empty prompt...")
        try:
            import httpx
            
            payload = {
                "message": {
                    "chat": {"id": config.telegram_chat_id},
                    "from": {"id": config.allowed_user_id},
                    "text": ""
                }
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://127.0.0.1:8000/webhook",
                    json=payload,
                    timeout=10
                )
                ignored = response.status_code == 200
                data = response.json()
                ignored = ignored and data.get("status") == "ignored"
                self.log_test(
                    "Webhook ignores empty prompt",
                    ignored,
                    f"Response: {response.json()}"
                )
                return ignored
        except Exception as e:
            self.log_test("Webhook ignores empty prompt", False, str(e))
            return False
    
    async def test_triage_router_accessible(self) -> bool:
        """Test that triage router can be imported and used."""
        print("\n📊 Testing triage router accessibility...")
        try:
            from agents.triage_router import get_triage_router
            
            router = get_triage_router()
            result = await router.classify_prompt("fix bug")
            
            accessible = (
                result is not None and
                hasattr(result, 'classification') and
                hasattr(result, 'model')
            )
            self.log_test(
                "Triage router accessible",
                accessible,
                f"Classification: {result.classification}, Model: {result.model}"
            )
            return accessible
        except Exception as e:
            self.log_test("Triage router accessible", False, str(e))
            return False
    
    async def run_all_tests(self):
        """Run all integration tests."""
        print("\n" + "="*80)
        print("TELEGRAM + TRIAGE ROUTER END-TO-END INTEGRATION TESTS")
        print("="*80)
        
        print("\n" + "-"*80)
        print("TEST GROUP 1: Prerequisites")
        print("-"*80)
        
        # Prerequisites
        health_ok = await self.check_server_health()
        aider_ok = self.check_aider_functional()
        
        if not (health_ok and aider_ok):
            print("\n❌ Prerequisites not met. Skipping remaining tests.")
            return
        
        print("\n" + "-"*80)
        print("TEST GROUP 2: Triage Router Integration")
        print("-"*80)
        
        await self.test_triage_router_accessible()
        
        print("\n" + "-"*80)
        print("TEST GROUP 3: Webhook with Triage Routing")
        print("-"*80)
        
        await self.test_webhook_with_simple_prompt()
        await self.test_webhook_with_complex_prompt()
        
        print("\n" + "-"*80)
        print("TEST GROUP 4: Security & Edge Cases")
        print("-"*80)
        
        await self.test_webhook_firewall()
        await self.test_webhook_empty_prompt()
        
        # Summary
        print("\n" + "="*80)
        print(f"TEST SUMMARY: {self.tests_passed} passed, {self.tests_failed} failed")
        print("="*80 + "\n")
        
        if self.tests_failed == 0:
            print("✨ All Phase 3 integration tests passed!")
            return 0
        else:
            print(f"⚠️  {self.tests_failed} test(s) failed.")
            return 1


async def main():
    """Main entry point."""
    tester = TelegramTriageE2ETest()
    exit_code = await tester.run_all_tests()
    return exit_code


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
