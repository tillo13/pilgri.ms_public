"""Consolidated email package for Pilgrims.

All outbound email code lives here:
- transport: Gmail API primitives (send_email, send_simple_email, ...)
- actions:   One-click email action tokens (claim sepolia, etc.)
- fomo:      Welcome-back / re-engagement emails
- bonds:     ARIA bond-detected notifications
- admin:     ARIA test emails (cron + admin variants)
- mentions:  Bug tracker @mention notifications

Jinja HTML templates live under `templates/emails/`.
"""
