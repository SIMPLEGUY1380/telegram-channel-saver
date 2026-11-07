# Telegram Channel Saver - Codebase Structure

This document provides an overview of the modular codebase structure in Telegram Channel Saver. The application has been refactored from a monolithic script into modular components to improve maintainability and readability.

## Directory Structure

```
telegram-channel-saver/
├── main.py                # Main entry point
├── src/                   # Source code modules
│   ├── __init__.py        # Package initialization
│   ├── app.py             # Main application class
│   ├── channels.py        # Channel management functions
│   ├── client.py          # Telegram client functions
│   ├── config.py          # Configuration and constants
│   ├── database.py        # Database operations
│   ├── link_downloader.py # Embedded yt-dlp downloader
│   ├── media.py           # Media handling functions
│   ├── messages.py        # Message operations
│   ├── post_scheduler.py  # Post scheduling manager
│   └── users.py           # User management functions
├── temp/                  # Temporary data storage
│   ├── channel_saver/     # Database and session files
│   └── videos/            # Downloaded videos
└── docs/                  # Documentation
```

## Modules Overview

### main.py

The entry point for the application that imports and runs the main function from `src/app.py`. This provides a clean interface for users to start the application.

### src/app.py

The core application module containing the `ChannelSaver` class which coordinates all functionality:
- Handles Telegram client initialization
- Manages user sessions
- Provides the main menu interface
- Coordinates operations between other modules

### src/config.py

Contains all configuration settings and constants:
- Batch sizes and timing settings
- Media download parameters
- Directory settings
- Logging configuration

### src/database.py

Handles database operations:
- Loading and saving the JSON database
- Database schema creation
- Provides a clean interface for other modules to access data

### src/client.py

Manages Telegram client interactions:
- Authentication and login
- Session management
- Client creation and connection

### src/channels.py

Functions for channel management:
- Listing available channels/groups
- Displaying channel information
- Selecting active channel
- Retrieving channel statistics

### src/users.py

User management functions:
- Saving channel users
- Displaying user statistics
- Listing saved users

### src/messages.py

Message operations:
- Saving channel messages
- Searching through messages
- Message display and formatting
- Handling message batches with rate limiting

### src/media.py

Media handling functionality:
- Enhanced media download mechanism with retry logic
- Video download management
- Media information display
- Chunked downloads for large files

### src/link_downloader.py

Embedded yt-dlp download functionality:
- Parses URLs from links files (`links.txt`)
- Downloads video and clip media directly to specified folders
- Maintains download history archive (`downloaded.txt`) to skip existing files
- Fault-tolerant batch execution with error reporting

### src/post_scheduler.py

Telegram post scheduling and publishing:
- Native MTProto schedule parameter integration for text and media
- Batch media scheduler with sequential intervals across files
- Flexible time parsing (relative e.g. `30m`, specific time, or datetime)
- Active channel verification and pending scheduled posts management

## Dependencies Between Modules

The codebase follows a hierarchical dependency structure:

1. `config.py` - No dependencies on other modules, only standard library imports
2. `database.py` - Depends on `config.py` for directory settings
3. `client.py` - Depends on `config.py` and `database.py`
4. `channels.py` - Depends on `database.py` for storing channel data
5. `users.py` - Depends on `channels.py` and `database.py`
6. `media.py` - Depends on `config.py`, but has minimal dependencies
7. `messages.py` - Depends on `channels.py`, `database.py`, and `media.py`
8. `app.py` - Depends on all other modules to orchestrate the application

This structure ensures that lower-level modules don't depend on higher-level ones, reducing circular dependencies.

## Key Functionality by Module

### Configuration (config.py)

- Sets up logging
- Defines batch sizes for message downloads
- Controls delay times to avoid rate limiting
- Sets timeouts and retry parameters
- Configures directory paths

### Database Operations (database.py)

- Loads JSON database or creates new if none exists
- Saves database state
- Provides schema for users, sessions, messages, etc.

### Client Management (client.py)

- Creates and initializes Telegram client
- Authenticates users (login, 2FA)
- Manages sessions (saving, restoring)

### Channel Management (channels.py)

- Lists all available channels/groups
- Displays channel information in a readable format
- Selects active channel for operations
- Shows channel statistics

### User Management (users.py)

- Retrieves and saves channel participants
- Tracks user information (premium status, etc.)
- Displays user statistics
- Lists saved users

### Message Operations (messages.py)

- Downloads messages in batches
- Handles rate limiting and retries
- Processes message content (text, reactions)
- Provides search functionality

### Media Handling (media.py)

- Downloads media with progress tracking
- Handles large file downloads efficiently
- Manages video downloads
- Provides retry mechanisms for failed downloads

### Application Orchestration (app.py)

- Initializes application components
- Provides user interface (menu)
- Coordinates between modules
- Handles application flow

## How to Extend the Codebase

### Adding New Features

1. Identify which module should contain your feature
2. Add necessary functions to that module
3. If needed, update `app.py` to expose the feature in the UI
4. Update configuration in `config.py` if new settings are required

### Modifying Existing Features

1. Locate the module containing the feature
2. Make changes while maintaining the module's responsibility
3. Ensure changes don't break dependencies
4. Update documentation to reflect changes

## Best Practices

When working with this codebase:

1. **Maintain separation of concerns**: Keep each module focused on its specific responsibility
2. **Avoid circular dependencies**: Lower-level modules shouldn't import higher-level ones
3. **Update configuration**: Use `config.py` for constants rather than hardcoding values
4. **Follow existing patterns**: Maintain consistency with the established code style
5. **Document changes**: Update comments and documentation when making significant changes 