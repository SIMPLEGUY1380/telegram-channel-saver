import os
import time
import logging
from datetime import datetime

from src.database import save_database
from src.config import get_export_dir, DATE_FORMAT_WITH_TZ, DATE_FORMAT_DISPLAY
from src.message_export import export_individual_messages

logger = logging.getLogger(__name__)

def get_channel_statistics(db, channel_id):
    """Get statistics for a channel"""
    channel_id = str(channel_id)
    
    # Count messages
    messages_count = 0
    if 'messages' in db and channel_id in db['messages']:
        messages_count = len(db['messages'][channel_id])
    
    # Count media
    media_count = 0
    video_count = 0
    if 'messages' in db and channel_id in db['messages']:
        for msg_id, msg in db['messages'][channel_id].items():
            if msg.get('has_media', False):
                media_count += 1
                if msg.get('media_type') in ['MessageMediaDocument', 'MessageMediaVideo']:
                    video_count += 1
    
    # Count users
    users_count = 0
    if 'users' in db and channel_id in db['users']:
        users_count = len(db['users'][channel_id])
        
    return {
        'messages': messages_count,
        'media': media_count,
        'videos': video_count,
        'users': users_count
    }

async def list_users_in_channel(db, channel_id, client=None):
    """List all users who have messages in a channel"""
    channel_id = str(channel_id)
    active_users = {}
    
    # Build user dictionary with message counts
    if 'messages' in db and channel_id in db['messages']:
        for msg_id, msg in db['messages'][channel_id].items():
            user_id = msg.get('from_id')
            if user_id:
                if user_id not in active_users:
                    active_users[user_id] = 0
                active_users[user_id] += 1
    
    # Get user info
    users = []
    for user_id, msg_count in active_users.items():
        # Try to get user info from database first, or fetch from API if needed
        user_info = await get_user_info_for_id(client, channel_id, user_id, db) if client else None
        
        if user_info:
            users.append({
                'id': user_id,
                'username': user_info.get('username', 'Unknown'),
                'first_name': user_info.get('first_name', ''),
                'last_name': user_info.get('last_name', ''),
                'message_count': msg_count
            })
        else:
            # If we couldn't get user info, use placeholder
            users.append({
                'id': user_id,
                'username': f'Unknown User ({user_id})',
                'first_name': '',
                'last_name': '',
                'message_count': msg_count
            })
    
    # Sort by message count, descending
    users.sort(key=lambda x: x['message_count'], reverse=True)
    return users

