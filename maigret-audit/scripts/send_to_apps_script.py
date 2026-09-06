import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import requests


ALLOWED_MIME_TYPES = {
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".html": "text/html",
}

MAX_FILE_SIZE = 4 * 1024 * 1024
MAX_TOTAL_SIZE = 10 * 1024 * 1024


def validate_job_id(job_id: str) -> None:
    allowed = set("abcdef0123456789-")

    if not 20 <= len(job_id) <= 50:
        raise ValueError("Panjang job ID tidak valid.")

    if any(character.lower() not in allowed for character in job_id):
        raise ValueError("Format job ID tidak valid.")


def encode_file(path: Path) -> dict:
    raw_content = path.read_bytes()

    if not raw_content:
        raise ValueError(
            f"File kosong tidak dikirim: {path.name}"
        )

    if len(raw_content) > MAX_FILE_SIZE:
        raise ValueError(
            f"File melebihi batas 4 MB: {path.name}"
        )

    extension = path.suffix.lower()
    mime_type = ALLOWED_MIME_TYPES.get(extension)

    if not mime_type:
        raise ValueError(
            f"Ekstensi tidak diperbolehkan: {path.name}"
        )

    checksum = hashlib.sha256(raw_content).hexdigest()

    encoded_content = base64.b64encode(
        raw_content
    ).decode("ascii")

    return {
        "name": path.name,
        "mimeType": mime_type,
        "encoding": "base64",
        "size": len(raw_content),
        "sha256": checksum,
        "content": encoded_content,
    }


def collect_files(report_folder: Path) -> listselected_files = []

    for path in sorted(report_folder.iterdir()):
        if not path.is_file():
            continue

        if path.suffix.lower() in ALLOWED_MIME_TYPES:
            selected_files.append(path)

    if not selected_files:
        raise RuntimeError(
            "Tidak ada laporan TXT, JSON, CSV, atau HTML."
        )

    total_size = sum(
        path.stat().st_size
        for path in selected_files
    )

    if total_size > MAX_TOTAL_SIZE:
        raise RuntimeError(
            "Total ukuran laporan melebihi 10 MB."
        )

    return selected_files


def send_payload(
    endpoint: str,
    payload: dict,
) -> dict:
    response = requests.post(
        endpoint,
        headers={
            "Content-Type": "text/plain;charset=utf-8",
            "User-Agent": "Maigret-GitHub-Actions/1.0",
        },
        data=json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8"),
        timeout=120,
        allow_redirects=True,
    )

    response.raise_for_status()

    try:
        result = response.json()
    except requests.JSONDecodeError as error:
        preview = response.text[:500]

        raise RuntimeError(
            "Apps Script tidak mengembalikan JSON. "
            f"Respons awal: {preview}"
        ) from error

    if not result.get("ok"):
        raise RuntimeError(
            result.get(
                "error",
                "Apps Script menolak unggahan.",
            )
        )

    return result


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Penggunaan: python "
            "scripts/send_to_apps_script.py "
            "<folder-laporan>"
        )

    report_folder = Path(sys.argv[1]).resolve()

    if not report_folder.exists():
        raise FileNotFoundError(
            f"Folder tidak ditemukan: {report_folder}"
        )

    if not report_folder.is_dir():
        raise NotADirectoryError(
            f"Path bukan folder: {report_folder}"
        )

    endpoint = os.environ.get(
        "APPS_SCRIPT_WEBHOOK_URL",
        "",
    ).strip()

    callback_secret = os.environ.get(
        "CALLBACK_SECRET",
        "",
    ).strip()

    job_id = os.environ.get(
        "JOB_ID",
        "",
    ).strip()

    if not endpoint:
        raise RuntimeError(
            "APPS_SCRIPT_WEBHOOK_URL belum tersedia."
        )

    if not endpoint.startswith("https://"):
        raise RuntimeError(
            "Endpoint Apps Script harus menggunakan HTTPS."
        )

    if not callback_secret:
        raise RuntimeError(
            "CALLBACK_SECRET belum tersedia."
        )

    validate_job_id(job_id)

    report_files = collect_files(report_folder)

    payload = {
        "action": "upload",
        "jobId": job_id,
        "callbackSecret": callback_secret,
        "files": [
            encode_file(path)
            for path in report_files
        ],
    }

    result = send_payload(
        endpoint,
        payload,
    )

    safe_result = {
        "ok": result.get("ok"),
        "jobId": result.get("jobId"),
        "status": result.get("status"),
        "files": result.get("files", []),
  