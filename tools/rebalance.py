#!/usr/bin/env python3
"""
Rebalance existing expedition_discoveries for DEV TESTING
Progressive system: Legendary in first 3 missions, then lockout until mission 10+
"""

import sys
import os
import random
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres.core import get_db_connection
from utilities.expedition_utils import calculate_enhanced_item_value

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Dev-friendly progressive distribution
def get_target_distribution(expedition_number: int) -> dict:
    """
    Returns target rarity percentages based on expedition number
    DEV MODE: Show all rarities early for testing
    """
    if expedition_number <= 3:
        # Early showcase: guarantee legendaries in first 3 missions
        return {
            'common': 0.50,      # 50% - will stack up (fine!)
            'uncommon': 0.25,    # 25%
            'rare': 0.15,        # 15% - guaranteed finds
            'legendary': 0.10    # 10% - test legendary mechanics
        }
    elif expedition_number <= 9:
        # Drought period: no legendaries to build anticipation
        return {
            'common': 0.75,      # 75% - stack up inventory
            'uncommon': 0.20,    # 20%
            'rare': 0.05,        # 5%
            'legendary': 0.00    # 0% - LOCKED OUT
        }
    else:
        # Mission 10+: legendaries return
        return {
            'common': 0.60,      # 60%
            'uncommon': 0.25,    # 25%
            'rare': 0.12,        # 12%
            'legendary': 0.03    # 3%
        }


def get_expedition_numbers_by_user():
    """Get expedition count per user to determine progression"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT user_id, COUNT(*) as expedition_count
            FROM pilgrim.expeditions
            GROUP BY user_id
            ORDER BY user_id
        """)
        
        user_expeditions = {row[0]: row[1] for row in cur.fetchall()}
        
        cur.close()
        conn.close()
        return user_expeditions
        
    except Exception as e:
        logger.error(f"Failed to get user expeditions: {e}")
        return {}


def get_current_distribution():
    """Check current rarity distribution of unclaimed discoveries"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT di.rarity, COUNT(ed.id) as count
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
            WHERE ed.claimed_by_user = false
            GROUP BY di.rarity
            ORDER BY 
                CASE di.rarity
                    WHEN 'legendary' THEN 1
                    WHEN 'rare' THEN 2
                    WHEN 'uncommon' THEN 3
                    WHEN 'common' THEN 4
                END
        """)
        
        results = cur.fetchall()
        total = sum(r[1] for r in results)
        
        logger.info(f"\n{'='*60}")
        logger.info("CURRENT DISTRIBUTION (Unclaimed Only)")
        logger.info(f"{'='*60}")
        for rarity, count in results:
            pct = (count / total * 100) if total > 0 else 0
            logger.info(f"{rarity:12} {count:5} ({pct:5.1f}%)")
        logger.info(f"{'='*60}")
        logger.info(f"TOTAL: {total}")
        
        cur.close()
        conn.close()
        return results, total
        
    except Exception as e:
        logger.error(f"Failed to get distribution: {e}")
        return [], 0


def get_available_items_by_rarity():
    """Get all available discovery items grouped by rarity"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, item_name, rarity, base_scientific_value, 
                   exploration_enhancement_value, stackable,
                   preferred_mars_features, min_distance_km, max_distance_km
            FROM pilgrim.discovery_items
            WHERE active = true
            ORDER BY rarity, item_name
        """)
        
        results = cur.fetchall()
        
        items_by_rarity = {'common': [], 'uncommon': [], 'rare': [], 'legendary': []}
        for row in results:
            item = {
                'id': row[0], 'item_name': row[1], 'rarity': row[2],
                'base_scientific_value': row[3], 'exploration_enhancement_value': row[4],
                'stackable': row[5], 'preferred_mars_features': row[6] or [],
                'min_distance_km': row[7], 'max_distance_km': row[8]
            }
            items_by_rarity[row[2]].append(item)
        
        logger.info(f"\nAvailable items by rarity:")
        for rarity, items in items_by_rarity.items():
            logger.info(f"  {rarity:12} {len(items)} items")
        
        cur.close()
        conn.close()
        return items_by_rarity
        
    except Exception as e:
        logger.error(f"Failed to get items: {e}")
        return {}


