import httpx
from lib.logging import get_logger

logger = get_logger("rag_fetcher")

class RAGFetcher:
    def __init__(self):
        self.doc_registry = {
            "tailwind": "https://raw.githubusercontent.com/tailwindlabs/tailwindcss/master/README.md",
            "react": "https://raw.githubusercontent.com/facebook/react/main/README.md",
        }

    async def fetch_context(self, framework: str) -> str:
        """
        Fetches official documentation schema for a given framework.
        In a production environment, this would hit a Vector DB for RAG.
        Here we mock a lightweight fetch for demonstration.
        """
        if framework not in self.doc_registry:
            return ""

        url = self.doc_registry[framework]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    text = response.text[:2000] # Grab first 2000 chars as context snippet
                    logger.info(f"📚 Speculative RAG fetched docs for {framework}")
                    return f"\n[OFFICIAL {framework.upper()} DOCUMENTATION CONTEXT]\n{text}\n"
        except Exception as e:
            logger.warning(f"Failed to fetch RAG docs for {framework}: {e}")
            
        return ""

def get_rag_fetcher() -> RAGFetcher:
    return RAGFetcher()
