"""ARIA test email senders (cron + admin-triggered variants).

Extracted from utilities/admin_utils.py (round 8 consolidation). Both emails
share the same Jinja template (`templates/emails/aria_test.html`) with a
`variant` flag controlling the subtle copy differences.
"""
import logging
from flask import render_template

from utilities.email.transport import send_email

logger = logging.getLogger(__name__)

__all__ = ['send_cron_aria_test', 'send_admin_aria_test']


def _render_aria_test(variant: str, fact: str) -> str:
    return render_template('emails/aria_test.html', variant=variant, fact=fact)


def send_cron_aria_test(fact: str) -> bool:
    """Cron-triggered ARIA test email — always sent to andy.tillo@gmail.com."""
    html_body = _render_aria_test('cron', fact)
    return send_email(
        subject="\U0001f4e1 ARIA Transmission - Mars Fact of the Hour",
        body=html_body,
        to_emails=["andy.tillo@gmail.com"],
        is_html=True,
        from_name="ARIA - Pilgrims",
    )


def send_admin_aria_test(to_email: str, fact: str) -> bool:
    """Admin-triggered ARIA test email — sends to specified address."""
    html_body = _render_aria_test('admin', fact)
    return send_email(
        subject="\U0001f4e1 ARIA Test - Admin Triggered",
        body=html_body,
        to_emails=[to_email],
        is_html=True,
        from_name="ARIA - Pilgrims",
    )
