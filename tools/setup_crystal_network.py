#!/usr/bin/env python3
"""
Shard Network Database Setup
Creates the tables needed for the ARG/Signal system:
- origin_sites: The 14 real Mars landing sites (legendary, first-finder glory)
- echo_sites: Dynamic sites that spawn from exploration (2% chance + pity timer)
- signal_messages: The Architects' story fragments
- site_claims: Who found what, when, what rank
"""

import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres_utils import get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE SCHEMA
# ============================================================================

SCHEMA_SQL = """
-- ============================================================================
-- SHARD NETWORK TABLES
-- The ARG/Signal system for Pilgrims - distributed memory across Mars
-- ============================================================================

-- Origin Sites: The 14 real Mars landing locations (Tier 1 - Legendary)
CREATE TABLE IF NOT EXISTS pilgrim.origin_sites (
    id SERIAL PRIMARY KEY,

    -- Identity
    site_code VARCHAR(30) UNIQUE NOT NULL,      -- "VIKING-1", "CURIOSITY", etc.
    mission_name VARCHAR(100) NOT NULL,          -- "Viking 1 Lander"

    -- Location (real Mars coordinates)
    latitude DECIMAL(10, 6) NOT NULL,
    longitude DECIMAL(10, 6) NOT NULL,

    -- Mission info
    mission_year INTEGER,
    mission_country VARCHAR(50),
    mission_status VARCHAR(50),                  -- "successful", "crashed", "lost"

    -- The memory this site unlocks
    memory_text TEXT NOT NULL,                   -- ARIA's memory fragment

    -- First Founder (Ready Player One moment)
    founder_user_id INTEGER REFERENCES pilgrim.users(id),
    founder_commander_name VARCHAR(100),
    founder_sol INTEGER,                         -- Game "day" when found
    founder_tx_hash VARCHAR(66),                 -- Blockchain proof
    founder_claimed_at TIMESTAMP,

    -- State
    is_active BOOLEAN DEFAULT TRUE,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Echo Sites: Dynamic sites that spawn from exploration (Tier 2 - Rare/Uncommon)
CREATE TABLE IF NOT EXISTS pilgrim.echo_sites (
    id SERIAL PRIMARY KEY,

    -- Identity
    site_code VARCHAR(30) UNIQUE NOT NULL,      -- "ECHO-001", "ECHO-042", etc.

    -- Location (near where triggering expedition went)
    latitude DECIMAL(10, 6) NOT NULL,
    longitude DECIMAL(10, 6) NOT NULL,
    nearby_landmark VARCHAR(200),                -- What Mars feature it's near

    -- How it spawned
    spawned_by_user_id INTEGER REFERENCES pilgrim.users(id),
    spawned_by_expedition_id INTEGER,
    spawned_at TIMESTAMP DEFAULT NOW(),

    -- The memory this site reveals
    message_id INTEGER,                          -- FK to signal_messages
    memory_text TEXT,                            -- The Architects' fragment

    -- Claim tracking
    total_claims INTEGER DEFAULT 0,
    max_ranked_claims INTEGER DEFAULT 10,        -- First 10 get ranked

    -- State
    is_active BOOLEAN DEFAULT TRUE,
    is_depleted BOOLEAN DEFAULT FALSE,           -- After max claims
    expires_at TIMESTAMP,                        -- Optional expiration

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Signal Messages: The Architects' story fragments (for Echo Sites)
CREATE TABLE IF NOT EXISTS pilgrim.signal_messages (
    id SERIAL PRIMARY KEY,

    -- Content
    category VARCHAR(50) NOT NULL,               -- "journey", "technology", "observation", "mystery"
    message_text TEXT NOT NULL,

    -- Usage tracking
    usage_count INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW()
);

-- Site Claims: Who found what, when, what rank
CREATE TABLE IF NOT EXISTS pilgrim.site_claims (
    id SERIAL PRIMARY KEY,

    -- What was claimed
    site_type VARCHAR(20) NOT NULL,              -- "origin" or "echo"
    origin_site_id INTEGER REFERENCES pilgrim.origin_sites(id),
    echo_site_id INTEGER REFERENCES pilgrim.echo_sites(id),

    -- Who claimed it
    user_id INTEGER REFERENCES pilgrim.users(id) NOT NULL,
    commander_name VARCHAR(100),

    -- Claim details
    claim_rank INTEGER NOT NULL,                 -- 1 = first finder, 2 = second, etc.
    claim_tier VARCHAR(20),                      -- "legendary", "rare", "uncommon", "common"
    expedition_id INTEGER,

    -- Blockchain record
    tx_hash VARCHAR(66),
    blockchain_message TEXT,

    -- Discovery reward
    discovery_item_id INTEGER,
    discovery_name VARCHAR(100),

    -- Metadata
    claimed_at TIMESTAMP DEFAULT NOW(),
    sol_number INTEGER,

    -- Constraints
    CONSTRAINT unique_origin_claim UNIQUE (origin_site_id, user_id),
    CONSTRAINT unique_echo_claim UNIQUE (echo_site_id, user_id)
);

-- Signal Puzzles: Decodable secrets that reward solvers
CREATE TABLE IF NOT EXISTS pilgrim.signal_puzzles (
    id SERIAL PRIMARY KEY,

    -- Identity
    puzzle_code VARCHAR(50) UNIQUE NOT NULL,     -- "HITCHHIKER", "ORIGIN_COUNT", etc.
    puzzle_name VARCHAR(100) NOT NULL,           -- Display name: "The Answer"

    -- Solution (hashed for security)
    answer_hash VARCHAR(128) NOT NULL,           -- SHA-256 hash of correct answer
    hint_text TEXT,                              -- Cryptic hint shown to players

    -- Reward configuration
    reward_type VARCHAR(50) DEFAULT 'legendary_discovery',
    reward_prompt TEXT,                          -- Flux prompt template with {commander_name}

    -- First solver (eternal glory)
    first_solver_id INTEGER REFERENCES pilgrim.users(id),
    first_solver_name VARCHAR(100),
    first_solved_at TIMESTAMP,

    -- State
    is_active BOOLEAN DEFAULT TRUE,
    max_solvers INTEGER DEFAULT 1,               -- How many can solve (1 = first only)
    times_solved INTEGER DEFAULT 0,

    -- Metadata
    created_at TIMESTAMP DEFAULT NOW()
);

-- Puzzle Solvers: Track all who solved each puzzle
CREATE TABLE IF NOT EXISTS pilgrim.puzzle_solvers (
    id SERIAL PRIMARY KEY,

    puzzle_id INTEGER REFERENCES pilgrim.signal_puzzles(id) NOT NULL,
    user_id INTEGER REFERENCES pilgrim.users(id) NOT NULL,
    commander_name VARCHAR(100),

    -- Solution details
    solved_at TIMESTAMP DEFAULT NOW(),
    solve_rank INTEGER NOT NULL,                 -- 1 = first, 2 = second, etc.

    -- Reward given
    reward_item_id INTEGER,                      -- FK to generated_images or discoveries
    reward_name VARCHAR(200),

    CONSTRAINT unique_puzzle_solver UNIQUE (puzzle_id, user_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_origin_sites_location ON pilgrim.origin_sites(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_origin_sites_founder ON pilgrim.origin_sites(founder_user_id);
CREATE INDEX IF NOT EXISTS idx_echo_sites_location ON pilgrim.echo_sites(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_echo_sites_active ON pilgrim.echo_sites(is_active, is_depleted);
CREATE INDEX IF NOT EXISTS idx_echo_sites_spawner ON pilgrim.echo_sites(spawned_by_user_id);
CREATE INDEX IF NOT EXISTS idx_site_claims_user ON pilgrim.site_claims(user_id);
CREATE INDEX IF NOT EXISTS idx_site_claims_type ON pilgrim.site_claims(site_type);
CREATE INDEX IF NOT EXISTS idx_signal_messages_category ON pilgrim.signal_messages(category);
CREATE INDEX IF NOT EXISTS idx_puzzle_solvers_puzzle ON pilgrim.puzzle_solvers(puzzle_id);
CREATE INDEX IF NOT EXISTS idx_puzzle_solvers_user ON pilgrim.puzzle_solvers(user_id);
"""

