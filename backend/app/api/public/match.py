"""POST /api/match — find photos of a guest from 1–3 selfies.

Privacy: selfies are parsed into memory buffers (never disk), decoded, embedded
and discarded at the end of the request. Nothing about the selfie — bytes,
embedding or metrics — is stored, cached or logged.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from app.api.public.inmemory_multipart import MemoryFile, parse_multipart_in_memory
from app.config import MAX_THRESHOLD, MIN_THRESHOLD, get_settings
from app.db.session import SessionLocal
from app.face.engine import SELFIE_ERROR_MESSAGES, SelfieError, engine_loaded, get_engine
from app.models import EVENT_TYPES
from app.ratelimit import rate_limit
from app.schemas import MatchResponse
from app.services.images import InvalidImageError, load_image, pil_to_bgr
from app.services.matching import build_response, find_matches

router = APIRouter(tags=["public"])

_OPENAPI_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["selfies"],
                    "properties": {
                        "selfies": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                            "description": "1–3 selfie images (JPEG/PNG/WebP/HEIC, max 8 MB each)",
                        },
                        "event_ids": {"type": "array", "items": {"type": "string", "format": "uuid"}},
                        "event_types": {"type": "array", "items": {"type": "string", "enum": list(EVENT_TYPES)}},
                        "threshold": {"type": "number", "minimum": MIN_THRESHOLD, "maximum": MAX_THRESHOLD},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 60},
                        "offset": {"type": "integer", "minimum": 0, "default": 0},
                    },
                }
            }
        },
    }
}


def _invalid(code: str, message: str) -> HTTPException:
    return HTTPException(422, detail={"code": code, "message": message})


def _parse_params(form) -> tuple[list[uuid.UUID], list[str], float, int, int]:
    s = get_settings()
    try:
        event_ids = [uuid.UUID(v) for raw in form.get_list("event_ids", "event_ids[]") for v in raw.split(",") if v.strip()]
    except ValueError:
        raise _invalid("INVALID_PARAMS", "event_ids must be UUIDs") from None
    event_types = [t.strip() for t in form.get_list("event_types", "event_types[]") if t.strip()]
    unknown = [t for t in event_types if t not in EVENT_TYPES]
    if unknown:
        raise _invalid("INVALID_PARAMS", f"Unknown event type(s): {', '.join(unknown)}")
    try:
        raw_threshold = form.get_one("threshold")
        threshold = float(raw_threshold) if raw_threshold not in (None, "") else s.MATCH_THRESHOLD
        limit = int(form.get_one("limit") or 60)
        offset = int(form.get_one("offset") or 0)
    except ValueError:
        raise _invalid("INVALID_PARAMS", "threshold, limit and offset must be numbers") from None
    if not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD:
        raise _invalid("INVALID_PARAMS", f"threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}")
    if not 1 <= limit <= s.MAX_MATCH_LIMIT:
        raise _invalid("INVALID_PARAMS", f"limit must be between 1 and {s.MAX_MATCH_LIMIT}")
    if offset < 0:
        raise _invalid("INVALID_PARAMS", "offset must be >= 0")
    return event_ids, event_types, threshold, limit, offset


def _analyze_selfies(selfies: list[MemoryFile]) -> tuple[list, list[dict]]:
    """Validate + embed each selfie (CPU-bound; runs in a worker thread)."""
    s = get_settings()
    engine = get_engine()
    embeddings, errors = [], []
    for i, selfie in enumerate(selfies):
        code: SelfieError | None = None
        if selfie.too_large:
            code = SelfieError.FILE_TOO_LARGE
        else:
            try:
                image = pil_to_bgr(load_image(bytes(selfie.data)))
            except InvalidImageError:
                code = SelfieError.INVALID_IMAGE
            else:
                result = engine.analyze_selfie(
                    image,
                    blur_threshold=s.BLUR_THRESHOLD,
                    dark_threshold=s.DARK_THRESHOLD,
                    bright_threshold=s.BRIGHT_THRESHOLD,
                )
                del image
                if result.ok:
                    embeddings.append(result.embedding)
                else:
                    code = result.error
        if code is not None:
            errors.append({"index": i, "code": code.value, "message": SELFIE_ERROR_MESSAGES[code]})
    return embeddings, errors


def _run_query(embeddings, event_ids, event_types, threshold, limit, offset) -> dict:
    with SessionLocal() as db:
        rows = find_matches(db, embeddings, threshold=threshold, event_ids=event_ids, event_types=event_types)
    return build_response(rows, limit=limit, offset=offset)


@router.post(
    "/match",
    response_model=MatchResponse,
    summary="Find photos matching 1–3 selfies (10/min per IP)",
    openapi_extra=_OPENAPI_BODY,
    dependencies=[Depends(rate_limit("match", "MATCH_RATE_LIMIT_PER_MIN"))],
    responses={
        422: {"description": "Invalid params, or one or more selfies rejected (per-selfie error codes)"},
        429: {"description": "Rate limited"},
        503: {"description": "Face models not loaded"},
    },
)
async def match(request: Request) -> dict:
    s = get_settings()
    if not engine_loaded():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "MODELS_NOT_LOADED", "message": "Face recognition is starting up. Try again shortly."},
        )

    form = await parse_multipart_in_memory(
        request,
        max_file_size=s.MAX_SELFIE_BYTES,
        max_files=s.MAX_SELFIES,
        # Room for MAX_SELFIES slightly-oversized files + form fields.
        max_body_size=s.MAX_SELFIES * s.MAX_SELFIE_BYTES + 1024 * 1024,
    )
    try:
        selfies = form.files.get("selfies", []) + form.files.get("selfies[]", [])
        if form.extra_files_dropped:
            raise _invalid("TOO_MANY_SELFIES", f"At most {s.MAX_SELFIES} selfies are allowed")
        if not selfies:
            raise _invalid("NO_SELFIES", "Please provide at least one selfie in the 'selfies' field")

        event_ids, event_types, threshold, limit, offset = _parse_params(form)

        embeddings, errors = await run_in_threadpool(_analyze_selfies, selfies)
        form.wipe()  # raw selfie bytes are no longer needed
        if errors:
            raise HTTPException(
                422,
                detail={"code": "SELFIE_REJECTED", "message": "One or more selfies could not be used", "errors": errors},
            )

        result = await run_in_threadpool(_run_query, embeddings, event_ids, event_types, threshold, limit, offset)
        del embeddings
        return result
    finally:
        form.wipe()
