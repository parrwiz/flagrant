"""Project config and API key management."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Prompt, Confirm

console = Console()

CONFIG_DIR = Path.home() / ".config" / "flagrant"
CONFIG_FILE = CONFIG_DIR / "config.json"

PROVIDERS = {
    "claude": {
        "name": "Claude (Anthropic)",
        "env_var": "ANTHROPIC_API_KEY",
        "models": ["claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022"],
    },
    "openai": {
        "name": "OpenAI",
        "env_var": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini"],
    },
    "gemini": {
        "name": "Gemini (Google)",
        "env_var": "GEMINI_API_KEY",
        "models": ["gemini-2.5-pro", "gemini-2.5-pro"],
    },
    "deepseek": {
        "name": "DeepSeek",
        "env_var": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-chat"],
    },
}


@dataclass
class ProjectConfig:
    """Per-project .flagrant config."""
    ignore: list[str] = field(default_factory=list)
    strict: bool = False
    explain: bool = False
    language: str = "auto"


@dataclass
class AppConfig:
    """Global app config (API key + provider)."""
    provider: str = "claude"
    api_key: str = ""
    model: Optional[str] = None

    @property
    def effective_model(self) -> str:
        if self.model:
            return self.model
        return PROVIDERS[self.provider]["models"][0]


def load_project_config(repo_root: Path) -> ProjectConfig:
    """Load .flagrant config from repo root, or return defaults."""
    config_path = repo_root / ".flagrant"
    if not config_path.exists():
        return ProjectConfig()

    try:
        with open(config_path) as f:
            data = json.load(f)
        return ProjectConfig(
            ignore=data.get("ignore", []),
            strict=data.get("strict", False),
            explain=data.get("explain", False),
            language=data.get("language", "auto"),
        )
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[yellow]warning: could not parse .flagrant config: {e}[/yellow]")
        return ProjectConfig()


def _save_app_config(config: AppConfig) -> None:
    """Write config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "provider": config.provider,
        "api_key": config.api_key,
        "model": config.model,
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _load_saved_config() -> Optional[AppConfig]:
    """Load config from disk, if it exists."""
    if not CONFIG_FILE.exists():
        return None
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return AppConfig(
            provider=data.get("provider", "claude"),
            api_key=data.get("api_key", ""),
            model=data.get("model"),
        )
    except (json.JSONDecodeError, OSError):
        return None


def _check_env_key() -> Optional[AppConfig]:
    """Check environment variables for API keys."""
    load_dotenv()
    for provider_id, info in PROVIDERS.items():
        key = os.getenv(info["env_var"])
        if key:
            return AppConfig(provider=provider_id, api_key=key)
    return None


def setup_api_key_interactive() -> AppConfig:
    """Run the interactive API key setup prompt."""
    console.print()
    console.print("[bold cyan]flagrant setup[/bold cyan]")
    console.print()
    console.print("Choose your AI provider:")
    console.print("  [bold]1[/bold]  Claude (Anthropic)")
    console.print("  [bold]2[/bold]  OpenAI")
    console.print("  [bold]3[/bold]  Gemini (Google)")
    console.print("  [bold]4[/bold]  DeepSeek")
    console.print()

    choice = Prompt.ask("Provider", choices=["1", "2", "3", "4"], default="1")
    provider_map = {"1": "claude", "2": "openai", "3": "gemini", "4": "deepseek"}
    provider = provider_map[choice]

    info = PROVIDERS[provider]
    console.print()
    api_key = Prompt.ask(f"Paste your {info['name']} API key")

    if not api_key.strip():
        console.print("[red]error: no API key provided[/red]")
        raise SystemExit(1)

    config = AppConfig(provider=provider, api_key=api_key.strip())
    _save_app_config(config)

    console.print(f"[green]saved. using {info['name']}[/green]")
    console.print(f"[dim]Config stored at {CONFIG_FILE}[/dim]")
    console.print()
    return config


def get_app_config(require_key: bool = True) -> AppConfig:
    """Resolve API config. Checks env, then saved config, then prompts."""
    # 1. Environment variable
    env_config = _check_env_key()
    if env_config and env_config.api_key:
        return env_config

    # 2. Saved config
    saved = _load_saved_config()
    if saved and saved.api_key:
        return saved

    # 3. Interactive setup
    if not require_key:
        return AppConfig()

    return setup_api_key_interactive()
