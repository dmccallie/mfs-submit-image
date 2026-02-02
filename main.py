from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import sqlite3
from iptcinfo3 import IPTCInfo
from starlette.datastructures import UploadFile
from starlette.responses import FileResponse, RedirectResponse

from fasthtml.common import *

APP_TITLE = "Family Archive Photo Submission"
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


def save_submission(
    filename: str,
    filebuffer: bytes,
    title: str | None,
    description: str | None,
    submitted_by: str | None,
    approximate_date: str | None,
) -> None:
    suffix = Path(filename or "upload").suffix
    filename = f"{uuid4().hex}{suffix}"
    image_path = IMAGE_DIR / filename
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
    # info.save()
    info.save_as(str(image_path), {'overwrite': True})

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
) -> None:
    row = db_row_by_id(image_id)
    if not row:
        return

    image_path = Path(row["image_path"])
    if image_path.exists():
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
            SET title = ?, description = ?, submitted_by = ?, approximate_date = ?
            WHERE id = ?
            """,
            (
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
        Script(
            """
            const setupDropzone = () => {
              const dropzone = document.getElementById('dropzone');
              const fileInput = document.getElementById('photo');
              const preview = document.getElementById('preview');
              if (!dropzone || !fileInput || !preview) return;

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

            window.addEventListener('DOMContentLoaded', setupDropzone);
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
                            onclick=f"window.location='{edit.to(image_id=row['id'])}'",
                            style="cursor: pointer;",
                        )
                        for row in rows
                    ]
                ),
            ),
            cls="table-wrap",
        ),
    )


@rt
def index(image_id: int | None = None):
    rows = db_rows()
    edit_row = db_row_by_id(image_id) if image_id else None
    is_edit = edit_row is not None
    image_exists = False
    image_src = ""
    if edit_row:
        image_path = Path(edit_row["image_path"])
        image_exists = image_path.exists()
        if image_exists:
            image_src = image_by_id.to(image_id=edit_row["id"])

    form = Form(method="post", action=update if is_edit else submit)(
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
            Button("Cancel", type="button", onclick="window.location='/'") if is_edit else "",
            style="display: flex; gap: 0.75rem; align-items: center;",
        ),
    )
    missing_notice = (
        P("Image file missing; IPTC update will be skipped.") if is_edit and not image_exists else ""
    )
    return Titled(APP_TITLE, form, missing_notice, submissions_table(rows))


@rt("/edit")
def edit(image_id: int):
    return RedirectResponse(url=f"/?image_id={image_id}", status_code=302)


@rt
async def submit(
    photo: UploadFile,
    title: str | None = None,
    description: str | None = None,
    approximate_date: str | None = None,
    submitted_by: str | None = None,
):
    filebuffer = await photo.read()
    await photo.close()
    save_submission(photo.filename or "upload", filebuffer, title, description, submitted_by, approximate_date)
    return RedirectResponse(url="/", status_code=303)


@rt
async def update(
    image_id: int,
    title: str | None = None,
    description: str | None = None,
    approximate_date: str | None = None,
    submitted_by: str | None = None,
):
    update_submission(image_id, title, description, submitted_by, approximate_date)
    return RedirectResponse(url="/", status_code=303)


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
