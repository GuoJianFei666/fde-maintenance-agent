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
        )
