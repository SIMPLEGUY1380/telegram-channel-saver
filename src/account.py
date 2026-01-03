"""
Account context management module.
Handles per-account directory structure and path resolution.
"""
import os
from dataclasses import dataclass
from typing import Optional

from src.config import ACCOUNTS_BASE_DIR


@dataclass
class AccountPaths:
    """Container for account-specific paths"""
    phone: str
    base_dir: str
    session_path: str
    database_path: str
    videos_dir: str
    exports_dir: str

    @classmethod
    def for_phone(cls, phone: str) -> 'AccountPaths':
        """Create AccountPaths for a given phone number"""
        base = os.path.join(ACCOUNTS_BASE_DIR, phone)
        return cls(
            phone=phone,
            base_dir=base,
            session_path=os.path.join(base, 'session'),
            database_path=os.path.join(base, 'database.json'),
            videos_dir=os.path.join(base, 'videos'),
            exports_dir=os.path.join(base, 'exports')
        )

    def ensure_directories(self):
        """Create all required directories for this account"""
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.exports_dir, exist_ok=True)


class AccountContext:
    """Singleton-like context manager for current account"""
    _current: Optional[AccountPaths] = None

    @classmethod
    def set_account(cls, phone: str) -> AccountPaths:
        """Set the current account context"""
        cls._current = AccountPaths.for_phone(phone)
        cls._current.ensure_directories()
        return cls._current

    @classmethod
    def get_current(cls) -> Optional[AccountPaths]:
        """Get current account paths, or None if not set"""
        return cls._current

    @classmethod
    def require_current(cls) -> AccountPaths:
        """Get current account paths, raise if not set"""
        if cls._current is None:
            raise RuntimeError("No account context set. Call set_account() first.")
        return cls._current

    @classmethod
    def clear(cls):
        """Clear the current account context"""
        cls._current = None
