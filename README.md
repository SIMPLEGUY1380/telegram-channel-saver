# Telegram Channel Saver

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram_API-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)
![Telethon](https://img.shields.io/badge/Telethon-MTProto-FF6B6B?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Claude](https://img.shields.io/badge/Built_with-Claude_AI-CC785C?style=for-the-badge&logo=anthropic&logoColor=white)

**Build your own Telegram client with Telethon**

*The foundation for the first Telegram-CMS system*

[Features](#-features) • [Installation](#-installation) • [Usage](#-usage) • [Documentation](#-documentation) • [Contributing](#-contributing)

</div>

---

## About This Project

This project demonstrates how to build a **personal Telegram client** using the [Telethon](https://github.com/LonamiWebs/Telethon) library to manage your Telegram messages at scale. It serves as both a practical tool and an educational resource for developers interested in:

- Building custom Telegram applications beyond standard bots
- Managing channel content programmatically
- Creating backup and archival systems for Telegram data
- Understanding MTProto protocol interactions

> **Vision**: This codebase is the foundation for a **Telegram-CMS** - a content management system for Telegram channels and groups, enabling publishers to manage, edit, and organize their content.

---

## Features

### Channel & Group Management

| Feature | Description |
|---------|-------------|
| **Multi-Channel Support** | Connect to and manage multiple channels and groups from a single interface |
| **Channel Selection** | Browse all your subscribed channels/groups and select which one to work with |
| **Channel Info Display** | View detailed information about channels including member counts and activity |
| **Permission Detection** | Automatically detects admin rights for editing capabilities |

### Message Operations

| Feature | Description |
|---------|-------------|
| **Bulk Message Download** | Download all messages or specify ranges (by count, ID range, or recent) |
| **Incremental Sync** | Download only new messages since last sync to save time and bandwidth |
| **Force Redownload** | Option to re-fetch all messages when needed |
| **Reaction Tracking** | Saves emoji reactions and reaction counts for each message |
| **Reply Threading** | Preserves reply relationships between messages |
| **Rate Limit Compliance** | Automatic rate limiting to respect Telegram's API limits (100 msgs/request) |

### Search & Replace (Channel Editing)

| Feature | Description |
|---------|-------------|
| **Local Search** | Search through locally saved messages by text, regex, date, or ID |
| **Bulk Search & Replace** | Find and replace text across multiple messages |
| **Formatting Preservation** | Maintains all Telegram formatting (bold, italic, links, etc.) during edits |
| **Native Entity Handling** | Works with Telegram's native entity format for pixel-perfect formatting |
| **One-by-One Approval** | Review each change before applying with preview |
| **Live Channel Editing** | Edit messages directly on Telegram (requires admin rights) |
| **Undo Capability** | Instantly undo the last edit during batch operations |
| **Backup & Restore** | All edited messages are backed up; restore originals anytime |

### Message Browsing

| Feature | Description |
|---------|-------------|
| **Paginated View** | Browse messages 10 per page with easy navigation |
| **Jump Navigation** | Jump to specific message ID or page number |
| **HTML Source View** | View the raw HTML/markdown source of any message |
| **Message Preview** | See ID, date, sender, and content snippet at a glance |

### Media Handling

| Feature | Description |
|---------|-------------|
| **Video Downloads** | Download all videos or just video circles (round videos) |
| **Photo Support** | Download and track photos attached to messages |
| **Chunked Downloads** | Large files downloaded in chunks for reliability |
| **Progress Indication** | Real-time progress during downloads |
| **Retry Mechanism** | Exponential backoff for failed downloads |
| **Timeout Handling** | Configurable timeouts for slow connections |

### Export Capabilities

| Feature | Description |
|---------|-------------|
| **Full Channel Export** | Export all messages to formatted text files |
| **User-Specific Export** | Export only messages from a specific user |
| **Individual Message Export** | Export single messages with full context |
| **AI Image Analysis** | Optional GPT-4 powered analysis of images via OpenRouter |
| **Statistics** | View channel stats (message count, media count, users) |
| **Structured Output** | Exports include timestamps, usernames, and reply context |

### User Management

| Feature | Description |
|---------|-------------|
| **User Tracking** | Save and track all users in a channel |
| **User Statistics** | View activity stats and user information |
| **User Message History** | Find all messages from a specific user |
| **Multi-Session Support** | Manage multiple Telegram accounts |
| **Session Cleanup** | Remove invalid or expired sessions |

### Search Features

| Feature | Description |
|---------|-------------|
| **Text Search** | Find messages containing specific text |
| **Date Range Filter** | Search within specific time periods |
| **ID-Based Search** | Look up messages by their ID |
| **Reaction Filter** | Find messages with specific reactions |
| **Media Filter** | Filter messages that contain media |

---

## Project Structure

```
/telegram-channel-saver/
  ├── main.py               # Application entry point
  ├── requirements.txt      # Python dependencies
  ├── LICENSE               # MIT License
  ├── CLAUDE.md             # AI development guidelines
  │
  ├── src/                  # Source code
  │   ├── app.py            # Main application class
  │   ├── channels.py       # Channel management
  │   ├── client.py         # Telegram client operations
  │   ├── config.py         # Configuration settings
  │   ├── database.py       # JSON database operations
  │   ├── export.py         # Export functionality
  │   ├── formatting.py     # Entity & formatting utilities
  │   ├── media.py          # Media file handling
  │   ├── messages.py       # Message operations
  │   ├── search_replace.py # Search & replace engine
  │   └── users.py          # User tracking
  │
  ├── docs/                 # Documentation
  │   ├── setup.md          # Setup instructions
  │   ├── codebase.md       # Codebase overview
  │   ├── contributing.md   # Contribution guidelines
  │   └── faq.md            # FAQ
  │
  ├── tools/                # Development utilities
  │   └── venv/             # Separate venv for tools
  │
  └── temp/                 # Data storage
      ├── channel_saver/    # Database files
      ├── media/            # Downloaded media
      └── videos/           # Downloaded videos
```

---

## Installation

### Prerequisites

- Python 3.8 or higher
- Telegram account
- Telegram API credentials (api_id and api_hash)

### Step-by-Step Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/chubajs/telegram-channel-saver.git
   cd telegram-channel-saver
   ```

2. **Create virtual environment**
   ```bash
   # macOS/Linux
   python3 -m venv venv
   source venv/bin/activate

   # Windows
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Get Telegram API credentials**
   - Visit [my.telegram.org/apps](https://my.telegram.org/apps)
   - Create a new application
   - Copy your `api_id` and `api_hash`

5. **Configure environment**

   Create a `.env` file in the project root:
   ```env
   # Required: Telegram API Credentials
   API_ID=your_api_id
   API_HASH=your_api_hash

   # Optional: AI Image Analysis
   OPENROUTER_API_KEY=your_openrouter_key
   ```

---

## Usage

### Starting the Application

```bash
python main.py
```

### First-Time Setup

1. Enter your phone number (international format: +1234567890)
2. Enter the verification code sent to your Telegram
3. If 2FA is enabled, enter your password

### Main Menu Options

```
Options:
1.  Show account info
2.  List channels/groups
3.  Select active channel
4.  Show active channel info
5.  Save channel users
6.  Show users statistics
7.  List saved sessions
8.  Switch session
9.  Cleanup invalid sessions
10. Save channel messages
11. List saved users
12. Search messages
13. Browse message index
14. Search and replace in messages
15. Restore edited messages
16. List edited messages
17. Download videos
18. List downloaded videos
19. Export messages
20. Logout
21. Exit
```

### Example Workflows

**Backup a Channel:**
```
2 → List channels
3 → Select your channel
10 → Save messages (option 1: new only)
```

**Find and Replace Text:**
```
3 → Select channel
14 → Search and replace
   → Enter search term
   → Enter replacement
   → Choose: Local only / Edit on Telegram
   → Approve each change or skip
```

**Export for Analysis:**
```
3 → Select channel
19 → Export messages
   → Choose export type
```

---

## Configuration

Edit `src/config.py` to customize:

| Setting | Default | Description |
|---------|---------|-------------|
| `MESSAGES_BATCH_SIZE` | 100 | Messages per API request |
| `BATCH_DELAY` | 2 | Seconds between batches |
| `SAVE_INTERVAL` | 300 | Auto-save interval (seconds) |
| `MAX_RETRIES` | 3 | Retry attempts for failed operations |
| `MEDIA_DOWNLOAD_TIMEOUT` | 120 | Timeout for media downloads |
| `CHUNK_SIZE` | 1MB | Chunk size for large downloads |

---

## Data Storage

All data is stored locally in JSON format:

| Location | Content |
|----------|---------|
| `temp/channel_saver/database.json` | Messages, users, settings |
| `temp/media/` | Downloaded photos and files |
| `temp/videos/` | Downloaded videos |
| `exports/` | Exported message logs |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **API Credentials Error** | Verify `.env` file exists with valid credentials |
| **Database Errors** | Check `temp/` directory has write permissions |
| **Rate Limiting** | Increase `BATCH_DELAY` in config |
| **Media Timeouts** | Increase `MEDIA_DOWNLOAD_TIMEOUT` |
| **Session Expired** | Use option 9 to cleanup, then re-login |

---

## Documentation

- [Setup Instructions](docs/setup.md)
- [Codebase Overview](docs/codebase.md)
- [Contributing Guidelines](docs/contributing.md)
- [FAQ](docs/faq.md)

---

## Contributing

Contributions are welcome! Please see our [Contributing Guidelines](docs/contributing.md).

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## Author

<div align="center">

Created by **[Sergey Bulaev](https://www.bulaev.net)**

[![Website](https://img.shields.io/badge/Website-bulaev.net-4285F4?style=for-the-badge&logo=google-chrome&logoColor=white)](https://www.bulaev.net)
[![LLMIndex](https://img.shields.io/badge/LLM_Benchmark-llmimdex.net-FF6B6B?style=for-the-badge&logo=openai&logoColor=white)](https://llmimdex.net)
[![Telegram](https://img.shields.io/badge/Telegram-@sergiobulaev-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/sergiobulaev)

</div>

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Disclaimer

This tool is for **educational and personal use only**. It demonstrates how to build custom Telegram clients using the Telethon library. Please ensure compliance with:

- [Telegram's Terms of Service](https://telegram.org/tos)
- [Telegram API Terms of Use](https://core.telegram.org/api/terms)
- Local laws regarding data processing and privacy

---

<div align="center">

**The Foundation for Telegram-CMS**

*Managing Telegram content at scale*

![Stars](https://img.shields.io/github/stars/chubajs/telegram-channel-saver?style=social)
![Forks](https://img.shields.io/github/forks/chubajs/telegram-channel-saver?style=social)

</div>
