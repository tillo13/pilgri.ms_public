#!/usr/bin/env python3
"""
Discovery Items Catalog Population Script
Generates Mars discovery items using Claude AI and stores them in the database.

Usage:
    python tools/populate_discovery_items.py
"""

import sys
import os
import json
import time
import logging

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.claude_utils import create_client
from utilities.postgres.core import get_db_connection
from utilities.google_secret_utils import get_credential_blob

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION - Adjust these values as needed
# ============================================================================

ITEMS_TO_GENERATE = 100

# Get Anthropic API key from Google Secret Manager (strip 0x prefix if present)
def get_anthropic_key():
    """Get Anthropic API key without hex prefix"""
    try:
        raw_key = get_credential_blob('KUMORI_ANTHROPIC_API_KEY')
        clean_key = raw_key.replace('0x', '').strip() if raw_key.startswith('0x') else raw_key.strip()
        return clean_key
    except Exception as e:
        logger.error(f"Failed to retrieve API key: {e}")
        raise

ANTHROPIC_API_KEY = get_anthropic_key()

PROMPT_TEMPLATE = """You are generating discoverable items for Pilgrims, a scientifically accurate Mars colony exploration game.

Generate a realistic Mars discovery item that matches these constraints:

ITEM TYPE: {item_type}
RARITY: {rarity}
MARS FEATURE TYPE: {mars_feature_type}
ITEM NUMBER: {item_number} of {total_items}

CRITICAL: Do NOT use these names (already exist): {existing_names}

{easter_egg_instructions}

Requirements:
1. Item must be scientifically plausible for Mars and this type of terrain
2. Name must be EXACTLY 2 words - short, evocative, player-friendly (not scientific jargon)
3. Description should be 1-2 sentences of immersive flavor text for players
4. description_for_flux must follow 2025 Flux best practices (see below)
5. Weight must be reasonable (0.1kg - 50kg for portable items, 0 for stationary finds)
6. Values should match rarity (see guidelines below)
7. This item can be found ANYWHERE but is more common in certain terrain types
8. Items should get progressively more interesting - item #{item_number} should be cooler than item #1

NAME EXAMPLES (2 words only):
- Good: "Crimson Shard", "Frozen Core", "Storm Glass", "Ancient Marker"
- Bad: "Iron-Rich Olivine Crystal", "Metamorphic Rock Sample", "CR-2491-B"

FLUX PROMPT BEST PRACTICES (description_for_flux):
- Must match cartoon video game art style (NOT photorealistic)
- Start with: "Cartoon video game item with bold outlines and stylized proportions:"
- Describe the item clearly and specifically
- Include Mars context: "on red Martian terrain" or "against Mars landscape background"
- Add style keywords: "vibrant colors", "bold outlines", "stylized", "video game asset"
- Color palette: "reds and oranges reflecting Mars atmosphere"
- Keep total length 40-80 words
- Natural language, not keyword soup

EXAMPLE GOOD FLUX PROMPTS:
"Cartoon video game item with bold outlines and stylized proportions: crystallized blue-green mineral shard with geometric facets, glowing faintly, resting on red Martian rocks, vibrant colors with reds and oranges of Mars atmosphere in background, video game asset style"

"Cartoon video game item with bold outlines and stylized proportions: ancient metallic device half-buried in rust-colored sand, weathered silver surface with alien markings, isolated on Mars terrain, vibrant Mars color palette, stylized video game art"

Rarity Value Guidelines:
- common: base_trade_value_eth: 0.000005-0.00002 (50-200 Sepolia), exploration_enhancement_value: 0.3-0.6
- uncommon: base_trade_value_eth: 0.00005-0.0001 (500-1000 Sepolia), exploration_enhancement_value: 0.7-1.0
- rare: base_trade_value_eth: 0.00015-0.0004 (1500-4000 Sepolia), exploration_enhancement_value: 1.1-1.5
- legendary: base_trade_value_eth: 0.0005-0.002 (5000-20000 Sepolia), exploration_enhancement_value: 1.6-2.0

Return ONLY valid JSON with NO markdown formatting, NO code blocks, NO explanations:
{{
  "item_name": "Two Words",
  "item_type": "{item_type}",
  "rarity": "{rarity}",
  "description": "Immersive 1-2 sentence discovery description for players",
  "description_for_flux": "Cartoon video game item with bold outlines and stylized proportions: [detailed description of item], on red Martian terrain, vibrant colors with reds and oranges reflecting Mars atmosphere, video game asset style",
  "weight_kg": 2.4,
  "stackable": true,
  "preferred_mars_features": ["{mars_feature_type}", "Crater", "Mons"],
  "min_distance_km": 0,
  "max_distance_km": 1000,
  "base_scientific_value": 65,
  "base_trade_value_eth": 0.00012,
  "exploration_enhancement_value": 0.85,
  "attributes": {{
    "potential_uses": ["construction", "research"],
    "mars_context": "Scientific context about this item type and where it's commonly found on Mars (reference terrain types, not specific locations)",
    "discovery_chance_weight": 15,
    "special_properties": ["property1"]
  }}
}}"""

