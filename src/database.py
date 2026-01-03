"""
Database operations for the Telegram Channel Saver.
Handles loading, saving, and managing the JSON database.
"""
import os
import json
import logging
from datetime import datetime

from typing import Optional
from src.config import LEGACY_TEMP_DIR

logger = logging.getLogger(__name__)

def load_database(db_path):
    """
    Load database from JSON file or create new if doesn't exist
    
    Args:
        db_path: Path to the database file
        
    Returns:
        dict: Loaded database or new database structure
    """
    if os.path.exists(db_path):
        try:
            with open(db_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Corrupted database file, creating new")
            return create_new_database(db_path)
    return create_new_database(db_path)

def create_new_database(db_path):
    """
    Create new database structure
    
    Args:
        db_path: Path to save the new database
        
    Returns:
        dict: New empty database structure
    """
    db = {
        'users': {},
        'last_login': None,
        'sessions': {},
        'active_channel': None,
        'messages': {},
        'videos': {}
    }
    save_database(db_path, db)
    return db

def save_database(db_path, db):
    """
    Save database to JSON file
    
    Args:
        db_path: Path to save the database
        db: Database dictionary to save
    """
    with open(db_path, 'w') as f:
        json.dump(db, f, indent=4, default=str)

def get_db_path(phone: Optional[str] = None) -> str:
    """
    Get the path to the database file.

    Args:
        phone: Optional phone number for per-account database.
               If None, uses current account context or legacy path.

    Returns:
        str: Path to the database file
    """
    if phone:
        from src.account import AccountPaths
        return AccountPaths.for_phone(phone).database_path

    from src.account import AccountContext
    ctx = AccountContext.get_current()
    if ctx:
        return ctx.database_path

    # Legacy fallback
    return os.path.join(LEGACY_TEMP_DIR, 'database.json')


def get_legacy_db_path() -> str:
    """Get legacy database path for migration purposes"""
    return os.path.join(LEGACY_TEMP_DIR, 'database.json') 