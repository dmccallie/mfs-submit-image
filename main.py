from __future__ import annotations

from datetime import datetime, timezone
import hmac
import mimetypes
import os
from pathlib import Path
import random
import re
import tempfile
from urllib.parse import quote, urlencode
from typing import Optional, List
from zoneinfo import ZoneInfo

import boto3
import sqlite3
from dotenv import load_dotenv

# NOTE - make sure a local executable of exiftool is available!
# use the script in this repo to download and place it in the project root if needed
# or have Dockerfile pull and bundle it in the image
from exiftool import ExifToolHelper

from starlette.datastructures import UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, JSONResponse

from fasthtml.common import *

APP_TITLE = "McCallie Family Archive Photo Submission"
DATA_DIR = Path("data")
IMAGE_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "submissions.db"

SUBMITTER_NAMES = ["DPM", "JBM", "ALM", "EMC", "KRM", "HHM", "SJMIII", "THMIII", "Other"]
S3_BUCKET_NAME = "mfs-photo-submissions"  # store images in S3

load_dotenv(dotenv_path=Path(".env"))

APP_PASSWORD = os.getenv("APP_PASSWORD", "")
APP_SESSION_SECRET = os.getenv("APP_SESSION_SECRET", "dev-insecure-session-secret-change-me")
APP_SESSION_MAX_AGE = int(os.getenv("APP_SESSION_MAX_AGE", "2592000"))  # 30 days
# set this to 0 for local testing, set to 1 when behind HTTPS in production to protect cookies from being sent over insecure connections
APP_SECURE_COOKIES = os.getenv("APP_SECURE_COOKIES", "0") == "1"

SORTABLE_COLUMNS = {
    "id": "id",
    "submitted_by": "submitted_by",
    "title": "title",
    "description": "description",
    "created_at": "created_at",
}
DEFAULT_SORT_BY = "id"
DEFAULT_SORT_DIR = "desc"


def normalize_submitter_name(value: str | None) -> str:
    if not value:
        return ""
    if value in SUBMITTER_NAMES:
        return value
    if "Other" in SUBMITTER_NAMES:
        return "Other"
    return ""


def sanitize_title_for_s3(value: str | None) -> str:
    base = (value or "").strip()
    if not base:
        base = "untitled"
    base = base.replace("_", " ")
    safe = re.sub(r"[^A-Za-z0-9]+", "-", base)
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "untitled"


def random_suffix() -> str:
    return f"{random.randint(0, 9999):04d}"


def build_s3_key(submitted_by: str | None, title: str | None, filename: str | None) -> str:
    submitter = normalize_submitter_name(submitted_by) or "Other"
    title_safe = sanitize_title_for_s3(title)
    suffix = Path(filename or "upload").suffix.lower() or ".jpg"
    return f"{submitter}/{title_safe}-{random_suffix()}{suffix}"


def temp_file_from_bytes(filebuffer: bytes, filename: str | None) -> Path:
    suffix = Path(filename or "upload").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=DATA_DIR) as fh:
        fh.write(filebuffer)
        fh.flush()
        os.fsync(fh.fileno())
        return Path(fh.name)


def s3_client():
    return boto3.client("s3")


def sanitize_s3_metadata_value(value: str | None) -> str:
    if value is None:
        return ""
    # S3 user metadata is transmitted in HTTP headers, so CR/LF must be escaped.
    return value.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n").strip()


