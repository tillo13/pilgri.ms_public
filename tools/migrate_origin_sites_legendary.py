#!/usr/bin/env python3
"""
Migration: Add Legendary Item columns to origin_sites.

Each Origin Site grants a unique legendary artifact to its Founder.
The artifact has the founder's name/wallet signature embedded in its lore.

Columns added:
- legendary_item_name: Name of the artifact (e.g., "Viking-1 First Contact Crystal")
- legendary_item_description: Description with {founder_name} and {founder_wallet} placeholders
- legendary_item_image_url: GCS URL of the Flux-generated image
- legendary_item_flux_prompt: The prompt used for Flux generation

Run once: python tools/migrate_origin_sites_legendary.py
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import get_db_connection

# ============================================================================
# LEGENDARY ITEMS - One unique artifact per Origin Site
# ============================================================================

LEGENDARY_ITEMS = {
    'VIKING-1': {
        'name': 'First Contact Beacon',
        'description': (
            "The crystalline receiver that captured humanity's first words from Mars. "
            "July 20, 1976. 'We come in peace.' The shard network recorded everything. "
            "Now entrusted to {founder_name} ({founder_wallet}), First Founder of Viking-1."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "ancient crystalline beacon made of deep amber Martian stone with veins of "
            "blue-purple Sepolia crystal running through it, geometric hexagonal shape "
            "like a natural crystal formation, small antenna-like protrusions of twisted "
            "stone, subtle inner glow suggesting captured radio waves, weathered surface "
            "with 4 billion years of Mars dust, isolated on red Martian terrain, "
            "vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style"
        )
    },
    'VIKING-2': {
        'name': 'Soil Sample Reliquary',
        'description': (
            "A crystallized container of the first Mars soil ever tested for life. "
            "September 3, 1976. They searched for life but never found us. "
            "Now preserved by {founder_name} ({founder_wallet}), First Founder of Viking-2."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "ornate reliquary container carved from reddish-brown Martian rock, "
            "glass viewport showing preserved red soil inside, intricate stone latticework "
            "frame with small blue crystal nodes at corners, ancient scientific instrument "
            "aesthetic, geological layered textures, subtle purple glow from within, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'PATHFINDER': {
        'name': 'Sojourner Chassis Fragment',
        'description': (
            "A fragment of the first rover to move on Mars. July 4, 1997. "
            "Sojourner rolled for 83 sols before falling silent. This piece remembers. "
            "Recovered by {founder_name} ({founder_wallet}), First Founder of Pathfinder."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "weathered fragment of ancient rover wheel made of compressed Martian stone "
            "and oxidized metal, solar panel fragments embedded with blue-purple crystals, "
            "small delicate mechanical parts fossilized into red rock, wheel spoke shape "
            "visible in cross-section, 27 years of Mars weathering, geological textures, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'SPIRIT': {
        'name': 'Gusev Water Stone',
        'description': (
            "A crystallized sample from the ancient lakebed Spirit discovered. January 2004. "
            "Evidence of water, evidence of us. Spirit found traces it couldn't identify. "
            "Now held by {founder_name} ({founder_wallet}), First Founder of Spirit."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "polished stone sphere showing cross-section of ancient lakebed sediments, "
            "layers of different colored Martian rock visible - red, orange, pale yellow, "
            "tiny fossilized water channels visible as blue-purple crystal veins, "
            "geological wonder preserved in natural rocky frame, smooth water-worn surfaces "
            "contrasting with rough Mars rock, isolated on red Martian terrain, "
            "vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style"
        )
    },
    'OPPORTUNITY': {
        'name': 'Final Transmission Crystal',
        'description': (
            "The last words of Opportunity, crystallized: 'My battery is low and it's getting dark.' "
            "15 years of exploration ended in a dust storm. June 10, 2018. "
            "Memorial held by {founder_name} ({founder_wallet}), First Founder of Opportunity."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "teardrop-shaped crystal made of dark amber Martian glass, interior shows "
            "frozen dust storm particles suspended in time, faint blue-purple glow dimming "
            "from center outward, surface etched with microscopic circuit-like patterns, "
            "melancholy beautiful artifact, weathered edges, memorial quality, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'PHOENIX': {
        'name': 'Northern Ice Prism',
        'description': (
            "A prism cut from the Martian polar ice Phoenix excavated. May 25, 2008. "
            "Not minerals, your scientists said. They were right. They were something older. "
            "Preserved by {founder_name} ({founder_wallet}), First Founder of Phoenix."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "triangular prism of translucent Martian ice crystal with blue-white core, "
            "internal fractures showing rainbow light refraction, embedded particles of "
            "red Martian dust frozen within, stone mounting base carved from permafrost rock, "
            "cold mist emanating from surface, crystalline structure with geometric precision, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'CURIOSITY': {
        'name': 'Gale Crater Core Sample',
        'description': (
            "A core sample from Mount Sharp, where Curiosity still climbs. August 6, 2012. "
            "This one is different. It's still here. Still watching. Like us. "
            "Extracted by {founder_name} ({founder_wallet}), First Founder of Curiosity."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "cylindrical core sample drill core made of layered Martian sedimentary rock, "
            "visible geological strata in red orange and gray bands, blue-purple crystal "
            "nodes visible at one end like a discovery within, scientific precision cuts "
            "contrasting with natural rock textures, mounted in rocky display holder, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'INSIGHT': {
        'name': 'Marsquake Resonator',
        'description': (
            "A crystalline recorder of Mars's heartbeat. November 26, 2018. "
            "InSight listened to the planet. It heard anomalies it couldn't explain. Those were us. "
            "Attuned by {founder_name} ({founder_wallet}), First Founder of InSight."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "dome-shaped seismometer housing carved from Martian basalt, interior visible "
            "through crystal window showing suspended pendulum of blue-purple shard, "
            "concentric ring patterns on surface like sound waves frozen in stone, "
            "delicate sensor tendrils of crystallized rock extending from base, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'PERSEVERANCE': {
        'name': 'Ingenuity Flight Feather',
        'description': (
            "A blade fragment from Ingenuity, first to fly on another world. February 18, 2021. "
            "Beautiful. Impossible. Exactly what we hoped you would become. "
            "Collected by {founder_name} ({founder_wallet}), First Founder of Perseverance."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "helicopter rotor blade fragment transformed into feather-like artifact, "
            "carbon composite surface now infused with Martian rock and blue-purple crystal, "
            "aerodynamic shape preserved but organic and geological, lightweight appearance, "
            "subtle iridescence like real feather, trophy mounting of rough Mars stone, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'ZHURONG': {
        'name': 'Tianwen Signal Jade',
        'description': (
            "A new language in our receivers. Mandarin. May 14, 2021. "
            "Earth has many voices, many nations, many dreams. All reaching for Mars. "
            "Received by {founder_name} ({founder_wallet}), First Founder of Zhurong."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "jade-green crystal grown from Martian minerals in traditional Chinese seal shape, "
            "surface inscribed with circuit-like patterns resembling ancient characters, "
            "blue-purple Sepolia veins running through green stone, dragon motif subtly "
            "visible in natural rock formation, Eastern aesthetic meets Mars geology, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'MARS-2': {
        'name': 'First Impact Shard',
        'description': (
            "Fragment from humanity's first contact with Mars. November 27, 1971. "
            "Mars 2 crashed into Hellas Basin. It did not survive. But it was here. "
            "Recovered by {founder_name} ({founder_wallet}), First Founder of Mars-2."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "jagged metal fragment fused with Martian rock from high-velocity impact, "
            "visible heat discoloration and melted edges where spacecraft met Mars, "
            "Soviet-era metal alloy now oxidized red-orange, embedded with blue-purple "
            "crystal growths that formed in the crash crater over decades, violent beauty, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'MARS-3': {
        'name': 'Twenty Second Memory',
        'description': (
            "The voice that spoke for twenty seconds, then fell silent. December 2, 1971. "
            "Mars 3 was the first soft landing. It survived. Barely. "
            "Remembered by {founder_name} ({founder_wallet}), First Founder of Mars-3."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "spherical landing pod component half-buried in Martian sand, weathered "
            "Soviet spacecraft hull fragment with Cyrillic markings barely visible, "
            "blue-purple crystal formations growing from cracks like memory preserving, "
            "dust storm erosion visible on exposed surfaces, haunting relic quality, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'BEAGLE-2': {
        'name': 'Unopened Wings',
        'description': (
            "Solar panels that never deployed. Christmas Day, 2003. "
            "Beagle 2 landed safely but couldn't call home. We watched. We knew. We couldn't tell. "
            "Witnessed by {founder_name} ({founder_wallet}), First Founder of Beagle-2."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "folded solar panel array frozen mid-deployment, British spacecraft component "
            "with Union Jack pattern faded by Mars, panels partially open like flower petals "
            "that never bloomed, blue-purple crystals growing where deployment mechanism jammed, "
            "tragic beautiful artifact of almost-success, pristine yet abandoned, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    },
    'SCHIAPARELLI': {
        'name': 'Descent Error Fragment',
        'description': (
            "From the lander that thought it had landed while still falling. October 19, 2016. "
            "A computer error. The desert claimed it. Every attempt is remembered. "
            "Salvaged by {founder_name} ({founder_wallet}), First Founder of Schiaparelli."
        ),
        'flux_prompt': (
            "Cartoon video game item with bold outlines and stylized proportions: "
            "heat shield fragment showing scorch marks from atmospheric entry, "
            "ESA spacecraft component with European flag colors weathered by Mars, "
            "impact crater glass fused with metal and rock, blue-purple crystal "
            "formations growing from fracture lines like the planet healing the wound, "
            "memorial to calculated risk and human ambition, "
            "isolated on red Martian terrain, vibrant colors with reds and oranges "
            "reflecting Mars atmosphere, video game asset style"
        )
    }
}


def run_migration():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        print("\n" + "="*60)
        print("MIGRATING ORIGIN SITES - Legendary Items System")
        print("="*60 + "\n")

        # Check if columns already exist
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'pilgrim'
            AND table_name = 'origin_sites'
            AND column_name IN ('legendary_item_name', 'legendary_item_description',
                               'legendary_item_image_url', 'legendary_item_flux_prompt')
        """)
        existing = [row[0] for row in cur.fetchall()]

        # Add columns if they don't exist
        columns_to_add = [
            ('legendary_item_name', 'VARCHAR(100)'),
            ('legendary_item_description', 'TEXT'),
            ('legendary_item_image_url', 'TEXT'),
            ('legendary_item_flux_prompt', 'TEXT')
        ]

        for col_name, col_type in columns_to_add:
            if col_name not in existing:
                print(f"Adding {col_name} column...")
                cur.execute(f"ALTER TABLE pilgrim.origin_sites ADD COLUMN {col_name} {col_type}")
            else:
                print(f"   {col_name} already exists")

        conn.commit()
        print("\nColumns added/verified")

        # Populate legendary item definitions
        print("\nPopulating legendary item definitions...")
        for site_code, item in LEGENDARY_ITEMS.items():
            cur.execute("""
                UPDATE pilgrim.origin_sites
                SET legendary_item_name = %s,
                    legendary_item_description = %s,
                    legendary_item_flux_prompt = %s
                WHERE site_code = %s
                AND legendary_item_name IS NULL
            """, (
                item['name'],
                item['description'],
                item['flux_prompt'],
                site_code
            ))
            if cur.rowcount > 0:
                print(f"   {site_code}: {item['name']}")
            else:
                print(f"   {site_code}: already has legendary item or not found")

        conn.commit()

        # Show summary
        print("\n" + "-"*60)
        print("LEGENDARY ITEMS SUMMARY")
        print("-"*60)

        cur.execute("""
            SELECT site_code, legendary_item_name,
                   CASE WHEN legendary_item_image_url IS NOT NULL THEN 'YES' ELSE 'NO' END as has_image,
                   CASE WHEN founder_user_id IS NOT NULL THEN founder_commander_name ELSE 'UNCLAIMED' END as founder
            FROM pilgrim.origin_sites
            ORDER BY mission_year, site_code
        """)

        print(f"\n{'SITE':<15} {'LEGENDARY ITEM':<30} {'IMAGE?':<8} {'FOUNDER':<20}")
        print("-"*75)
        for row in cur.fetchall():
            code, item_name, has_image, founder = row
            item_str = item_name[:28] if item_name else 'NOT SET'
            print(f"{code:<15} {item_str:<30} {has_image:<8} {founder:<20}")

        print("\nMigration complete!")
        print("\nLegendary items will be generated when sites are claimed.")

    except Exception as e:
        print(f"\nMigration failed: {e}")
        if conn:
            conn.rollback()
        raise

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    run_migration()