def rebalance_progressive(dry_run=True):
    """Rebalance using progressive system based on expedition number"""
    
    # Get user expedition counts
    user_expeditions = get_expedition_numbers_by_user()
    logger.info("\nUser expedition counts:")
    for user_id, count in user_expeditions.items():
        logger.info(f"  User {user_id}: {count} expeditions")
    
    # Get current state
    current_dist, total_discoveries = get_current_distribution()
    if total_discoveries == 0:
        logger.warning("No unclaimed discoveries found")
        return
    
    # Get available items
    items_by_rarity = get_available_items_by_rarity()
    if not any(items_by_rarity.values()):
        logger.error("No discovery items found in catalog")
        return
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get all unclaimed discoveries grouped by expedition
        cur.execute("""
            SELECT ed.id, ed.expedition_id, ed.discovery_item_id, ed.found_at_km,
                   ed.found_at_coordinates, ed.nearby_feature, ed.base_value,
                   e.distance_km, e.commander_exploration, e.user_id,
                   di.rarity,
                   ROW_NUMBER() OVER (PARTITION BY e.user_id ORDER BY e.departed_at) as expedition_number
            FROM pilgrim.expedition_discoveries ed
            JOIN pilgrim.expeditions e ON ed.expedition_id = e.id
            JOIN pilgrim.discovery_items di ON ed.discovery_item_id = di.id
            WHERE ed.claimed_by_user = false
            ORDER BY e.user_id, e.departed_at, ed.found_at_km
        """)
        
        discoveries = cur.fetchall()
        logger.info(f"\nFound {len(discoveries)} unclaimed discoveries to rebalance\n")
        
        # Group by expedition for progressive distribution
        by_expedition = {}
        for disc in discoveries:
            exp_id = disc[1]
            exp_num = disc[11]
            user_id = disc[9]
            
            if exp_id not in by_expedition:
                by_expedition[exp_id] = {
                    'expedition_number': exp_num,
                    'user_id': user_id,
                    'discoveries': []
                }
            by_expedition[exp_id]['discoveries'].append(disc)
        
        logger.info("Expedition breakdown:")
        for exp_id, data in by_expedition.items():
            logger.info(f"  Expedition {exp_id} (User {data['user_id']}, Mission #{data['expedition_number']}): {len(data['discoveries'])} items")
        
        changes = []
        
        # Rebalance each expedition according to its mission number
        for exp_id, exp_data in by_expedition.items():
            exp_num = exp_data['expedition_number']
            user_id = exp_data['user_id']
            exp_discoveries = exp_data['discoveries']
            
            # Get target distribution for this mission number
            target_dist = get_target_distribution(exp_num)
            
            logger.info(f"\nExpedition {exp_id} (Mission #{exp_num}):")
            logger.info(f"  Target: {target_dist}")
            
            # Calculate target counts
            total_items = len(exp_discoveries)
            target_counts = {
                rarity: int(total_items * pct)
                for rarity, pct in target_dist.items()
            }
            
            # Shuffle for randomness
            random.shuffle(exp_discoveries)
            
            # Assign rarities based on target distribution
            assigned = 0
            for rarity in ['legendary', 'rare', 'uncommon', 'common']:
                count_needed = target_counts[rarity]
                
                for i in range(count_needed):
                    if assigned >= len(exp_discoveries):
                        break
                    
                    disc = exp_discoveries[assigned]
                    disc_id, _, old_item_id, found_km, coords, feature, old_value, \
                        distance_km, exploration, _, old_rarity, _ = disc
                    
                    # Skip if already correct rarity
                    if old_rarity == rarity:
                        assigned += 1
                        continue
                    
                    # Select random item from target rarity
                    available = items_by_rarity[rarity]
                    if not available:
                        logger.warning(f"  No {rarity} items available")
                        assigned += 1
                        continue
                    
                    new_item = random.choice(available)
                    
                    # Recalculate enhanced value
                    enhanced = calculate_enhanced_item_value(
                        new_item['base_scientific_value'],
                        exploration,
                        new_item['exploration_enhancement_value']
                    )
                    
                    changes.append({
                        'discovery_id': disc_id,
                        'expedition_id': exp_id,
                        'expedition_number': exp_num,
                        'old_item_id': old_item_id,
                        'old_rarity': old_rarity,
                        'new_item_id': new_item['id'],
                        'new_rarity': rarity,
                        'new_item_name': new_item['item_name'],
                        'new_base_value': enhanced['base_value'],
                        'new_enhanced_value': enhanced['enhanced_value']
                    })
                    
                    assigned += 1
        
        logger.info(f"\n{'='*60}")
        logger.info(f"CHANGES TO APPLY: {len(changes)}")
        logger.info(f"{'='*60}")
        
        # Group changes by expedition for summary
        by_exp = {}
        for change in changes:
            exp_num = change['expedition_number']
            if exp_num not in by_exp:
                by_exp[exp_num] = []
            by_exp[exp_num].append(change)
        
        for exp_num in sorted(by_exp.keys()):
            exp_changes = by_exp[exp_num]
            logger.info(f"\nMission #{exp_num}: {len(exp_changes)} changes")
            for change in exp_changes[:5]:
                logger.info(f"  {change['old_rarity']:12} → {change['new_rarity']:12} | {change['new_item_name']}")
            if len(exp_changes) > 5:
                logger.info(f"  ... and {len(exp_changes) - 5} more")
        
        if dry_run:
            logger.info(f"\n{'='*60}")
            logger.info("DRY RUN - No changes applied")
            logger.info("Run with --execute to apply changes")
            logger.info(f"{'='*60}")
        else:
            logger.info(f"\n{'='*60}")
            logger.info("APPLYING CHANGES...")
            logger.info(f"{'='*60}")
            
            for change in changes:
                cur.execute("""
                    UPDATE pilgrim.expedition_discoveries
                    SET discovery_item_id = %s,
                        base_value = %s,
                        enhanced_value = %s
                    WHERE id = %s
                """, (
                    change['new_item_id'],
                    change['new_base_value'],
                    change['new_enhanced_value'],
                    change['discovery_id']
                ))
            
            conn.commit()
            logger.info(f"✅ Applied {len(changes)} changes")
        
        cur.close()
        conn.close()
        
        # Show new distribution
        if not dry_run:
            logger.info("\n")
            get_current_distribution()
        
    except Exception as e:
        logger.error(f"Failed to rebalance: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Rebalance expedition discoveries (progressive)")
    parser.add_argument('--execute', action='store_true', 
                       help='Actually apply changes (default is dry run)')
    
    args = parser.parse_args()
    
    logger.info(f"\n{'='*60}")
    logger.info("PROGRESSIVE EXPEDITION DISCOVERIES REBALANCER (DEV MODE)")
    logger.info(f"{'='*60}\n")
    
    rebalance_progressive(dry_run=not args.execute)