def decode_escaped_newlines(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("\\r\\n", "\r\n").replace("\\n", "\n").replace("\\r", "\r")


def upload_file_to_s3(local_path: Path, s3_key: str, title: str | None, description: str | None, submitted_by: str | None) -> None:
    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    metadata = {
        "submitted_by": sanitize_s3_metadata_value(normalize_submitter_name(submitted_by) or ""),
        "title": sanitize_s3_metadata_value(title),
        "description": sanitize_s3_metadata_value(description),
    }
    s3_client().upload_file(
        str(local_path),
        S3_BUCKET_NAME,
        s3_key,
        ExtraArgs={"Metadata": metadata, "ContentType": content_type},
    )


def delete_s3_key(s3_key: str) -> None:
    if not s3_key:
        return
    s3_client().delete_object(Bucket=S3_BUCKET_NAME, Key=s3_key)


def download_s3_object_to_temp(s3_key: str) -> Path:
    response = s3_client().get_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
    body = response["Body"].read()
    return temp_file_from_bytes(body, Path(s3_key).name)


def presigned_s3_url(s3_key: str, expires_seconds: int = 3600) -> str:
    return s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET_NAME, "Key": s3_key},
        ExpiresIn=expires_seconds,
    )


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL,
                title TEXT,
                description TEXT,
                submitted_by TEXT,
                created_at TEXT NOT NULL
            )
            """
        )


def normalize_sort(sort_by: str | None, sort_dir: str | None) -> tuple[str, str]:
    normalized_by = sort_by if sort_by in SORTABLE_COLUMNS else DEFAULT_SORT_BY
    normalized_dir = "asc" if sort_dir == "asc" else "desc"
    return normalized_by, normalized_dir


def build_index_url(sort_by: str, sort_dir: str, image_id: int | None = None) -> str:
    params: dict[str, str] = {"sort_by": sort_by, "sort_dir": sort_dir}
    if image_id is not None:
        params["image_id"] = str(image_id)
    return f"/?{urlencode(params)}"


def db_rows(sort_by: str = DEFAULT_SORT_BY, sort_dir: str = DEFAULT_SORT_DIR) -> list[sqlite3.Row]:
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)
    sort_expr = SORTABLE_COLUMNS[safe_sort_by]
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        SELECT id, image_path, title, description, submitted_by, created_at
        FROM submissions
        ORDER BY {sort_expr} {safe_sort_dir.upper()}, id DESC
        """
    ).fetchall()
    conn.close()
    return rows


