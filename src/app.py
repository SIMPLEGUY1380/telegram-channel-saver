"""
Main application module for Telegram Channel Saver.
This is the entry point for the application.
"""
import json
import os
import shutil
import asyncio
import logging
from dotenv import load_dotenv
from datetime import datetime
from telethon import TelegramClient

from src.config import logger, LEGACY_TEMP_DIR, ACCOUNTS_BASE_DIR
from src.database import load_database, save_database, get_db_path, get_legacy_db_path
from src.migration import needs_migration, run_migration
from src.client import check_authorized, login, restore_session, save_session, get_session_path
from src.account import AccountContext, AccountPaths
from src.channels import list_channels, display_channels, select_active_channel, show_active_channel
from src.users import save_channel_users, show_channel_users_stats, list_saved_users
from src.messages import save_channel_messages, search_messages, browse_messages
from src.media import download_video_messages, list_downloaded_videos
from src.export import export_menu
from src.search_replace import search_replace_messages, restore_edited_messages, list_edited_messages


def validate_phone_number(phone: str) -> bool:
    """
    Validate phone number format.

    Args:
        phone: Phone number string to validate

    Returns:
        bool: True if valid, False otherwise
    """
    if not phone:
        return False

    # Remove common formatting characters
    cleaned = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

    # Must start with + for international format
    if not cleaned.startswith('+'):
        return False

    # Rest must be digits
    digits = cleaned[1:]
    if not digits.isdigit():
        return False

    # Phone numbers are typically 7-15 digits
    if len(digits) < 7 or len(digits) > 15:
        return False

    # Check for path traversal attempts
    if '..' in phone or '/' in phone or '\\' in phone:
        return False

    return True