async def format_message_for_export(msg, db, channel_id, client=None):
    """Format a message for export"""
    # Get sender information
    sender_name = "Unknown"
    user_id = msg.get('from_id')
    
    if user_id:
        # Try to get user info from database or fetch from API if needed
        user = None
        if 'users' in db and channel_id in db['users'] and str(user_id) in db['users'][channel_id]:
            user = db['users'][channel_id][str(user_id)]
        elif client:
            user = await get_user_info_for_id(client, channel_id, user_id, db)
            
        if user:
            if user.get('username'):
                sender_name = f"@{user['username']}"
            else:
                first_name = user.get('first_name', '')
                last_name = user.get('last_name', '')
                sender_name = f"{first_name} {last_name}".strip()
        else:
            sender_name = f"User_{user_id}"
    
    # Format date
    date_str = "Unknown date"
    try:
        date_obj = datetime.strptime(msg.get('date'), DATE_FORMAT_WITH_TZ)
        date_str = date_obj.strftime(DATE_FORMAT_DISPLAY)
    except (ValueError, TypeError):
        pass
    
    # Check if it's a reply
    reply_text = ""
    if msg.get('reply_to'):
        reply_msg_id = msg.get('reply_to')
        if reply_msg_id and str(reply_msg_id) in db['messages'][channel_id]:
            reply_msg = db['messages'][channel_id][str(reply_msg_id)]
            reply_sender_id = reply_msg.get('from_id')
            reply_sender_name = "Unknown"
            
            if reply_sender_id:
                # Try to get reply user info
                reply_user = None
                if 'users' in db and channel_id in db['users'] and str(reply_sender_id) in db['users'][channel_id]:
                    reply_user = db['users'][channel_id][str(reply_sender_id)]
                elif client:
                    reply_user = await get_user_info_for_id(client, channel_id, reply_sender_id, db)
                    
                if reply_user:
                    if reply_user.get('username'):
                        reply_sender_name = f"@{reply_user['username']}"
                    else:
                        first = reply_user.get('first_name', '')
                        last = reply_user.get('last_name', '')
                        reply_sender_name = f"{first} {last}".strip()
                else:
                    reply_sender_name = f"User_{reply_sender_id}"
            
            reply_content = reply_msg.get('text', '')
            if len(reply_content) > 50:
                reply_content = reply_content[:47] + "..."
            
            reply_text = f"[Replying to {reply_sender_name}: \"{reply_content}\"]\n"
    
    # Build message text
    media_text = ""
    if msg.get('has_media'):
        media_type = msg.get('media_type', 'Unknown media')
        media_text = f"[{media_type}]\n"
    
    views = msg.get('views', 0)
    forwards = msg.get('forwards', 0)
    
    # Format reactions if any
    reactions_text = ""
    if msg.get('reactions') and len(msg.get('reactions')) > 0:
        reactions = []
        for reaction in msg.get('reactions'):
            emoji = reaction.get('reaction', '👍')
            count = reaction.get('count', 1)
            reactions.append(f"{emoji} {count}")
        
        reactions_text = f" [Reactions: {', '.join(reactions)}]"
    
    stats_text = ""
    if views or forwards:
        stats_items = []
        if views:
            stats_items.append(f"{views} views")
        if forwards:
            stats_items.append(f"{forwards} forwards")
        stats_text = f" [{', '.join(stats_items)}]"
    
    formatted_msg = (
        f"[{date_str}] {sender_name}:{stats_text}{reactions_text}\n"
        f"{reply_text}{media_text}{msg.get('text', '')}\n\n"
    )
    
    return formatted_msg

async def export_channel_messages(db, channel_id, channel_title, export_dir=None, client=None):
    """Export all messages from a channel to a text file"""
    channel_id = str(channel_id)

    # Use account-specific export directory by default
    if export_dir is None:
        export_dir = get_export_dir()

    # Create export directory if it doesn't exist
    if not os.path.exists(export_dir):
        os.makedirs(export_dir)
    
    # Sanitize channel title for filename
    safe_title = ''.join(c if c.isalnum() or c in [' ', '-', '_'] else '_' for c in channel_title)
    safe_title = safe_title.strip().replace(' ', '_')
    
    # Create filename with channel ID and sanitized title
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{export_dir}/{channel_id}_{safe_title}_{timestamp}.txt"
    
    # Check if we have messages for this channel
    if 'messages' not in db or channel_id not in db['messages'] or not db['messages'][channel_id]:
        print(f"No messages found for channel {channel_title}")
        return None
    
    # Sort messages by date
    messages = []
    for msg_id, msg in db['messages'][channel_id].items():
        try:
            date_str = msg.get('date')
            if date_str:
                date_obj = datetime.strptime(date_str, DATE_FORMAT_WITH_TZ)
                messages.append((date_obj, msg))
        except (ValueError, TypeError):
            # If date parsing fails, append to the end
            messages.append((datetime.max, msg))
    
    messages.sort(key=lambda x: x[0])
    
    # Write messages to file
    message_count = 0
    with open(filename, 'w', encoding='utf-8') as f:
        # Write header
        f.write(f"Export of channel: {channel_title} (ID: {channel_id})\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total messages: {len(messages)}\n")
        f.write("-" * 80 + "\n\n")
        
        # Write messages
        for _, msg in messages:
            formatted_msg = await format_message_for_export(msg, db, channel_id, client)
            f.write(formatted_msg)
            message_count += 1
            
            # Print progress every 100 messages
            if message_count % 100 == 0:
                print(f"Exported {message_count}/{len(messages)} messages...")
    
    print(f"\nExport complete: {message_count} messages exported to {filename}")
    return filename

