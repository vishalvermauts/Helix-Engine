import logging
from pathlib import Path
from lib.ast_verifier import ASTVerifier

logger = logging.getLogger("contract_validator")

class ContractValidator:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.ast_verifier = ASTVerifier()

    def validate_workspace(self) -> tuple[bool, str]:
        """
        Validates the workspace frontend and backend code against the blueprint.
        Returns (is_valid, error_message).
        """
        logger.info("Running contract validation on workspace...")
        
        py_files = list(self.workspace_dir.rglob("*.py"))
        js_files = list(self.workspace_dir.rglob("*.js")) + list(self.workspace_dir.rglob("*.ts")) + list(self.workspace_dir.rglob("*.jsx")) + list(self.workspace_dir.rglob("*.tsx"))
        
        backend_code = ""
        for py_file in py_files:
            try:
                backend_code += py_file.read_text(encoding='utf-8') + "\n"
            except Exception:
                pass
                
        frontend_code = ""
        for js_file in js_files:
            try:
                frontend_code += js_file.read_text(encoding='utf-8') + "\n"
            except Exception:
                pass
                
        if not backend_code and not frontend_code:
            return True, "No code to validate yet."
            
        is_valid = self.ast_verifier.verify_network_ports(frontend_code, backend_code)
        
        if not is_valid:
            error_msg = "AST Verification Failed: Frontend fetch URLs do not match backend routes defined in active_blueprint.json."
            logger.error(error_msg)
            return False, error_msg
            
        deps_valid, missing_deps = self.ast_verifier.verify_dependencies(backend_code, str(self.workspace_dir.parent / "requirements.txt"))
        if not deps_valid:
            error_msg = f"AST Dependency Check Failed: The following required imports are missing from requirements.txt: {', '.join(missing_deps)}"
            logger.error(error_msg)
            return False, error_msg
            
        return True, "Code successfully validated against the active blueprint and requirements.txt."
