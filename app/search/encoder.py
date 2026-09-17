import logging
import threading
from typing import Any

# from embedding.encoder import Encoder

_logger = logging.getLogger(__name__)

_encoder = None
_lock = threading.Lock()

def get_encoder() -> Any:
    global _encoder
    with _lock:
        if _encoder is None:
            from embedding.encoder import Encoder
            _encoder = Encoder()
        return _encoder

def warmup() -> None:
    get_encoder().encode_query("warmup")


def _start_warmup() -> None:
    threading.Thread(target=_warmup, name="encoder-warmup", daemon=True).start()


def _warmup() -> None:
    _logger.info("encoder warmup started")
    try:
        warmup()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("encoder warmup failed: %s: %s", type(exc).__name__, exc)
    else:
        _logger.info("encoder warmup done")