def db_row_by_id(submission_id: int) -> sqlite3.Row | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT id, image_path, title, description, submitted_by, created_at
        FROM submissions
        WHERE id = ?
        """,
        (submission_id,),
    ).fetchone()
    conn.close()
    return row


def format_submitted_time(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    cst = ZoneInfo("America/Chicago")
    return dt.astimezone(cst).strftime("%b %d %Y %I:%M %p CST")


def clip_text(value: str | None, limit: int = 40) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    return f"{text[:limit - 3]}..."


def encode_exiftool_newlines(value: str | None) -> str | None:
    if value is None:
        return None
    # ExifToolHelper expects escaped newline characters in text fields.
    return value.replace("\r\n", "\\r\\n").replace("\r", "\\r").replace("\n", "\\n")

def embed_photo_metadata_with_xmp( 
    image_path: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    creator: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    circa_date_created: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    country: Optional[str] = None,
    credit: Optional[str] = None,
    source: Optional[str] = None,
):
    """
    Embed archival metadata into a JPEG using XMP fields.

    Parameters
    ----------
    image_path : str
        Path to the JPEG image.

    title : str
        Title of the image.
        Shows in Photoshop as Basic: "Title"
        In our case we will use this to build a meaningful filename (eg THM Golden Wedding)

    description : str
        Caption or description.
        Shows in Photoshop as Basic: "Description"

    creator : str
        Photographer or archive creator.
        Shows in Photoshop Basic: "Author"
        Shows in PS IPTC as "Creator"

    keywords : list[str]
        Searchable keywords.
        Shows in Photoshop Basic: "Keywords"

    circa_date_created : str
        Historical or estimated date of photo (as text).
        Does not appear in Photoshop's XMP viewer so we shouldn't rely on it.
        Maybe store this info in the Description field by convention?

    city/state/country : str
        Location metadata.
        Shows in PS IPTC and PS Origin as "City", "State/Province", and "Country"

    credit : str
        Archive credit line.
        Shows in PS Origin and IPTC as "Credit Line"

    source : str
        Provenance or submission source.
        Shows in PS Origin and IPTC as "Source"
    """

    tags = {}

    encoded_title = encode_exiftool_newlines(title)
    encoded_description = encode_exiftool_newlines(description)

    if encoded_title:
        tags["XMP-dc:Title"] = encoded_title
        # old IIM model that some support - ObjectName
        tags['XMP-iptc:ObjectName'] = encoded_title

    if encoded_description:
        tags["XMP-dc:Description"] = encoded_description

    if creator:
        tags["XMP-dc:Creator"] = creator

    if keywords:
        tags["XMP-dc:Subject"] = keywords

    if circa_date_created:
        # CircaDateCreated doesn't show in PS XMP viewer but some apps can see it
        tags["XMP-iptcExt:CircaDateCreated"] = circa_date_created

    if city:
        tags["XMP-photoshop:City"] = city

    if state:
        tags["XMP-photoshop:State"] = state

    if country:
        tags["XMP-photoshop:Country"] = country

    if credit:
        tags["XMP-photoshop:Credit"] = credit

    if source:
        tags["XMP-photoshop:Source"] = source
        tags["XMP-iptcCore:Source"] = source

    if not tags:
        return

    print("Embedding metadata with ExifTool:", tags)
    with ExifToolHelper() as et:
        et.set_tags(
            image_path,
            tags,
            params=["-overwrite_original"],
        )

def prepare_local_image_with_xmp(
    filename: str,
    filebuffer: bytes,
    title: str | None,
    description: str | None,
    submitted_by: str | None,
) -> Path:
    local_path = temp_file_from_bytes(filebuffer, filename)
    embed_photo_metadata_with_xmp(
        image_path=str(local_path),
        title=title,
        description=description,
        source=submitted_by,
    )
    return local_path


def upload_submission_image(
    filename: str,
    filebuffer: bytes,
    title: str | None,
    description: str | None,
    submitted_by: str | None,
) -> str:
    local_path = prepare_local_image_with_xmp(filename, filebuffer, title, description, submitted_by)
    try:
        s3_key = build_s3_key(submitted_by, title, filename)
        upload_file_to_s3(local_path, s3_key, title, description, submitted_by)
        return s3_key
    finally:
        try:
            local_path.unlink(missing_ok=True)
        except OSError:
            pass


def _coerce_exif_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _coerce_exif_value(item)
            if text:
                return text
        return ""
    if isinstance(value, dict):
        preferred = ["lang-default", "x-default", "en-US", "en"]
        for key in preferred:
            text = _coerce_exif_value(value.get(key))
            if text:
                return text
        for item in value.values():
            text = _coerce_exif_value(item)
            if text:
                return text
        return ""
    return str(value).strip()


def extract_xmp_form_fields(image_path: Path) -> dict[str, str]:
    with ExifToolHelper() as et:
        metadata_list = et.get_metadata(str(image_path))
        # print("Raw metadata extracted from image:", metadata_list)
    metadata = metadata_list[0] if metadata_list else {}

    title_dc = _coerce_exif_value(metadata.get("XMP-dc:Title"))
    title_iptc = _coerce_exif_value(metadata.get("XMP-iptc:ObjectName"))
    title_xmp = _coerce_exif_value(metadata.get("XMP:Title"))
    title = decode_escaped_newlines(title_dc or title_iptc or title_xmp)

    description_dc = _coerce_exif_value(metadata.get("XMP-dc:Description"))
    description_iptc = _coerce_exif_value(metadata.get("XMP-iptc:Caption-Abstract"))
    description_xmp = _coerce_exif_value(metadata.get("XMP:Description"))
    description = decode_escaped_newlines(description_dc or description_iptc or description_xmp)

    source_iptc = _coerce_exif_value(metadata.get("XMP-iptcCore:Source"))
    source_photoshop = _coerce_exif_value(metadata.get("XMP-photoshop:Source"))
    source_xmp = _coerce_exif_value(metadata.get("XMP:Source"))
    source = decode_escaped_newlines(source_iptc or source_photoshop or source_xmp)

    # IPTC Core Source takes precedence when both are present.
    source = source_iptc or source_photoshop
    normalized_source = normalize_submitter_name(source)

    return {
        "title": title,
        "description": description,
        "submitted_by": normalized_source,
    }

def save_submission(
    filename: str,
    filebuffer: bytes,
    title: str | None,
    description: str | None,
    submitted_by: str | None,
) -> None:
    image_key = upload_submission_image(filename, filebuffer, title, description, submitted_by)

    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO submissions (
                image_path, title, description, submitted_by, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                image_key,
                title or "",
                description or "",
                submitted_by or "",
                created_at,
            ),
        )

def update_submission(
    image_id: int,
    title: str | None,
    description: str | None,
    submitted_by: str | None,
    photo_filename: str | None = None,
    photo_buffer: bytes | None = None,
) -> None:
    row = db_row_by_id(image_id)
    if not row:
        return

    old_s3_key = row["image_path"]
    old_name = Path(old_s3_key).name if old_s3_key else "upload.jpg"
    source_filename = photo_filename or old_name

    if photo_filename and photo_buffer:
        working_filebuffer = photo_buffer
    else:
        download_path = download_s3_object_to_temp(old_s3_key)
        try:
            working_filebuffer = download_path.read_bytes()
        finally:
            try:
                download_path.unlink(missing_ok=True)
            except OSError:
                pass

    new_s3_key = upload_submission_image(
        source_filename,
        working_filebuffer,
        title,
        description,
        submitted_by,
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE submissions
            SET image_path = ?, title = ?, description = ?, submitted_by = ?
            WHERE id = ?
            """,
            (
                new_s3_key,
                title or "",
                description or "",
                submitted_by or "",
                image_id,
            ),
        )

    delete_s3_key(old_s3_key)


