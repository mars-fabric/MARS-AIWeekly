"""
Configuration settings for the AI Weekly backend.
"""

import os
from typing import List
from dataclasses import dataclass, field


@dataclass
class Settings:
    """Application settings with sensible defaults."""

    # App metadata
    app_title: str = "AI Weekly API"
    app_version: str = "1.0.0"

    # CORS settings
    cors_origins: List[str] = field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://localhost:3004",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
        "http://127.0.0.1:3003",
        "http://127.0.0.1:3004",
        "*",  # Allow all origins for development
    ])

    # Default work directory
    default_work_dir: str = "~/Desktop/cmbdir/aiweekly"

    # File size limits
    max_file_size_mb: int = 10

    # Debug settings
    debug: bool = False

    # Azure OpenAI settings
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_verify_ssl: bool = True

    def __post_init__(self):
        """Load settings from environment variables if available."""
        self.app_title = os.getenv("AIWEEKLY_APP_TITLE", self.app_title)
        self.app_version = os.getenv("AIWEEKLY_APP_VERSION", self.app_version)
        self.default_work_dir = os.getenv("AIWEEKLY_DEFAULT_WORK_DIR", self.default_work_dir)
        
        # Load CORS origins from environment variable (comma-separated list)
        cors_env = os.getenv("AIWEEKLY_CORS_ORIGINS")
        if cors_env:
            self.cors_origins = [origin.strip() for origin in cors_env.split(",")]
        self.max_file_size_mb = int(os.getenv("AIWEEKLY_MAX_FILE_SIZE_MB", str(self.max_file_size_mb)))
        self.debug = os.getenv("AIWEEKLY_DEBUG", "false").lower() == "true"

        # Azure OpenAI settings
        self.azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY", self.azure_openai_api_key)
        self.azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", self.azure_openai_endpoint)
        self.azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", self.azure_openai_deployment)
        self.azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION", self.azure_openai_api_version)
        self.azure_openai_verify_ssl = os.getenv("AZURE_OPENAI_VERIFY_SSL", "true").lower() != "false"


# Global settings instance
settings = Settings()
