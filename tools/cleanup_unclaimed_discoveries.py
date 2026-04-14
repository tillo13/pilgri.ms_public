#!/usr/bin/env python3
"""
One-time cleanup script to auto-claim ALL unclaimed expedition discoveries for all users.

This resolves the backlog of unclaimed items that were blocking expedition slots.
Future discoveries will be handled by the improved UI flow.

Run: python tools/cleanup_unclaimed_discoveries.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import db_cursor

def cleanup_unclaimed_discoveries():
    """Auto-claim all unclaimed discoveries for all users."""

    print("🔍 Finding all unclaimed expedition discoveries...")

    with db_cursor() as cur:
        # First, get stats on what we're about to clean up
        cur.execute("""
            SELECT
                u.id as user_id,
                u.email,
                COUNT(ed.id) as unclaimed_count,
                COALESCE(SUM(ed.enhanced_value), 0) as total_value
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            JOIN pilgrim.users u ON e.user_id = u.id
            WHERE ed.claimed_by_user = false
            GROUP BY u.id, u.email
            ORDER BY unclaimed_count DESC
        """)
        users_with_unclaimed = cur.fetchall()

        if not users_with_unclaimed:
            print("✅ No unclaimed discoveries found - nothing to clean up!")
            return

        total_items = sum(u['unclaimed_count'] for u in users_with_unclaimed)
        total_value = sum(float(u['total_value']) for u in users_with_unclaimed)

        print(f"\n📊 Found {total_items} unclaimed discoveries across {len(users_with_unclaimed)} users")
        print(f"   Total value: {total_value:.6f} ETH\n")

        print("Users with unclaimed items:")
        for u in users_with_unclaimed:
            print(f"   • {u['email']}: {u['unclaimed_count']} items ({float(u['total_value']):.6f} ETH)")

        print("\n" + "="*60)
        print("Auto-claiming all discoveries...")

    # Now do the actual cleanup
    with db_cursor(commit=True) as cur:
        # Also unlock any that aren't unlocked yet (set unlocked_at)
        cur.execute("""
            UPDATE pilgrim.expedition_discoveries
            SET
                unlocked_at = COALESCE(unlocked_at, NOW()),
                claimed_by_user = true,
                claimed_at = NOW()
            WHERE claimed_by_user = false
            RETURNING id
        """)
        claimed_count = cur.rowcount

        print(f"\n✅ Successfully claimed {claimed_count} discoveries!")
        print("   All expedition slots should now be free for new expeditions.")

if __name__ == '__main__':
    cleanup_unclaimed_discoveries()
