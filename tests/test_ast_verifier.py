import unittest
from unittest.mock import patch
import sys
import os

# Ensure lib module can be found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from lib.ast_verifier import ASTVerifier, TREE_SITTER_AVAILABLE

class TestASTVerifier(unittest.TestCase):
    def setUp(self):
        if not TREE_SITTER_AVAILABLE:
            self.skipTest("Tree-sitter is not available")
        self.verifier = ASTVerifier(blueprint_path="dummy_path.json")

    @patch('lib.ast_verifier.ASTVerifier.load_blueprint')
    def test_verify_network_ports_valid(self, mock_load):
        # Mock active blueprint with defined paths
        mock_load.return_value = {
            "paths": {
                "/api/v1/health": {},
                "/api/v1/data": {}
            }
        }
        
        backend_code = """
from fastapi import FastAPI
app = FastAPI()

@app.get("/api/v1/health")
def health():
    return {"status": "ok"}
"""
        frontend_code = """
async function fetchData() {
    const res = await fetch("/api/v1/health");
    return res.json();
}
"""
        is_valid = self.verifier.verify_network_ports(frontend_code, backend_code)
        self.assertTrue(is_valid)

    @patch('lib.ast_verifier.ASTVerifier.load_blueprint')
    def test_verify_network_ports_drift(self, mock_load):
        # Mock active blueprint without /api/v1/unknown
        mock_load.return_value = {
            "paths": {
                "/api/v1/health": {}
            }
        }
        
        backend_code = """
@app.post("/api/v1/unknown")
def create_unknown():
    pass
"""
        frontend_code = """
fetch("/api/v1/health");
"""
        is_valid = self.verifier.verify_network_ports(frontend_code, backend_code)
        self.assertFalse(is_valid)

if __name__ == '__main__':
    unittest.main()
