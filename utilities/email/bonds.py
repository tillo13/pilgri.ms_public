"""ARIA bond-detected email notifications.

Extracted from utilities/aria/bonds.py (round 8 consolidation).
Sends an individual email to each captain when a bond is formed at a landmark.
"""
import logging
from flask import render_template

from utilities.postgres.core import db_cursor
from utilities.email.transport import send_email

logger = logging.getLogger(__name__)

__all__ = ['send_bond_notification']


def _get_commander_name_local(user_id: int):
    """Minimal fetch for commander display name — mirrors aria/bonds helper."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT commander_name FROM pilgrim.replicate_assets
                WHERE user_id = %s AND commander_name IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
            """, (user_id,))
            row = cur.fetchone()
            if row and row.get('commander_name'):
                return row['commander_name']
    except Exception:
        pass
    return None


def send_bond_notification(bond_id: int, user_id_1: int, user_id_2: int,
                           landmark_name: str, captain_1: str, captain_2: str,
                           bond_image_url: str = None):
    """Send individual bond notification emails to BOTH captains.

    Each gets their own email (To: their email) — no email sharing between users.
    Also BCC's andy.tillo@gmail.com for monitoring.
    """
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, email, name FROM pilgrim.users WHERE id IN (%s, %s)",
                (user_id_1, user_id_2)
            )
            users = {row['id']: row for row in cur.fetchall()}

        for uid in [user_id_1, user_id_2]:
            user = users.get(uid)
            if not user or not user.get('email'):
                logger.warning(f"No email for user {uid}, skipping bond notification")
                continue

            partner_id = user_id_2 if uid == user_id_1 else user_id_1
            my_name = _get_commander_name_local(uid) or f'Captain {uid}'
            partner_name = _get_commander_name_local(partner_id) or f'Captain {partner_id}'

            subject = f"ARIA Bond Detected at {landmark_name}"

            body = render_template(
                'emails/bond_notification.html',
                landmark_name=landmark_name,
                bond_image_url=bond_image_url or '',
                my_name=my_name,
                partner_name=partner_name,
            )

            send_email(
                subject=subject,
                body=body,
                to_emails=[user.get('email')],
                bcc_emails=['andy.tillo@gmail.com'],
                is_html=True
            )
            logger.info(f"Bond notification email sent to user {uid} ({user.get('email')})")

    except Exception as e:
        logger.error(f"Failed to send bond notification emails: {e}")
