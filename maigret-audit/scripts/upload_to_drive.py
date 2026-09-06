import json
import os
import sys
from pathlib import Path

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]


def load_service_account():
    raw = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    info = json.loads(raw)

    return service_account.Credentials.from_service_account_info(
        info,
        scopes=SCOPES,
    )


def upload_file(service, path, parent_id):
    metadata = {
        "name": path.name,
        "parents": [parent_id],
    }

    media = MediaFileUpload(
        str(path),
        resumable=True,
    )

    created = (
        service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id,name,mimeType,webViewLink,webContentLink",
        )
        .execute()
    )

    return created


def create_folder(service, name, parent_id):
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }

    return (
        service.files()
        .create(
            body=metadata,
            fields="id,name,webViewLink",
        )
        .execute()
    )


def choose_file_by_suffix(uploaded, suffix):
    for item in uploaded:
        if item["name"].lower().endswith(suffix):
            return item
    return None


def callback(payload):
    callback_url = os.environ["APPS_SCRIPT_CALLBACK_URL"]
    callback_secret = os.environ["CALLBACK_SECRET"]

    response = requests.post(
        callback_url,
        json=payload,
        headers={
            "X-Callback-Secret": callback_secret,
        },
        timeout=30,
    )

    response.raise_for_status()


def main():
    report_dir = Path(sys.argv[1]).resolve()

    if not report_dir.is_dir():
        raise RuntimeError("Folder laporan tidak ditemukan.")

    job_id = report_dir.name
    parent_id = os.environ["GOOGLE_DRIVE_FOLDER_ID"]

    credentials = load_service_account()
    service = build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )

    job_folder = create_folder(
        service,
        job_id,
        parent_id,
    )

    uploaded = []

    for path in sorted(report_dir.iterdir()):
        if path.is_file():
            uploaded.append(
                upload_file(
                    service,
                    path,
                    job_folder["id"],
                )
            )

    html_file = choose_file_by_suffix(uploaded, ".html")
    txt_file = choose_file_by_suffix(uploaded, ".txt")
    json_file = choose_file_by_suffix(uploaded, ".json")
    csv_file = choose_file_by_suffix(uploaded, ".csv")

    payload = {
        "action": "complete",
        "jobId": job_id,
        "status": "completed",
        "folderId": job_folder["id"],
        "folderUrl": job_folder.get("webViewLink"),
        "viewUrl": (
            html_file.get("webViewLink")
            if html_file else None
        ),
        "txtUrl": (
            txt_file.get("webViewLink")
            if txt_file else None
        ),
        "jsonUrl": (
            json_file.get("webViewLink")
            if json_file else None
        ),
        "csvUrl": (
            csv_file.get("webViewLink")
            if csv_file else None
        ),
    }

    callback(payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()