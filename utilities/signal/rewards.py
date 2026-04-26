"""Legendary item + visitor reward image generation (Flux)."""

import logging
from typing import Dict, Any, List, Optional

from utilities.postgres.core import db_cursor

logger = logging.getLogger(__name__)


def _tier_for_rank(rank: int) -> str:
    """Map claim_rank to the tier key used in VISITOR_TIER_INCOME_BONUSES."""
    if rank == 1:
        return 'Founder'
    if 2 <= rank <= 3:
        return 'Early Witness'
    if 4 <= rank <= 10:
        return 'Pioneer'
    if 11 <= rank <= 42:
        return 'Pilgrim'
    return 'Wanderer'


def get_user_signal_income_bonuses(user_id: int) -> Dict[str, Any]:
    """Sum per-site hourly income bonuses across every Origin Site claim the
    captain holds — Founder (rank 1) or Visitor (rank 2+).

    Returns::

        {
          'shards_per_hour': float,
          'sv_per_hour': float,
          'sites_count': int,
          'per_tier': {tier_name: {'count': int, 'shards_per_hour': float,
                                    'sv_per_hour': float}, ...}
        }

    Used by utilities.infrastructure.income.calculate_accumulated_income to
    reflect the captain's Signal Network contribution on the Base homepage
    (Signal Phase 2 spec — Luke's hard requirement).
    """
    from utilities.signal.config import VISITOR_TIER_INCOME_BONUSES

    per_tier: Dict[str, Dict[str, Any]] = {}
    total_shards_per_hour = 0.0
    total_sv_per_hour = 0.0
    sites_count = 0

    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT claim_rank
                FROM pilgrim.site_claims
                WHERE user_id = %s AND site_type = 'origin'
            """, (user_id,))
            rows = cur.fetchall()

        for row in rows:
            rank = int(row['claim_rank'] or 99999)
            tier = _tier_for_rank(rank)
            bonus = VISITOR_TIER_INCOME_BONUSES.get(tier, {'shards_per_hour': 0, 'sv_per_hour': 0})
            total_shards_per_hour += bonus['shards_per_hour']
            total_sv_per_hour += bonus['sv_per_hour']
            sites_count += 1
            if tier not in per_tier:
                per_tier[tier] = {'count': 0, 'shards_per_hour': 0.0, 'sv_per_hour': 0.0}
            per_tier[tier]['count'] += 1
            per_tier[tier]['shards_per_hour'] += bonus['shards_per_hour']
            per_tier[tier]['sv_per_hour'] += bonus['sv_per_hour']
    except Exception as e:
        logger.warning(f"get_user_signal_income_bonuses({user_id}) failed: {e}")

    return {
        'shards_per_hour': round(total_shards_per_hour, 2),
        'sv_per_hour': round(total_sv_per_hour, 2),
        'sites_count': sites_count,
        'per_tier': per_tier,
    }


# ============================================================================
# LEGENDARY ITEM GENERATION
# ============================================================================

def generate_legendary_item_for_origin(
    site_id: int,
    founder_name: str,
    founder_wallet_prefix: str
) -> Optional[Dict]:
    """
    Generate the legendary item image for an Origin Site after it's claimed.
    This uses Flux to create a unique artifact and stores it in GCS.

    Called in a background thread after claim_origin_site() succeeds.

    Args:
        site_id: The origin site ID
        founder_name: The founder's commander name
        founder_wallet_prefix: The founder's wallet prefix (e.g., "0x570a")

    Returns:
        Dict with image_url and item details, or None on failure
    """
    try:
        # Get the site's legendary item definition
        with db_cursor() as cur:
            cur.execute("""
                SELECT site_code, legendary_item_name, legendary_item_description,
                       legendary_item_flux_prompt, legendary_item_image_url
                FROM pilgrim.origin_sites
                WHERE id = %s
            """, (site_id,))
            row = cur.fetchone()

        if not row:
            logger.error(f"Origin site {site_id} not found for legendary generation")
            return None

        site_code = row['site_code']
        item_name = row['legendary_item_name']
        item_description = row['legendary_item_description']
        flux_prompt = row['legendary_item_flux_prompt']
        existing_image = row['legendary_item_image_url']

        # If already has an image, skip generation
        if existing_image:
            logger.info(f"Legendary item for {site_code} already has image, skipping")
            return {
                'site_code': site_code,
                'item_name': item_name,
                'image_url': existing_image,
                'already_exists': True
            }

        if not flux_prompt:
            logger.error(f"No Flux prompt defined for {site_code}")
            return None

        logger.info(f"Generating legendary item image for {site_code}: {item_name}")

        # Generate the image using Flux
        from utilities.replicate_utils import FluxGenerator
        from utilities.google_cloud_storage_utils import upload_blob_from_url
        from config import FLUX_MODEL
        import time

        generator = FluxGenerator()

        # Build the founder inscription text
        # Format: "FOUNDED BY Andy ◆ 0x570a" engraved on the artifact
        founder_text = founder_name or "Unknown"
        if founder_wallet_prefix:
            founder_text = f"{founder_name} {founder_wallet_prefix}"

        # Append the engraving requirement to the Flux prompt
        # This ensures the text appears visibly engraved on the artifact
        engraved_prompt = f"{flux_prompt}, with clearly visible engraved golden text inscription reading 'FOUNDER: {founder_text}' carved prominently into the artifact surface, the text should be legible and stand out"

        logger.info(f"Flux prompt with engraving: {engraved_prompt[:100]}...")

        # Use the project's standard Flux model (flux-kontext-pro) with just a prompt
        # The prompt already follows the Mars-material aesthetic from CLAUDE.md
        try:
            from utilities.replicate_utils import _killswitched_run
            output = _killswitched_run(generator.client, FLUX_MODEL,
                                        {"prompt": engraved_prompt},
                                        feature='signal_reward_engrave')
        except Exception as e:
            logger.error(f"Flux generation failed for {site_code}: {e}")
            return None

        if not output:
            logger.error(f"Flux returned no output for {site_code}")
            return None

        # Get the image URL from Replicate
        if isinstance(output, list) and len(output) > 0:
            replicate_url = str(output[0])
        elif hasattr(output, 'url'):
            replicate_url = output.url
        else:
            replicate_url = str(output)

        logger.info(f"Flux generated image: {replicate_url[:60]}...")

        # Save to GCS with permanent URL
        timestamp = int(time.time())
        blob_name = f"legendary_items/{site_code.lower()}_{timestamp}.png"
        gcs_url = upload_blob_from_url(replicate_url, blob_name, content_type='image/png')

        if not gcs_url:
            logger.error(f"Failed to upload legendary item to GCS for {site_code}")
            return None

        logger.info(f"Legendary item saved to GCS: {gcs_url}")

        # Update the origin_sites record with the image URL
        # Also personalize the description with founder info
        personalized_description = item_description
        if founder_name:
            personalized_description = personalized_description.replace(
                '{founder_name}', founder_name
            )
        if founder_wallet_prefix:
            personalized_description = personalized_description.replace(
                '{founder_wallet}', founder_wallet_prefix
            )

        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE pilgrim.origin_sites
                SET legendary_item_image_url = %s,
                    legendary_item_description = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (gcs_url, personalized_description, site_id))

        logger.info(f"Legendary item for {site_code} complete: {item_name}")

        return {
            'site_code': site_code,
            'item_name': item_name,
            'item_description': personalized_description,
            'image_url': gcs_url,
            'already_exists': False
        }

    except Exception as e:
        logger.error(f"Failed to generate legendary item for site {site_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def get_user_origin_eligibility_payload(user_id) -> Dict:
    """Build the API response payload for GET /api/signal/user/origin_eligibility."""
    from utilities.signal.claims import get_user_origin_site_eligibility
    sites = get_user_origin_site_eligibility(user_id)
    claimable = [s for s in sites if s['can_claim']]
    return {
        'success': True,
        'sites': sites,
        'claimable_count': len(claimable),
        'claimable_sites': claimable,
    }


def get_legendary_item_payload(site_id: int) -> Dict:
    """Build the API response payload for GET /api/signal/origin/<id>/legendary."""
    item = get_origin_site_legendary_item(site_id)
    if not item:
        return {'success': False, 'error': 'Origin Site not found'}
    return {
        'success': True,
        'site_code': item['site_code'],
        'mission_name': item['mission_name'],
        'item_name': item['item_name'],
        'item_description': item['item_description'],
        'image_url': item['image_url'],
        'has_image': item['has_image'],
        'founder_name': item['founder_name'],
        'founder_wallet_prefix': item['founder_wallet_prefix'],
    }


def get_origin_site_legendary_item(site_id: int) -> Optional[Dict]:
    """
    Get the legendary item details for an Origin Site.
    Used by the Signal page and claim modal.
    """
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT site_code, mission_name, legendary_item_name,
                       legendary_item_description, legendary_item_image_url,
                       founder_commander_name, founder_wallet_prefix
                FROM pilgrim.origin_sites
                WHERE id = %s
            """, (site_id,))
            row = cur.fetchone()

        if not row:
            return None

        return {
            'site_code': row['site_code'],
            'mission_name': row['mission_name'],
            'item_name': row['legendary_item_name'],
            'item_description': row['legendary_item_description'],
            'image_url': row['legendary_item_image_url'],
            'founder_name': row['founder_commander_name'],
            'founder_wallet_prefix': row['founder_wallet_prefix'],
            'has_image': row['legendary_item_image_url'] is not None
        }

    except Exception as e:
        logger.error(f"Failed to get legendary item for site {site_id}: {e}")
        return None


