"""Strictly in-memory multipart/form-data parser for selfie uploads.

Why not FastAPI's `UploadFile`? Starlette stores uploaded files in a
`SpooledTemporaryFile` that rolls over to DISK once a part exceeds 1 MB. Phone
selfies are usually larger than that, which would write biometric data to
/tmp. This parser streams the request body straight into memory buffers with
hard size limits, so selfies never touch the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status

try:  # python-multipart >= 0.0.13
    from python_multipart.multipart import MultipartParser, parse_options_header
except ImportError:  # pragma: no cover - older package layout
    from multipart.multipart import MultipartParser, parse_options_header  # type: ignore[no-redef]


@dataclass
class MemoryFile:
    field: str
    filename: str
    content_type: str
    data: bytearray = field(default_factory=bytearray)
    too_large: bool = False

    def wipe(self) -> None:
        """Best-effort zeroing of the buffer once we're done with it."""
        self.data[:] = b"\x00" * len(self.data)
        self.data.clear()


@dataclass
class MemoryForm:
    fields: dict[str, list[str]] = field(default_factory=dict)
    files: dict[str, list[MemoryFile]] = field(default_factory=dict)
    extra_files_dropped: int = 0

    def get_list(self, *names: str) -> list[str]:
        out: list[str] = []
        for n in names:
            out.extend(self.fields.get(n, []))
        return out

    def get_one(self, name: str) -> str | None:
        vals = self.fields.get(name)
        return vals[-1] if vals else None

    def wipe(self) -> None:
        for files in self.files.values():
            for f in files:
                f.wipe()
        self.files.clear()


def _bad_request(message: str, code: str = "BAD_REQUEST", http: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(http, detail={"code": code, "message": message})


async def parse_multipart_in_memory(
    request: Request,
    *,
    max_file_size: int,
    max_files: int,
    max_body_size: int,
    max_fields: int = 100,
    max_field_size: int = 4096,
) -> MemoryForm:
    ctype, params = parse_options_header(request.headers.get("content-type", ""))
    if ctype != b"multipart/form-data":
        raise _bad_request("Expected multipart/form-data", "INVALID_CONTENT_TYPE")
    boundary = params.get(b"boundary")
    if not boundary:
        raise _bad_request("Missing multipart boundary", "INVALID_CONTENT_TYPE")

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_body_size:
        raise _bad_request("Request too large", "PAYLOAD_TOO_LARGE", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    form = MemoryForm()
    state: dict = {"hname": bytearray(), "hvalue": bytearray(), "headers": {}, "file": None, "field": None,
                   "fname": None, "nfiles": 0, "nfields": 0, "discard": False}

    def on_part_begin() -> None:
        state.update(headers={}, file=None, field=None, fname=None, discard=False)

    def on_header_field(data: bytes, start: int, end: int) -> None:
        state["hname"] += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        state["hvalue"] += data[start:end]

    def on_header_end() -> None:
        state["headers"][bytes(state["hname"]).lower()] = bytes(state["hvalue"])
        state["hname"], state["hvalue"] = bytearray(), bytearray()

    def on_headers_finished() -> None:
        disp, opts = parse_options_header(state["headers"].get(b"content-disposition", b""))
        if disp != b"form-data" or b"name" not in opts:
            state["discard"] = True
            return
        name = opts[b"name"].decode("utf-8", "replace")
        if b"filename" in opts:
            if state["nfiles"] >= max_files:
                form.extra_files_dropped += 1
                state["discard"] = True
                return
            state["nfiles"] += 1
            f = MemoryFile(
                field=name,
                filename=opts[b"filename"].decode("utf-8", "replace"),
                content_type=state["headers"].get(b"content-type", b"").decode("latin-1"),
            )
            form.files.setdefault(name, []).append(f)
            state["file"] = f
        else:
            state["nfields"] += 1
            if state["nfields"] > max_fields:
                raise _bad_request("Too many form fields")
            state["fname"] = name
            state["field"] = bytearray()

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if state["discard"]:
            return
        chunk = data[start:end]
        f: MemoryFile | None = state["file"]
        if f is not None:
            if f.too_large:
                return
            if len(f.data) + len(chunk) > max_file_size:
                f.too_large = True
                f.wipe()
                return
            f.data += chunk
        elif state["field"] is not None:
            if len(state["field"]) + len(chunk) > max_field_size:
                raise _bad_request("Form field too large")
            state["field"] += chunk

    def on_part_end() -> None:
        if state["field"] is not None and state["fname"] is not None:
            form.fields.setdefault(state["fname"], []).append(bytes(state["field"]).decode("utf-8", "replace"))
        state.update(file=None, field=None, fname=None)

    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
        },
    )

    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > max_body_size:
                raise _bad_request("Request too large", "PAYLOAD_TOO_LARGE", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            parser.write(chunk)
        parser.finalize()
    except HTTPException:
        form.wipe()
        raise
    except Exception as exc:
        form.wipe()
        raise _bad_request("Malformed multipart body") from exc
    return form