async def export_user_messages(db, channel_id, channel_title, user_id, export_dir=None, client=None):
    """Export messages from a specific user in a channel"""
    channel_id = str(channel_id)
    user_id = str(user_id)

    # Use account-specific export directory by default
    if export_dir is None:
        export_dir = get_export_dir()

    # Get user info - try to fetch from API if not in database
    user_info = await get_user_info_for_id(client, channel_id, user_id, db) if client else None
    username = f"user_{user_id}"

    if user_info:
        if user_info.get('username'):
            username = user_info.get('username')
        else:
            first = user_info.get('first_name', '')
            last = user_info.get('last_name', '')
            if first or last:
                username = f"{first}_{last}".strip('_')

    # Create export directory if it doesn't exist
    if not os.path.exists(export_dir):
        os.makedirs(export_dir)
    
    # Sanitize channel title and username for filename
    safe_title = ''.join(c if c.isalnum() or c in [' ', '-', '_'] else '_' for c in channel_title)
    safe_title = safe_title.strip().replace(' ', '_')
    
    safe_username = ''.join(c if c.isalnum() or c in ['-', '_'] else '_' for c in username)
    
    # Create filename
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{export_dir}/{channel_id}_{safe_title}_{safe_username}_{timestamp}.txt"
    
    # Check if we have messages for this channel
    if 'messages' not in db or channel_id not in db['messages'] or not db['messages'][channel_id]:
        print(f"No messages found for channel {channel_title}")
        return None
    
    # Filter and sort messages by the specific user
    user_messages = []
    for msg_id, msg in db['messages'][channel_id].items():
        if str(msg.get('from_id')) == user_id:
            try:
                date_str = msg.get('date')
                if date_str:
                    date_obj = datetime.strptime(date_str, DATE_FORMAT_WITH_TZ)
                    user_messages.append((date_obj, msg))
            except (ValueError, TypeError):
                # If date parsing fails, append to the end
                user_messages.append((datetime.max, msg))
    
    if not user_messages:
        print(f"No messages found for user {username} in channel {channel_title}")
        return None
    
    user_messages.sort(key=lambda x: x[0])
    
    # Write messages to file
    message_count = 0
    with open(filename, 'w', encoding='utf-8') as f:
        # Write header
        f.write(f"Export of messages by ")
        if user_info:
            if user_info.get('username'):
                f.write(f"@{user_info['username']}")
            else:
                f.write(f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip())
        else:
            f.write(f"User ID: {user_id}")
        
        f.write(f" in channel: {channel_title} (ID: {channel_id})\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total messages: {len(user_messages)}\n")
        f.write("-" * 80 + "\n\n")
        
        # Write messages
        for _, msg in user_messages:
            formatted_msg = await format_message_for_export(msg, db, channel_id, client)
            f.write(formatted_msg)
            message_count += 1
            
            # Print progress every 100 messages
            if message_count % 100 == 0:
                print(f"Exported {message_count}/{len(user_messages)} messages...")
    
    print(f"\nExport complete: {message_count} messages exported to {filename}")
    return filename

async def get_user_info_for_id(client, channel_id, user_id, db):
    """
    Fetch user information for a given user ID from the channel
    Try to find it in the database first, if not found, fetch from Telegram API
    """
    user_id = str(user_id)
    
    # Check if user is already in the database
    if 'users' in db and channel_id in db['users'] and user_id in db['users'][channel_id]:
        return db['users'][channel_id][user_id]
    
    # User not found in database, fetch from API if client is provided
    if client:
        try:
            # Initialize users dict if needed
            if 'users' not in db:
                db['users'] = {}
            if channel_id not in db['users']:
                db['users'][channel_id] = {}
                
            # Try to get user info from Telegram
            entity = await client.get_entity(int(user_id))
            
            # Save user info
            user_dict = {
                'id': entity.id,
                'username': entity.username,
                'first_name': entity.first_name,
                'last_name': entity.last_name,
                'phone': getattr(entity, 'phone', None),
                'bot': getattr(entity, 'bot', False),
                'scam': getattr(entity, 'scam', False),
                'fake': getattr(entity, 'fake', False),
                'premium': getattr(entity, 'premium', False),
                'verified': getattr(entity, 'verified', False),
                'restricted': getattr(entity, 'restricted', False),
                'first_seen': str(datetime.now()),
                'last_seen': str(datetime.now())
            }
            
            # Save to database
            db['users'][channel_id][user_id] = user_dict
            logger.info(f"Added new user {entity.id} to database")
            
            return user_dict
        except Exception as e:
            logger.error(f"Error fetching user info for {user_id}: {str(e)}")
            return None
    
    return None