init_db()

app, rt = fast_app(
        hdrs=(
                Link(rel="stylesheet", href="/static/styles.css"),
                Script(src="https://unpkg.com/htmx.org@1.9.12", defer=True),
                Script(src="/static/app.js", defer=True),
        )
)


def _build_login_redirect_target(request: Request) -> str:
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return quote(target, safe="/?=&")


class RequireLoginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not APP_PASSWORD: #if no password is set, disable authentication requirement
            return await call_next(request)

        path = request.url.path
        if path == "/login" or path.startswith("/static/"): # allow these
            return await call_next(request)

        if request.session.get("authenticated"): # allow if already authenticated
            return await call_next(request)

        login_url = f"/login?next={_build_login_redirect_target(request)}"
        if "hx-request" in request.headers:
            response = JSONResponse({"detail": "authentication required"}, status_code=401)
            response.headers["HX-Redirect"] = login_url
            return response
        return RedirectResponse(url=login_url, status_code=303)


app.add_middleware(RequireLoginMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SESSION_SECRET,
    max_age=APP_SESSION_MAX_AGE,
    same_site="lax",
    https_only=APP_SECURE_COOKIES,
)


def login_panel(error: str | None = None, next_url: str = "/"):
    return Titled(
        APP_TITLE,
        Div(
            H2("Sign In"),
            P("Enter the shared password to access the archive submission app."),
            P(error, style="color: #b42318; font-weight: 600;") if error else "",
            Form(method="post", action="/login")(
                Label(
                    "Password",
                    Input(type="password", name="password", autocomplete="current-password", required=True),
                ),
                Input(type="hidden", name="next", value=next_url or "/"),
                Div(
                    Button("Sign in", type="submit"),
                    style="margin-top: 0.75rem;",
                ),
            ),
            cls="container",
            style="max-width: 560px;",
        ),
    )


@rt("/login")
async def login(
    request: Request,
    password: str | None = None,
    next: str | None = "/",
):
    if not APP_PASSWORD:
        return RedirectResponse(url="/", status_code=303)

    next_url = next or "/"
    if not next_url.startswith("/"):
        next_url = "/"

    if request.method == "GET":
        if request.session.get("authenticated"):
            return RedirectResponse(url=next_url, status_code=303)
        return login_panel(next_url=next_url)

    if password and hmac.compare_digest(password, APP_PASSWORD):
        request.session["authenticated"] = True
        return RedirectResponse(url=next_url, status_code=303)

    return login_panel(error="Incorrect password.", next_url=next_url)


