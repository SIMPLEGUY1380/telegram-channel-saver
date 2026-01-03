"""
Migration module for converting shared data to per-account structure.
Handles the transition from legacy single-database layout to per-account directories.
"""
import os
import json
import shutil
import logging
from datetime import datetime

from src.config import LEGACY_TEMP_DIR, LEGACY_VIDEO_DIR, LEGACY_EXPORT_DIR, ACCOUNTS_BASE_DIR
from src.account import AccountPaths

logger = logging.getLogger(__name__)


def needs_migration() -> bool:
    """
    Check if legacy data exists that needs migration.

    Returns:
        bool: True if legacy database exists and has unmigrated accounts
    """
    legacy_db = os.path.join(LEGACY_TEMP_DIR, 'database.json')

    if not os.path.exists(legacy_db):
        return False

    # Check if we have any sessions in legacy database that need migration
    try:
        with open(legacy_db, 'r') as f:
            db = json.load(f)
        sessions = db.get('sessions', {})
        if not sessions:
            return False

        # Check if at least one session still needs migration
        for phone in sessions.keys():
            account_db = os.path.join(ACCOUNTS_BASE_DIR, phone, 'database.json')
            if not os.path.exists(account_db):
                # Found an unmigrated account
                return True

        # All accounts already migrated
        return False
    except (json.JSONDecodeError, IOError):
        return False


def get_accounts_from_legacy_db() -> list:
    """
    Extract phone numbers from legacy database.

    Returns:
        list: List of phone numbers found in sessions
    """
    legacy_db_path = os.path.join(LEGACY_TEMP_DIR, 'database.json')
    if not os.path.exists(legacy_db_path):
        return []

    try:
        with open(legacy_db_path, 'r') as f:
            db = json.load(f)
        return list(db.get('sessions', {}).keys())
    except (json.JSONDecodeError, IOError):
        return []


def migrate_account(phone: str, legacy_db: dict) -> bool:
    """
    Migrate data for a single account to new structure.

    Args:
        phone: Phone number
        legacy_db: Loaded legacy database dict

    Returns:
        bool: True if successful
    """
    logger.info(f"Migrating account: {phone}")

    # Create account paths
    account = AccountPaths.for_phone(phone)
    account.ensure_directories()

    # Create per-account database
    account_db = {
        'users': {},
        'last_login': None,
        'sessions': {},
        'active_channel': None,
        'messages': {},
        'videos': {}
    }

    # Copy session info for this account
    if phone in legacy_db.get('sessions', {}):
        account_db['sessions'][phone] = legacy_db['sessions'][phone]
        account_db['sessions'][phone]['active'] = True

        if legacy_db.get('last_login', {}).get('phone') == phone:
            account_db['last_login'] = legacy_db['last_login']

    # Copy active_channel if it was set by this account (the active one)
    if legacy_db.get('active_channel') and legacy_db['sessions'].get(phone, {}).get('active'):
        account_db['active_channel'] = legacy_db['active_channel']

    # Copy messages (all shared data goes to each account)
    account_db['messages'] = legacy_db.get('messages', {})

    # Copy users
    account_db['users'] = legacy_db.get('users', {})

    # Copy videos
    account_db['videos'] = legacy_db.get('videos', {})

    # Save per-account database
    with open(account.database_path, 'w') as f:
        json.dump(account_db, f, indent=4, default=str)
    logger.info(f"Created account database at {account.database_path}")

    # Move session file
    legacy_session = os.path.join(LEGACY_TEMP_DIR, f'user_{phone}')
    legacy_session_journal = f"{legacy_session}-journal"

    if os.path.exists(legacy_session):
        shutil.copy2(legacy_session, account.session_path)
        logger.info(f"Copied session file to {account.session_path}")

    if os.path.exists(legacy_session_journal):
        shutil.copy2(legacy_session_journal, f"{account.session_path}-journal")

    # Copy videos (shared, so copy to all accounts)
    if os.path.exists(LEGACY_VIDEO_DIR):
        video_count = 0
        for filename in os.listdir(LEGACY_VIDEO_DIR):
            src = os.path.join(LEGACY_VIDEO_DIR, filename)
            dst = os.path.join(account.videos_dir, filename)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                video_count += 1
        if video_count > 0:
            logger.info(f"Copied {video_count} video files to {account.videos_dir}")

    # Copy exports (shared, so copy to all accounts)
    if os.path.exists(LEGACY_EXPORT_DIR):
        export_count = 0
        for item in os.listdir(LEGACY_EXPORT_DIR):
            src = os.path.join(LEGACY_EXPORT_DIR, item)
            dst = os.path.join(account.exports_dir, item)
            if not os.path.exists(dst):
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                    export_count += 1
                elif os.path.isdir(src):
                    shutil.copytree(src, dst)
                    export_count += 1
        if export_count > 0:
            logger.info(f"Copied {export_count} export items to {account.exports_dir}")

    logger.info(f"Account {phone} migrated successfully")
    return True