def create_tables():
    """Create the Shard Network tables"""
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        logger.info("Creating Shard Network tables...")
        cur.execute(SCHEMA_SQL)
        conn.commit()

        logger.info("✅ Shard Network tables created successfully!")

        # Check what was created
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'pilgrim'
            AND table_name IN ('origin_sites', 'echo_sites', 'signal_messages', 'site_claims')
            ORDER BY table_name
        """)
        tables = [row[0] for row in cur.fetchall()]
        logger.info(f"   Tables: {', '.join(tables)}")

        return True

    except Exception as e:
        logger.error(f"❌ Failed to create tables: {e}")
        if conn:
            conn.rollback()
        return False

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def check_tables_exist():
    """Check if tables already exist"""
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'pilgrim'
            AND table_name IN ('origin_sites', 'echo_sites', 'signal_messages', 'site_claims')
        """)
        existing = [row[0] for row in cur.fetchall()]
        return existing

    except Exception as e:
        logger.error(f"Error checking tables: {e}")
        return []

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    print("\n" + "="*60)
    print("CRYSTAL NETWORK DATABASE SETUP")
    print("="*60 + "\n")

    existing = check_tables_exist()
    if existing:
        print(f"Existing tables found: {', '.join(existing)}")
        response = input("Tables may already exist. Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    success = create_tables()

    if success:
        print("\n✅ Setup complete! Next steps:")
        print("   1. Run: python tools/generate_origin_sites.py")
        print("   2. Run: python tools/generate_echo_messages.py")
        print("   3. Test the /signal page")
    else:
        print("\n❌ Setup failed. Check the logs above.")
        sys.exit(1)