@rt("/logout")
def logout(request: Request):
    request.session.clear()
    if "hx-request" in request.headers:
        response = JSONResponse({"detail": "logged out"}, status_code=200)
        response.headers["HX-Redirect"] = "/login"
        return response
    return RedirectResponse(url="/login", status_code=303)

def submissions_table(rows: list[sqlite3.Row], sort_by: str, sort_dir: str):
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)

    def sortable_header(label: str, key: str, width: str | None = None):
        next_dir = "desc" if (safe_sort_by == key and safe_sort_dir == "asc") else "asc"
        indicator = ""
        if safe_sort_by == key:
            indicator = " ▲" if safe_sort_dir == "asc" else " ▼"
        attrs = {
            "hx_get": table_partial.to(sort_by=key, sort_dir=next_dir),
            "hx_target": "#table-panel",
            "hx_swap": "outerHTML",
            "hx_push_url": build_index_url(key, next_dir),
            "style": "cursor: pointer; user-select: none;",
        }
        if width:
            attrs["width"] = width
        return Th(f"{label}{indicator}", **attrs)

    return Div(
        H2("Previous submissions"),
        Div(
            Table(
                Thead(
                    Tr(
                        sortable_header("Submitted By", "submitted_by", width="10%"),
                        sortable_header("Title", "title"),
                        sortable_header("Description", "description"),
                        sortable_header("Date Submitted", "created_at", width="15%"),
                        # Th("Approximate Date"),
                    )
                ),
                Tbody(
                    *[
                        Tr(
                            Td(row["submitted_by"]),
                            Td(clip_text(row["title"])),
                            Td(clip_text(row["description"])),
                            Td(format_submitted_time(row["created_at"])),
                            # Td(row["approximate_date"]),
                            hx_get=form_partial.to(image_id=row["id"], sort_by=safe_sort_by, sort_dir=safe_sort_dir),
                            hx_target="#form-panel",
                            hx_swap="outerHTML",
                            hx_push_url=build_index_url(safe_sort_by, safe_sort_dir, image_id=row["id"]),
                            style="cursor: pointer;",
                        )
                        for row in rows
                    ]
                ),
            ),
            cls="table-wrap",
        ),
    )


def notice_panel(message: str | None, *, oob: bool = False):
    attrs = {"id": "notice-panel"}
    if oob:
        attrs["hx-swap-oob"] = "true"
    return Div(P(message) if message else "", **attrs)


def form_panel(
    edit_row: sqlite3.Row | None,
    image_src: str,
    image_exists: bool,
    sort_by: str,
    sort_dir: str,
    *,
    oob: bool = False,
):
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)
    is_edit = edit_row is not None
    selected_submitter = normalize_submitter_name(edit_row["submitted_by"] if edit_row else "")
    attrs = {"id": "form-panel"}
    if oob:
        attrs["hx-swap-oob"] = "true"

    form = Form(
        id="submission-form",
        method="post",
        action=update if is_edit else submit,
        enctype="multipart/form-data",
        hx_post=update if is_edit else submit,
        hx_target="#form-panel",
        hx_swap="outerHTML",
        hx_encoding="multipart/form-data",
    )(
        Fieldset(
            Div(
                Strong("Drag and drop a photo here (or click to choose a file)"),
                Input(
                    type="file",
                    id="photo",
                    name="photo",
                    accept="image/*",
                    required=not is_edit,
                ),
                Img(
                    id="preview",
                    alt="Photo preview",
                    src=image_src or None,
                    style="display: block;" if image_src else None,
                ),
                id="dropzone",
            ),
            Label(
                "Title (A SHORT meaningful name for the image, e.g THM Golden Wedding Anniversary)",
                   Input(name="title", type="text", value=(edit_row["title"] if edit_row else "")),
                   id="title-label",),
            Label(
                "Description (e.g., people, context, and an APPROXIMATE DATE of the image)",
                Textarea(edit_row["description"] if edit_row else "", name="description", rows=8),
            ),
            Label(
                "Submitted by (ask David to add you if you are not in list!)",
                Select(
                    *[
                        Option(name, value=name, selected=(name == selected_submitter))
                        for name in SUBMITTER_NAMES
                    ],
                    name="submitted_by",
                    required=True,
                ),
                id="submitted-by-label",
            ),
        ),
        Input(type="hidden", name="image_id", value=str(edit_row["id"]) if edit_row else ""),
        Div(
            Button("Save changes" if is_edit else "Submit", type="submit"),
            Button(
                "Cancel",
                type="button",
                hx_get=form_partial.to(sort_by=safe_sort_by, sort_dir=safe_sort_dir),
                hx_target="#form-panel",
                hx_swap="outerHTML",
                hx_push_url=build_index_url(safe_sort_by, safe_sort_dir),
            )
            if is_edit
            else "",
            Button(
                "Log out",
                id="logout-button",
                type="submit",
                formaction="/logout",
                formmethod="post",
                hx_post=logout,
                hx_swap="none",
            ) if APP_PASSWORD else "",
            style="display: flex; gap: 0.75rem; align-items: center;",
        ),
        Input(type="hidden", name="sort_by", value=safe_sort_by),
        Input(type="hidden", name="sort_dir", value=safe_sort_dir),
    )

    missing_notice = (
        "Image file missing; IPTC update will be skipped." if is_edit and not image_exists else None
    )
    return Div(form, notice_panel(missing_notice), **attrs)


