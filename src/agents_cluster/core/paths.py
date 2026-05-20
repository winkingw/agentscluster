from __future__ import annotations

from pathlib import Path


CLUSTER_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = CLUSTER_ROOT / "config"
CONFIG_PATH = CONFIG_DIR / "agents.yaml"
CONFIG_EXAMPLE_PATH = CONFIG_DIR / "agents.example.yaml"
ENV_PATH = CLUSTER_ROOT / ".env"
DB_PATH = CLUSTER_ROOT / "agentsCluster.db"
RUNS_DIR = CLUSTER_ROOT / "runs"
WORKTREES_DIR = CLUSTER_ROOT / "worktrees"
PATCHES_DIR = CLUSTER_ROOT / "patches"
UI_DIR = CLUSTER_ROOT / "ui"
UI_DIST_DIR = UI_DIR / "dist"
