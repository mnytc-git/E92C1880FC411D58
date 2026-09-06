"""
Mengirim laporan Maigret dari GitHub Actions
ke Google Apps Script Web App.
"""

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
REQUEST_TIMEOUT_SECONDS = 120


def validate_job_id(job_id):
    """Memvalidasi format job ID."""

    allowed_characters = set(
        "abcdef0123456789-"
    )

    if not job_id:
        raise ValueError(
            "JOB_ID belum tersedia."
        )

    if len(job_id) not in range(20, 51):
        raise ValueError(
            "Panjang JOB_ID harus antara "
            "20 sampai 50 karakter."
        )

    for character in job_id:
        if (
            character.lower()
            not in allowed_characters
        ):
            raise ValueError(
                "Format JOB_ID tidak valid."
            )


def validate_endpoint(endpoint):
    """Memvalidasi URL Apps Script."""

    if not endpoint:
        raise ValueError(
            "APPS_SCRIPT_WEBHOOK_URL "
            "belum tersedia."
        )

    if not endpoint.startswith(
        "https://"
    ):
        raise ValueError(
            "Endpoint Apps Script harus "
            "menggunakan HTTPS."
        )

    if "/exec" not in endpoint:
        raise ValueError(
            "Gunakan URL deployment "
            "Apps Script yang berakhir /exec."
        )


def validate_file_name(file_name):
    """Memvalidasi nama file."""

    if not file_name:
        raise ValueError(
            "Nama file tidak boleh kosong."
        )

    if file_name in {".", ".."}:
        raise ValueError(
            "Nama file tidak valid."
        )

    if "/" in file_name:
        raise ValueError(
            "Nama file mengandung pemisah path."
        )

    if "\\" in file_name:
        raise ValueError(
            "Nama file mengandung pemisah path."
        )

    if Path(file_name).name != file_name:
        raise ValueError(
            "Nama file tidak aman: "
            + file_name
        )


def calculate_sha256(raw_content):
    """Menghasilkan checksum SHA-256."""

    return hashlib.sha256(
        raw_content
    ).hexdigest()


def encode_file(path):
    """Mengubah satu file menjadi Base64."""

    validate_file_name(
        path.name
    )

    extension = path.suffix.lower()

    mime_type = ALLOWED_MIME_TYPES.get(
        extension
    )

    if not mime_type:
        raise ValueError(
            "Ekstensi tidak diperbolehkan: "
            + path.name
        )

    raw_content = path.read_bytes()

    if not raw_content:
        raise ValueError(
            "File kosong tidak dikirim: "
            + path.name
        )

    file_size = len(
        raw_content
    )

    if file_size > MAX_FILE_SIZE:
        raise ValueError(
            "File melebihi batas 4 MB: "
            + path.name
        )

    checksum = calculate_sha256(
        raw_content
    )

    encoded_content = base64.b64encode(
        raw_content
    ).decode("ascii")

    return {
        "name": path.name,
        "mimeType": mime_type,
        "encoding": "base64",
        "size": file_size,
        "sha256": checksum,
        "content": encoded_content,
    }


def collect_files(report_folder):
    """
    Mengambil laporan TXT, JSON, CSV,
    dan HTML dari folder hasil.
    """

    selected_files = []

    sorted_files = sorted(
        report_folder.iterdir(),
        key=lambda item: item.name.lower(),
    )

    for path in sorted_files:
        if not path.is_file():
            continue

        if path.is_symlink():
            print(
                "Melewati symbolic link: "
                + path.name,
                file=sys.stderr,
            )
            continue

        extension = path.suffix.lower()

        if extension not in ALLOWED_MIME_TYPES:
            print(
                "Melewati file tidak didukung: "
                + path.name,
                file=sys.stderr,
            )
            continue

        selected_files.append(
            path
        )

    if not selected_files:
        raise RuntimeError(
            "Tidak ada laporan TXT, JSON, "
            "CSV, atau HTML."
        )

    total_size = sum(
        path.stat().st_size
        for path in selected_files
    )

    if total_size > MAX_TOTAL_SIZE:
        raise RuntimeError(
            "Total laporan melebihi 10 MB."
        )

    return selected_files


def create_payload(
    job_id,
    callback_secret,
    report_files,
):
    """Membentuk payload untuk Apps Script."""

    encoded_files = []

    for path in report_files:
        encoded_files.append(
            encode_file(path)
        )

    return {
        "action": "upload",
        "jobId": job_id,
        "callbackSecret": callback_secret,
        "githubRunId": os.environ.get(
            "GITHUB_RUN_ID",
            "",
        ),
        "githubRunAttempt": os.environ.get(
            "GITHUB_RUN_ATTEMPT",
            "",
        ),
        "repository": os.environ.get(
            "GITHUB_REPOSITORY",
            "",
        ),
        "files": encoded_files,
    }