def table_panel(rows: list[sqlite3.Row], sort_by: str, sort_dir: str, *, oob: bool = False):
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)
    attrs = {"id": "table-panel"}
    if oob:
        attrs["hx-swap-oob"] = "true"
    return Div(
        submissions_table(rows, safe_sort_by, safe_sort_dir),
        Div(
            Button(
                "Rebuild Database",
                type="button",
                hx_post=rebuild_db,
                hx_vals=f'{{"sort_by":"{safe_sort_by}","sort_dir":"{safe_sort_dir}"}}',
                hx_confirm="Are you sure you want to rebuild the database? This will clear and repopulate all submission rows.",
                hx_target="#table-panel",
                hx_swap="outerHTML",
                style="margin-top: 1rem;"
            ),
            style="display: flex; justify-content: flex-end;"
        ),
        **attrs
    )
@rt("/rebuild-db")
async def rebuild_db(
    request: Request,
    sort_by: str | None = None,
    sort_dir: str | None = None,
):
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)
    # Scan S3 bucket and repopulate DB
    s3 = s3_client()
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET_NAME):
        for obj in page.get("Contents", []):
            objects.append(obj["Key"])

    rows = []
    for key in objects:
        try:
            head = s3.head_object(Bucket=S3_BUCKET_NAME, Key=key)
            meta = head.get("Metadata", {})
            submitted_by = decode_escaped_newlines(meta.get("submitted_by", ""))
            title = decode_escaped_newlines(meta.get("title", ""))
            description = decode_escaped_newlines(meta.get("description", ""))
            created_at = head.get("LastModified")
            if created_at:
                created_at = created_at.astimezone(timezone.utc).isoformat()
            else:
                created_at = datetime.now(timezone.utc).isoformat()
            rows.append((key, title, description, submitted_by, created_at))
        except Exception as e:
            continue

    # Clear and repopulate DB
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM submissions")
        conn.executemany(
            "INSERT INTO submissions (image_path, title, description, submitted_by, created_at) VALUES (?, ?, ?, ?, ?)",
            rows
        )

    # Return updated table
    return table_panel(db_rows(safe_sort_by, safe_sort_dir), safe_sort_by, safe_sort_dir, oob=True)


@rt
def index(
    image_id: int | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
):
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)
    rows = db_rows(safe_sort_by, safe_sort_dir)
    edit_row = db_row_by_id(image_id) if image_id else None
    image_exists = False
    image_src = ""
    if edit_row:
        image_exists = bool(edit_row["image_path"])
        if image_exists:
            image_src = image_by_id.to(image_id=edit_row["id"], v=edit_row["image_path"])
    return Titled(
        APP_TITLE,
        Div(
            form_panel(edit_row, image_src, image_exists, safe_sort_by, safe_sort_dir),
            table_panel(rows, safe_sort_by, safe_sort_dir),
            cls="container",
            hx_boost="true",
        ),
    )


