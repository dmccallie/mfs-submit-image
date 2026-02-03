from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import sqlite3
from iptcinfo3 import IPTCInfo
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse

from fasthtml.common import *

APP_TITLE = "McCallie Family Archive Photo Submission"
DATA_DIR = Path("data")
IMAGE_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "submissions.db"


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
                approximate_date TEXT,
                created_at TEXT NOT NULL
            )
            """
        )


def db_rows() -> list[sqlite3.Row]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, image_path, title, description, submitted_by, approximate_date, created_at
        FROM submissions
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()
    return rows


def db_row_by_id(submission_id: int) -> sqlite3.Row | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT id, image_path, title, description, submitted_by, approximate_date, created_at
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


def write_image_file(
    filename: str,
    filebuffer: bytes,
    title: str | None,
    description: str | None,
    submitted_by: str | None,
) -> Path:
    suffix = Path(filename or "upload").suffix
    stored_name = f"{uuid4().hex}{suffix}"
    image_path = IMAGE_DIR / stored_name
    with open(image_path, "wb") as fh:
        fh.write(filebuffer)
        fh.flush()
        os.fsync(fh.fileno())

    info = IPTCInfo(str(image_path), force=True)
    if title:
        info["object name"] = title
    if description:
        info["caption/abstract"] = description
    if submitted_by:
        info["source"] = submitted_by
    info.save_as(str(image_path), {"overwrite": True})
    return image_path


def save_submission(
    filename: str,
    filebuffer: bytes,
    title: str | None,
    description: str | None,
    submitted_by: str | None,
    approximate_date: str | None,
) -> None:
    image_path = write_image_file(filename, filebuffer, title, description, submitted_by)

    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO submissions (
                image_path, title, description, submitted_by, approximate_date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(image_path),
                title or "",
                description or "",
                submitted_by or "",
                approximate_date or "",
                created_at,
            ),
        )


def update_submission(
    image_id: int,
    title: str | None,
    description: str | None,
    submitted_by: str | None,
    approximate_date: str | None,
    photo_filename: str | None = None,
    photo_buffer: bytes | None = None,
) -> None:
    row = db_row_by_id(image_id)
    if not row:
        return

    image_path = Path(row["image_path"])
    new_image_path = None
    if photo_filename and photo_buffer:
        new_image_path = write_image_file(photo_filename, photo_buffer, title, description, submitted_by)
    elif image_path.exists():
        info = IPTCInfo(str(image_path), force=True)
        if title is not None:
            info["object name"] = title
        if description is not None:
            info["caption/abstract"] = description
        if submitted_by is not None:
            info["source"] = submitted_by
        info.save_as(str(image_path), {"overwrite": True})

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE submissions
            SET image_path = ?, title = ?, description = ?, submitted_by = ?, approximate_date = ?
            WHERE id = ?
            """,
            (
                str(new_image_path) if new_image_path else str(image_path),
                title or "",
                description or "",
                submitted_by or "",
                approximate_date or "",
                image_id,
            ),
        )


init_db()

app, rt = fast_app(
        hdrs=(
                Style(
                        """
                        #dropzone {
                                border: 2px dashed var(--pico-muted-border-color);
                                border-radius: 10px;
                                padding: 1.5rem;
                                text-align: center;
                                background: var(--pico-card-background-color);
                        }
                        #dropzone.dragover {
                                border-color: var(--pico-primary);
                                background: var(--pico-muted-border-color);
                        }
                        #preview {
                                max-width: 100%;
                                max-height: 360px;
                                margin-top: 1rem;
                                display: none;
                        }
                        #photo {
                                display: none;
                        }
                        .table-wrap {
                                max-height: 320px;
                                overflow-y: auto;
                                margin-top: 2rem;
                        }
                        table {
                                width: 100%;
                        }
                        """
                ),
                Script(src="https://unpkg.com/htmx.org@1.9.12", defer=True),
                Script(
                        """
                        const setupDropzone = (root = document) => {
                            const dropzone = root.querySelector('#dropzone');
                            const fileInput = root.querySelector('#photo');
                            const preview = root.querySelector('#preview');
                            if (!dropzone || !fileInput || !preview) return;
                            if (dropzone.dataset.initialized === 'true') return;
                            dropzone.dataset.initialized = 'true';

                            const showPreview = (file) => {
                                if (!file) return;
                                const url = URL.createObjectURL(file);
                                preview.src = url;
                                preview.style.display = 'block';
                            };

                            dropzone.addEventListener('dragover', (evt) => {
                                evt.preventDefault();
                                dropzone.classList.add('dragover');
                            });

                            dropzone.addEventListener('dragleave', () => {
                                dropzone.classList.remove('dragover');
                            });

                            dropzone.addEventListener('drop', (evt) => {
                                evt.preventDefault();
                                dropzone.classList.remove('dragover');
                                const [file] = evt.dataTransfer.files;
                                if (file) {
                                    const dt = new DataTransfer();
                                    dt.items.add(file);
                                    fileInput.files = dt.files;
                                    showPreview(file);
                                }
                            });

                            dropzone.addEventListener('click', () => {
                                fileInput.click();
                            });

                            fileInput.addEventListener('change', (evt) => {
                                const [file] = evt.target.files;
                                showPreview(file);
                            });
                        };

                        window.addEventListener('DOMContentLoaded', () => setupDropzone(document));
                        if (window.htmx) {
                            htmx.onLoad((elt) => {
                                setupDropzone(elt);
                            });
                            document.body.addEventListener('htmx:historyRestore', () => {
                                setupDropzone(document);
                            });
                        }
                        """
                ),
        )
)

