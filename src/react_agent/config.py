"""Load local credentials without logging their values."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout: float = 45
    max_rounds: int = 6
    tool_transport: str = "inprocess"
    mcp_transport: str = "stdio"
    mcp_url: str = ""
    text_normaliser: str = "rules"
    retriever: str = "bm25"
    rrf_k: int = 60
    retrieval_candidates: int = 20
    embedding_model: str = "intfloat/multilingual-e5-small"
    reranker_model: str = "BAAI/bge-reranker-base"
    embedder: str = "sentence-transformers"

    def __post_init__(self):
        if not 1 <= self.max_rounds <= 12:
            raise ValueError("MAX_AGENT_ROUNDS must be between 1 and 12")
        if not 1 <= self.timeout <= 120:
            raise ValueError("MODEL_TIMEOUT_SECONDS must be between 1 and 120")
        if self.tool_transport not in {"inprocess", "mcp"}:
            raise ValueError("TOOL_TRANSPORT must be inprocess or mcp")
        if self.mcp_transport not in {"stdio", "streamable-http"}:
            raise ValueError("MCP_TRANSPORT must be stdio or streamable-http")
        if self.text_normaliser not in {"off", "rules", "llm"}:
            raise ValueError("TEXT_NORMALISER must be off, rules, or llm")
        if self.retriever not in {"bm25", "dense", "hybrid", "hybrid_rerank"}:
            raise ValueError("RETRIEVER must be bm25, dense, hybrid, or hybrid_rerank")
        if not 1 <= self.rrf_k <= 1000:
            raise ValueError("RRF_K must be between 1 and 1000")
        if not 1 <= self.retrieval_candidates <= 50:
            raise ValueError("RETRIEVAL_CANDIDATES must be between 1 and 50")
        if self.embedder not in {"sentence-transformers", "fake"}:
            raise ValueError("EMBEDDER must be sentence-transformers or fake")

    @classmethod
    def from_env(cls, root: Path | None = None):
        root = (root or Path.cwd()).resolve()
        load_dotenv(root / ".env", override=False)
        data = Path(os.getenv("OPS_DATA_DIR", "runtime"))
        return cls(
            data_dir=data if data.is_absolute() else root / data,
            api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip(),
            timeout=float(os.getenv("MODEL_TIMEOUT_SECONDS", "45")),
            max_rounds=int(os.getenv("MAX_AGENT_ROUNDS", "6")),
            tool_transport=os.getenv("TOOL_TRANSPORT", "inprocess").strip() or "inprocess",
            mcp_transport=os.getenv("MCP_TRANSPORT", "stdio").strip() or "stdio",
            mcp_url=os.getenv("MCP_URL", "").strip(),
            text_normaliser=os.getenv("TEXT_NORMALISER", "rules").strip() or "rules",
            retriever=os.getenv("RETRIEVER", "bm25").strip() or "bm25",
            rrf_k=int(os.getenv("RRF_K", "60")),
            retrieval_candidates=int(os.getenv("RETRIEVAL_CANDIDATES", "20")),
            embedding_model=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small").strip()
            or "intfloat/multilingual-e5-small",
            reranker_model=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base").strip()
            or "BAAI/bge-reranker-base",
            embedder=os.getenv("EMBEDDER", "sentence-transformers").strip() or "sentence-transformers",
        )
