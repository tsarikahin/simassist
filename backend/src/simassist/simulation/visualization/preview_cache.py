"""Disposable, versioned derived cache; validate ownership BEFORE calling this module."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

from fastapi import Response
from simassist.simulation.visualization.mesh_preview import (
    PREVIEW_VERSION,
    build_mesh_preview,
)

logger = logging.getLogger(__name__)
_registry_lock = Lock()
_locks = WeakValueDictionary()


class _BuildLock:
    def __init__(self):
        self.lock = Lock()


def _lock_for(key):
    with _registry_lock:
        holder = _locks.get(key)
        if holder is None:
            holder = _BuildLock()
            _locks[key] = holder
        return holder


@dataclass
class CachedPreview:
    body: bytes
    metadata: dict
    timings: dict
    hit: bool

    def response(self, mesh_job_id, artifact_id):
        # Append small per-route identity fields to the cached JSON bytes. Avoid
        # decoding, re-encoding, and FastAPI's recursive jsonable_encoder on warm hits.
        suffix = json.dumps(
            {"mesh_job_id": str(mesh_job_id), "mesh_artifact_id": str(artifact_id)},
            separators=(",", ":"),
        ).encode()
        body = self.body[:-1] + b"," + suffix[1:]
        timing = ", ".join(
            f"{name.removesuffix('_ms')};dur={value:.3f}"
            for name, value in self.timings.items()
        )
        return Response(
            body,
            media_type="application/json",
            headers={
                "Server-Timing": timing,
                "X-Preview-Cache": "HIT" if self.hit else "MISS",
                "Timing-Allow-Origin": "*",
                "Cache-Control": "private, max-age=0, must-revalidate",
            },
        )


def cached_mesh_preview(mesh_path: Path, artifact_id: UUID):
    started = perf_counter()
    stat = mesh_path.stat()
    fingerprint = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    directory = mesh_path.parent / ".simassist-preview-cache"
    # LocalArtifactStore already gives each immutable artifact its own directory.
    # Keep derived filenames short: repeating UUIDs in Windows temp paths can
    # exceed MAX_PATH. Full artifact identity is validated in the sidecar too.
    cache = directory / f"v{PREVIEW_VERSION}.json"
    meta = cache.with_suffix(".meta.json")
    holder = _lock_for(str(cache.resolve()))
    with holder.lock:
        try:
            metadata = json.loads(meta.read_bytes())
            if (
                metadata["source"] == fingerprint
                and metadata["version"] == PREVIEW_VERSION
                and metadata["artifact_id"] == str(artifact_id)
            ):
                body = cache.read_bytes()
                if (
                    len(body) == metadata["serialized_bytes"]
                    and hashlib.sha256(body).hexdigest() == metadata["body_sha256"]
                ):
                    return CachedPreview(
                        body,
                        metadata,
                        {"cache_ms": (perf_counter() - started) * 1000},
                        True,
                    )
        except (OSError, ValueError, KeyError, TypeError):
            pass
        timings = {}
        preview = build_mesh_preview(mesh_path, timings)
        serialized = perf_counter()
        body = json.dumps(preview, separators=(",", ":"), allow_nan=False).encode()
        timings["serialize_ms"] = (perf_counter() - serialized) * 1000
        metadata = {
            "version": PREVIEW_VERSION,
            "artifact_id": str(artifact_id),
            "source": fingerprint,
            "serialized_bytes": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "point_count": preview["point_count"],
            "triangle_count": preview["triangle_count"],
            "quad_count": preview["quad_count"],
            "line_count": preview["line_count"],
            "build_timings": timings.copy(),
        }
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # Unique temporary names and atomic replacement also protect concurrent
            # API/worker processes; duplicate cold builds are safe across processes.
            for target, value in ((cache, body), (meta, json.dumps(metadata).encode())):
                temporary = target.with_name(f"p-{uuid4().hex[:12]}.tmp")
                try:
                    temporary.write_bytes(value)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Mesh preview cache write unavailable artifact=%s", artifact_id
            )
        timings["total_ms"] = (perf_counter() - started) * 1000
        logger.info(
            "mesh_preview artifact=%s bytes=%s points=%s triangles=%s timings=%s",
            artifact_id,
            len(body),
            preview["point_count"],
            preview["triangle_count"],
            timings,
        )
        return CachedPreview(body, metadata, timings, False)