def submissions_table(rows: list[sqlite3.Row]):
    return Div(
        H2("Previous submissions"),
        Div(
            Table(
                Thead(
                    Tr(
                        Th("Submitted"),
                        Th("Title"),
                        Th("Description"),
                        Th("Submitted By"),
                        Th("Approximate Date"),
                    )
                ),
                Tbody(
                    *[
                        Tr(
                            Td(format_submitted_time(row["created_at"])),
                            Td(clip_text(row["title"])),
                            Td(clip_text(row["description"])),
                            Td(row["submitted_by"]),
                            Td(row["approximate_date"]),
                            hx_get=form_partial.to(image_id=row["id"]),
                            hx_target="#form-panel",
                            hx_swap="outerHTML",
                            hx_push_url=f"/?image_id={row['id']}",
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
    *,
    oob: bool = False,
):
    is_edit = edit_row is not None
    attrs = {"id": "form-panel"}
    if oob:
        attrs["hx-swap-oob"] = "true"

    form = Form(
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
                Strong("Drag and drop a photo here"),
                P("or click to choose a file"),
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
            Label("Title", Input(name="title", type="text", value=(edit_row["title"] if edit_row else ""))),
            Label(
                "Description",
                Textarea(edit_row["description"] if edit_row else "", name="description", rows=8),
            ),
            Label(
                "Approximate date",
                Input(name="approximate_date", type="text", value=(edit_row["approximate_date"] if edit_row else "")),
            ),
            Label(
                "Submitted by",
                Input(name="submitted_by", type="text", value=(edit_row["submitted_by"] if edit_row else "")),
            ),
        ),
        Input(type="hidden", name="image_id", value=str(edit_row["id"]) if edit_row else ""),
        Div(
            Button("Save changes" if is_edit else "Submit", type="submit"),
            Button(
                "Cancel",
                type="button",
                hx_get=form_partial.to(),
                hx_target="#form-panel",
                hx_swap="outerHTML",
                hx_push_url="/",
            )
            if is_edit
            else "",
            style="display: flex; gap: 0.75rem; align-items: center;",
        ),
    )

    missing_notice = (
        "Image file missing; IPTC update will be skipped." if is_edit and not image_exists else None
    )
    return Div(form, notice_panel(missing_notice), **attrs)


def table_panel(rows: list[sqlite3.Row], *, oob: bool = False):
    attrs = {"id": "table-panel"}
    if oob:
        attrs["hx-swap-oob"] = "true"
    return Div(submissions_table(rows), **attrs)


@rt
def index(image_id: int | None = None):
    rows = db_rows()
    edit_row = db_row_by_id(image_id) if image_id else None
    image_exists = False
    image_src = ""
    if edit_row:
        image_path = Path(edit_row["image_path"])
        image_exists = image_path.exists()
        if image_exists:
            image_src = image_by_id.to(image_id=edit_row["id"])
    return Titled(
        APP_TITLE,
        Div(
            form_panel(edit_row, image_src, image_exists),
            table_panel(rows),
            cls="container",
            hx_boost="true",
        ),
    )


@rt("/edit")
def edit(image_id: int):
    return RedirectResponse(url=f"/?image_id={image_id}", status_code=302)


@rt("/partials/form")
def form_partial(image_id: int | None = None):
    edit_row = db_row_by_id(image_id) if image_id else None
    image_exists = False
    image_src = ""
    if edit_row:
        image_path = Path(edit_row["image_path"])
        image_exists = image_path.exists()
        if image_exists:
            image_src = image_by_id.to(image_id=edit_row["id"])
    return form_panel(edit_row, image_src, image_exists)


@rt("/partials/table")
def table_partial():
    return table_panel(db_rows())


@rt
async def submit(
    request: Request,
    photo: UploadFile,
    title: str | None = None,
    description: str | None = None,
    approximate_date: str | None = None,
    submitted_by: str | None = None,
):
    filebuffer = await photo.read()
    await photo.close()
    save_submission(photo.filename or "upload", filebuffer, title, description, submitted_by, approximate_date)
    if "hx-request" not in request.headers:
        return RedirectResponse(url="/", status_code=303)
    return Div(
        form_panel(None, "", False, oob=True),
        table_panel(db_rows(), oob=True),
    )


@rt
async def update(
    request: Request,
    image_id: int,
    photo: UploadFile | None = None,
    title: str | None = None,
    description: str | None = None,
    approximate_date: str | None = None,
    submitted_by: str | None = None,
):
    photo_filename = None
    photo_buffer = None
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
        approximate_date,
        photo_filename,
        photo_buffer,
    )
    if "hx-request" not in request.headers:
        return RedirectResponse(url="/", status_code=303)
    return Div(
        form_panel(None, "", False, oob=True),
        table_panel(db_rows(), oob=True),
    )


@rt("/image/{image_id}")
def image_by_id(image_id: int):
    row = db_row_by_id(image_id)
    if not row:
        return RedirectResponse(url="/", status_code=302)
    image_path = Path(row["image_path"])
    if not image_path.exists():
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(image_path)


serve()
