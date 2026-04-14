"""
Sepolia Integration - Refactored for DRY principles
Handles all blockchain transactions with consistent patterns
"""
import os
import secrets
import time
import logging
import random
from datetime import datetime
from web3 import Web3
from eth_account import Account

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PILGRIM_MAX_TRANSACTION_ETH = 1.0
PILGRIM_ADDRESS = '0x82482c729cCDE2479cD0e303FA634fdc1759B9d3'

DEFAULT_SEPOLIA_RPCS = [
    "https://ethereum-sepolia.publicnode.com",
    "https://sepolia.gateway.tenderly.co",
    "https://rpc.sepolia.org",
    "https://1rpc.io/sepolia"
]
SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_ETHERSCAN_BASE = "https://sepolia.etherscan.io"

ASTEROID_MIN_SEPOLIA = 0.00001
ASTEROID_MAX_SEPOLIA = 0.00002

# Gas safety caps (Sepolia testnet)
MAX_BASE_FEE_GWEI = 200.0  # Sepolia can spike during congestion
MAX_PRIORITY_GWEI = 10.0
MAX_LEGACY_GWEI = 200.0

# ============================================================================
# ERROR SANITIZATION (hide blockchain details from users)
# ============================================================================

def sanitize_tx_error(raw_error: str) -> str:
    """
    Convert raw blockchain errors to user-friendly messages.
    Per CLAUDE.md: NEVER expose blockchain/crypto terms to users.
    """
    raw_lower = (raw_error or '').lower()

    if 'replacement transaction underpriced' in raw_lower or 'nonce' in raw_lower:
        return 'Transaction already in progress. Please wait a moment and try again.'
    if 'insufficient funds' in raw_lower:
        return 'Insufficient Sepolia shards for this operation.'
    if 'gas' in raw_lower:
        return 'Network is busy. Please try again in a few moments.'
    if 'timeout' in raw_lower or 'timed out' in raw_lower:
        return 'Request timed out. Please try again.'

    # Generic fallback - never show raw error
    return 'Unable to complete transaction. Please try again.'


# ============================================================================
# CRYPTIC MESSAGE SYSTEM
# ============================================================================

def append_cryptic_mars_message(base_message: str) -> str:
    """Append cryptic Mars mission message to transaction"""
    from utilities.postgres.shop import get_next_mars_message
    
    mars_message = get_next_mars_message()
    mars_text = mars_message['message_text'] if mars_message else random.choice([
        "Signal detected. Origin: Unknown.",
        "Anomaly logged. Investigation pending.",
        "Pattern recognized. Coordinates classified."
    ])
    
    styles = [
        ('[SYS_ERR_0x{:02X}]: {}', lambda: random.randint(0x10, 0xFF)),
        ('~~~SIGNAL_INTRUSION~~~{}~~~', None),
        ('<MEM_OVERFLOW>: {}</MEM_OVERFLOW>', None),
        ('|PKT_FRGMT_{:02d}|{}|END|', lambda: random.randint(10, 99)),
        ('>>DEBUG_LOG: {}<<DEBUG_END', None),
        ('+++BUFFER_APPEND+++{}+++', None),
        ('[UNAUTH_WRITE_0x{:04X}]: {}', lambda: random.randint(0x1000, 0xFFFF)),
        ('{{STACK_PUSH}}: {}{{/STACK}}', None),
        ('<!INT_0x{:02X}!>{}<!END_INT!>', lambda: random.randint(0x10, 0xFF)),
        ('//APPEND_ERR//{}//EOF//', None)
    ]
    
    format_template, value_func = random.choice(styles)
    formatted = format_template.format(value_func(), mars_text) if value_func else format_template.format(mars_text)
    
    return base_message + formatted

# ============================================================================
# SECURITY VALIDATION
# ============================================================================

ALLOWED_CONTEXTS = [
    "mining_spin", "mining_operation", "shop_purchase", "return_to_hub",
    "infrastructure_reward", "infrastructure_completion", "infrastructure_income",
    "mission_reward", "expedition_reward", "expedition_discovery", "expedition_launch",
    "discovery_analysis", "origin_claim", "echo_claim", "tech_complete",
    "aria_bond"
]