# Item generation distribution
ITEM_TYPES = ['mineral', 'artifact', 'equipment', 'biological', 'data']
RARITIES = ['common', 'uncommon', 'rare', 'legendary']

# Rarity distribution weights
RARITY_WEIGHTS = {
    'common': 50,
    'uncommon': 30,
    'rare': 15,
    'legendary': 5
}

# ============================================================================
# DATABASE OPERATIONS - RARITY DISTRIBUTION
# ============================================================================

def get_existing_item_names():
    """Get all existing item names to avoid duplicates"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT item_name FROM pilgrim.discovery_items")
        
        names = set()
        for row in cur.fetchall():
            names.add(row[0])
        
        return names
        
    except Exception as e:
        logger.error(f"Error fetching existing names: {e}")
        return set()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def get_current_rarity_distribution():
    """Get current count of each rarity in the database"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT rarity, COUNT(*) 
            FROM pilgrim.discovery_items 
            GROUP BY rarity
        """)
        
        distribution = {'common': 0, 'uncommon': 0, 'rare': 0, 'legendary': 0}
        for row in cur.fetchall():
            distribution[row[0]] = row[1]
        
        return distribution
        
    except Exception as e:
        logger.error(f"Error fetching rarity distribution: {e}")
        return {'common': 0, 'uncommon': 0, 'rare': 0, 'legendary': 0}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def select_next_rarity():
    """
    Select next rarity based on maintaining target distribution percentages
    Target: 60% common, 25% uncommon, 12% rare, 3% legendary
    """
    current = get_current_rarity_distribution()
    total_current = sum(current.values())
    
    # Target percentages
    target_pct = {
        'common': 60.0,
        'uncommon': 25.0,
        'rare': 12.0,
        'legendary': 3.0
    }
    
    # Calculate current percentages
    current_pct = {}
    for rarity in ['common', 'uncommon', 'rare', 'legendary']:
        if total_current > 0:
            current_pct[rarity] = (current[rarity] / total_current) * 100
        else:
            current_pct[rarity] = 0
    
    # Find which rarity is most behind its target percentage
    best_rarity = 'common'
    best_deficit = -999
    
    for rarity in ['legendary', 'rare', 'uncommon', 'common']:  # Priority order
        deficit = target_pct[rarity] - current_pct[rarity]
        if deficit > best_deficit:
            best_deficit = deficit
            best_rarity = rarity
    
    logger.info("=" * 60)
    logger.info(f"CURRENT TOTAL: {total_current} items")
    logger.info(f"  Common:    {current['common']:3d} ({current_pct['common']:5.1f}% - target 60%)")
    logger.info(f"  Uncommon:  {current['uncommon']:3d} ({current_pct['uncommon']:5.1f}% - target 25%)")
    logger.info(f"  Rare:      {current['rare']:3d} ({current_pct['rare']:5.1f}% - target 12%)")
    logger.info(f"  Legendary: {current['legendary']:3d} ({current_pct['legendary']:5.1f}% - target 3%)")
    logger.info(f"SELECTING: {best_rarity.upper()} (deficit: {best_deficit:+.1f}%)")
    logger.info("=" * 60)
    
    return best_rarity

def get_random_mars_message():
    """Get random Mars mission message for rare/legendary item context"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT mission_name, message_text, latitude, longitude
            FROM pilgrim.mars_messages
            ORDER BY RANDOM()
            LIMIT 1
        """)
        
        result = cur.fetchone()
        if result:
            message_data = {
                'mission': result[0],
                'message': result[1],
                'lat': float(result[2]) if result[2] else None,
                'lon': float(result[3]) if result[3] else None
            }
            logger.info(f"🔮 Easter egg source: {message_data['mission']}")
            logger.info(f"   Message: {message_data['message'][:80]}...")
            return message_data
        return None
        
    except Exception as e:
        logger.error(f"Error fetching Mars message: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ============================================================================
# MARS LOCATION DATA FETCHING
# ============================================================================

def get_random_mars_feature_type():
    """Get random Mars feature type from mars_mappings table for variety"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get random feature TYPE (not specific location)
        # Use subquery to avoid DISTINCT + ORDER BY conflict
        cur.execute("""
            SELECT type
            FROM (
                SELECT DISTINCT type
                FROM pilgrim.mars_mappings
                WHERE type IS NOT NULL
            ) AS distinct_types
            ORDER BY RANDOM()
            LIMIT 1
        """)
        
        result = cur.fetchone()
        return result[0] if result else "Crater"
        
    except Exception as e:
        logger.error(f"❌ Error fetching Mars feature type: {e}")
        return "Crater"  # Fallback
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ============================================================================
# SCHEMA VALIDATION
# ============================================================================

