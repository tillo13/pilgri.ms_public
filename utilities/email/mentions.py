"""Bug tracker @mention email notifications.

Extracted from utilities/postgres/bugs.py (round 8 consolidation).
"""
import logging
from flask import render_template

from utilities.email.transport import send_simple_email

logger = logging.getLogger(__name__)

__all__ = ['send_mention_notification']


def send_mention_notification(bug_id: int, bug_name: str, to_email: str,
                              author: str, comment_body: str) -> bool:
    """Send an @mention email for a bug tracker comment.

    Args:
        bug_id:       the bug id
        bug_name:     the bug title (for subject + link text)
        to_email:     recipient
        author:       name of commenter who wrote the @mention
        comment_body: full body of the comment (raw text, will be rendered)

    Returns:
        True on successful send, False otherwise.
    """
    link = f'https://pilgri.ms/admin/bugs?open={bug_id}'
    subject = f'Bug #{bug_id}: {bug_name}'

    html_body = render_template(
        'emails/mention.html',
        bug_id=bug_id,
        bug_name=bug_name,
        author=author,
        comment_body=comment_body,
        link=link,
    )

    return send_simple_email(subject, html_body, to_email, is_html=True)
