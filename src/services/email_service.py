"""Send audit PDF reports via Azure Communication Services."""
import base64
import logging
import os

logger = logging.getLogger("brand-guardian")


def send_audit_report(to_email: str, audit_id: str, pdf_bytes: bytes) -> None:
    """Send audit PDF report via Azure Communication Services."""
    from azure.communication.email import EmailClient

    conn_str = os.getenv("AZURE_COMM_CONNECTION_STRING", "")
    if not conn_str:
        logger.warning("AZURE_COMM_CONNECTION_STRING not set — email skipped")
        return

    client = EmailClient.from_connection_string(conn_str)
    message = {
        "senderAddress": os.getenv("EMAIL_SENDER", "noreply@brandguardian.ai"),
        "recipients": {"to": [{"address": to_email}]},
        "content": {
            "subject": f"Brand Guardian Audit Report — {audit_id[:8]}",
            "plainText": "Your compliance audit is complete. Report attached.",
        },
        "attachments": [{
            "name": "audit-report.pdf",
            "contentType": "application/pdf",
            "contentInBase64": base64.b64encode(pdf_bytes).decode(),
        }],
    }
    poller = client.begin_send(message)
    poller.result()
    logger.info("Audit report emailed to %s for audit %s", to_email, audit_id[:8])
