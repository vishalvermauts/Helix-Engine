import os
import re
from lib.logging import get_logger

logger = get_logger("ast_mapper")

class ASTMapper:
    def __init__(self, workspace_dir: str = "/workspaces/AirCode/workspace"):
        self.workspace_dir = workspace_dir

    def generate_dependency_context(self) -> str:
        """
        Scans the workspace directory and builds a fast regex-based AST dependency graph.
        Returns a formatted string warning Aider of connected files.
        """
        dependencies = {}
        
        if not os.path.exists(self.workspace_dir):
            return ""

        for root, _, files in os.walk(self.workspace_dir):
            for file in files:
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, self.workspace_dir)
                deps = self._parse_file_dependencies(filepath)
                if deps:
                    dependencies[rel_path] = deps

        if not dependencies:
            return ""

        context = "\n[AST DEPENDENCY GRAPH - WARNING]\n"
        context += "The following files are heavily linked. If you modify a class or ID in one file, you MUST ensure you do not break its linked dependencies:\n"
        for file, deps in dependencies.items():
            context += f"  - `{file}` depends on: {', '.join(deps)}\n"
        
        logger.info(f"🕸️ AST Mapper generated dependency graph for {len(dependencies)} files.")
        return context + "\n"

    def _parse_file_dependencies(self, filepath: str) -> list:
        deps = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if filepath.endswith('.html'):
                # match <link href="..."> and <script src="...">
                links = re.findall(r'<link[^>]+href=["\'](.*?)["\']', content, re.IGNORECASE)
                scripts = re.findall(r'<script[^>]+src=["\'](.*?)["\']', content, re.IGNORECASE)
                deps.extend([d for d in links + scripts if not d.startswith('http')])
                
            elif filepath.endswith('.css'):
                # match @import url("...");
                imports = re.findall(r'@import\s+(?:url\()?["\'](.*?)["\']', content, re.IGNORECASE)
                deps.extend([d for d in imports if not d.startswith('http')])
                
        except Exception as e:
            logger.debug(f"Failed to parse {filepath} for AST dependencies: {e}")
            
        return list(set(deps))

def get_ast_mapper() -> ASTMapper:
    return ASTMapper()