def validate_pilgrim_security(sender_address: str, amount_eth: float, context: str) -> tuple:
    """Validate pilgrim transactions"""
    sender_lower = sender_address.lower() if sender_address else ""
    pilgrim_lower = PILGRIM_ADDRESS.lower()
    
    if sender_lower == pilgrim_lower:
        try:
            amount_float = float(amount_eth)
        except (ValueError, TypeError):
            return False, f"Invalid amount format: {amount_eth}"
        
        if context not in ALLOWED_CONTEXTS:
            return False, f"Invalid context: {context}"
        
        if amount_float > PILGRIM_MAX_TRANSACTION_ETH:
            return False, f"Max: {PILGRIM_MAX_TRANSACTION_ETH} ETH, Requested: {amount_float} ETH"
        
        if amount_float <= 0 or amount_float > 5:
            return False, f"Invalid amount: {amount_float}"
        
        logger.info(f"✅ {context.upper()}: {amount_float} ETH validated")
        return True, f"Transaction validated: {amount_float} ETH"
    
    return True, "Non-pilgrim transaction, no additional limits"

# ============================================================================
# CONNECTION
# ============================================================================

class SepoliaConnector:
    """Handles connection to Sepolia network"""
    def __init__(self, rpc_endpoints=None, show_logs=True):
        self.rpc_endpoints = rpc_endpoints or DEFAULT_SEPOLIA_RPCS
        self.show_logs = show_logs
        self.w3 = None
    
    def connect(self):
        """Connect to Sepolia network"""
        for rpc in self.rpc_endpoints:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc))
                if w3.is_connected():
                    logger.info(f"✅ Sepolia connected: Block {w3.eth.block_number:,}, Gas {w3.from_wei(w3.eth.gas_price, 'gwei'):.1f} Gwei")
                    self.w3 = w3
                    return w3
            except Exception as e:
                logger.warning(f"⚠️  RPC {rpc[:30]}... failed: {str(e)[:50]}")
        logger.error("❌ Failed to connect to any Sepolia RPC")
        return None

# ============================================================================
# GAS ESTIMATION
# ============================================================================

