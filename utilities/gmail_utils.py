import base64
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from os import path
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Sends as kumoridotai@gmail.com via Gmail API + OAuth (refresh token in
# `KUMORI_GMAIL_OAUTH_REFRESH_TOKEN` secret on project kumori-404602). Swapped
# from SMTP app-password — Gmail was bouncing those as 550 5.7.1 spam.
PROJECT_ID = 'kumori-404602'
OAUTH_SECRET_ID = 'KUMORI_GMAIL_OAUTH_REFRESH_TOKEN'
SENDER_EMAIL = 'kumoridotai@gmail.com'

_cached_service = None
_cached_creds = None
_sm_client = None


def _get_gmail_service():
    """Build (and cache) a Gmail API client authed as kumoridotai@gmail.com."""
    global _cached_service, _cached_creds, _sm_client
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    if _cached_creds is None:
        from google.cloud import secretmanager
        if _sm_client is None:
            _sm_client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{PROJECT_ID}/secrets/{OAUTH_SECRET_ID}/versions/latest"
        payload = json.loads(
            _sm_client.access_secret_version(request={"name": name}).payload.data.decode("UTF-8")
        )
        _cached_creds = Credentials(
            token=None,
            refresh_token=payload["refresh_token"],
            client_id=payload["client_id"],
            client_secret=payload["client_secret"],
            token_uri=payload["token_uri"],
            scopes=payload.get("scopes"),
        )

    if not _cached_creds.valid:
        _cached_creds.refresh(Request())
        _cached_service = None

    if _cached_service is None:
        _cached_service = build("gmail", "v1", credentials=_cached_creds, cache_discovery=False)
    return _cached_service


def send_email(
    subject: str,
    body: str,
    to_emails: List[str],
    cc_emails: Optional[List[str]] = None,
    bcc_emails: Optional[List[str]] = None,
    attachment_paths: Optional[List[str]] = None,
    is_html: bool = False,
    from_name: str = "Pilgrims"
) -> bool:
    """Send an email via Gmail API as kumoridotai@gmail.com."""
    try:
        message = MIMEMultipart()
        message['From'] = f'{from_name} <{SENDER_EMAIL}>'
        message['To'] = ', '.join(to_emails)
        message['Subject'] = subject

        if cc_emails:
            message['Cc'] = ', '.join(cc_emails)
        if bcc_emails:
            message['Bcc'] = ', '.join(bcc_emails)

        if is_html:
            message.attach(MIMEText(body, 'html'))
        else:
            message.attach(MIMEText(body, 'plain'))

        if attachment_paths:
            for attachment_path in attachment_paths:
                if not path.exists(attachment_path):
                    logger.warning(f"Attachment file not found: {attachment_path}")
                    continue
                part = MIMEBase('application', 'octet-stream')
                with open(attachment_path, 'rb') as file:
                    part.set_payload(file.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', 'attachment', filename=path.basename(attachment_path))
                message.attach(part)

        svc = _get_gmail_service()
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        svc.users().messages().send(userId='me', body={'raw': raw}).execute()

        logger.info(f'Email sent successfully to {to_emails}')
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_simple_email(subject: str, body: str, to_email: str, is_html: bool = False) -> bool:
    """Send email to a single recipient."""
    return send_email(subject, body, [to_email], is_html=is_html)


# =============================================================================
# PILGRIMS-SPECIFIC EMAIL TEMPLATES
# =============================================================================


def send_expedition_complete_email(to_email: str, user_name: str, destination: str, discoveries: List[Dict]) -> bool:
    """Notify user their expedition has returned."""
    discovery_list = ""
    total_value = 0
    for d in discoveries:
        discovery_list += f"  - {d.get('item_name', 'Unknown')} ({d.get('rarity', 'common')})\n"
        total_value += d.get('value', 0)

    body = f"""Captain {user_name},

Your expedition to {destination} has returned!

Discoveries:
{discovery_list}
Total Value: {total_value:.1f} Sepolia

Log in to claim your finds: https://pilgri.ms

- Mission Control
"""
    return send_simple_email(f"Expedition Complete: {destination}", body, to_email)



# ==============================================================================
# DAILY DIGEST EMAIL
# ==============================================================================

def send_daily_digest_email(to_email: str, user_name: str, stats: Dict) -> bool:
    """Daily summary of colony status."""
    body = f"""Captain {user_name},

Daily Colony Report:

Resources:
  - Current Balance: {stats.get('balance', 0):.1f} Sepolia
  - Generated Today: {stats.get('generated', 0):.1f} Sepolia

Activity:
  - Active Expeditions: {stats.get('active_expeditions', 0)}
  - Completed Today: {stats.get('completed_expeditions', 0)}
  - Discoveries: {stats.get('discoveries', 0)}

Colony Status: Operational

View full dashboard: https://pilgri.ms

- Mission Control
"""
    return send_simple_email("Daily Colony Report", body, to_email)


# ==============================================================================
# FOMO EMAIL (Backwards Compatibility)
# ==============================================================================
# The FOMO email template has moved to fomo_email_utils.py
# These imports are at the END to avoid circular import issues

def send_welcome_back_email(*args, **kwargs):
    """Backwards-compat wrapper - use fomo_email_utils.send_welcome_back_email directly."""
    from utilities.fomo_email_utils import send_welcome_back_email as _send_fomo
    return _send_fomo(*args, **kwargs)
