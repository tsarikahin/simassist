"""Streaming uploads with size/quota limits and isolated CAD validation."""

import hashlib
import json
import os
import subprocess
import sys
from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, File, HTTPException, UploadFile

from simassist.api.dependencies import get_data_root
from simassist.files.repository import FileRepository

router = APIRouter(prefix="/api/projects/{project_id}/files", tags=["Files"])


def max_upload_bytes():
    return int(os.getenv("SIMASSIST_MAX_UPLOAD_BYTES", str(32 * 1024 * 1024)))


def _parse_step_in_thread(path):
    """Keep the native parser isolated without relying on asyncio subprocess support.

    Uvicorn reload/workers use SelectorEventLoop on Windows, whose subprocess
    transport is unimplemented. Popen works on that platform; its bounded wait
    runs in an AnyIO worker thread so other API requests remain responsive.
    """
    with subprocess.Popen(
        [sys.executable, "-m", "simassist.files.inspect_cad", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        try:
            output, _ = process.communicate(timeout=60)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise ValueError(
                "STEP inspection timed out; simplify the model and try again"
            ) from exc
        if process.returncode:
            raise ValueError("Invalid STEP file: CAD parser rejected this model")
        try:
            return json.loads(output.decode().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise ValueError(
                "CAD inspector returned an invalid response; retry the upload"
            ) from exc


async def parse_step(path):
    # Cancellation waits for the bounded parser operation to finish. This keeps
    # cleanup from removing the STEP file while the native process still reads it.
    return await anyio.to_thread.run_sync(_parse_step_in_thread, path)


@router.post("")
async def upload_file(project_id: UUID, file: Annotated[UploadFile, File()]):
    store = FileRepository(get_data_root())
    file_id = None
    committed = False
    try:
        filename = file.filename or ""
        if (
            not filename
            or len(filename) > 255
            or any(c in filename for c in "/\\:")
            or any(ord(c) < 32 for c in filename)
        ):
            raise HTTPException(
                422, "Use a plain filename without directories or control characters"
            )
        allowed = {
            x.strip().lower()
            for x in os.getenv(
                "SIMASSIST_ALLOWED_UPLOAD_EXTENSIONS", ".step,.stp"
            ).split(",")
        }
        suffix = os.path.splitext(filename)[1].lower()
        if suffix not in {".step", ".stp"} or suffix not in allowed:
            raise HTTPException(
                415,
                "This release supports STEP CAD (.step, .stp). Existing meshes and STL reconstruction are not supported yet.",
            )
        if not file.size:
            raise HTTPException(422, "The uploaded file is empty")
        if file.size > max_upload_bytes():
            raise HTTPException(413, "File exceeds the configured upload size limit")
        file_id = store.reserve(project_id, filename, file.size)
        temporary = store.path(project_id, file_id, temporary=True)
        temporary.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        header = b""
        with temporary.open("xb") as stream:
            while chunk := await file.read(256 * 1024):
                size += len(chunk)
                if size > max_upload_bytes() or size > file.size:
                    raise HTTPException(
                        413, "File exceeds the configured upload size limit"
                    )
                if len(header) < 512:
                    header += chunk[: 512 - len(header)]
                stream.write(chunk)
                digest.update(chunk)
        if not header.lstrip().startswith(b"ISO-10303-21;"):
            raise HTTPException(422, "File content is not a STEP exchange file")
        inspection = await parse_step(temporary)
        temporary.replace(store.path(project_id, file_id))
        result = store.commit(project_id, file_id, size, digest.hexdigest(), inspection)
        committed = True
        return result
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            503,
            "File processing is unavailable. Check backend storage permissions and the Python installation, then retry.",
        ) from exc
    finally:
        with anyio.CancelScope(shield=True):
            try:
                if file_id and not committed:
                    store.discard(project_id, file_id)
                    store.path(project_id, file_id, temporary=True).unlink(
                        missing_ok=True
                    )
                    store.path(project_id, file_id).unlink(missing_ok=True)
            finally:
                await file.close()


@router.get("")
def list_files(project_id: UUID):
    try:
        return FileRepository(get_data_root()).list(project_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{file_id}")
def get_file(project_id: UUID, file_id: UUID):
    try:
        return FileRepository(get_data_root()).get(project_id, file_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


class UploadLimitMiddleware:
    """Limit multipart bodies before Starlette spools them to disk."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].endswith("/files")
        ):
            return await self.app(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > max_upload_bytes() + 64 * 1024:
                raise HTTPException(
                    413, "Upload request exceeds the configured size limit"
                )
            return message

        await self.app(scope, limited_receive, send)