def parse_response(response):
    """Memvalidasi respons Apps Script."""

    try:
        result = response.json()
    except ValueError as error:
        preview = response.text[:500]

        raise RuntimeError(
            "Apps Script tidak "
            "mengembalikan JSON. "
            "Kode HTTP: "
            + str(response.status_code)
            + ". Respons awal: "
            + preview
        ) from error

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "Format respons Apps Script "
            "tidak valid."
        )

    return result


def send_payload(endpoint, payload):
    """Mengirim laporan ke Apps Script."""

    serialized_payload = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    try:
        response = requests.post(
            endpoint,
            headers={
                "Content-Type": (
                    "text/plain;charset=utf-8"
                ),
                "Accept": "application/json",
                "User-Agent": (
                    "Maigret-GitHub-Actions/1.0"
                ),
            },
            data=serialized_payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=True,
        )

        response.raise_for_status()

    except requests.exceptions.Timeout as error:
        raise RuntimeError(
            "Permintaan ke Apps Script "
            "mengalami timeout."
        ) from error

    except requests.exceptions.ConnectionError as error:
        raise RuntimeError(
            "GitHub Actions tidak dapat "
            "terhubung ke Apps Script."
        ) from error

    except requests.exceptions.HTTPError as error:
        if error.response is not None:
            status_code = str(
                error.response.status_code
            )

            response_preview = (
                error.response.text[:500]
            )
        else:
            status_code = "tidak diketahui"
            response_preview = ""

        raise RuntimeError(
            "Apps Script mengembalikan "
            "kesalahan HTTP. Kode: "
            + status_code
            + ". Respons: "
            + response_preview
        ) from error

    except requests.exceptions.RequestException as error:
        raise RuntimeError(
            "Pengiriman laporan gagal: "
            + str(error)
        ) from error

    result = parse_response(
        response
    )

    if not result.get("ok"):
        error_message = str(
            result.get(
                "error",
                "Apps Script menolak unggahan.",
            )
        )

        raise RuntimeError(
            error_message
        )

    return result


def get_required_environment(name):
    """Membaca environment variable wajib."""

    value = os.environ.get(
        name,
        "",
    ).strip()

    if not value:
        raise RuntimeError(
            "Environment variable "
            + name
            + " belum tersedia."
        )

    return value


def print_file_summary(report_files):
    """Menampilkan ringkasan file."""

    print(
        "File laporan yang akan dikirim:"
    )

    total_size = 0

    for path in report_files:
        file_size = path.stat().st_size
        total_size += file_size

        print(
            "- "
            + path.name
            + ": "
            + str(file_size)
            + " byte"
        )

    print(
        "Total ukuran asli: "
        + str(total_size)
        + " byte"
    )


def main():
    """Titik masuk program."""

    if len(sys.argv) != 2:
        raise SystemExit(
            "Penggunaan: python "
            "maigret-audit/scripts/"
            "send_to_apps_script.py "
            "reports/JOB_ID"
        )

    report_folder = Path(
        sys.argv[1]
    ).resolve()

    if not report_folder.exists():
        raise FileNotFoundError(
            "Folder tidak ditemukan: "
            + str(report_folder)
        )

    if not report_folder.is_dir():
        raise NotADirectoryError(
            "Path bukan folder: "
            + str(report_folder)
        )

    endpoint = get_required_environment(
        "APPS_SCRIPT_WEBHOOK_URL"
    )

    callback_secret = get_required_environment(
        "CALLBACK_SECRET"
    )

    job_id = get_required_environment(
        "JOB_ID"
    )

    validate_endpoint(
        endpoint
    )

    validate_job_id(
        job_id
    )

    report_files = collect_files(
        report_folder
    )

    print(
        "JOB_ID: " + job_id
    )

    print_file_summary(
        report_files
    )

    payload = create_payload(
        job_id,
        callback_secret,
        report_files,
    )

    print(
        "Mengirim laporan ke Apps Script..."
    )

    result = send_payload(
        endpoint,
        payload,
    )

    safe_result = {
        "ok": result.get("ok"),
        "jobId": result.get("jobId"),
        "status": result.get("status"),
        "files": result.get(
            "files",
            [],
        ),
        "duplicate": result.get(
            "duplicate",
            False,
        ),
    }

    print(
        "Apps Script menerima laporan."
    )

    print(
        json.dumps(
            safe_result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
