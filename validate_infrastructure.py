#!/usr/bin/env python3
"""
AirCode Infrastructure Validation Script
Tests config loading, logging, and agent startup.
"""

import sys
import asyncio
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

def test_config():
    """Test config loading & validation."""
    print("🧪 Testing config layer...")
    try:
        from lib.config import get_config
        cfg = get_config()
        
        print(f"  ✅ Config loaded")
        print(f"     - Workspace: {cfg.workspace_dir}")
        print(f"     - Aider model: {cfg.gemini_model}")
        print(f"     - Timeout: {cfg.aider_timeout}s")
        print(f"     - Safe output: {cfg.to_dict()}")
        return True
    except Exception as e:
        print(f"  ❌ Config test failed: {e}")
        return False


def test_logging():
    """Test structured logging."""
    print("\n🧪 Testing logging layer...")
    try:
        from lib.logging import get_logger
        logger = get_logger("test", level="INFO", format_type="json")
        
        print(f"  ✅ Logger created")
        print(f"     - Sample log output:")
        logger.info("Test info message", test_id=123, status="pass")
        logger.warning("Test warning message", component="telegram")
        return True
    except Exception as e:
        print(f"  ❌ Logging test failed: {e}")
        return False


async def test_monitor_agent():
    """Test system monitor agent (quick smoke test)."""
    print("\n🧪 Testing system monitor agent...")
    try:
        from agents.system_monitor import SystemMonitor
        monitor = SystemMonitor()
        
        print(f"  ✅ Monitor agent initialized")
        print(f"     - Tunnel URL: {monitor.last_tunnel_url}")
        print(f"     - Health checks: {monitor.health_checks_passed} passed, {monitor.health_checks_failed} failed")
        
        # Quick health check
        await monitor._check_fastapi_health()
        print(f"     - FastAPI health check completed")
        return True
    except Exception as e:
        print(f"  ❌ Monitor test failed: {e}")
        return False


def test_refactored_server():
    """Test refactored server imports."""
    print("\n🧪 Testing refactored server...")
    try:
        # Just import to check syntax
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "server_refactored",
            "/workspaces/AirCode/server.refactored.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        print(f"  ✅ Refactored server imports OK")
        print(f"     - FastAPI app: {module.app}")
        print(f"     - Routes: {[route.path for route in module.app.routes if hasattr(route, 'path')]}")
        return True
    except Exception as e:
        print(f"  ❌ Refactored server test failed: {e}")
        return False


async def main():
    """Run all validation tests."""
    print("=" * 60)
    print("     AirCode Infrastructure Validation")
    print("=" * 60)
    
    results = []
    results.append(("Config Layer", test_config()))
    results.append(("Logging Layer", test_logging()))
    results.append(("Refactored Server", test_refactored_server()))
    results.append(("Monitor Agent", await test_monitor_agent()))
    
    print("\n" + "=" * 60)
    print("     Summary")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {test_name}")
    
    all_passed = all(result[1] for result in results)
    if all_passed:
        print("\n🎉 All tests passed! Infrastructure ready.")
        return 0
    else:
        print("\n⚠️  Some tests failed. See above for details.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
