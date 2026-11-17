"""Shared runtime storage selection for the API and simulation worker."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def resolve_data_root(data_root: Path | None = None) -> Path:
    """Select CLI override, absolute environment setting, or checkout default.

    Explicit relative worker paths retain their invocation-directory semantics.
    Resolution only inspects paths and never creates storage.
    """
    if data_root is not None:
        return data_root.resolve()

    configured = os.environ.get("SIMASSIST_DATA_DIR")
    if configured is not None:
        path = Path(configured)
        if not configured.strip() or not path.is_absolute():
            raise ValueError("SIMASSIST_DATA_DIR must be an absolute directory path")
        return path.resolve()

    default = (REPOSITORY_ROOT / "data").resolve()
    legacy = (REPOSITORY_ROOT / "backend" / "data").resolve()
    if legacy != default and legacy.is_dir() and any(legacy.iterdir()):
        message = (
            f"Existing runtime storage found at {legacy}. The canonical default is "
            f"{default}. Select a data root explicitly before startup by setting "
            "SIMASSIST_DATA_DIR to an absolute path (or --data-root for the worker). "
            "Choose the existing directory to continue using its projects and chats."
        )
        logger.warning(message)
        raise ValueError(message)
    return default