def run_migration() -> dict:
    """
    Run full migration from legacy to per-account structure.

    Returns:
        dict: Migration results with 'success', 'accounts_migrated', and 'errors'
    """
    results = {
        'success': True,
        'accounts_migrated': [],
        'errors': []
    }

    if not needs_migration():
        logger.info("No migration needed")
        return results

    print("Starting migration from legacy format to per-account structure...")

    # Load legacy database
    legacy_db_path = os.path.join(LEGACY_TEMP_DIR, 'database.json')
    try:
        with open(legacy_db_path, 'r') as f:
            legacy_db = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load legacy database: {e}")
        results['success'] = False
        results['errors'].append({'phone': 'N/A', 'error': f'Failed to load legacy database: {e}'})
        return results

    # Get accounts to migrate
    accounts = get_accounts_from_legacy_db()

    if not accounts:
        logger.warning("No accounts found in legacy database")
        return results

    print(f"Found {len(accounts)} account(s) to migrate")

    # Migrate each account (skip already migrated ones)
    for phone in accounts:
        account_db_path = os.path.join(ACCOUNTS_BASE_DIR, phone, 'database.json')
        if os.path.exists(account_db_path):
            logger.info(f"Account {phone} already migrated, skipping")
            print(f"  Account {phone} already migrated, skipping")
            continue

        try:
            print(f"  Migrating account: {phone}...")
            migrate_account(phone, legacy_db)
            results['accounts_migrated'].append(phone)
            print(f"  Account {phone} migrated successfully")
        except Exception as e:
            logger.error(f"Failed to migrate account {phone}: {e}")
            results['errors'].append({'phone': phone, 'error': str(e)})
            results['success'] = False

    # Backup legacy data
    if results['accounts_migrated']:
        backup_legacy_data()

    return results


def backup_legacy_data():
    """Backup legacy database before cleanup"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Backup legacy database
    legacy_db = os.path.join(LEGACY_TEMP_DIR, 'database.json')
    if os.path.exists(legacy_db):
        backup_path = os.path.join(LEGACY_TEMP_DIR, f'database_backup_{timestamp}.json')
        try:
            shutil.copy2(legacy_db, backup_path)
            logger.info(f"Legacy database backed up to {backup_path}")
            print(f"  Legacy database backed up to {backup_path}")

            # Rename original to indicate it's been migrated
            # Use shutil.move for cross-filesystem compatibility
            migrated_path = os.path.join(LEGACY_TEMP_DIR, 'database_migrated.json')

            # Remove existing migrated file if present to allow atomic replace
            if os.path.exists(migrated_path):
                os.remove(migrated_path)

            shutil.move(legacy_db, migrated_path)
            logger.info(f"Legacy database renamed to {migrated_path}")
        except OSError as e:
            logger.error(f"Failed to backup/rename legacy database: {e}")
            print(f"  Warning: Could not complete backup: {e}")
