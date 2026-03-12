import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from google.cloud import secretmanager
from os import path
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Google Cloud Secret Manager config
PROJECT_ID = 'kumori-404602'
GMAIL_USERNAME_SECRET_ID = 'KUMORI_GMAIL_USERNAME'
GMAIL_APP_PASSWORD_SECRET_ID = 'KUMORI_GMAIL_APP_PASSWORD'

_secrets_cache = {}
_sm_client = None

def get_secret_version(project_id: str, secret_id: str, version_id: str = "latest") -> str:
    """Get secret from Google Cloud Secret Manager (cached)."""
    cache_key = f"{project_id}:{secret_id}:{version_id}"
    if cache_key in _secrets_cache:
        return _secrets_cache[cache_key]
    global _sm_client
    if _sm_client is None:
        _sm_client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    response = _sm_client.access_secret_version(request={"name": name})
    val = response.payload.data.decode('UTF-8')
    _secrets_cache[cache_key] = val
    return val

def get_gmail_credentials() -> Dict[str, str]:
    """Get Gmail credentials from Google Cloud Secret Manager."""
    return {
        'user': get_secret_version(PROJECT_ID, GMAIL_USERNAME_SECRET_ID),
        'password': get_secret_version(PROJECT_ID, GMAIL_APP_PASSWORD_SECRET_ID),
    }


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
    """
    Send an email using Gmail SMTP.

    Args:
        subject: Email subject line
        body: Email body content
        to_emails: List of recipient email addresses
        cc_emails: List of CC email addresses (optional)
        bcc_emails: List of BCC email addresses (optional)
        attachment_paths: List of file paths to attach (optional)
        is_html: Whether the body is HTML format (default: False)
        from_name: Display name for sender (default: "Pilgrims")

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        gmail_credentials = get_gmail_credentials()
        gmail_user = gmail_credentials['user']
        gmail_password = gmail_credentials['password']

        message = MIMEMultipart()
        message['From'] = f'{from_name} <{gmail_user}>'
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

        all_recipients = to_emails.copy()
        if cc_emails:
            all_recipients.extend(cc_emails)
        if bcc_emails:
            all_recipients.extend(bcc_emails)

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(message, to_addrs=all_recipients)

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