@rt("/edit")
def edit(image_id: int):
    return RedirectResponse(url=f"/?image_id={image_id}", status_code=302)


@rt("/partials/form")
def form_partial(
    image_id: int | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
):
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)
    edit_row = db_row_by_id(image_id) if image_id else None
    image_exists = False
    image_src = ""
    if edit_row:
        image_exists = bool(edit_row["image_path"])
        if image_exists:
            image_src = image_by_id.to(image_id=edit_row["id"], v=edit_row["image_path"])
    return form_panel(edit_row, image_src, image_exists, safe_sort_by, safe_sort_dir)


@rt("/partials/table")
def table_partial(sort_by: str | None = None, sort_dir: str | None = None):
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)
    return table_panel(db_rows(safe_sort_by, safe_sort_dir), safe_sort_by, safe_sort_dir)


@rt("/extract-metadata")
async def extract_metadata(photo: UploadFile):
    filebuffer = await photo.read()
    await photo.close()
    if not filebuffer:
        return JSONResponse({"title": "", "description": "", "submitted_by": ""})

    temp_path = temp_file_from_bytes(filebuffer, photo.filename or "upload")
    try:
        payload = extract_xmp_form_fields(temp_path)
        print("Extracted metadata from uploaded image:", payload)
    except Exception:
        payload = {"title": "", "description": "", "submitted_by": ""}
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
    return JSONResponse(payload)


@rt
async def submit(
    request: Request,
    photo: UploadFile,
    title: str | None = None,
    description: str | None = None,
    submitted_by: str | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
):
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)
    filebuffer = await photo.read()
    await photo.close()
    submitted_by = normalize_submitter_name(submitted_by)
    save_submission(photo.filename or "upload", filebuffer, title, description, submitted_by)
    if "hx-request" not in request.headers:
        return RedirectResponse(url=build_index_url(safe_sort_by, safe_sort_dir), status_code=303)
    return Div(
        form_panel(None, "", False, safe_sort_by, safe_sort_dir, oob=True),
        table_panel(db_rows(safe_sort_by, safe_sort_dir), safe_sort_by, safe_sort_dir, oob=True),
    )


@rt
async def update(
    request: Request,
    image_id: int,
    photo: UploadFile | None = None,
    title: str | None = None,
    description: str | None = None,
    submitted_by: str | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
):
    safe_sort_by, safe_sort_dir = normalize_sort(sort_by, sort_dir)
    photo_filename = None
    photo_buffer = None
    submitted_by = normalize_submitter_name(submitted_by)
    if photo and photo.filename:
        photo_buffer = await photo.read()
        await photo.close()
        if photo_buffer:
            photo_filename = photo.filename or "upload"
        else:
            photo_buffer = None
    update_submission(
        image_id,
        title,
        description,
        submitted_by,
        photo_filename,
        photo_buffer,
    )
    if "hx-request" not in request.headers:
        return RedirectResponse(url=build_index_url(safe_sort_by, safe_sort_dir), status_code=303)
    return Div(
        form_panel(None, "", False, safe_sort_by, safe_sort_dir, oob=True),
        table_panel(db_rows(safe_sort_by, safe_sort_dir), safe_sort_by, safe_sort_dir, oob=True),
    )


@rt("/image/{image_id}")
def image_by_id(image_id: int, v: str | None = None):
    row = db_row_by_id(image_id)
    if not row:
        return RedirectResponse(url="/", status_code=302)
    image_key = row["image_path"]
    if not image_key:
        return RedirectResponse(url="/", status_code=302)
    try:
        response = RedirectResponse(url=presigned_s3_url(image_key), status_code=302)
        # Force reload to avoid browsers reusing a stale redirect target for /image/{id}
        response.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except Exception:
        return RedirectResponse(url="/", status_code=302)


serve()
