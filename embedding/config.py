"""embedding config"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

ENCODER_URL = os.getenv("ENCODER_URL", "").strip()
ENCODER_PORT = int(os.getenv("ENCODER_PORT", "8020"))
ENCODER_MAX_BATCH = int(os.getenv("ENCODER_MAX_BATCH", "32"))
ENCODER_BATCH_WAIT_MS = float(os.getenv("ENCODER_BATCH_WAIT_MS", "5"))

ENCODER_TIMEOUT_S = float(os.getenv("ENCODER_TIMEOUT_S", "2"))
ENCODER_SERVER_TIMEOUT_S = 5.0

__all__ = [
    "ENCODER_URL",
    "ENCODER_PORT",
    "ENCODER_MAX_BATCH",
    "ENCODER_BATCH_WAIT_MS",
    "ENCODER_TIMEOUT_S",
    "ENCODER_SERVER_TIMEOUT_S",
]