REQUIRED_FIELDS = [
    'item_name', 'item_type', 'rarity', 'description', 'description_for_flux',
    'weight_kg', 'stackable', 'preferred_mars_features', 'min_distance_km',
    'base_scientific_value', 'base_trade_value_eth', 'exploration_enhancement_value',
    'attributes'
]

REQUIRED_ATTRIBUTE_FIELDS = [
    'potential_uses', 'mars_context', 'discovery_chance_weight'
]

def validate_item_json(item_data):
    """Validate that JSON matches expected schema"""
    
    # Check all required top-level fields
    for field in REQUIRED_FIELDS:
        if field not in item_data:
            raise ValueError(f"Missing required field: {field}")
    
    # Validate types
    if not isinstance(item_data['item_name'], str) or not item_data['item_name']:
        raise ValueError("item_name must be a non-empty string")
    
    # Validate 2-word name
    name_words = item_data['item_name'].strip().split()
    if len(name_words) != 2:
        raise ValueError(f"item_name must be exactly 2 words, got: '{item_data['item_name']}'")
    
    if item_data['item_type'] not in ITEM_TYPES:
        raise ValueError(f"item_type must be one of: {ITEM_TYPES}")
    
    if item_data['rarity'] not in RARITIES:
        raise ValueError(f"rarity must be one of: {RARITIES}")
    
    if not isinstance(item_data['weight_kg'], (int, float)) or item_data['weight_kg'] < 0:
        raise ValueError("weight_kg must be a non-negative number")
    
    if not isinstance(item_data['stackable'], bool):
        raise ValueError("stackable must be a boolean")
    
    if not isinstance(item_data['preferred_mars_features'], list):
        raise ValueError("preferred_mars_features must be an array")
    
    if not isinstance(item_data['base_trade_value_eth'], (int, float)) or item_data['base_trade_value_eth'] <= 0:
        raise ValueError("base_trade_value_eth must be a positive number")
    
    if not isinstance(item_data['exploration_enhancement_value'], (int, float)):
        raise ValueError("exploration_enhancement_value must be a number")
    
    # Validate attributes
    if not isinstance(item_data['attributes'], dict):
        raise ValueError("attributes must be an object")
    
    for attr_field in REQUIRED_ATTRIBUTE_FIELDS:
        if attr_field not in item_data['attributes']:
            raise ValueError(f"Missing required attribute field: {attr_field}")
    
    logger.info(f"✅ Validated: {item_data['item_name']}")
    return True