class ChannelSaver:
    """Main application class for Telegram Channel Saver"""
    
    def __init__(self):
        """Initialize the application"""
        # Load environment variables from .env file
        load_dotenv()

        # Database will be loaded after account is determined
        self.db_path = None
        self.db = None
        self.account = None

        # Telegram client setup
        try:
            self.api_id = int(os.getenv('API_ID'))
            if not self.api_id:
                raise ValueError("API_ID not found in environment variables")

            self.api_hash = os.getenv('API_HASH')
            if not self.api_hash:
                raise ValueError("API_HASH not found in environment variables")

        except (TypeError, ValueError) as e:
            logger.error(f"Error loading API credentials: {e}")
            print("\nError: Please make sure API_ID and API_HASH are properly set in .env file")
            raise

        self.client = None
        self.phone = None

    def _setup_account(self, phone: str):
        """
        Set up account context and load account-specific database.

        Args:
            phone: Phone number for the account
        """
        # Set account context (creates directories if needed)
        self.account = AccountContext.set_account(phone)

        # Update paths for this account
        self.db_path = self.account.database_path
        self.db = load_database(self.db_path)

        logger.info(f"Account context set for {phone}")

    def _get_sessions_db(self):
        """
        Get database with sessions info for restore/switch operations.
        Uses legacy DB if it exists, otherwise scans accounts directory.

        Returns:
            dict: Database with sessions info
        """
        # First check legacy database
        legacy_path = get_legacy_db_path()
        if os.path.exists(legacy_path):
            return load_database(legacy_path)

        # Otherwise, build sessions from accounts directory
        sessions = {}

        if os.path.exists(ACCOUNTS_BASE_DIR):
            for phone in os.listdir(ACCOUNTS_BASE_DIR):
                account_dir = os.path.join(ACCOUNTS_BASE_DIR, phone)
                if os.path.isdir(account_dir):
                    db_file = os.path.join(account_dir, 'database.json')
                    if os.path.exists(db_file):
                        try:
                            with open(db_file, 'r') as f:
                                account_db = json.load(f)
                                if phone in account_db.get('sessions', {}):
                                    sessions[phone] = account_db['sessions'][phone]
                        except (json.JSONDecodeError, IOError) as e:
                            logger.debug(f"Could not load account database for {phone}: {e}")

        return {'sessions': sessions, 'last_login': None}

    async def cleanup_sessions(self):
        """Remove invalid sessions"""
        sessions_db = self._get_sessions_db()
        if not sessions_db.get('sessions'):
            print("\nNo sessions to clean up!")
            return

        print("\nChecking sessions validity...")
        invalid = []

        for phone, session in sessions_db['sessions'].items():
            # Skip current session
            if phone == self.phone:
                continue

            # Try to connect with session
            client = TelegramClient(
                get_session_path(phone),
                self.api_id,
                self.api_hash
            )

            try:
                await client.connect()
                if not await client.is_user_authorized():
                    invalid.append(phone)
            except Exception as e:
                logger.debug(f"Session check failed for {phone}: {e}")
                invalid.append(phone)
            finally:
                await client.disconnect()

        if invalid:
            print(f"\nFound {len(invalid)} invalid sessions")
            if input("Remove them? (y/N): ").lower() == 'y':
                for phone in invalid:
                    # Remove account directory
                    account_dir = os.path.join(ACCOUNTS_BASE_DIR, phone)
                    try:
                        if os.path.exists(account_dir):
                            shutil.rmtree(account_dir)
                            print(f"  Removed account directory: {phone}")
                    except OSError as e:
                        print(f"  Error removing {phone}: {e}")
                print("\nInvalid sessions removed!")
        else:
            print("\nAll sessions are valid!")

    async def list_sessions(self):
        """Display all saved sessions"""
        sessions_db = self._get_sessions_db()
        if not sessions_db.get('sessions'):
            print("\nNo saved sessions found!")
            return

        print("\nSaved Sessions:")
        print("--------------")
        for phone, session in sessions_db['sessions'].items():
            is_current = phone == self.phone
            status = "CURRENT" if is_current else ("active" if session.get('active') else "inactive")
            print(f"\nPhone: {phone} [{status}]")
            print(f"Username: @{session.get('username', 'N/A')}")
            print(f"Created: {session.get('created_at', 'N/A')}")
            print(f"Last used: {session.get('last_used', 'N/A')}")

    async def switch_session(self):
        """Switch to a different saved session"""
        # Get all available sessions
        sessions_db = self._get_sessions_db()
        if not sessions_db.get('sessions'):
            print("\nNo saved sessions found!")
            return False

        # Display available sessions
        print("\nAvailable Sessions:")
        print("------------------")
        for phone, session in sessions_db['sessions'].items():
            is_current = phone == self.phone
            status = "CURRENT" if is_current else ("active" if session.get('active') else "inactive")
            print(f"\nPhone: {phone} [{status}]")
            print(f"Username: @{session.get('username', 'N/A')}")
            print(f"Last used: {session.get('last_used', 'N/A')}")

        while True:
            phone = input("\nEnter phone number to switch to (or 0 to cancel): ")
            if phone == '0':
                return False

            if not validate_phone_number(phone):
                print("\nInvalid phone number format!")
                continue

            if phone in sessions_db['sessions']:
                # Disconnect current client if exists
                if self.client:
                    await self.client.disconnect()

                # Switch to new account context
                self.phone = phone
                self._setup_account(phone)

                # Create new client with selected session
                self.client = TelegramClient(
                    get_session_path(phone),
                    self.api_id,
                    self.api_hash
                )

                await self.client.connect()
                if await check_authorized(self.client):
                    # Update session info
                    me = await self.client.get_me()
                    await save_session(self.db, phone, me)
                    save_database(self.db_path, self.db)
                    print(f"\nSwitched to session: {phone}")
                    return True
                else:
                    print("\nSession is no longer valid!")
                    return False
            else:
                print("\nInvalid phone number!")

    async def start(self):
        """Main entry point"""
        print("\nWelcome to Channel Saver!")
        print("------------------------")

        # Check for legacy data migration
        if needs_migration():
            print("\nDetected legacy data format. Running migration...")
            result = run_migration()
            if result['success']:
                print(f"Migration complete! Migrated {len(result['accounts_migrated'])} account(s).")
            else:
                print("Migration had errors. Check logs for details.")
                for err in result['errors']:
                    print(f"  - {err['phone']}: {err['error']}")

        # Ensure clean start
        if self.client:
            await self.client.disconnect()
            self.client = None

        # Get sessions database for restore attempt
        sessions_db = self._get_sessions_db()

        # Try to restore session first
        self.client, self.phone = await restore_session(
            sessions_db, self.api_id, self.api_hash, None
        )
        if self.client:
            # Set up account context for restored session
            self._setup_account(self.phone)
            # Update session info in account-specific database
            me = await self.client.get_me()
            await save_session(self.db, self.phone, me)
            save_database(self.db_path, self.db)
            print(f"\nRestored session for {self.phone}")
            relogin = False
        else:
            relogin = True

        try:
            if relogin:
                # New login required
                while True:
                    self.phone = input('Please enter your phone number (international format, e.g. +1234567890): ')
                    if validate_phone_number(self.phone):
                        break
                    print("Invalid phone number format. Please use international format starting with +")

                # Set up account context first (creates directories)
                self._setup_account(self.phone)

                # Create new client
                self.client = TelegramClient(
                    get_session_path(self.phone),
                    self.api_id,
                    self.api_hash
                )

                await self.client.connect()
                me = await login(self.client, self.phone)

                # Save session after successful login
                await save_session(self.db, self.phone, me)
                save_database(self.db_path, self.db)

                logger.info(f"Successfully logged in as {me.first_name} (@{me.username})")
                
            print("\nSuccessfully connected!")
            
            while True:
                # Show active channel in menu if selected
                active_channel = self.db.get('active_channel')
                if active_channel:
                    print(f"\nActive: {active_channel['title']} ({active_channel['type']})")
                
                print("\nOptions:")
                print("1. Show account info")
                print("2. List channels/groups")
                print("3. Select active channel")
                print("4. Show active channel info")
                print("5. Save channel users")
                print("6. Show users statistics")
                print("7. List saved sessions")
                print("8. Switch session")
                print("9. Cleanup invalid sessions")
                print("10. Save channel messages")
                print("11. List saved users")
                print("12. Search messages")
                print("13. Browse message index")
                print("14. Search and replace in messages")
                print("15. Restore edited messages")
                print("16. List edited messages")
                print("17. Download videos")
                print("18. List downloaded videos")
                print("19. Export messages")
                print("20. Logout")
                print("21. Exit")

                choice = input("\nEnter your choice (1-21): ")
                
                if choice == '1':
                    me = await self.client.get_me()
                    print(f"\nAccount Information:")
                    print(f"Phone: {self.phone}")
                    print(f"Username: @{me.username}")
                    print(f"First Name: {me.first_name}")
                    print(f"Last Name: {me.last_name}")
                    print(f"User ID: {me.id}")
                elif choice == '2':
                    channels = await list_channels(self.client)
                    display_channels(channels)
                elif choice == '3':
                    await select_active_channel(self.client, self.db, self.db_path)
                elif choice == '4':
                    await show_active_channel(self.client, self.db)
                elif choice == '5':
                    await save_channel_users(self.client, self.db, self.db_path)
                elif choice == '6':
                    await show_channel_users_stats(self.db)
                elif choice == '7':
                    await self.list_sessions()
                elif choice == '8':
                    await self.switch_session()
                elif choice == '9':
                    await self.cleanup_sessions()
                elif choice == '10':
                    print("\nMessage Download Options:")
                    print("1. Download new messages only")
                    print("2. Force redownload all messages")
                    print("3. Download most recent messages")
                    print("4. Download messages by ID range")
                    print("5. Back to main menu")
                    
                    dl_choice = input("\nEnter choice (1-5): ")
                    
                    if dl_choice == '1':
                        limit = input("\nEnter number of messages to save (or press Enter for all): ")
                        limit = int(limit) if limit.strip() else None
                        await save_channel_messages(self.client, self.db, self.db_path, limit=limit, force_redownload=False)
                    elif dl_choice == '2':
                        confirm = input("\nThis will redownload all messages. Continue? (y/N): ").lower()
                        if confirm == 'y':
                            limit = input("\nEnter number of messages to save (or press Enter for all): ")
                            limit = int(limit) if limit.strip() else None
                            await save_channel_messages(self.client, self.db, self.db_path, limit=limit, force_redownload=True)
                    elif dl_choice == '3':
                        count = input("\nEnter number of recent messages to download: ")
                        try:
                            count = int(count)
                            if count <= 0:
                                print("\nPlease enter a positive number")
                                continue
                            await save_channel_messages(self.client, self.db, self.db_path, recent_count=count)
                        except ValueError:
                            print("\nPlease enter a valid number")
                    elif dl_choice == '4':
                        try:
                            min_id = input("\nEnter minimum message ID (or press Enter for first message): ")
                            min_id = int(min_id) if min_id.strip() else None
                            
                            max_id = input("Enter maximum message ID (or press Enter for last message): ")
                            max_id = int(max_id) if max_id.strip() else None
                            
                            limit = input("Enter maximum number of messages to download (or press Enter for all): ")
                            limit = int(limit) if limit.strip() else None
                            
                            force = input("Force redownload existing messages? (y/N): ").lower() == 'y'
                            
                            await save_channel_messages(
                                self.client,
                                self.db,
                                self.db_path,
                                min_id=min_id, 
                                max_id=max_id, 
                                limit=limit,
                                force_redownload=force
                            )
                        except ValueError:
                            print("\nPlease enter valid message IDs (numbers only)")
                    elif dl_choice == '5':
                        continue
                elif choice == '11':
                    await list_saved_users(self.db)
                elif choice == '12':
                    await search_messages(self.db)
                elif choice == '13':
                    await browse_messages(self.db)
                elif choice == '14':
                    await search_replace_messages(self.db, self.db_path, self.client)
                elif choice == '15':
                    await restore_edited_messages(self.db, self.db_path, self.client)
                elif choice == '16':
                    list_edited_messages(self.db)
                elif choice == '17':
                    print("\nVideo Download Options:")
                    print("1. Download all videos")
                    print("2. Download video circles only (round videos)")
                    print("3. Back to main menu")

                    video_choice = input("\nEnter choice (1-3): ")

                    if video_choice == '1':
                        limit = input("\nEnter number of videos to download (or press Enter for all): ")
                        limit = int(limit) if limit.strip() else None
                        await download_video_messages(self.client, self.db, self.db_path, limit=limit, round_videos_only=False)
                    elif video_choice == '2':
                        limit = input("\nEnter number of video circles to download (or press Enter for all): ")
                        limit = int(limit) if limit.strip() else None
                        await download_video_messages(self.client, self.db, self.db_path, limit=limit, round_videos_only=True)
                    elif video_choice == '3':
                        continue
                elif choice == '18':
                    list_downloaded_videos(self.db)
                elif choice == '19':
                    await export_menu(self.db, self.client)
                elif choice == '20':
                    await self.client.log_out()
                    print("\nLogged out successfully!")
                    # Clear account data
                    if self.phone in self.db.get('sessions', {}):
                        del self.db['sessions'][self.phone]
                    self.db['last_login'] = None
                    self.db['active_channel'] = None
                    save_database(self.db_path, self.db)
                    # Clear account context
                    AccountContext.clear()
                    self.account = None
                    break
                elif choice == '21':
                    break
                else:
                    print("\nInvalid choice!")

        finally:
            if self.client:
                await self.client.disconnect()
                self.client = None

def main():
    """Entry point function"""
    app = ChannelSaver()
    asyncio.run(app.start())

if __name__ == '__main__':
    main() 