def generate_visitor_reward_image(
    claim_id: int,
    commander_name: str,
    wallet_prefix: str,
    tier_name: str,
    flux_prompt: str,
    site_code: str
) -> Optional[Dict]:
    """
    Generate a unique Flux image for a visitor's reward item.
    Called in background thread after visit_origin_site() succeeds.
    """
    try:
        if not flux_prompt:
            logger.error(f"No Flux prompt for visitor reward {claim_id}")
            return None

        logger.info(f"Generating visitor reward image for {commander_name} at {site_code}")

        from utilities.replicate_utils import FluxGenerator
        from utilities.google_cloud_storage_utils import upload_blob_from_url
        from config import FLUX_MODEL
        import time

        generator = FluxGenerator()

        # Add visitor name to prompt for personalization
        visitor_text = commander_name
        if wallet_prefix:
            visitor_text = f"{commander_name} {wallet_prefix}"

        engraved_prompt = f"{flux_prompt}, with small engraved text '{visitor_text}' subtly visible on the surface"

        logger.info(f"Flux prompt: {engraved_prompt[:80]}...")

        try:
            from utilities.replicate_utils import _killswitched_run
            output = _killswitched_run(generator.client, FLUX_MODEL,
                                        {"prompt": engraved_prompt},
                                        feature='signal_reward_engrave')
        except Exception as e:
            logger.error(f"Flux generation failed for visitor {claim_id}: {e}")
            return None

        if not output:
            logger.error(f"Flux returned no output for visitor {claim_id}")
            return None

        # Get the image URL from Replicate
        if isinstance(output, list) and len(output) > 0:
            replicate_url = str(output[0])
        elif hasattr(output, 'url'):
            replicate_url = output.url
        else:
            replicate_url = str(output)

        logger.info(f"Flux generated image: {replicate_url[:60]}...")

        # Save to GCS
        timestamp = int(time.time())
        tier_slug = tier_name.lower().replace(' ', '_')
        blob_name = f"origin_visitor_rewards/{site_code.lower()}_{tier_slug}_{claim_id}_{timestamp}.png"
        gcs_url = upload_blob_from_url(replicate_url, blob_name, content_type='image/png')

        if not gcs_url:
            logger.error(f"Failed to upload visitor reward to GCS for claim {claim_id}")
            return None

        logger.info(f"Visitor reward saved to GCS: {gcs_url}")

        # Update site_claims with the image URL (we'll add this column)
        # For now, store in replicate_assets as a backup
        with db_cursor(commit=True) as cur:
            # Store in replicate_assets for inventory display
            cur.execute("""
                INSERT INTO pilgrim.replicate_assets
                (user_id, asset_type, gcs_url, gcs_blob_name, prompt_used, commander_name, created_at)
                SELECT user_id, 'origin_visit_reward', %s, %s, %s, %s, NOW()
                FROM pilgrim.site_claims WHERE id = %s
                RETURNING id
            """, (gcs_url, blob_name, engraved_prompt, commander_name, claim_id))
            asset_row = cur.fetchone()
            asset_id = asset_row['id'] if asset_row else None

        return {
            'claim_id': claim_id,
            'image_url': gcs_url,
            'asset_id': asset_id
        }

    except Exception as e:
        logger.error(f"Failed to generate visitor reward image: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
