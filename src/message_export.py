"""
Message export module for individual file export functionality.
Exports messages as separate text files with media analysis.
"""
import os
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.config import get_export_dir
from src.channels import get_active_channel
from src.image_analysis import analyze_image_with_openrouter, analyze_multiple_images

logger = logging.getLogger(__name__)

def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing or replacing invalid characters.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename safe for filesystem
    """
    # Remove or replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Replace multiple underscores with single underscore
    while '__' in filename:
        filename = filename.replace('__', '_')
    
    # Remove trailing dots and spaces
    filename = filename.rstrip('. ')
    
    # Ensure filename is not empty
    if not filename:
        filename = 'untitled'
    
    # Limit filename length
    if len(filename) > 200:
        filename = filename[:200]
    
    return filename

def format_message_content(message: Dict[str, Any], include_media_analysis: bool = True) -> str:
    """
    Format message content for export to text file.
    
    Args:
        message: Message dictionary
        include_media_analysis: Whether to include AI analysis of media
        
    Returns:
        Formatted message content as string
    """
    content_lines = []
    
    # Message header
    content_lines.append("=" * 80)
    content_lines.append(f"Message #{message['id']}")
    content_lines.append("=" * 80)
    
    # Metadata
    content_lines.append(f"Date: {message['date']}")
    if message.get('edit_date'):
        content_lines.append(f"Edited: {message['edit_date']}")
    
    if message.get('post_author'):
        content_lines.append(f"Author: {message['post_author']}")
    elif message.get('from_id'):
        content_lines.append(f"From ID: {message['from_id']}")
    
    if message.get('views'):
        content_lines.append(f"Views: {message['views']}")
    
    if message.get('forwards'):
        content_lines.append(f"Forwards: {message['forwards']}")
    
    if message.get('reply_to'):
        content_lines.append(f"Reply to: #{message['reply_to']}")
    
    content_lines.append("")
    
    # Media analysis section
    if include_media_analysis and message.get('has_media'):
        media_analysis = analyze_message_media(message)
        if media_analysis:
            content_lines.append("MEDIA ANALYSIS:")
            content_lines.append("-" * 40)
            content_lines.append(media_analysis)
            content_lines.append("")
    
    # Message text content
    if message.get('text'):
        content_lines.append("MESSAGE CONTENT:")
        content_lines.append("-" * 40)
        content_lines.append(message['text'])
        content_lines.append("")
    
    # Media information
    if message.get('has_media'):
        content_lines.append("MEDIA INFORMATION:")
        content_lines.append("-" * 40)
        content_lines.append(f"Media Type: {message.get('media_type', 'Unknown')}")
        
        if message.get('media_file_path'):
            content_lines.append(f"File Path: {message['media_file_path']}")
        
        if message.get('grouped_id'):
            content_lines.append(f"Media Group ID: {message['grouped_id']}")
        
        content_lines.append("")
    
    # Reactions
    if message.get('reactions') and len(message['reactions']) > 0:
        content_lines.append("REACTIONS:")
        content_lines.append("-" * 40)
        for reaction in message['reactions']:
            emoji = reaction.get('emoticon') or f"Custom({reaction.get('document_id')})"
            count = reaction.get('count', 0)
            chosen = " (chosen)" if reaction.get('chosen') else ""
            content_lines.append(f"{emoji}: {count}{chosen}")
        content_lines.append("")
    
    # Technical metadata
    content_lines.append("TECHNICAL METADATA:")
    content_lines.append("-" * 40)
    content_lines.append(f"Message ID: {message['id']}")
    content_lines.append(f"Post: {message.get('post', False)}")
    content_lines.append(f"Silent: {message.get('silent', False)}")
    content_lines.append(f"Pinned: {message.get('pinned', False)}")
    content_lines.append(f"No Forwards: {message.get('noforwards', False)}")
    content_lines.append(f"Last Update: {message.get('last_update', 'Unknown')}")
    
    return "\n".join(content_lines)

def analyze_message_media(message: Dict[str, Any]) -> Optional[str]:
    """
    Analyze media in a message using AI if applicable.
    
    Args:
        message: Message dictionary
        
    Returns:
        Analysis text or None if no analysis available
    """
    if not message.get('has_media') or not message.get('media_file_path'):
        return None
    
    media_path = message['media_file_path']
    
    # Check if file exists
    if not os.path.exists(media_path):
        return f"[Media file not found: {media_path}]"
    
    # Check if it's an image
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    file_extension = os.path.splitext(media_path)[1].lower()
    
    if file_extension in image_extensions:
        try:
            result = analyze_image_with_openrouter(media_path)
            
            if result['success']:
                return f"[Image was attached: {result['analysis']}]"
            else:
                return f"[Image analysis failed: {result['error']}]"
        except Exception as e:
            logger.error(f"Error analyzing image {media_path}: {str(e)}")
            return f"[Image analysis error: {str(e)}]"
    else:
        # For non-image media, just mention the type
        media_type = message.get('media_type', 'Unknown')
        return f"[{media_type} was attached: {os.path.basename(media_path)}]"

def get_media_group_messages(db: Dict[str, Any], channel_id: str, grouped_id: str) -> List[Dict[str, Any]]:
    """
    Get all messages that belong to the same media group.
    
    Args:
        db: Database dictionary
        channel_id: Channel ID
        grouped_id: Media group ID
        
    Returns:
        List of messages in the same media group
    """
    if 'messages' not in db or channel_id not in db['messages']:
        return []
    
    messages = db['messages'][channel_id]
    group_messages = []
    
    for msg_id, msg in messages.items():
        if msg.get('grouped_id') == grouped_id:
            group_messages.append(msg)
    
    # Sort by message ID
    group_messages.sort(key=lambda x: int(x['id']))
    return group_messages

def analyze_media_group(group_messages: List[Dict[str, Any]]) -> Optional[str]:
    """
    Analyze a media group using AI.
    
    Args:
        group_messages: List of messages in the media group
        
    Returns:
        Analysis text or None if no analysis available
    """
    # Collect all image paths from the media group
    image_paths = []
    
    for msg in group_messages:
        if (msg.get('has_media') and 
            msg.get('media_file_path') and 
            os.path.exists(msg['media_file_path'])):
            
            file_extension = os.path.splitext(msg['media_file_path'])[1].lower()
            image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
            
            if file_extension in image_extensions:
                image_paths.append(msg['media_file_path'])
    
    if not image_paths:
        return None
    
    if len(image_paths) == 1:
        # Single image
        try:
            result = analyze_image_with_openrouter(image_paths[0])
            if result['success']:
                return f"[Image was attached: {result['analysis']}]"
            else:
                return f"[Image analysis failed: {result['error']}]"
        except Exception as e:
            logger.error(f"Error analyzing single image: {str(e)}")
            return f"[Image analysis error: {str(e)}]"
    else:
        # Multiple images
        try:
            result = analyze_multiple_images(image_paths)
            if result['success']:
                return f"[Media group with {len(image_paths)} images was attached: {result['analysis']}]"
            else:
                return f"[Media group analysis failed: {result['error']}]"
        except Exception as e:
            logger.error(f"Error analyzing media group: {str(e)}")
            return f"[Media group analysis error: {str(e)}]"

def export_individual_messages(db: Dict[str, Any], include_media_analysis: bool = True) -> Dict[str, Any]:
    """
    Export all messages from active channel as individual text files.
    
    Args:
        db: Database dictionary
        include_media_analysis: Whether to include AI analysis of media
        
    Returns:
        Dict with export results
    """
    active = get_active_channel(db)
    if not active:
        return {
            'success': False,
            'error': 'No active channel selected'
        }
    
    channel_id = str(active['id'])
    if 'messages' not in db or channel_id not in db['messages']:
        return {
            'success': False,
            'error': 'No messages found for active channel'
        }
    
    messages = db['messages'][channel_id]
    if not messages:
        return {
            'success': False,
            'error': 'No messages to export'
        }
    
    # Create export directory for this channel (uses account-specific directory)
    channel_name = sanitize_filename(active['title'])
    export_path = os.path.join(get_export_dir(), f"{channel_name}_{channel_id}")
    os.makedirs(export_path, exist_ok=True)
    
    # Track processed media groups to avoid duplicates
    processed_groups = set()
    
    exported_count = 0
    skipped_count = 0
    error_count = 0
    
    print(f"\nExporting {len(messages)} messages to individual files...")
    print(f"Export directory: {export_path}")
    print(f"Media analysis: {'Enabled' if include_media_analysis else 'Disabled'}")
    print("-" * 50)
    
    # Sort messages by ID for consistent processing
    sorted_messages = sorted(messages.items(), key=lambda x: int(x[1]['id']))
    
    for msg_id, message in sorted_messages:
        try:
            # Handle media groups
            if message.get('grouped_id'):
                group_id = message['grouped_id']
                
                # Skip if we already processed this group
                if group_id in processed_groups:
                    skipped_count += 1
                    continue
                
                # Get all messages in this group
                group_messages = get_media_group_messages(db, channel_id, group_id)
                
                if group_messages:
                    # Export as a single file for the media group
                    first_message = group_messages[0]
                    
                    # Create filename based on first message
                    date_str = first_message['date'][:10]  # YYYY-MM-DD
                    preview = first_message.get('text', '')[:30] if first_message.get('text') else 'media_group'
                    preview = sanitize_filename(preview)
                    
                    filename = f"msg_{first_message['id']}_{date_str}_{preview}.txt"
                    filepath = os.path.join(export_path, filename)
                    
                    # Combine content from all messages in the group
                    combined_content = []
                    combined_content.append("=" * 80)
                    combined_content.append(f"MEDIA GROUP ({len(group_messages)} messages)")
                    combined_content.append("=" * 80)
                    combined_content.append("")
                    
                    # Add media group analysis if enabled
                    if include_media_analysis:
                        group_analysis = analyze_media_group(group_messages)
                        if group_analysis:
                            combined_content.append("MEDIA GROUP ANALYSIS:")
                            combined_content.append("-" * 40)
                            combined_content.append(group_analysis)
                            combined_content.append("")
                    
                    # Add each message in the group
                    for i, group_msg in enumerate(group_messages):
                        if i > 0:
                            combined_content.append("\n" + "=" * 40)
                            combined_content.append(f"Message #{group_msg['id']} (part of group)")
                            combined_content.append("=" * 40)
                        
                        # Don't include individual media analysis for group messages
                        # as we already have the group analysis
                        msg_content = format_message_content(group_msg, include_media_analysis=False)
                        combined_content.append(msg_content)
                    
                    # Write combined content to file
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(combined_content))
                    
                    exported_count += 1
                    processed_groups.add(group_id)
                    
                    print(f"✓ Exported media group: {filename}")
                else:
                    error_count += 1
                    print(f"✗ Error: Could not find group messages for group {group_id}")
            else:
                # Regular message (not in a group)
                date_str = message['date'][:10]  # YYYY-MM-DD
                preview = message.get('text', '')[:30] if message.get('text') else 'no_text'
                preview = sanitize_filename(preview)
                
                filename = f"msg_{message['id']}_{date_str}_{preview}.txt"
                filepath = os.path.join(export_path, filename)
                
                # Format message content
                content = format_message_content(message, include_media_analysis)
                
                # Write to file
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                exported_count += 1
                print(f"✓ Exported: {filename}")
        
        except Exception as e:
            error_count += 1
            logger.error(f"Error exporting message {msg_id}: {str(e)}")
            print(f"✗ Error exporting message {msg_id}: {str(e)}")
    
    # Create summary file
    summary_content = []
    summary_content.append("MESSAGE EXPORT SUMMARY")
    summary_content.append("=" * 50)
    summary_content.append(f"Channel: {active['title']}")
    summary_content.append(f"Channel ID: {active['id']}")
    summary_content.append(f"Export Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    summary_content.append(f"Total Messages in Channel: {len(messages)}")
    summary_content.append(f"Files Exported: {exported_count}")
    summary_content.append(f"Messages Skipped: {skipped_count}")
    summary_content.append(f"Errors: {error_count}")
    summary_content.append(f"Media Analysis: {'Enabled' if include_media_analysis else 'Disabled'}")
    summary_content.append("")
    summary_content.append("Export completed successfully!")
    
    summary_path = os.path.join(export_path, "_export_summary.txt")
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary_content))
    
    print(f"\n{'-' * 50}")
    print(f"Export completed!")
    print(f"Files exported: {exported_count}")
    print(f"Messages skipped: {skipped_count}")
    print(f"Errors: {error_count}")
    print(f"Export directory: {export_path}")
    
    return {
        'success': True,
        'exported_count': exported_count,
        'skipped_count': skipped_count,
        'error_count': error_count,
        'export_path': export_path,
        'summary_path': summary_path
    }