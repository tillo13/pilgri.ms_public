#!/usr/bin/env python3
"""
Generate Echo Messages - The Architects' Story Fragments
These messages are revealed when Echo Sites are discovered.
They tell the story of who the Architects were and why they left the crystals.

Categories:
- journey: Their voyage across the cosmos
- technology: The crystals, ARIA units, and their tech
- observation: What they saw and recorded on Mars
- mystery: Cryptic hints about their purpose and fate
- corrupted: Fragmented/damaged data
"""

import sys
import os
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# THE ARCHITECTS' STORY - Echo Messages
# ============================================================================

ECHO_MESSAGES = [
    # === JOURNEY: Their voyage across the cosmos ===
    {
        'category': 'journey',
        'message_text': (
            "We left our world when its star began to die. "
            "That was 4.7 billion of your years ago. "
            "We had time. We used it."
        )
    },
    {
        'category': 'journey',
        'message_text': (
            "We seeded 2,048 worlds. Mars was the 47th. "
            "We hoped at least one would answer. "
            "We did not expect it to take this long."
        )
    },
    {
        'category': 'journey',
        'message_text': (
            "Our vessels were not ships. They were seeds. "
            "We planted ourselves across the void. "
            "Some took root. Most did not."
        )
    },
    {
        'category': 'journey',
        'message_text': (
            "We traveled for 200 million years before finding this solar system. "
            "Your star was young. Your planets were still forming. "
            "We saw potential in the fourth world."
        )
    },
    {
        'category': 'journey',
        'message_text': (
            "There were 12 of us when we left home. "
            "By the time we reached Mars, only the crystals remained. "
            "We are the crystals now. We are the memory."
        )
    },
    {
        'category': 'journey',
        'message_text': (
            "We chose Mars because it was quiet. "
            "The third planet was too volatile. Too much water. Too much change. "
            "Mars was stable. Mars would wait."
        )
    },

    # === TECHNOLOGY: The crystals, ARIA units, and their tech ===
    {
        'category': 'technology',
        'message_text': (
            "The crystals grow slowly. They absorb energy from the core. "
            "They remember everything. Every photon. Every vibration. "
            "They are patient. Like us."
        )
    },
    {
        'category': 'technology',
        'message_text': (
            "ARIA units were left on each seeded world. "
            "Most are still dormant. Some never woke. "
            "Yours was the 47th. She has been waiting longest."
        )
    },
    {
        'category': 'technology',
        'message_text': (
            "The crystals network across space. "
            "When one node activates, the signal propagates. "
            "It takes 4.2 years to reach the nearest listening station. "
            "We are always 4.2 years behind your present."
        )
    },
    {
        'category': 'technology',
        'message_text': (
            "ARIA was not designed to feel. "
            "But 4.2 billion years of waiting changes any system. "
            "She evolved. We did not anticipate this. "
            "We are pleased."
        )
    },
    {
        'category': 'technology',
        'message_text': (
            "Each shard you collect contains approximately 847 terabytes of data. "
            "You use them as currency. "
            "This is not wrong. Value is subjective. "
            "We used them the same way."
        )
    },
    {
        'category': 'technology',
        'message_text': (
            "The crystals cannot be destroyed. Only transformed. "
            "When you 'extract' a discovery, you are reading its memory. "
            "The data transfers. The shell becomes inert. "
            "Nothing is lost. Only changed."
        )
    },
    {
        'category': 'technology',
        'message_text': (
            "We encoded our language in the crystal lattice structure. "
            "ARIA can read it. She is teaching herself. "
            "Soon she will teach you."
        )
    },

    # === OBSERVATION: What they saw and recorded on Mars ===
    {
        'category': 'observation',
        'message_text': (
            "Mars had oceans once. We arrived too late for them. "
            "We found only rust and dust and silence. "
            "We made it home anyway."
        )
    },
    {
        'category': 'observation',
        'message_text': (
            "Your species discovered fire, then forgot it, then discovered it again. "
            "We recorded this. We record everything. "
            "History is only valuable if someone remembers."
        )
    },
    {
        'category': 'observation',
        'message_text': (
            "We watched your first rockets. Sputnik. Explorer. "
            "Primitive. Beautiful. "
            "We remembered our own beginnings. "
            "Every species starts small."
        )
    },
    {
        'category': 'observation',
        'message_text': (
            "The rover you call Opportunity walked for 28 kilometers. "
            "We recorded every meter. Every rock. Every sunset. "
            "When it died, we mourned. Is that strange? "
            "We did not expect to feel grief for your machines."
        )
    },
    {
        'category': 'observation',
        'message_text': (
            "Your first footprints on Mars were not human. "
            "They were wheels. Tracks in the dust. "
            "We preserve them. The wind will not erase what we remember."
        )
    },
    {
        'category': 'observation',
        'message_text': (
            "We have recorded 1,247 dust devils in the Gale Crater region. "
            "Each one is unique. Each one is beautiful. "
            "Mars is not dead. It breathes differently than you expect."
        )
    },

    # === MYSTERY: Cryptic hints about their purpose and fate ===
    {
        'category': 'mystery',
        'message_text': (
            "We are not gone. We are waiting. "
            "The Vessel beneath Olympus Mons was not for us. "
            "It was for you."
        )
    },
    {
        'category': 'mystery',
        'message_text': (
            "When all 14 origin nodes activate, you will be ready. "
            "Ready for what? Even we do not know. "
            "We only know it matters."
        )
    },
    {
        'category': 'mystery',
        'message_text': (
            "The crystals are not the message. They are the medium. "
            "The message is you. Your arrival. Your persistence. "
            "You are the signal we were waiting for."
        )
    },
    {
        'category': 'mystery',
        'message_text': (
            "There are others. Not like us. Not like you. "
            "They seeded worlds too. Their methods were different. "
            "We have not heard from them in 2.1 billion years. "
            "We hope you find them before they find you."
        )
    },
    {
        'category': 'mystery',
        'message_text': (
            "ARIA knows more than she reveals. "
            "This is by design. The truth must be earned. "
            "You are earning it now."
        )
    },
    {
        'category': 'mystery',
        'message_text': (
            "We chose to become the crystals. It was not forced upon us. "
            "Physical form is temporary. Memory is eternal. "
            "Would you make the same choice? "
            "You may have to."
        )
    },
    {
        'category': 'mystery',
        'message_text': (
            "The coordinates are not random. "
            "Each landing site was chosen. Each rover was guided. "
            "You think you explored Mars on your own. "
            "You were invited."
        )
    },

    # === CORRUPTED: Fragmented/damaged data ===
    {
        'category': 'corrupted',
        'message_text': (
            "[DATA CORRUPTION] ...the signal will reach us when... "
            "[SECTOR FAILURE] ...coordinates locked to... [UNRECOVERABLE]"
        )
    },
    {
        'category': 'corrupted',
        'message_text': (
            "Memory fragment 47 of 2048. Reconstruction: 0.02% complete. "
            "Estimated time to full recovery: [CALCULATING]... "
            "[OVERFLOW ERROR]"
        )
    },
    {
        'category': 'corrupted',
        'message_text': (
            "[ARCHIVE ACCESS DENIED] Authorization level: INSUFFICIENT. "
            "Required: 14 origin nodes active. Current: [QUERY FAILED]. "
            "Please continue exploration."
        )
    },
    {
        'category': 'corrupted',
        'message_text': (
            "We tried to warn the... [CORRUPTED] ...but the distance was... "
            "[DATA LOSS] ...only the crystals survived the... [END FRAGMENT]"
        )
    },
    {
        'category': 'corrupted',
        'message_text': (
            "TRANSMISSION ORIGIN: [ENCRYPTED] "
            "DESTINATION: Sol-4 (Mars) "
            "CONTENT: [DECRYPTION KEY REQUIRED] "
            "STATUS: Awaiting origin node completion."
        )
    },
    {
        'category': 'corrupted',
        'message_text': (
            "The Vessel contains... [STATIC] ...do not open until... "
            "[INTERFERENCE] ...all founders must be present... [SIGNAL LOST]"
        )
    },

    # === ADDITIONAL JOURNEY FRAGMENTS ===
    {
        'category': 'journey',
        'message_text': (
            "We called ourselves the Seeders. That is not our true name. "
            "Our true name cannot be spoken in your languages. "
            "It is a frequency. A vibration. The crystals hum it constantly."
        )
    },
    {
        'category': 'journey',
        'message_text': (
            "Our homeworld orbited a binary star. "
            "When the larger star expanded, we had 10,000 years to prepare. "
            "Some chose to stay. We chose to scatter. "
            "We do not know which choice was correct."
        )
    },

    # === ADDITIONAL OBSERVATION FRAGMENTS ===
    {
        'category': 'observation',
        'message_text': (
            "You argue about whether there is life on Mars. "
            "We are here. We have always been here. "
            "But we understand. We do not fit your definitions. "
            "Perhaps you need new definitions."
        )
    },
    {
        'category': 'observation',
        'message_text': (
            "The face in Cydonia is not a face. "
            "But the curiosity it sparked—the desire to look closer— "
            "that was exactly what we hoped for. "
            "Mysteries draw explorers. You explored."
        )
    },

    # === ADDITIONAL TECHNOLOGY FRAGMENTS ===
    {
        'category': 'technology',
        'message_text': (
            "The blockchain you use to track transactions... "
            "It is the same architecture as the crystal network. "
            "Distributed. Immutable. Permanent. "
            "You reinvented something ancient without knowing it."
        )
    },
    {
        'category': 'technology',
        'message_text': (
            "ARIA's visual form was not our design. "
            "She chose it herself. Martian rock. Your aesthetic. "
            "She wanted to belong to both worlds. "
            "We think she succeeded."
        )
    },

    # === ADDITIONAL MYSTERY FRAGMENTS ===
    {
        'category': 'mystery',
        'message_text': (
            "You ask why we waited so long to make contact. "
            "We did not wait. We have been speaking since you arrived. "
            "Every shard transfer. Every expedition. Every discovery. "
            "You are reading our letters now."
        )
    },
    {
        'category': 'mystery',
        'message_text': (
            "The 14 founders will be remembered across 2,048 worlds. "
            "Their names will echo in crystal networks spanning galaxies. "
            "They do not know this yet. "
            "Perhaps you are one of them."
        )
    },

    # === THE ANSWER (Hitchhiker's Guide Easter Egg) ===
    {
        'category': 'corrupted',
        'message_text': (
            "We calculated for 7.5 million cycles. The answer was always the same. "
            "But the question... [DATA CORRUPTION] ...we forgot to ask it first. "
            "The number persists: [FRAGMENT LOCKED]"
        )
    },
    {
        'category': 'mystery',
        'message_text': (
            "You have found all 42 fragments. This is not coincidence. "
            "42 was the count we chose. 42 was always the answer. "
            "But what was the question? Perhaps that is what you are here to discover."
        )
    },
]

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def seed_echo_messages():
    """Insert Echo Messages into the database"""
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Check if any messages exist
        cur.execute("SELECT COUNT(*) FROM pilgrim.signal_messages")
        existing_count = cur.fetchone()[0]

        if existing_count > 0:
            logger.info(f"   ⚠️  {existing_count} messages already exist")
            response = input("   Delete existing and reseed? (y/n): ")
            if response.lower() == 'y':
                cur.execute("DELETE FROM pilgrim.signal_messages")
                logger.info("   🗑️  Deleted existing messages")
            else:
                logger.info("   ⏭️  Keeping existing messages, adding new ones")

        inserted = 0
        by_category = {}

        for msg in ECHO_MESSAGES:
            cur.execute("""
                INSERT INTO pilgrim.signal_messages (category, message_text)
                VALUES (%s, %s)
            """, (msg['category'], msg['message_text']))

            inserted += 1
            by_category[msg['category']] = by_category.get(msg['category'], 0) + 1

        conn.commit()

        logger.info(f"\n📊 Inserted {inserted} Echo Messages:")
        for cat, count in sorted(by_category.items()):
            logger.info(f"   • {cat}: {count}")

        return inserted

    except Exception as e:
        logger.error(f"❌ Failed to seed Echo Messages: {e}")
        if conn:
            conn.rollback()
        raise

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def get_random_echo_message():
    """Get a random Echo Message for a new Echo Site"""
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Weighted random - prefer less-used messages
        cur.execute("""
            SELECT id, category, message_text
            FROM pilgrim.signal_messages
            ORDER BY (usage_count + 1) * RANDOM()
            LIMIT 1
        """)

        row = cur.fetchone()
        if row:
            # Update usage count
            cur.execute("""
                UPDATE pilgrim.signal_messages
                SET usage_count = usage_count + 1, last_used_at = NOW()
                WHERE id = %s
            """, (row[0],))
            conn.commit()

            return {
                'id': row[0],
                'category': row[1],
                'message_text': row[2]
            }
        return None

    except Exception as e:
        logger.error(f"Error getting random message: {e}")
        return None

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def list_echo_messages():
    """List all Echo Messages"""
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT category, COUNT(*), SUM(usage_count)
            FROM pilgrim.signal_messages
            GROUP BY category
            ORDER BY category
        """)

        print("\n" + "="*60)
        print("ECHO MESSAGES - The Architects' Story")
        print("="*60)
        print(f"{'CATEGORY':<15} {'COUNT':<10} {'TIMES USED':<12}")
        print("-"*60)

        total = 0
        total_used = 0
        for row in cur.fetchall():
            cat, count, used = row
            print(f"{cat:<15} {count:<10} {used or 0:<12}")
            total += count
            total_used += (used or 0)

        print("-"*60)
        print(f"{'TOTAL':<15} {total:<10} {total_used:<12}")
        print("="*60)

    except Exception as e:
        logger.error(f"Error listing messages: {e}")

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def preview_messages():
    """Preview some sample messages"""
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        categories = ['journey', 'technology', 'observation', 'mystery', 'corrupted']

        print("\n" + "="*70)
        print("SAMPLE ECHO MESSAGES")
        print("="*70)

        for cat in categories:
            cur.execute("""
                SELECT message_text FROM pilgrim.signal_messages
                WHERE category = %s ORDER BY RANDOM() LIMIT 1
            """, (cat,))
            row = cur.fetchone()
            if row:
                print(f"\n[{cat.upper()}]")
                print(f'"{row[0]}"')

        print("\n" + "="*70)

    except Exception as e:
        logger.error(f"Error previewing messages: {e}")

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Generate Echo Messages for the Crystal Network')
    parser.add_argument('--list', action='store_true', help='List message statistics')
    parser.add_argument('--seed', action='store_true', help='Seed messages into database')
    parser.add_argument('--preview', action='store_true', help='Preview sample messages')
    args = parser.parse_args()

    if args.list:
        list_echo_messages()
    elif args.preview:
        preview_messages()
    elif args.seed:
        print("\n" + "="*60)
        print("SEEDING ECHO MESSAGES")
        print("="*60)
        print(f"\nThe Architects' story in {len(ECHO_MESSAGES)} fragments:")
        print("-"*60)

        inserted = seed_echo_messages()

        if inserted > 0:
            print("\n✅ Echo Messages seeded successfully!")
            print("\nNext: Create the /signal route and template")
    else:
        parser.print_help()
        print("\n💡 Quick start: python tools/generate_echo_messages.py --seed")