# ============================================================================
# ITEM GENERATION
# ============================================================================

def generate_item_with_claude(item_type, rarity, mars_feature_type, claude_client, item_number, total_items, mars_message=None, existing_names=None):
    """Generate a single item using Claude API with Mars feature type for context"""
    
    if existing_names is None:
        existing_names = set()
    
    # Format existing names for prompt (limit to 50 most recent to avoid token bloat)
    name_list = ", ".join(list(existing_names)[-50:]) if existing_names else "none"
    
    # Build Easter egg instructions based on rarity
    easter_egg_instructions = ""
    
    if rarity == 'common':
        easter_egg_instructions = """
COMMON ITEM INSTRUCTIONS:
- This is a COMMON natural Mars item - something any explorer might find
- Pure geology/chemistry - rocks, minerals, ice, dust, natural formations
- Scientific but mundane - iron oxide, basalt, frozen CO2, etc.
- NO hints of past civilization or missions
- Flux prompt: natural Mars materials in cartoon game style
"""
    
    elif rarity == 'uncommon':
        easter_egg_instructions = """
UNCOMMON ITEM EASTER EGG INSTRUCTIONS:
- This item should subtly suggest SOMEONE was here before (not aliens, but humans or predecessors)
- Make it ambiguous - could be natural but shows signs of past human/intelligent activity
- Examples: "tool marks on rock surface", "refined metal fragment", "processed material", "geometric patterns"
- NOT overtly mission-related, just... suspicious
- Flux prompt: include subtle hints like "weathered markings", "too-perfect edges", "organized structure"
- Make players wonder: "Did someone live here long ago?"
"""
    
    elif rarity == 'rare':
        if mars_message:
            easter_egg_instructions = f"""
RARE ITEM EASTER EGG INSTRUCTIONS:
This is a RARE item - directly tied to past Mars MISSIONS and their anomalies:
- Reference mission: {mars_message['mission']}
- Mission anomaly context: "{mars_message['message']}"
- This item is CLEARLY mission-related - fragments, equipment, readings from real missions
- Examples: "sensor housing with {mars_message['mission']} serial numbers", "sample with Viking instrument markings"
- Description should reference the mission by name and tie to their unexplained findings
- Flux prompt: include "mission logo", "technical markings", "{mars_message['mission']} insignia", "instrument fragments"
- Make it clear this is FROM the historical missions
"""
        else:
            easter_egg_instructions = """
RARE ITEM EASTER EGG INSTRUCTIONS:
This is a RARE item - Mars mission equipment/fragments:
- Make it clearly from past Mars missions (Viking, Spirit, Opportunity, etc.)
- Include mission markings, serial numbers, technical components
- Flux prompt: "mission logos", "technical inscriptions", "spacecraft fragments"
"""
    
    elif rarity == 'legendary':
        if mars_message:
            easter_egg_instructions = f"""
LEGENDARY ITEM EASTER EGG INSTRUCTIONS:
This is LEGENDARY - OBVIOUSLY ALIEN/NON-HUMAN technology or artifacts:
- Mission {mars_message['mission']} detected something impossible: "{mars_message['message']}"
- This item is the SOURCE or EVIDENCE of that alien/unexplained phenomenon
- CLEARLY not human, not natural - ancient alien civilization or technology
- Description: "glowing symbols", "impossible materials", "predates human civilization", "alien glyphs"
- Flux prompt MUST include: "alien symbols glowing", "otherworldly technology", "non-human craftsmanship", "ancient alien artifact"
- Make it UNMISTAKABLE that this is extraterrestrial
- Examples: "Artifact covered in glowing symbols that match no Earth language", "Device that operates despite being millions of years old"
"""
        else:
            easter_egg_instructions = """
LEGENDARY ITEM EASTER EGG INSTRUCTIONS:
This is LEGENDARY - make it OBVIOUSLY alien technology:
- Ancient alien civilization artifacts
- Glowing symbols, impossible geometry, materials that defy physics
- Flux prompt: "alien glyphs", "otherworldly technology", "extraterrestrial origin"
"""
    
    prompt = PROMPT_TEMPLATE.format(
        item_type=item_type,
        rarity=rarity,
        mars_feature_type=mars_feature_type,
        item_number=item_number,
        total_items=total_items,
        existing_names=name_list,
        easter_egg_instructions=easter_egg_instructions
    )
    
    try:
        logger.info(f"\n{'='*60}")
        logger.info(f"GENERATING ITEM {item_number}/{total_items}")
        logger.info(f"Type: {item_type.upper()} | Rarity: {rarity.upper()}")
        logger.info(f"Terrain: {mars_feature_type}")
        
        response = claude_client.generate_text(
            prompt=prompt,
            max_tokens=800,
            temperature=0.9
        )
        
        # Clean response (remove markdown if present)
        response_clean = response.strip()
        if response_clean.startswith('```json'):
            response_clean = response_clean.split('```json')[1].split('```')[0].strip()
        elif response_clean.startswith('```'):
            response_clean = response_clean.split('```')[1].split('```')[0].strip()
        
        # Parse JSON
        item_data = json.loads(response_clean)
        
        # Validate schema
        validate_item_json(item_data)
        
        return item_data
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON parsing error: {e}")
        logger.error(f"Response was: {response[:500]}")
        raise
    except ValueError as e:
        logger.error(f"❌ Validation error: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        raise

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

def insert_item_to_db(item_data):
    """Insert item into discovery_items table"""
    
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Prepare attributes as JSON string
        attributes_json = json.dumps(item_data['attributes'])
        
        cur.execute("""
            INSERT INTO pilgrim.discovery_items 
            (item_name, item_type, rarity, description, description_for_flux,
             weight_kg, stackable, preferred_mars_features, min_distance_km, max_distance_km,
             base_scientific_value, base_trade_value_eth, exploration_enhancement_value,
             attributes, image_url, gcs_blob_name, icon_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            item_data['item_name'],
            item_data['item_type'],
            item_data['rarity'],
            item_data['description'],
            item_data['description_for_flux'],
            item_data['weight_kg'],
            item_data['stackable'],
            item_data['preferred_mars_features'],
            item_data['min_distance_km'],
            item_data.get('max_distance_km'),
            item_data['base_scientific_value'],
            item_data['base_trade_value_eth'],
            item_data['exploration_enhancement_value'],
            attributes_json,
            None,  # image_url
            None,  # gcs_blob_name
            None   # icon_url
        ))
        
        item_id = cur.fetchone()[0]
        conn.commit()
        
        logger.info(f"✅ Inserted: {item_data['item_name']} (ID: {item_id}) - Common in {item_data['preferred_mars_features'][0]} terrain")
        return item_id
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Database error: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""
    
    logger.info("=" * 80)
    logger.info("DISCOVERY ITEMS CATALOG POPULATION")
    logger.info("=" * 80)
    
    # Check current state
    current_dist = get_current_rarity_distribution()
    current_total = sum(current_dist.values())
    remaining = ITEMS_TO_GENERATE - current_total
    
    if remaining <= 0:
        logger.info(f"Already have {current_total} items (target: {ITEMS_TO_GENERATE})")
        logger.info("Set ITEMS_TO_GENERATE higher or truncate table to continue")
        return
    
    logger.info(f"Current: {current_total} items | Target: {ITEMS_TO_GENERATE} items")
    logger.info(f"Will generate: {remaining} more items")
    logger.info("")
    
    # Get existing names to avoid duplicates
    existing_names = get_existing_item_names()
    logger.info(f"Loaded {len(existing_names)} existing item names to avoid duplicates")
    logger.info("")
    
    # Initialize Claude client with API key from Secret Manager
    try:
        claude_client = create_client(api_key=ANTHROPIC_API_KEY)
        logger.info("✅ Claude client initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Claude client: {e}")
        return
    
    # Generate items
    generated_items = []
    failed_attempts = 0
    max_failures = 20  # Increased for duplicate retries
    
    import random
    import time as time_module
    
    start_time = time_module.time()
    generation_times = []
    
    while len(generated_items) + current_total < ITEMS_TO_GENERATE and failed_attempts < max_failures:
        try:
            item_start_time = time_module.time()
            
            # Select item type
            item_type = random.choice(ITEM_TYPES)
            
            # Select rarity based on current distribution percentages
            rarity = select_next_rarity()
            
            # Get random Mars feature type for context (not specific location)
            mars_feature_type = get_random_mars_feature_type()
            
            # Get Mars message for rare/legendary items ONLY
            mars_message = None
            if rarity in ['rare', 'legendary']:
                mars_message = get_random_mars_message()
            
            # Generate item
            item_number = len(generated_items) + current_total + 1
            item_data = generate_item_with_claude(
                item_type, 
                rarity, 
                mars_feature_type, 
                claude_client,
                item_number,
                ITEMS_TO_GENERATE,
                mars_message,
                existing_names  # Pass existing names to avoid duplicates
            )
            
            # Check for duplicate name
            if item_data['item_name'] in existing_names:
                logger.warning(f"⚠️  Duplicate name generated: {item_data['item_name']} - retrying...")
                failed_attempts += 1
                time.sleep(1)
                continue
            
            # Insert to database
            item_id = insert_item_to_db(item_data)
            
            # Add to existing names set
            existing_names.add(item_data['item_name'])
            
            generated_items.append({
                'id': item_id,
                'name': item_data['item_name'],
                'rarity': item_data['rarity'],
                'type': item_data['item_type'],
                'terrain': item_data['preferred_mars_features'][0]
            })
            
            # Calculate timing
            item_time = time_module.time() - item_start_time
            generation_times.append(item_time)
            
            # Calculate ETA
            items_done = len(generated_items)
            items_remaining = ITEMS_TO_GENERATE - (current_total + items_done)
            
            if items_done > 0:
                avg_time = sum(generation_times) / len(generation_times)
                eta_seconds = avg_time * items_remaining
                eta_minutes = eta_seconds / 60
                
                logger.info(f"✅ SUCCESS: {item_data['item_name']} (ID: {item_id}) - took {item_time:.1f}s")
                logger.info(f"Progress: {current_total + items_done}/{ITEMS_TO_GENERATE} | Avg: {avg_time:.1f}s/item | ETA: {eta_minutes:.1f} min ({items_remaining} items left)\n")
            else:
                logger.info(f"✅ SUCCESS: {item_data['item_name']} (ID: {item_id})")
                logger.info(f"Progress: {current_total + items_done}/{ITEMS_TO_GENERATE}\n")
            
            # Rate limiting
            time.sleep(1)
            
        except Exception as e:
            failed_attempts += 1
            logger.error(f"Failed attempt {failed_attempts}/{max_failures}: {e}")
            logger.info("")
            time.sleep(2)
            continue
    
    # Summary
    logger.info("=" * 80)
    logger.info("GENERATION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Successfully generated: {len(generated_items)}/{ITEMS_TO_GENERATE} items")
    logger.info(f"Failed attempts: {failed_attempts}")
    logger.info("")
    
    if generated_items:
        logger.info("Generated Items:")
        for item in generated_items:
            logger.info(f"  • [{item['rarity'].upper()}] {item['name']} ({item['type']}) - Common in {item['terrain']}")
    
    if len(generated_items) < ITEMS_TO_GENERATE:
        logger.warning(f"⚠️  Only generated {len(generated_items)} of {ITEMS_TO_GENERATE} requested items")

if __name__ == "__main__":
    main()