class GasEstimator:
    """Handles gas estimation with safety caps"""
    def __init__(self, w3, show_logs=True):
        self.w3 = w3
        self.show_logs = show_logs
    
    def get_optimal_gas_price(self, use_dynamic=True, manual_gwei=1, speed="standard"):
        """Get optimal gas price with safety caps"""
        try:
            if use_dynamic:
                current_gas_price = self.w3.eth.gas_price
                
                # Try EIP-1559
                try:
                    fee_history = self.w3.eth.fee_history(10, 'latest', [25, 50, 75])
                    if fee_history and 'baseFeePerGas' in fee_history:
                        latest_base_fee = fee_history['baseFeePerGas'][-1]
                        priority_fees = [fee for rewards in fee_history['reward'] if rewards for fee in rewards]
                        
                        if priority_fees:
                            priority_fees.sort()
                            idx = len(priority_fees)//4 if speed == "slow" else len(priority_fees)*3//4 if speed == "fast" else len(priority_fees)//2
                            priority_fee = priority_fees[idx]
                            
                            max_fee_per_gas = latest_base_fee + priority_fee + (latest_base_fee // 2)
                            max_fee_per_gas = min(max_fee_per_gas, self.w3.to_wei(MAX_BASE_FEE_GWEI, 'gwei'))
                            priority_fee = min(priority_fee, self.w3.to_wei(MAX_PRIORITY_GWEI, 'gwei'))
                            
                            if self.show_logs:
                                logger.info(f"⚡ Gas (EIP-1559): Base={self.w3.from_wei(latest_base_fee, 'gwei'):.2f} gwei (capped to {MAX_BASE_FEE_GWEI})")
                            
                            return {'type': 'eip1559', 'maxFeePerGas': max_fee_per_gas, 'maxPriorityFeePerGas': priority_fee}
                except Exception as e:
                    if self.show_logs:
                        logger.warning(f"EIP-1559 failed, using legacy: {e}")
                
                # Legacy fallback
                multiplier = 1.0 if speed == "slow" else 1.5 if speed == "fast" else 1.25
                legacy_price = int(current_gas_price * multiplier)
                legacy_price = min(legacy_price, self.w3.to_wei(MAX_LEGACY_GWEI, 'gwei'))
                
                if self.show_logs:
                    logger.info(f"⚡ Gas (legacy): {self.w3.from_wei(legacy_price, 'gwei'):.2f} gwei (capped to {MAX_LEGACY_GWEI})")
                
                return {'type': 'legacy', 'gasPrice': legacy_price}
            else:
                manual_gwei = min(manual_gwei, MAX_LEGACY_GWEI)
                return {'type': 'legacy', 'gasPrice': self.w3.to_wei(manual_gwei, 'gwei')}
        
        except Exception as e:
            logger.error(f"Gas estimation failed: {e}")
            return {'type': 'legacy', 'gasPrice': self.w3.to_wei(1, 'gwei')}

# ============================================================================
# TRANSACTION MANAGEMENT
# ============================================================================

class TransactionManager:
    """Handles transaction creation and broadcasting"""
    def __init__(self, w3, show_logs=True):
        self.w3 = w3
        self.show_logs = show_logs
    
    def encode_message_to_hex(self, message):
        """Convert message to hex"""
        return '0x' + message.encode('utf-8').hex() if message else '0x'
    
    def estimate_gas_for_transaction(self, transaction_params):
        """Estimate gas limit"""
        try:
            estimated_gas = self.w3.eth.estimate_gas(transaction_params)
            return int(estimated_gas * 1.1)
        except:
            data_size = len(transaction_params.get('data', '0x'))
            return 21000 if data_size <= 2 else 25000 if data_size <= 100 else 30000 if data_size <= 500 else 35000
    


    def create_transfer_transaction(self, from_address, to_address, amount_eth, gas_config, custom_message=None, context="unknown"):
        """Create transfer transaction with balance checking"""
        is_valid, validation_msg = validate_pilgrim_security(from_address, amount_eth, context)
        if not is_valid:
            raise Exception(validation_msg)
        
        nonce = self.w3.eth.get_transaction_count(from_address)
        amount_wei = self.w3.to_wei(amount_eth, 'ether')
        message_with_cryptic = append_cryptic_mars_message(custom_message or "Transaction")
        input_data = self.encode_message_to_hex(message_with_cryptic)
        
        base_tx_params = {'from': from_address, 'to': to_address, 'value': amount_wei, 'data': input_data}
        estimated_gas = self.estimate_gas_for_transaction(base_tx_params)
        
        # Check balance before creating transaction
        if gas_config['type'] == 'eip1559':
            max_gas_cost = estimated_gas * gas_config['maxFeePerGas']
        else:
            max_gas_cost = estimated_gas * gas_config['gasPrice']
        
        total_cost = amount_wei + max_gas_cost
        current_balance = self.w3.eth.get_balance(from_address)
        
        if current_balance < total_cost:
            balance_eth = float(self.w3.from_wei(current_balance, 'ether'))
            amount_display_eth = float(self.w3.from_wei(amount_wei, 'ether'))
            gas_display_eth = float(self.w3.from_wei(max_gas_cost, 'ether'))
            total_display_eth = float(self.w3.from_wei(total_cost, 'ether'))

            # Convert to display units (1 ETH = 10,000,000 Sepolia)
            balance_display = balance_eth * 10000000
            amount_display = amount_display_eth * 10000000
            gas_display = gas_display_eth * 10000000
            total_display = total_display_eth * 10000000
            shortfall = total_display - balance_display

            raise Exception(
                f"Insufficient shards. Need {total_display:.0f} total "
                f"({amount_display:.0f} + {gas_display:.0f} ops fee). "
                f"You have {balance_display:.0f}, need {shortfall:.0f} more."
            )
        
        # Build transaction
        if gas_config['type'] == 'eip1559':
            return {
                'to': to_address, 'value': amount_wei, 'gas': estimated_gas,
                'maxFeePerGas': gas_config['maxFeePerGas'], 
                'maxPriorityFeePerGas': gas_config['maxPriorityFeePerGas'],
                'nonce': nonce, 'chainId': SEPOLIA_CHAIN_ID, 'data': input_data
            }
        else:
            return {
                'to': to_address, 'value': amount_wei, 'gas': estimated_gas,
                'gasPrice': gas_config['gasPrice'], 
                'nonce': nonce, 'chainId': SEPOLIA_CHAIN_ID, 'data': input_data
            }
        
    def sign_and_send_transaction(self, transaction, private_key, context="unknown", max_retries=3):
        """Sign and broadcast transaction with retry logic for nonce conflicts"""
        for attempt in range(max_retries):
            try:
                signed_txn = self.w3.eth.account.sign_transaction(transaction, private_key)
                raw_tx = getattr(signed_txn, 'rawTransaction', None) or getattr(signed_txn, 'raw_transaction', None)
                return self.w3.eth.send_raw_transaction(raw_tx).hex()
            except ValueError as e:
                error_msg = str(e)
                # Handle nonce conflicts by incrementing and retrying
                if 'replacement transaction underpriced' in error_msg or 'nonce too low' in error_msg:
                    if attempt < max_retries - 1:
                        # Get fresh nonce with pending transactions included
                        from_address = Account.from_key(private_key).address
                        new_nonce = self.w3.eth.get_transaction_count(from_address, 'pending')
                        transaction['nonce'] = new_nonce
                        logger.warning(f"⚠️ Nonce conflict on attempt {attempt + 1}, retrying with nonce {new_nonce}")
                        time.sleep(1)  # Brief delay before retry
                        continue
                raise  # Re-raise if not a nonce issue or out of retries
    
    def wait_for_confirmation(self, tx_hash, max_attempts=60, poll_interval=2):
        """Wait for transaction confirmation"""
        logger.info(f"⏳ Waiting for confirmation: {tx_hash}")
        for attempt in range(max_attempts):
            try:
                receipt = self.w3.eth.get_transaction_receipt(tx_hash)
                if receipt:
                    status = "✅ SUCCESS" if receipt['status'] == 1 else "❌ FAILED"
                    logger.info(f"{status} | Block: {receipt['blockNumber']} | Gas: {receipt['gasUsed']:,}")
                    return receipt
            except:
                pass
            if attempt % 10 == 0 and attempt > 0:
                logger.info(f"   Still waiting... {attempt * poll_interval}s elapsed")
            time.sleep(poll_interval)
        logger.warning(f"⚠️  Confirmation timeout after {max_attempts * poll_interval}s")
        return None

# ============================================================================
# MAIN CLASS
# ============================================================================

class MarsAsteroidMiner:
    """Handles all Sepolia transactions for Mars gameplay"""
    def __init__(self):
        self.connector = SepoliaConnector(show_logs=False)
        self.w3 = None
        self.gas_estimator = None
        self.transaction_manager = None
    
    def connect(self) -> bool:
        """Connect to Sepolia network"""
        self.w3 = self.connector.connect()
        if self.w3:
            self.gas_estimator = GasEstimator(self.w3, show_logs=False)
            self.transaction_manager = TransactionManager(self.w3, show_logs=False)
        return self.w3 is not None
    
    def create_resource_cache(self, cache_name: str) -> dict:
        """Create new Sepolia wallet"""
        try:
            private_key = "0x" + secrets.token_hex(32)
            account = Account.from_key(private_key)
            return {
                'success': True, 'cache_name': cache_name, 'address': account.address,
                'private_key': private_key, 'etherscan_url': f"{SEPOLIA_ETHERSCAN_BASE}/address/{account.address}",
                'short_address': f"{account.address[:10]}...{account.address[-4:]}"
            }
        except Exception as e:
            return {'success': False, 'error': sanitize_tx_error(str(e))}

    def check_cache_balance(self, address: str) -> float:
        """Check wallet balance"""
        try:
            if not self.w3 and not self.connect():
                return 0.0
            return float(self.w3.from_wei(self.w3.eth.get_balance(address), 'ether'))
        except Exception as e:
            logger.error(f"Failed to check balance for {address}: {e}")
            return 0.0
    
    def get_mars_atmospheric_conditions(self):
        """Get current Mars atmospheric conditions based on gas prices"""
        try:
            gas_gwei = float(self.w3.from_wei(self.w3.eth.gas_price, 'gwei'))
        except:
            gas_gwei = 2.0
        
        base_angle = 45.0
        solar_angle = max(15.0, min(75.0, base_angle + (gas_gwei - 2.0) * 3.2))
        
        if gas_gwei < 2:
            efficiency, condition, fee_multiplier = 98, "Optimal", 1.0
        elif gas_gwei < 5:
            efficiency, condition, fee_multiplier = 85, "Moderate Dust", 1.0 + (gas_gwei - 2) * 0.15
        elif gas_gwei < 10:
            efficiency, condition, fee_multiplier = 70, "Heavy Atmospheric Interference", 1.0 + (gas_gwei - 2) * 0.25
        elif gas_gwei < 20:
            efficiency, condition, fee_multiplier = 55, "Solar Storm Activity", 1.0 + (gas_gwei - 2) * 0.35
        else:
            efficiency, condition, fee_multiplier = 40, "Severe Atmospheric Disturbance", 1.0 + (gas_gwei - 2) * 0.45
        
        return {
            'gas_gwei': gas_gwei, 'solar_angle': round(solar_angle, 1), 'efficiency': efficiency,
            'condition': condition, 'fee_multiplier': fee_multiplier,
            'base_gas_cost_eth': float(self.w3.from_wei(self.w3.eth.gas_price * 21000, 'ether'))
        }
    
    def calculate_total_transaction_cost(self, base_cost_eth, from_address=None, message_length=200):
        """Calculate total transaction cost with atmospheric fees and gas"""
        if not self.w3:
            return {'success': False, 'error': 'Network not connected'}
        
        base_cost_eth = float(base_cost_eth)
        conditions = self.get_mars_atmospheric_conditions()
        atmospheric_fee = base_cost_eth * (conditions['fee_multiplier'] - 1.0)
        
        # Estimate gas
        base_gas = 21000
        if message_length > 0:
            data_gas = (message_length * 68)
            total_gas = base_gas + data_gas + 5000
        else:
            total_gas = base_gas
        
        gas_price = self.w3.eth.gas_price
        max_gas_price = self.w3.to_wei(2, 'gwei')
        gas_price = min(gas_price, max_gas_price)
        gas_cost_eth = float(self.w3.from_wei(total_gas * gas_price, 'ether'))
        
        total_cost_eth = base_cost_eth + atmospheric_fee + gas_cost_eth
        
        can_afford = True
        current_balance = 0.0
        if from_address:
            current_balance = float(self.w3.from_wei(self.w3.eth.get_balance(from_address), 'ether'))
            can_afford = current_balance >= total_cost_eth
        
        return {
            'success': True,
            'base_cost_eth': base_cost_eth,
            'base_cost_display': base_cost_eth * 10000000,
            'atmospheric_fee_eth': atmospheric_fee,
            'atmospheric_fee_display': atmospheric_fee * 10000000,
            'gas_cost_eth': gas_cost_eth,
            'gas_cost_display': gas_cost_eth * 10000000,
            'total_cost_eth': total_cost_eth,
            'total_cost_display': total_cost_eth * 10000000,
            'conditions': conditions,
            'estimated_gas_units': total_gas,
            'gas_price_gwei': float(self.w3.from_wei(gas_price, 'gwei')),
            'can_afford': can_afford,
            'current_balance_eth': current_balance,
            'current_balance_display': current_balance * 10000000,
            'shortfall_eth': max(0, total_cost_eth - current_balance) if from_address else 0,
            'shortfall_display': max(0, (total_cost_eth - current_balance) * 10000000) if from_address else 0
        }
    
    def send_sepolia_reward(self, to_address: str, amount_eth: float, message: str, context: str = "reward") -> dict:
        """Send Sepolia FROM pilgrim hub TO user (rewards)"""
        try:
            if not self.w3 and not self.connect():
                return {'success': False, 'error': 'Failed to connect'}
            
            from utilities.google_secret_utils import get_credential_blob
            pilgrim_key = get_credential_blob()
            if not pilgrim_key:
                return {'success': False, 'error': 'Mining pool not available'}
            
            display_amount = round(amount_eth * 10000000, 1)
            logger.info(f"💰 REWARD TX | {context.upper()} | {display_amount} Sepolia → {to_address[:10]}...")
            
            gas_config = self.gas_estimator.get_optimal_gas_price(use_dynamic=True, manual_gwei=1, speed='standard')
            transaction = self.transaction_manager.create_transfer_transaction(
                PILGRIM_ADDRESS, to_address, amount_eth, gas_config, message, context=context
            )
            tx_hash = self.transaction_manager.sign_and_send_transaction(transaction, pilgrim_key, context=context)
            
            logger.info(f"📡 Broadcast: {tx_hash}")
            receipt = self.transaction_manager.wait_for_confirmation(tx_hash, max_attempts=30, poll_interval=2)
            if not receipt:
                # Timeout - transaction is still pending, not failed
                logger.warning(f"⏳ Transaction pending (timeout): {tx_hash} - will likely confirm later")
                return {'success': True, 'pending': True, 'tx_hash': tx_hash,
                        'message': 'Transaction broadcast successfully, awaiting confirmation',
                        'etherscan_url': f"{SEPOLIA_ETHERSCAN_BASE}/tx/{tx_hash}"}
            if receipt['status'] != 1:
                logger.error(f"❌ Transaction reverted: {tx_hash}")
                return {'success': False, 'error': 'Transaction reverted on-chain', 'tx_hash': tx_hash}
            
            tx = self.w3.eth.get_transaction(tx_hash)
            target_balance = self.w3.from_wei(self.w3.eth.get_balance(to_address), 'ether')

            # Sync recipient's DB balance to match on-chain
            try:
                from utilities.postgres.wallets import update_sepolia_wallet_balance
                update_sepolia_wallet_balance(to_address, float(target_balance))
            except Exception as db_err:
                logger.warning(f"⚠️ DB balance sync failed (non-fatal): {db_err}")

            gas_price = tx.get('gasPrice', 0) or tx.get('maxFeePerGas', 0)
            tx_fee_wei = receipt['gasUsed'] * gas_price

            logger.info(f"✅ COMPLETE | New balance: {float(target_balance) * 10000000:.1f} Sepolia | {SEPOLIA_ETHERSCAN_BASE}/tx/{tx_hash}")
            
            return {
                'success': True, 'sepolia_collected': amount_eth, 'tx_hash': tx_hash,
                'target_balance': float(target_balance), 'etherscan_url': f"{SEPOLIA_ETHERSCAN_BASE}/tx/{tx_hash}",
                'message': message, 'block_number': receipt['blockNumber'],
                'gas_used': receipt['gasUsed'],
                'gas_price_gwei': float(self.w3.from_wei(gas_price, 'gwei')),
                'tx_fee_eth': float(self.w3.from_wei(tx_fee_wei, 'ether')),
                'confirmations': self.w3.eth.block_number - receipt['blockNumber']
            }
        except Exception as e:
            logger.error(f"❌ REWARD FAILED | {context} | {str(e)[:100]}")
            import traceback
            logger.error(traceback.format_exc())
            return {'success': False, 'error': sanitize_tx_error(str(e))}

    def send_sepolia_reward_fast(self, to_address: str, amount_eth: float, message: str, context: str = "reward") -> dict:
        """
        FAST version - broadcasts transaction and returns immediately.
        Does NOT wait for confirmation (that takes 30-60 seconds).
        Use this for UI responsiveness - confirmation happens in background.
        """
        try:
            if not self.w3 and not self.connect():
                return {'success': False, 'error': 'Failed to connect'}

            from utilities.google_secret_utils import get_credential_blob
            pilgrim_key = get_credential_blob()
            if not pilgrim_key:
                return {'success': False, 'error': 'Mining pool not available'}

            display_amount = round(amount_eth * 10000000, 1)
            logger.info(f"⚡ FAST REWARD TX | {context.upper()} | {display_amount} Sepolia → {to_address[:10]}...")

            gas_config = self.gas_estimator.get_optimal_gas_price(use_dynamic=True, manual_gwei=1, speed='standard')
            transaction = self.transaction_manager.create_transfer_transaction(
                PILGRIM_ADDRESS, to_address, amount_eth, gas_config, message, context=context
            )
            tx_hash = self.transaction_manager.sign_and_send_transaction(transaction, pilgrim_key, context=context)

            logger.info(f"📡 Broadcast (fast): {tx_hash} - NOT waiting for confirmation")

            # Return immediately - transaction is broadcast, will confirm in ~12 seconds
            return {
                'success': True,
                'broadcast': True,
                'tx_hash': tx_hash,
                'etherscan_url': f"{SEPOLIA_ETHERSCAN_BASE}/tx/{tx_hash}",
                'message': message,
                'sepolia_amount': display_amount
            }
        except Exception as e:
            logger.error(f"❌ FAST REWARD FAILED | {context} | {str(e)[:100]}")
            return {'success': False, 'error': sanitize_tx_error(str(e))}

    def return_to_hub(self, from_address: str, from_private_key: str, amount_eth: float, reason: str = "Shop purchase") -> dict:
        """Send Sepolia FROM user TO hub (depot purchases)"""
        try:
            if not self.w3 and not self.connect():
                return {'success': False, 'error': 'Failed to connect'}
            
            display_amount = round(amount_eth * 10000000, 1)
            logger.info(f"🛒 PURCHASE TX | {reason} | {display_amount} Sepolia | {from_address[:10]}... → Hub")
            
            gas_config = self.gas_estimator.get_optimal_gas_price(use_dynamic=True, speed='standard')
            transaction = self.transaction_manager.create_transfer_transaction(
                from_address, PILGRIM_ADDRESS, amount_eth, gas_config, 
                f"Return to Hub: {reason}", context="return_to_hub"
            )
            tx_hash = self.transaction_manager.sign_and_send_transaction(transaction, from_private_key, context="return_to_hub")
            
            logger.info(f"📡 Broadcast: {tx_hash}")
            receipt = self.transaction_manager.wait_for_confirmation(tx_hash, max_attempts=30, poll_interval=2)
            
            if not receipt or receipt['status'] != 1:
                logger.error(f"❌ PURCHASE FAILED | {reason} | Transaction failed")
                return {'success': False, 'error': 'Transaction failed or not confirmed', 'tx_hash': tx_hash}
            
            tx = self.w3.eth.get_transaction(tx_hash)
            gas_price = tx.get('gasPrice', 0) or tx.get('maxFeePerGas', 0)
            tx_fee_wei = receipt['gasUsed'] * gas_price
            
            logger.info(f"✅ PURCHASE COMPLETE | {reason} | {SEPOLIA_ETHERSCAN_BASE}/tx/{tx_hash}")
            
            return {
                'success': True,
                'tx_hash': tx_hash,
                'amount_returned': amount_eth,
                'etherscan_url': f"{SEPOLIA_ETHERSCAN_BASE}/tx/{tx_hash}",
                'block_number': receipt['blockNumber'],
                'gas_used': receipt['gasUsed'],
                'gas_price_gwei': float(self.w3.from_wei(gas_price, 'gwei')),
                'tx_fee_eth': float(self.w3.from_wei(tx_fee_wei, 'ether')),
                'confirmations': self.w3.eth.block_number - receipt['blockNumber']
            }
            
        except Exception as e:
            logger.error(f"❌ PURCHASE FAILED | {reason} | {str(e)[:100]}")
            import traceback
            logger.error(traceback.format_exc())
            return {'success': False, 'error': sanitize_tx_error(str(e))}

    def return_to_hub_with_reconciliation(self, from_address: str, from_private_key: str, 
                                        estimated_total_eth: float, base_cost_eth: float,
                                        reason: str = "Expedition") -> dict:
        """Send Sepolia FROM user TO hub with cost reconciliation (expeditions)"""
        try:
            if not self.w3 and not self.connect():
                return {'success': False, 'error': 'Failed to connect'}
            
            display_amount = round(estimated_total_eth * 10000000, 1)
            logger.info(f"🚀 EXPEDITION | {reason} | ~{display_amount} Sepolia | {from_address[:10]}...")
            
            gas_config = self.gas_estimator.get_optimal_gas_price(use_dynamic=True, speed='standard')
            transaction = self.transaction_manager.create_transfer_transaction(
                from_address, PILGRIM_ADDRESS, estimated_total_eth, gas_config, 
                f"Mars Expedition: {reason}", context="expedition_launch"
            )
            tx_hash = self.transaction_manager.sign_and_send_transaction(transaction, from_private_key, context="expedition_launch")
            
            logger.info(f"📡 Broadcast: {tx_hash}")
            receipt = self.transaction_manager.wait_for_confirmation(tx_hash, max_attempts=30, poll_interval=2)
            
            if not receipt or receipt['status'] != 1:
                logger.error(f"❌ Transaction failed: {tx_hash}")
                return {'success': False, 'error': 'Transaction failed', 'tx_hash': tx_hash}
            
            tx = self.w3.eth.get_transaction(tx_hash)
            gas_price = tx.get('gasPrice', 0) or tx.get('maxFeePerGas', 0)
            actual_gas_cost_eth = float(self.w3.from_wei(receipt['gasUsed'] * gas_price, 'ether'))
            
            estimated_atmospheric_fee_eth = estimated_total_eth - base_cost_eth - (estimated_total_eth * 0.00005)
            actual_atmospheric_overhead = estimated_total_eth - base_cost_eth - actual_gas_cost_eth
            atmospheric_difference_eth = actual_atmospheric_overhead - estimated_atmospheric_fee_eth
            atmospheric_diff_display = atmospheric_difference_eth * 10000000
            
            if atmospheric_diff_display < -10:
                reconciliation_msg = f"☀️ Optimal solar alignment reduced atmospheric costs by {abs(atmospheric_diff_display):.1f} Sepolia"
            elif atmospheric_diff_display > 10:
                reconciliation_msg = f"🌫️ Dust storm increased atmospheric processing by {atmospheric_diff_display:.1f} Sepolia"
            else:
                reconciliation_msg = "✓ Atmospheric conditions matched predictions"
            
            logger.info(f"✅ EXPEDITION LAUNCHED | {reconciliation_msg} | {SEPOLIA_ETHERSCAN_BASE}/tx/{tx_hash}")
            
            return {
                'success': True,
                'tx_hash': tx_hash,
                'amount_spent': estimated_total_eth,
                'etherscan_url': f"{SEPOLIA_ETHERSCAN_BASE}/tx/{tx_hash}",
                'block_number': receipt['blockNumber'],
                'gas_used': receipt['gasUsed'],
                'actual_gas_cost_eth': actual_gas_cost_eth,
                'actual_gas_cost_display': actual_gas_cost_eth * 10000000,
                'atmospheric_difference_display': atmospheric_diff_display,
                'reconciliation_message': reconciliation_msg,
                'confirmations': self.w3.eth.block_number - receipt['blockNumber']
            }
            
        except Exception as e:
            logger.error(f"❌ EXPEDITION FAILED | {reason} | {str(e)[:100]}")
            return {'success': False, 'error': sanitize_tx_error(str(e))}

    def fetch_and_decode_transaction(self, tx_hash: str) -> dict:
        """
        Fetch a transaction from Sepolia and decode its data field.
        Used by the Signal decoder to validate transaction-based puzzles.

        Returns:
            dict with 'success', 'decoded_data', 'from', 'to', etc.
        """
        # Test mode: 0x123 triggers test response
        if tx_hash == '0x123':
            return {
                'success': True,
                'tx_hash': tx_hash,
                'decoded_data': 'TEST://SIGNAL_DECODER_WORKING | This is a test transaction',
                'from': '0xTEST',
                'to': '0xTEST',
                'is_test': True
            }

        if not self.w3 and not self.connect():
            return {'success': False, 'error': 'Cannot connect to Sepolia network'}

        try:
            # Fetch the transaction
            tx = self.w3.eth.get_transaction(tx_hash)
            if not tx:
                return {'success': False, 'error': 'Transaction not found on Sepolia'}

            # Decode the input data (hex -> string)
            # Web3 may return HexBytes — convert to hex string first
            input_data = tx.get('input', '0x')
            if hasattr(input_data, 'hex'):
                input_data = '0x' + input_data.hex()
            else:
                input_data = str(input_data)
            decoded_data = ''

            if input_data and input_data != '0x':
                try:
                    hex_str = input_data[2:] if input_data.startswith('0x') else input_data
                    decoded_data = bytes.fromhex(hex_str).decode('utf-8', errors='ignore')
                except Exception as e:
                    logger.warning(f"Could not decode tx data: {e}")
                    decoded_data = f"[Could not decode data]"

            return {
                'success': True,
                'tx_hash': tx_hash,
                'decoded_data': decoded_data,
                'from': tx.get('from', ''),
                'to': tx.get('to', ''),
                'value_eth': float(self.w3.from_wei(tx.get('value', 0), 'ether')),
                'block_number': tx.get('blockNumber'),
                'etherscan_url': f"{SEPOLIA_ETHERSCAN_BASE}/tx/{tx_hash}"
            }

        except Exception as e:
            logger.error(f"Failed to fetch transaction {tx_hash}: {e}")
            return {'success': False, 'error': sanitize_tx_error(str(e))}

    def trigger_asteroid_impact(self, target_address: str) -> dict:
        """LEGACY: Initial asteroid mining (use send_sepolia_reward for new features)"""
        sepolia_amount = round(random.uniform(ASTEROID_MIN_SEPOLIA, ASTEROID_MAX_SEPOLIA), 8)
        display_amount = round(sepolia_amount * 100000, 1)
        
        message = (
            f"You've discovered something extraordinary on Mars—a crystalline mineral unknown to Earth. "
            f"The expedition logs call it Sepolia. You've just claimed {display_amount} units from this cache. "
            f"Ancient markers nearby suggest more deposits scattered across the red planet... "
            f"But the coordinates are fragmented. Keep exploring. "
        )
        
        return self.send_sepolia_reward(target_address, sepolia_amount, message, context="mining_operation")
    
    def calculate_atmospheric_pricing(self, base_cost_eth):
        """LEGACY: Use calculate_total_transaction_cost() instead"""
        return self.calculate_total_transaction_cost(base_cost_eth)
    

    def get_live_wallet_balance(self, wallet_address, fallback_balance=0):
        """
        Check live Sepolia balance and update database
        Pure blockchain + DB operation - no session logic
        """
        from utilities.postgres.wallets import update_sepolia_wallet_balance
        
        if not self.w3 and not self.connect():
            logger.warning(f"Network unavailable, using fallback: {fallback_balance}")
            return fallback_balance
        
        try:
            live_balance = self.check_cache_balance(wallet_address)
            update_sepolia_wallet_balance(wallet_address, live_balance)
            logger.info(f"✅ Live balance: {wallet_address[:10]}... = {live_balance * 10000000:.1f} Sepolia")
            return live_balance
        except Exception as e:
            logger.error(f"Live balance check failed for {wallet_address[:10]}...: {e}")
            return fallback_balance