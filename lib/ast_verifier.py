import json
import logging
from pathlib import Path
import re
import subprocess
import importlib.metadata

# Try to import tree_sitter, fail gracefully if not installed yet
try:
    from tree_sitter import Language, Parser, Query
    import tree_sitter_python
    import tree_sitter_javascript
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

logger = logging.getLogger("ast_verifier")

class ASTVerifier:
    def __init__(self, blueprint_path: str = None):
        if not TREE_SITTER_AVAILABLE:
            logger.warning("Tree-sitter not installed. AST Verification will be skipped.")
            self.py_parser = None
            self.js_parser = None
        else:
            self.PY_LANGUAGE = Language(tree_sitter_python.language())
            self.JS_LANGUAGE = Language(tree_sitter_javascript.language())
            
            self.py_parser = Parser(self.PY_LANGUAGE)
            self.js_parser = Parser(self.JS_LANGUAGE)
        
        if blueprint_path is None:
            self.blueprint_path = Path(__file__).parent.parent / "core_memory" / "contracts" / "active_blueprint.json"
        else:
            self.blueprint_path = Path(blueprint_path)

    def load_blueprint(self) -> dict:
        try:
            with open(self.blueprint_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load blueprint: {e}")
            return {}

    def extract_python_routes(self, code: bytes) -> list:
        if not self.py_parser: return []
        
        tree = self.py_parser.parse(code)
        routes = []
        
        def walk(node):
            if node.type == "decorator":
                for child in node.children:
                    if child.type == "call":
                        for arg_child in child.children:
                            if arg_child.type == "argument_list":
                                for arg in arg_child.children:
                                    if arg.type == "string":
                                        for s_child in arg.children:
                                            if s_child.type in ("string_content", "string_fragment"):
                                                routes.append(s_child.text.decode('utf-8'))
            for child in node.children:
                walk(child)
                
        walk(tree.root_node)
        return routes

    def extract_js_fetch_urls(self, code: bytes) -> list:
        if not self.js_parser: return []
        
        tree = self.js_parser.parse(code)
        urls = []
        
        def walk(node):
            if node.type == "call_expression":
                is_fetch = False
                for child in node.children:
                    if child.type == "identifier" and child.text.decode('utf-8') == "fetch":
                        is_fetch = True
                    elif child.type == "member_expression" and b"axios" in child.text:
                        is_fetch = True
                        
                    if is_fetch and child.type == "arguments":
                        for arg in child.children:
                            if arg.type == "string":
                                for s_child in arg.children:
                                    if s_child.type in ("string_content", "string_fragment"):
                                        urls.append(s_child.text.decode('utf-8'))
            for child in node.children:
                walk(child)
                
        walk(tree.root_node)
        return urls

    def verify_network_ports(self, frontend_code: str, backend_code: str) -> bool:
        """
        Cross-checks that the frontend fetch URLs align with backend routes 
        and that they exist in the active_blueprint.json contract.
        """
        if not TREE_SITTER_AVAILABLE: return True
        
        blueprint = self.load_blueprint()
        valid_paths = blueprint.get("paths", {}).keys()
        
        py_routes = self.extract_python_routes(backend_code.encode('utf-8'))
        js_urls = self.extract_js_fetch_urls(frontend_code.encode('utf-8'))
        
        # Check Python backend adheres to blueprint
        for route in py_routes:
            if route not in valid_paths:
                logger.error(f"Backend route drift detected! '{route}' not in active_blueprint.json")
                return False
                
        # Check JS frontend targets valid backend routes
        for url in js_urls:
            is_valid = any(valid_path in url for valid_path in valid_paths)
            if not is_valid:
                logger.error(f"Frontend URL drift detected! '{url}' does not match any valid route in blueprint.")
                return False
                
        logger.info("AST Verification Passed: Cross-file alignment confirmed.")
        return True

    def extract_python_imports(self, code: bytes) -> list:
        if not self.py_parser: return []
        
        tree = self.py_parser.parse(code)
        imports = set()
        
        def walk(node):
            if node.type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        imports.add(child.text.decode('utf-8').split('.')[0])
            elif node.type == "import_from_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        imports.add(child.text.decode('utf-8').split('.')[0])
                        break # Only grab the base module
            for child in node.children:
                walk(child)
                
        walk(tree.root_node)
        return list(imports)

    def verify_dependencies(self, backend_code: str, requirements_path: str = "requirements.txt") -> tuple[bool, list]:
        """
        Cross-checks AST extracted imports against requirements.txt to detect missing runtime dependencies.
        Returns (is_valid, list_of_missing_deps)
        """
        if not TREE_SITTER_AVAILABLE: return True, []
        
        extracted_imports = self.extract_python_imports(backend_code.encode('utf-8'))
        
        req_path = Path(requirements_path)
        if not req_path.exists():
            req_path = self.blueprint_path.parent.parent.parent / "requirements.txt"
            
        if not req_path.exists():
            logger.warning(f"No requirements.txt found at {req_path}. Skipping dependency verification.")
            return True, []
            
        declared_deps = set()
        with open(req_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.split('#')[0].strip()
                if line:
                    # Strip version specifiers
                    dep_name = line.split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].strip().lower()
                    # Python packages often use '-' in pip but '_' in import (e.g. tree-sitter vs tree_sitter)
                    declared_deps.add(dep_name.replace('-', '_'))
                    declared_deps.add(dep_name) # Add original too just in case
        
        # Add standard library modules that don't need to be in requirements.txt
        import sys
        stdlib = set(sys.builtin_module_names)
        try:
            from stdlib_list import stdlib_list
            stdlib.update(stdlib_list())
        except ImportError:
            # Fallback for common stdlib if stdlib_list isn't installed
            stdlib.update(['json', 'os', 'sys', 'pathlib', 'logging', 'asyncio', 'typing', 'datetime', 'time', 'subprocess'])
            
        missing = []
        for imp in extracted_imports:
            imp_lower = imp.lower()
            if imp_lower not in stdlib and imp_lower not in declared_deps:
                missing.append(imp)
                
        if missing:
            logger.error(f"Dependency Verification Failed! Missing from requirements.txt: {missing}")
            return False, missing
            
        logger.info("Dependency Verification Passed.")
        return True, []

def verify_and_sync_dependencies(file_path: str):
    """Scans the AST/imports of a file and auto-installs missing dependencies via pip."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract clean package imports from code string
    imports = re.findall(r'^(?:import|from)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE)
    installed_packages = {dist.metadata["Name"].lower().replace("-", "_") for dist in importlib.metadata.distributions()}
    
    # Standard library exclusions fallback
    stdlib_ignore = {"sys", "os", "json", "time", "asyncio", "subprocess", "re", "math"}

    for module in set(imports):
        if module in stdlib_ignore or module in installed_packages:
            continue
            
        print(f"📦 [Pip Interceptor] Missing import detected: '{module}'. Resolving environment package balance...")
        try:
            # Dynamically target context virtual env pip binary via sys.executable
            import sys
            subprocess.run([sys.executable, "-m", "pip", "install", module], check=True, stdout=subprocess.DEVNULL)
            print(f"✅ [Pip Interceptor] Successfully synchronized '{module}' inside sandbox runtime.")
        except subprocess.CalledProcessError:
            print(f"❌ [Pip Interceptor] Failed automatic installation hook for module: {module}")

