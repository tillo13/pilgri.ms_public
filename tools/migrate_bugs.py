#!/usr/bin/env python3
"""
One-time migration: Google Sheets bug tracker → PostgreSQL.

Reads all 3 tabs (Active, Completed, Parking Lot) and inserts into:
  - pilgrim.bugs (Active + Completed)
  - pilgrim.bug_ideas (Parking Lot)
  - Also migrates pilgrim.pilgrimbot_reports → pilgrim.bugs

Run: python tools/migrate_bugs.py [--dry-run]

Does NOT delete the Google Sheet (kept as archive).
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import gspread
from google.oauth2.service_account import Credentials
from utilities.postgres_utils import db_cursor
from utilities.db_bugs import ensure_bug_tables

CREDENTIALS_PATH = Path(__file__).parent / 'credentials' / os.environ.get('GCP_SA_FILENAME', 'service-account.json')
SPREADSHEET_ID = os.environ.get('BUGS_SPREADSHEET_ID', '')
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']


def get_sheets():
    creds = Credentials.from_service_account_file(str(CREDENTIALS_PATH), scopes=SCOPES)
    client = gspread.authorize(creds)
    ss = client.open_by_key(SPREADSHEET_ID)
    return ss.worksheet('Active'), ss.worksheet('Completed'), ss.worksheet('Parking Lot')


def parse_date(date_str):
    """Parse M/D/YYYY or similar dates from sheet."""
    if not date_str:
        return None
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def migrate_active(active_sheet, dry_run=False):
    """Migrate Active tab rows to pilgrim.bugs with completed_at = NULL."""
    rows = active_sheet.get_all_records()
    count = 0
    for row in rows:
        name = row.get('Name', '').strip()
        if not name:
            continue

        # Map sheet columns to DB columns
        qa_val = str(row.get('QA Approved', '')).upper()
        qa_approved = qa_val in ('TRUE', 'YES', '1', 'X')

        values = (
            name[:200],
            row.get('Description', ''),
            row.get('To Validate', ''),
            row.get('Type', 'Bug') or 'Bug',
            row.get('Priority', 'P3') or 'P3',
            row.get('Status', 'New') or 'New',
            qa_approved,
            row.get('Source', 'CLI') or 'CLI',
            row.get('QA Notes', ''),
            row.get('Extra AI added words', ''),
        )

        if dry_run:
            print(f"  [DRY] Active: {name} ({row.get('Priority','P3')} {row.get('Status','New')})")
        else:
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO pilgrim.bugs
                        (name, description, to_validate, type, priority, status,
                         qa_approved, source, qa_notes, extra_notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, values)
        count += 1

    return count


def migrate_completed(completed_sheet, dry_run=False):
    """Migrate Completed tab rows to pilgrim.bugs with completed_at set."""
    rows = completed_sheet.get_all_records()
    count = 0
    for row in rows:
        name = row.get('Name', '').strip()
        if not name:
            continue

        completed_date = parse_date(str(row.get('Completed', '')))
        time_str = str(row.get('Time', ''))
        if completed_date and time_str:
            try:
                h, m, s = time_str.split(':')
                completed_date = completed_date.replace(
                    hour=int(h), minute=int(m), second=int(s))
            except (ValueError, TypeError):
                pass

        values = (
            name,
            row.get('Description', ''),
            row.get('Dev Details', ''),
            row.get('Type', 'Bug') or 'Bug',
            row.get('Priority', 'P3') or 'P3',
            'Done',
            True,  # qa_approved
            row.get('Source', 'CLI') or 'CLI',
            row.get('QA Notes', ''),
            completed_date or datetime.utcnow(),
        )

        if dry_run:
            print(f"  [DRY] Completed: {name} ({row.get('Completed','')})")
        else:
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO pilgrim.bugs
                        (name, description, to_validate, type, priority, status,
                         qa_approved, source, qa_notes, completed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, values)
        count += 1

    return count


def migrate_parking_lot(parking_sheet, dry_run=False):
    """Migrate Parking Lot tab to pilgrim.bug_ideas."""
    rows = parking_sheet.get_all_records()
    count = 0
    for row in rows:
        name = (row.get('Idea', '') or row.get('Name', '')).strip()
        if not name:
            continue

        values = (
            name[:200],
            row.get('Description', ''),
            row.get('Category', 'Feature') or 'Feature',
            row.get('Status', 'New') or 'New',
            row.get('Notes', ''),
        )

        if dry_run:
            print(f"  [DRY] Idea: {name} ({row.get('Category','Feature')})")
        else:
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO pilgrim.bug_ideas
                        (name, description, category, status, notes)
                    VALUES (%s, %s, %s, %s, %s)
                """, values)
        count += 1

    return count


def migrate_pilgrimbot_reports(dry_run=False):
    """Migrate existing pilgrimbot_reports into bugs table."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, title, description, submitted_by, status, created_at
                FROM pilgrim.pilgrimbot_reports
                ORDER BY id
            """)
            rows = cur.fetchall()
    except Exception:
        print("  No pilgrimbot_reports table found, skipping.")
        return 0

    count = 0
    for row in rows:
        if dry_run:
            print(f"  [DRY] PilgrimBot report: {row['title']}")
        else:
            with db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO pilgrim.bugs
                        (name, description, source, status)
                    VALUES (%s, %s, 'PilgrimBot', %s)
                """, (row['title'], row['description'] or '', row['status'] or 'New'))
        count += 1

    return count


def main():
    parser = argparse.ArgumentParser(description='Migrate Google Sheets bugs to PostgreSQL')
    parser.add_argument('--dry-run', action='store_true', help='Print what would be migrated')
    args = parser.parse_args()

    print("Bug Tracker Migration: Google Sheets → PostgreSQL")
    print("=" * 50)

    if args.dry_run:
        print("DRY RUN — no data will be written\n")

    # Ensure tables exist
    ensure_bug_tables()

    # Check if already migrated
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM pilgrim.bugs")
        existing = cur.fetchone()['cnt']
    if existing > 0 and not args.dry_run:
        print(f"\nWARNING: pilgrim.bugs already has {existing} rows.")
        resp = input("Continue and add more? (y/N): ").strip().lower()
        if resp != 'y':
            print("Aborted.")
            return

    # Read Google Sheets
    print("\nReading Google Sheets...")
    active_sheet, completed_sheet, parking_sheet = get_sheets()

    print("\n--- Active Bugs ---")
    active_count = migrate_active(active_sheet, args.dry_run)
    print(f"  {'Would migrate' if args.dry_run else 'Migrated'}: {active_count} active bugs")

    print("\n--- Completed Bugs ---")
    completed_count = migrate_completed(completed_sheet, args.dry_run)
    print(f"  {'Would migrate' if args.dry_run else 'Migrated'}: {completed_count} completed bugs")

    print("\n--- Parking Lot Ideas ---")
    ideas_count = migrate_parking_lot(parking_sheet, args.dry_run)
    print(f"  {'Would migrate' if args.dry_run else 'Migrated'}: {ideas_count} ideas")

    print("\n--- PilgrimBot Reports ---")
    reports_count = migrate_pilgrimbot_reports(args.dry_run)
    print(f"  {'Would migrate' if args.dry_run else 'Migrated'}: {reports_count} reports")

    print(f"\n{'=' * 50}")
    print(f"Total: {active_count + completed_count + ideas_count + reports_count} items")
    if not args.dry_run:
        print("Migration complete! Google Sheet preserved as archive.")
    else:
        print("Run without --dry-run to execute migration.")


if __name__ == '__main__':
    main()
