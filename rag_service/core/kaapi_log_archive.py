"""Copy a Kaapi Webhook Log's request and callback bodies to GCS as .txt files.

The request (submission) body goes to   kaapi_logs/kaapi_logs_request_*.txt
The callback (webhook) body goes to     kaapi_logs/kaapi_logs_response_*.txt
in the assignment_submission_tap bucket. Objects are stored with
`Content-Disposition: attachment`, so opening the saved
https://storage.cloud.google.com/... URL (as a signed-in Google user with read access)
downloads the file instead of rendering it in the browser.

The upload runs as a background job keyed by log name, so neither the Kaapi submit nor
the webhook response waits on GCS, and a GCS failure never affects grading. The job reads
the already-redacted body from the committed log and records the object URL back on it.
"""
import frappe

BUCKET = "assignment_submission_tap"
FOLDER = "kaapi_logs"
# body field -> (field storing the GCS URL, field holding the timestamp, file prefix)
BODIES = {
    "raw_body": ("raw_body_gcs_url", "received_at", "kaapi_logs_request"),
    "callback_body": ("callback_body_gcs_url", "callback_received_at", "kaapi_logs_response"),
}
URL_PREFIX = "https://storage.cloud.google.com"


def enqueue_raw_body_upload(log_name: str, body_field: str = "raw_body") -> None:
    """Queue the GCS upload of one body of a committed log. Never raises."""
    try:
        frappe.enqueue(
            "rag_service.core.kaapi_log_archive.upload_raw_body",
            queue="short",
            job_name=f"kaapi-log-upload-{log_name}-{body_field}",
            log_name=log_name,
            body_field=body_field,
        )
    except Exception as e:
        frappe.log_error(f"Could not enqueue GCS upload for Kaapi Webhook Log {log_name}: {e}",
                         "Kaapi Webhook Log Error")


def object_name(log_name: str, prefix: str, logged_at) -> str:
    stamp = frappe.utils.get_datetime(logged_at).strftime("%Y%m%d_%H%M%S")
    return f"{FOLDER}/{prefix}_{stamp}_{log_name}.txt"


def upload_raw_body(log_name: str, body_field: str = "raw_body") -> str:
    """Background job: write one body of the log to GCS as a downloadable attachment and
    store its storage.cloud.google.com URL on the log."""
    from ..utils.gcp_service_client import GCPServiceClient

    url_field, time_field, prefix = BODIES[body_field]
    log = frappe.db.get_value("Kaapi Webhook Log", log_name, [time_field, body_field], as_dict=True)
    if not log:
        raise ValueError(f"Kaapi Webhook Log {log_name} not found")

    name = object_name(log_name, prefix, log[time_field])
    blob = GCPServiceClient().client.bucket(BUCKET).blob(name)
    blob.content_disposition = f'attachment; filename="{name.rsplit("/", 1)[-1]}"'
    blob.upload_from_string((log[body_field] or "").encode("utf-8"),
                            content_type="text/plain; charset=utf-8")

    url = f"{URL_PREFIX}/{BUCKET}/{name}"
    frappe.db.set_value("Kaapi Webhook Log", log_name, url_field, url)
    frappe.db.commit()
    return url
