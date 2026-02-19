"""
Zentrale Konfiguration - liest .env und settings.yaml
"""

import os
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Umgebungsvariablen aus .env"""

    # Home Assistant
    ha_url: str = "http://192.168.1.100:8123"
    ha_token: str = ""

    # MindHome
    mindhome_url: str = "http://192.168.1.100:8099"

    # Ollama
    ollama_url: str = "http://localhost:11434"
    model_fast: str = "qwen3:4b"
    model_smart: str = "qwen3:14b"
    model_deep: str = "qwen3:32b"

    # MindHome Assistant Server
    assistant_host: str = "0.0.0.0"
    assistant_port: int = 8200

    # Redis + ChromaDB
    redis_url: str = "redis://localhost:6379"
    chroma_url: str = "http://localhost:8100"

    # User
    user_name: str = "Max"
    autonomy_level: int = 2
    language: str = "de"

    # Assistent-Identitaet
    assistant_name: str = "Jarvis"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def load_yaml_config() -> dict:
    """Laedt settings.yaml"""
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


# Globale Instanzen
settings = Settings()
yaml_config = load_yaml_config()

# settings.yaml ueberschreibt .env fuer bestimmte Werte
_yaml_name = yaml_config.get("assistant", {}).get("name")
if _yaml_name:
    settings.assistant_name = _yaml_name

# Modelle aus settings.yaml uebernehmen (wenn gesetzt)
_models = yaml_config.get("models", {})
if _models.get("fast"):
    settings.model_fast = _models["fast"]
if _models.get("smart"):
    settings.model_smart = _models["smart"]
if _models.get("deep"):
    settings.model_deep = _models["deep"]
