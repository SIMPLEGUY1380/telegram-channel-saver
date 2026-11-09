"""
Telegram client management module.
Handles client initialization, authentication, and session management.
"""
import os
import logging
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import asyncio

from src.config import LEGACY_TEMP_DIR
from src.database import save_database

logger = logging.getLogger(__name__)

async def create_client(api_id, api_hash, session_path):
    """
    Create and initialize a Telegram client
    
    Args:
        api_id: Telegram API ID
        api_hash: Telegram API hash
        session_path: Path to session file
        
    Returns:
        TelegramClient: Initialized Telegram client
    """
    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()
    return client

async def check_authorized(client):
    """
    Check if the client is authorized
    
    Args:
        client: Telegram client
        
    Returns:
        bool: True if authorized, False otherwise
    """
    if not client:
        return False
    try:
        return await client.is_user_authorized()
    except Exception as e:
        logger.error(f"Error checking authorization: {e}")
        return False

async def login(client, phone, force=False):
    """
    Log in to Telegram
    
    Args:
        client: Telegram client
        phone: Phone number
        force: Force new login
        
    Returns:
        bool: True if login successful, False otherwise
    """
    if not await client.is_user_authorized():
        try:
            await client.send_code_request(phone)
            code = input('Enter the code you received: ')
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            # 2FA is enabled
            password = input('Please enter your 2FA password: ')
            await client.sign_in(password=password)
    
    # Get user info
    me = await client.get_me()
    return me

def get_session_path(phone):
    """
    Get full path to session file for given phone number.
    Uses new per-account directory structure.

    Args:
        phone: Phone number

    Returns:
        str: Path to session file
    """
    from src.account import AccountPaths
    return AccountPaths.for_phone(phone).session_path


def get_legacy_session_path(phone):
    """
    Get legacy session path for migration purposes.

    Args:
        phone: Phone number

    Returns:
        str: Path to legacy session file
    """
    return os.path.join(LEGACY_TEMP_DIR, f'user_{phone}')

async def save_session(db, phone, me):
    """
    Save current session info to database
    
    Args:
        db: Database
        phone: Phone number
        me: User info
    """
    if not phone:
        return
        
    # Update sessions info
    db['sessions'][phone] = {
        'session_file': f'user_{phone}',
        'created_at': db['sessions'].get(phone, {}).get('created_at', str(datetime.now())),
        'last_used': str(datetime.now()),
        'user_id': me.id,
        'username': me.username,
        'active': True
    }
    
    # Update last login
    db['last_login'] = {
        'phone': phone,
        'user_id': me.id,
        'username': me.username,
        'date': str(datetime.now())
    }
    
    # Deactivate other sessions
    for p in db['sessions']:
        if p != phone:
            db['sessions'][p]['active'] = False

async def restore_session(db, api_id, api_hash, db_path):
    """
    Try to restore last active session
    
    Args:
        db: Database
        api_id: Telegram API ID
        api_hash: Telegram API hash
        db_path: Path to database file
        
    Returns:
        tuple: (client, phone) tuple if successful, (None, None) otherwise
    """
    if not db.get('sessions'):
        return None, None
        
    # Find active session
    active_session = None
    active_phone = None
    
    for phone, session in db['sessions'].items():
        if session.get('active'):
            active_session = session
            active_phone = phone
            break
    
    if not active_session:
        return None, None

    # Try to restore session
    client = None
    try:
        phone = active_phone
        client = TelegramClient(
            get_session_path(phone),
            api_id,
            api_hash
        )
        
        await client.connect()
        if await check_authorized(client):
            # Update last used time
            me = await client.get_me()
            await save_session(db, phone, me)
            if db_path:
                save_database(db_path, db)
            logger.info(f"Restored session for {phone}")
            return client, phone
                
    except Exception as e:
        logger.error(f"Failed to restore session: {e}")
        if client:
            await client.disconnect()
            
    return None, None
