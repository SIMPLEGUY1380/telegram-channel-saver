"""
Tests for interactive menus in link_downloader and post_scheduler.
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.link_downloader import interactive_download_links
from src.post_scheduler import post_scheduler_menu


class TestInteractiveMenus(unittest.TestCase):
    """Test interactive menu flows without blocking for real input."""

    @patch('builtins.input', side_effect=['4'])
    @patch('builtins.print')
    def test_interactive_download_links_exit(self, mock_print, mock_input):
        """Test exiting the interactive download menu immediately."""
        interactive_download_links()
        self.assertTrue(mock_input.called)

    @patch('builtins.input', side_effect=['3', 'temp_archive_nonexistent.txt'])
    @patch('builtins.print')
    def test_interactive_view_archive(self, mock_print, mock_input):
        """Test viewing download archive."""
        interactive_download_links()
        self.assertTrue(mock_input.called)

    async def _async_test_post_scheduler_no_active_channel(self):
        """Test scheduler menu when no active channel is set in db."""
        client = AsyncMock()
        db = {}
        with patch('builtins.print') as mock_print:
            await post_scheduler_menu(client, db, "dummy_db.json")
            mock_print.assert_any_call("\nError: No active channel selected!")

    def test_post_scheduler_no_active_channel(self):
        import asyncio
        asyncio.run(self._async_test_post_scheduler_no_active_channel())

    async def _async_test_post_scheduler_exit(self):
        """Test exiting post scheduler menu."""
        client = AsyncMock()
        db = {'active_channel': {'id': -100123456, 'title': 'Test Channel'}}
        with patch('builtins.input', side_effect=['7']):
            await post_scheduler_menu(client, db, "dummy_db.json")

    def test_post_scheduler_exit(self):
        import asyncio
        asyncio.run(self._async_test_post_scheduler_exit())


class TestAccountResolution(unittest.TestCase):
    """Test multi-account discovery and auto-detection."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        from src.account import AccountContext
        AccountContext.clear()

    def test_find_active_account(self):
        import json
        import shutil
        from src.account import AccountContext

        # Create dummy account structure
        phone = "+1234567890"
        acct_dir = os.path.join(self.test_dir, phone)
        os.makedirs(acct_dir, exist_ok=True)
        db_file = os.path.join(acct_dir, "database.json")
        with open(db_file, "w", encoding="utf-8") as f:
            json.dump({
                "sessions": {
                    phone: {"active": True, "last_used": "2026-11-07 12:00:00"}
                },
                "active_channel": {"id": 12345, "title": "Test Channel"}
            }, f)

        with patch('src.account.ACCOUNTS_BASE_DIR', self.test_dir):
            found = AccountContext.find_active_account()
            self.assertIsNotNone(found)
            self.assertEqual(found.phone, phone)
            self.assertEqual(AccountContext.get_current().phone, phone)


if __name__ == '__main__':
    unittest.main()