async def export_menu(db, client=None):
    """Display export options menu"""
    if not db.get('active_channel'):
        print("\nNo active channel selected! Please select a channel first.")
        return
    
    active = db['active_channel']
    channel_id = str(active['id'])
    channel_title = active['title']
    
    # Get statistics for the channel
    stats = get_channel_statistics(db, channel_id)
    
    print(f"\nExport options for channel: {channel_title}")
    print("-" * 50)
    print(f"Messages: {stats['messages']}")
    print(f"Media files: {stats['media']}")
    print(f"Videos: {stats['videos']}")
    print(f"Users: {stats['users']}")
    print("-" * 50)
    
    # Check if we have user data
    if stats['users'] == 0 and stats['messages'] > 0:
        print("\nWarning: No user data found for this channel.")
        print("User information may be incomplete in exports.")
        print("Consider saving channel users first (option 5 in main menu).")
    
    print("\nExport Options:")
    print("1. Export all messages")
    print("2. Export messages from a specific user")
    print("3. Export individual message files with AI media analysis")
    print("0. Cancel")
    
    choice = input("\nEnter your choice (0-3): ")
    
    if choice == '1':
        # Export all messages
        print(f"\nExporting all messages from {channel_title}...")
        await export_channel_messages(db, channel_id, channel_title, client=client)
    elif choice == '2':
        # List users and export messages from a specific user
        users = await list_users_in_channel(db, channel_id, client=client)
        
        if not users:
            print("\nNo users found in this channel!")
            return
        
        print("\nUsers in this channel:")
        print("-" * 50)
        for i, user in enumerate(users[:30], 1):  # Show top 30 users by message count
            if user['username']:
                display_name = user['username']
            else:
                first = user.get('first_name') or ''
                last = user.get('last_name') or ''
                display_name = f"{first} {last}".strip() or f"User_{user['id']}"
            print(f"{i}. {display_name} - {user['message_count']} messages")
        
        if len(users) > 30:
            print(f"... and {len(users) - 30} more users")
        
        print("0. Cancel")
        
        user_choice = input("\nEnter user number to export their messages (or 0 to cancel): ")
        
        if user_choice == '0':
            return
        
        try:
            user_index = int(user_choice)
            if 1 <= user_index <= len(users):
                selected_user = users[user_index - 1]
                print(f"\nExporting messages from {selected_user['username']}...")
                await export_user_messages(db, channel_id, channel_title, selected_user['id'], client=client)
            else:
                print("\nInvalid user number!")
        except ValueError:
            print("\nPlease enter a valid number!")
    elif choice == '3':
        # Export individual message files with AI analysis
        print(f"\nExporting individual message files from {channel_title}...")
        print("This will create a separate text file for each message/media group.")
        
        # Check if OpenRouter API key is configured
        # Load environment variables fresh to catch any updates
        from dotenv import load_dotenv
        load_dotenv()
        import os
        api_key = os.getenv('OPENROUTER_API_KEY')
        if api_key:
            print("✓ OpenRouter API key found - AI image analysis will be included")
            include_analysis = True
        else:
            print("⚠ OpenRouter API key not found - AI image analysis will be disabled")
            print("To enable AI analysis, set OPENROUTER_API_KEY environment variable")
            include_analysis = False
        
        confirm = input(f"\nProceed with individual file export? (y/N): ").lower()
        if confirm == 'y':
            result = export_individual_messages(db, include_media_analysis=include_analysis)
            if result['success']:
                print(f"\n✓ Export completed successfully!")
                print(f"Files exported: {result['exported_count']}")
                print(f"Export location: {result['export_path']}")
            else:
                print(f"\n✗ Export failed: {result['error']}")
        else:
            print("\nExport cancelled.")
    elif choice == '0':
        return
    else:
        print("\nInvalid option!")