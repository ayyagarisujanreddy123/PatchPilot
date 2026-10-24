"""Shared default path and runtime settings."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
VAR_DIR = BASE_DIR / "var"
RUNS_DIR = VAR_DIR / "runs"
RECIPES_DIR = VAR_DIR / "recipes"
CONFIG_DIR = BASE_DIR / "config"
FIXTURES_DIR = BASE_DIR / "fixtures"
