#!/usr/bin/env python3
"""
create_new_caches.py
Creates pre-mined Sepolia wallets for the demo pool
Run this script to populate user_id=5 wallets that new users can claim
"""

import random
import time
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from utilities.sepolia_utils import MarsAsteroidMiner
from utilities.postgres.wallets import create_sepolia_wallet_for_user

# ============================================================================
# CONFIGURATION
# ============================================================================

NUMBER_OF_CACHES_TO_MAKE = 10
MIN_CACHE_SIZE = 0.00001  # Minimum Sepolia per cache (100 display units)
MAX_CACHE_SIZE = 0.00002  # Maximum Sepolia per cache (200 display units)
POOL_USER_ID = 5          # Anonymous pool user ID

# ============================================================================

def create_cache_pool():
    """Create a pool of pre-mined wallets for fast onboarding"""
    
    print("="*70)
    print("PILGRIM CACHE POOL CREATOR")
    print("="*70)
    print(f"Creating {NUMBER_OF_CACHES_TO_MAKE} pre-mined caches")
    print(f"Size range: {MIN_CACHE_SIZE} - {MAX_CACHE_SIZE} ETH")
    print(f"Pool user ID: {POOL_USER_ID}")
    print("="*70)
    
    # Initialize miner (uses Google Secret Manager internally)
    print("\nConnecting to Sepolia network...")
    miner = MarsAsteroidMiner()
    if not miner.connect():
        print("Failed to connect to Sepolia network")
        return
    print("Connected!\n")
    
    successful = 0
    failed = 0
    total_mined = 0.0
    
    for i in range(1, NUMBER_OF_CACHES_TO_MAKE + 1):
        print(f"{'='*70}")
        print(f"Cache {i}/{NUMBER_OF_CACHES_TO_MAKE}")
        print(f"{'='*70}")
        
        try:
            # Create wallet
            cache_name = f"pool-cache-{int(time.time())}-{i}"
            print(f"Creating wallet: {cache_name}")
            cache_result = miner.create_resource_cache(cache_name)
            
            if not cache_result['success']:
                print(f"Failed to create wallet: {cache_result.get('error')}")
                failed += 1
                continue
            
            wallet_address = cache_result['address']
            private_key = cache_result['private_key']
            print(f"Wallet created: {wallet_address}")
            
            # Determine random mining amount
            mine_amount = round(random.uniform(MIN_CACHE_SIZE, MAX_CACHE_SIZE), 8)
            display_amount = mine_amount * 10000000  # Convert to display units
            
            print(f"Mining {mine_amount} ETH ({display_amount:.1f} Sepolia display units)...")
            
            # Mine into wallet
            impact_result = miner.trigger_asteroid_impact(wallet_address)
            
            if not impact_result['success']:
                print(f"Mining failed: {impact_result.get('error')}")
                failed += 1
                continue
            
            actual_mined = impact_result['sepolia_collected']
            print(f"Mined: {actual_mined} ETH")
            print(f"TX: {impact_result['tx_hash']}")
            
            # Save to database (uses Google Secret Manager for DB credentials)
            mining_data = {
                'tx_hash': impact_result['tx_hash'],
                'block_number': impact_result.get('block_number'),
                'block_hash': impact_result.get('block_hash'),
                'block_timestamp': impact_result.get('block_timestamp'),
                'tx_index': impact_result.get('tx_index'),
                'from_address': impact_result.get('from_address'),
                'nonce': impact_result.get('nonce'),
                'gas_limit': impact_result.get('gas_limit'),
                'gas_used': impact_result.get('gas_used'),
                'gas_price_gwei': impact_result.get('gas_price_gwei'),
                'tx_fee_eth': impact_result.get('tx_fee_eth'),
                'max_fee_gwei': impact_result.get('max_fee_gwei'),
                'max_priority_gwei': impact_result.get('max_priority_gwei'),
                'base_fee_gwei': impact_result.get('base_fee_gwei'),
                'input_data_length': impact_result.get('input_data_length'),
                'decoded_message': impact_result.get('decoded_message'),
                'etherscan_tx_url': impact_result.get('etherscan_url'),
                'etherscan_wallet_url': f"https://sepolia.etherscan.io/address/{wallet_address}",
                'confirmations': impact_result.get('confirmations', 0)
            }
            
            wallet_id = create_sepolia_wallet_for_user(
                user_id=POOL_USER_ID,
                wallet_name=cache_name,
                wallet_address=wallet_address,
                wallet_private_key=private_key,
                initial_balance=actual_mined,
                campaign_id=None,
                custom_message="Pre-mined pool cache for fast onboarding",
                mining_data=mining_data
            )
            
            if wallet_id:
                print(f"Saved to database (ID: {wallet_id})")
                successful += 1
                total_mined += actual_mined
            else:
                print("Failed to save to database")
                failed += 1
            
            # Brief pause between mining operations
            if i < NUMBER_OF_CACHES_TO_MAKE:
                print("Waiting 3 seconds before next cache...\n")
                time.sleep(3)
                
        except Exception as e:
            print(f"Error creating cache: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    # Summary
    print("\n" + "="*70)
    print("POOL CREATION COMPLETE")
    print("="*70)
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total mined: {total_mined} ETH ({total_mined * 10000000:.1f} Sepolia)")
    print(f"\nPool ready for {successful} new users!")

if __name__ == "__main__":
    try:
        create_cache_pool()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)