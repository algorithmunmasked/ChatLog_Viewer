"""
HTML import service for ChatGPT exported HTML files
Parses HTML conversation exports and imports them into the database
"""
import os
import re
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from .models import ChatGPTConversation, ChatGPTMessage, ChatGPTTimeline, ChatGPTImportLog
from .database_service import ChatGPTDatabaseService


class HTMLImportService:
    """Service for importing ChatGPT HTML export files"""
    
    def __init__(self, html_folder_path: Optional[str] = None):
        """
        Initialize HTML import service
        
        Args:
            html_folder_path: Path to HTMLS folder. If None, uses chatlog/HTMLS in project root
        """
        if html_folder_path is None:
            # Get project root (parent of app directory)
            project_root = os.path.dirname(os.path.dirname(__file__))
            html_folder_path = os.path.join(project_root, 'chatlog', 'HTMLS')
        
        self.html_folder_path = html_folder_path
    
    def scan_html_files(self) -> List[Dict[str, str]]:
        """
        Scan HTMLS folder for HTML files
        Supports both flat structure and subfolder structure (chatgpt, grok, perplexity, anthropic)
        
        Returns:
            List of dicts with 'filename' and 'subfolder' keys (subfolder may be empty string)
        """
        if not os.path.exists(self.html_folder_path):
            return []
        
        html_files = []
        
        # Check for subfolder structure first
        expected_subfolders = ['chatgpt', 'grok', 'perplexity', 'anthropic']
        has_subfolders = False
        
        for subfolder in expected_subfolders:
            subfolder_path = os.path.join(self.html_folder_path, subfolder)
            if os.path.isdir(subfolder_path):
                has_subfolders = True
                # Scan this subfolder
                for item in os.listdir(subfolder_path):
                    if item.endswith('.html') and not item.startswith('.'):
                        html_files.append({
                            'filename': item,
                            'subfolder': subfolder,
                            'relative_path': f"{subfolder}/{item}"
                        })
        
        # If no subfolders found, scan root HTMLS folder (backward compatibility)
        if not has_subfolders:
            for item in os.listdir(self.html_folder_path):
                if item.endswith('.html') and not item.startswith('.'):
                    html_files.append({
                        'filename': item,
                        'subfolder': '',
                        'relative_path': item
                    })
        
        return sorted(html_files, key=lambda x: (x['subfolder'], x['filename']))
    
    def import_all(self) -> Dict[str, Any]:
        """Import all HTML files from HTMLS folder (supports subfolder structure)"""
        html_files = self.scan_html_files()
        results = {
            'html_files_found': len(html_files),
            'conversations_imported': 0,
            'messages_imported': 0,
            'errors': []
        }
        
        db_service = ChatGPTDatabaseService()
        db = db_service.get_session()
        
        try:
            for file_info in html_files:
                html_file = file_info['filename']
                subfolder = file_info['subfolder']
                relative_path = file_info['relative_path']
                
                try:
                    result = self.import_html_file(db, html_file, subfolder, relative_path)
                    results['conversations_imported'] += result.get('conversations', 0)
                    results['messages_imported'] += result.get('messages', 0)
                    
                    # Track skipped files (already imported or not ChatGPT) separately
                    if result.get('reason') in ['already_exists', 'not_chatgpt']:
                        if 'skipped' not in results:
                            results['skipped'] = []
                        results['skipped'].append({
                            'file': relative_path,
                            'reason': result.get('reason', 'unknown')
                        })
                except Exception as e:
                    import traceback
                    error_detail = traceback.format_exc()
                    results['errors'].append({
                        'file': relative_path,
                        'error': str(e),
                        'traceback': error_detail
                    })
                    print(f"Error importing {relative_path}: {e}")
                    print(error_detail)
            
            db.commit()
        finally:
            db.close()
        
        return results
    
    def import_html_file(self, db: Session, html_filename: str, subfolder: str = '', relative_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Import a single HTML file
        
        Args:
            db: Database session
            html_filename: Name of the HTML file
            subfolder: Subfolder name (e.g., 'chatgpt', 'grok', etc.) - empty string for root
            relative_path: Full relative path from HTMLS folder (e.g., 'chatgpt/file.html') - used for export_folder
        
        Returns:
            Dict with import results
        """
        if subfolder:
            html_path = os.path.join(self.html_folder_path, subfolder, html_filename)
        else:
            html_path = os.path.join(self.html_folder_path, html_filename)
        
        # Use relative_path if provided, otherwise construct it
        if relative_path is None:
            relative_path = f"{subfolder}/{html_filename}" if subfolder else html_filename
        
        if not os.path.exists(html_path):
            return {'conversations': 0, 'messages': 0}
        
        # Store html_content and html_path for use in message extraction
        self._current_html_content = None
        self._current_html_filename = html_filename
        
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        self._current_html_content = html_content
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract conversation ID from URL - try multiple patterns
        conversation_id = None
        
        # Pattern 1: Standard ChatGPT URL pattern /c/xxxxx
        url_match = re.search(r'/c/([a-f0-9-]+)', html_content)
        if url_match:
            conversation_id = url_match.group(1)
        
        # Pattern 2: Look in href attributes
        if not conversation_id:
            href_match = re.search(r'href=["\']https://chatgpt\.com/c/([a-f0-9-]+)', html_content)
            if href_match:
                conversation_id = href_match.group(1)
        
        # Pattern 3: Look for conversation ID in data attributes or script tags
        if not conversation_id:
            data_match = re.search(r'["\']conversation[_-]?id["\']\s*:\s*["\']([a-f0-9-]+)["\']', html_content, re.I)
            if data_match:
                conversation_id = data_match.group(1)
        
        # Extract title from filename or HTML title
        title = html_filename.replace('.html', '')
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        
        # If still no conversation ID, try to import as other service (Grok, Anthropic, Perplexity)
        if not conversation_id:
            # Check subfolder first, then filename patterns
            subfolder_lower = subfolder.lower() if subfolder else ''
            filename_lower = html_filename.lower()
            
            # Determine service from subfolder or filename
            if subfolder_lower == 'grok' or 'grok' in filename_lower:
                return self._import_grok_file(db, html_path, html_filename, soup, html_content, relative_path)
            elif subfolder_lower == 'anthropic' or 'anthropic' in filename_lower or 'claude' in filename_lower:
                return self._import_anthropic_file(db, html_path, html_filename, soup, html_content, relative_path)
            elif subfolder_lower == 'perplexity' or 'perplexity' in filename_lower:
                return self._import_perplexity_file(db, html_path, html_filename, soup, html_content, relative_path)
            elif subfolder_lower == 'chatgpt':
                # ChatGPT folder but no conversation ID - might be malformed, raise error
                raise ValueError(f"No conversation ID found in {relative_path} (ChatGPT export)")
            else:
                # Unknown file type - raise error
                raise ValueError(f"No conversation ID found in {relative_path} (may not be a supported export)")
        
        # Check if conversation already exists
        existing_conv = db.query(ChatGPTConversation).filter(
            ChatGPTConversation.conversation_id == conversation_id
        ).first()
        
        is_new_conversation = existing_conv is None
        
        # If conversation exists and has messages from JSON import, skip HTML import
        # HTML exports often have incomplete data and different message IDs
        if existing_conv and not is_new_conversation:
            from .models import ChatGPTMessage
            existing_message_count = db.query(ChatGPTMessage).filter(
                ChatGPTMessage.conversation_id == conversation_id
            ).count()
            
            # If conversation has messages and export_folder suggests JSON import (not HTMLS), skip
            if existing_message_count > 0 and existing_conv.export_folder and not existing_conv.export_folder.startswith('HTMLS/'):
                # Conversation already imported from JSON with messages, skip HTML import
                return {'conversations': 0, 'messages': 0, 'reason': 'already_exists_json'}
        
        # Get file modification time - this is the most reliable date source for HTML exports
        file_mtime = None
        try:
            file_mtime = os.path.getmtime(html_path)
        except:
            pass
        
        # Extract messages
        messages = self._extract_messages_from_html(soup, conversation_id, html_path)
        
        if not messages:
            # No messages found - this might be an issue
            print(f"Warning: No messages extracted from {html_filename}")
            return {'conversations': 0, 'messages': 0, 'reason': 'no_messages'}
        
        # Use file modification time for conversation dates (most reliable for HTML exports)
        # Calculate create_time by subtracting estimated duration
        if file_mtime:
            # Estimate: assume average conversation takes 1 minute per message
            estimated_duration = len(messages) * 60  # seconds
            create_time = file_mtime - estimated_duration
            update_time = file_mtime
        else:
            # Fallback to message timestamps if file mtime unavailable
            create_time = messages[0].get('timestamp') if messages else None
            update_time = messages[-1].get('timestamp') if messages else None
            
            # Final fallback
            if not create_time:
                create_time = datetime.utcnow().timestamp()
            if not update_time:
                update_time = datetime.utcnow().timestamp()
        
        # Create or update conversation record
        if is_new_conversation:
            conversation = ChatGPTConversation(
                conversation_id=conversation_id,
                title=title,
                create_time=create_time,
                update_time=update_time,
                export_folder=f'HTMLS/{relative_path}',
                raw_data=json.dumps({'source': 'html_export', 'filename': html_filename, 'file_mtime': file_mtime})
            )
            db.add(conversation)
            db.flush()
            
            # Create conversation creation timeline entry
            if messages:
                timeline_entry = ChatGPTTimeline(
                    conversation_id=conversation_id,
                    event_type='conversation_created',
                    timestamp=messages[0].get('timestamp', datetime.utcnow().timestamp()),
                    title_preview=title,
                    timeline_metadata=json.dumps({'title': title, 'source': 'html_export'})
                )
                db.add(timeline_entry)
        else:
            # Update existing conversation metadata
            if update_time and (not existing_conv.update_time or update_time > existing_conv.update_time):
                existing_conv.update_time = update_time
            if title and title != existing_conv.title:
                existing_conv.title = title
            db.flush()
        
        # Import messages - check each message by message_id
        message_count = 0
        for msg_data in messages:
            try:
                message_id = msg_data.get('message_id', f"html_{msg_data.get('index', 0)}")
                
                # Check if message already exists
                existing_msg = db.query(ChatGPTMessage).filter(
                    ChatGPTMessage.message_id == message_id,
                    ChatGPTMessage.conversation_id == conversation_id
                ).first()
                
                if existing_msg:
                    # Message already exists, skip it
                    continue
                
                message = ChatGPTMessage(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    parent_id=msg_data.get('parent_id'),
                    role=msg_data.get('role'),
                    author=msg_data.get('role'),
                    content=msg_data.get('content', ''),
                    model=msg_data.get('model'),
                    model_slug=msg_data.get('model'),
                    create_time=msg_data.get('timestamp'),
                    status='finished_successfully',
                    raw_data=json.dumps({
                        'source': 'html_export',
                        'message_data': msg_data
                    })
                )
                db.add(message)
                message_count += 1
                
                # Create timeline entry
                if msg_data.get('timestamp'):
                    timeline_entry = ChatGPTTimeline(
                        conversation_id=conversation_id,
                        event_type='message_sent',
                        timestamp=msg_data.get('timestamp'),
                        message_id=message_id,
                        title_preview='',
                        content_preview=msg_data.get('content', '')[:500],
                        timeline_metadata=json.dumps({
                            'role': msg_data.get('role'),
                            'model': msg_data.get('model'),
                            'source': 'html_export'
                        })
                    )
                    db.add(timeline_entry)
            except Exception as e:
                # Skip problematic messages but continue
                continue
        
        db.commit()
        
        return {
            'conversations': 1 if is_new_conversation else 0,
            'messages': message_count
        }
    
    def _extract_messages_from_html(self, soup: BeautifulSoup, conversation_id: str, html_path: str) -> List[Dict[str, Any]]:
        """Extract messages from HTML soup"""
        messages = []
        
        # Get file modification time for use in timestamp calculation
        file_mtime = None
        try:
            file_mtime = os.path.getmtime(html_path)
        except:
            pass
        
        # Find all message articles
        article_tags = soup.find_all('article', {'data-testid': re.compile('conversation-turn')})
        
        for idx, article in enumerate(article_tags):
            try:
                # Find message div
                msg_div = article.find('div', {'data-message-id': True})
                if not msg_div:
                    continue
                
                message_id = msg_div.get('data-message-id')
                role = msg_div.get('data-message-author-role', 'unknown')
                model = msg_div.get('data-message-model-slug', '')
                
                # Extract content
                content = ''
                # Try different selectors for content
                content_selectors = [
                    'div.whitespace-pre-wrap',
                    'div.markdown',
                    'div[class*="text-message"]',
                    'div[data-message-author-role]'
                ]
                
                for selector in content_selectors:
                    content_div = article.select_one(selector)
                    if content_div:
                        content = content_div.get_text(separator='\n', strip=False)
                        if content.strip():
                            break
                
                # If still no content, get all text from article
                if not content.strip():
                    content = article.get_text(separator='\n', strip=False)
                
                # Try to extract timestamp (look for time elements, data attributes, or file modification time)
                timestamp = None
                
                # Method 1: Check for time element with datetime attribute
                time_elem = article.find('time')
                if time_elem and time_elem.get('datetime'):
                    try:
                        dt_str = time_elem.get('datetime').replace('Z', '+00:00')
                        dt = datetime.fromisoformat(dt_str)
                        timestamp = dt.timestamp()
                    except:
                        pass
                
                # Method 2: Look for timestamp in data attributes or script tags in the full HTML
                if not timestamp and hasattr(self, '_current_html_content'):
                    timestamp_match = re.search(r'["\']timestamp["\']\s*:\s*["\']?(\d{10,13})', self._current_html_content, re.I)
                    if timestamp_match:
                        try:
                            ts = int(timestamp_match.group(1))
                            if ts > 1e12:  # milliseconds
                                ts = ts / 1000
                            timestamp = ts
                        except:
                            pass
                
                # Method 3: Use file modification time as fallback (better than current time)
                if not timestamp and file_mtime:
                    # Use file modification time minus some offset based on message position
                    # Assume messages are roughly 1 minute apart
                    messages_before = len(article_tags) - idx - 1
                    timestamp = file_mtime - (messages_before * 60)
                
                # Last resort: use current time minus index (approximate) - but this should rarely happen
                if not timestamp:
                    timestamp = datetime.utcnow().timestamp() - (len(article_tags) - idx) * 60
                    print(f"Warning: Using fallback timestamp for message {idx} in {html_path}")
                
                # Determine parent_id (simplified - assume linear conversation)
                parent_id = None
                if idx > 0 and messages:
                    parent_id = messages[-1].get('message_id')
                
                messages.append({
                    'message_id': message_id,
                    'parent_id': parent_id,
                    'role': role,
                    'model': model,
                    'content': content.strip(),
                    'timestamp': timestamp,
                    'index': idx
                })
            except Exception as e:
                # Skip problematic messages
                continue
        
        return messages
    
    def _import_grok_file(self, db: Session, html_path: str, html_filename: str, soup: BeautifulSoup, html_content: str, relative_path: str) -> Dict[str, Any]:
        """Import Grok conversation from HTML"""
        # Generate a unique ID for Grok conversations
        conversation_id = f"grok_{hashlib.md5(html_filename.encode()).hexdigest()[:32]}"
        
        # Extract title from filename or HTML
        title = html_filename.replace('.html', '')
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        
        # Check if already exists
        existing = db.query(ChatGPTConversation).filter(
            ChatGPTConversation.conversation_id == conversation_id
        ).first()
        
        if existing:
            return {'conversations': 0, 'messages': 0, 'reason': 'already_exists'}
        
        # Try to extract messages from Grok HTML structure
        # Grok HTML structure may be different, so we'll extract what we can
        messages = []
        
        # Look for message-like elements (this will need to be adapted based on actual Grok HTML structure)
        # Common patterns: divs with message classes, article tags, etc.
        potential_messages = soup.find_all(['div', 'article'], class_=re.compile('message|chat|user|assistant', re.I))
        
        # Get file modification time
        file_mtime = os.path.getmtime(html_path) if os.path.exists(html_path) else datetime.utcnow().timestamp()
        
        for idx, elem in enumerate(potential_messages[:50]):  # Limit to avoid too many
            content = elem.get_text(separator='\n', strip=True)
            if content and len(content) > 10:  # Only include meaningful messages
                messages.append({
                    'message_id': f"grok_msg_{idx}",
                    'parent_id': f"grok_msg_{idx-1}" if idx > 0 else None,
                    'role': 'user' if idx % 2 == 0 else 'assistant',  # Rough guess
                    'model': 'grok',
                    'content': content,
                    'timestamp': file_mtime - (len(potential_messages) - idx) * 60,
                    'index': idx
                })
        
        if not messages:
            return {'conversations': 0, 'messages': 0, 'reason': 'no_messages'}
        
        # Create conversation
        conversation = ChatGPTConversation(
            conversation_id=conversation_id,
            title=f"[Grok] {title}",
            create_time=file_mtime - len(messages) * 60,
            update_time=file_mtime,
            export_folder=f'HTMLS/{relative_path}',
            raw_data=json.dumps({'source': 'grok_html_export', 'filename': html_filename})
        )
        
        db.add(conversation)
        db.flush()
        
        # Import messages
        message_count = 0
        for msg_data in messages:
            try:
                message = ChatGPTMessage(
                    conversation_id=conversation_id,
                    message_id=msg_data['message_id'],
                    parent_id=msg_data['parent_id'],
                    role=msg_data['role'],
                    author=msg_data['role'],
                    content=msg_data['content'],
                    model=msg_data['model'],
                    create_time=msg_data['timestamp'],
                    status='finished_successfully',
                    raw_data=json.dumps({'source': 'grok_html_export', 'message_data': msg_data})
                )
                db.add(message)
                message_count += 1
                
                # Create timeline entry
                if msg_data.get('timestamp'):
                    timeline_entry = ChatGPTTimeline(
                        conversation_id=conversation_id,
                        event_type='message_sent',
                        timestamp=msg_data.get('timestamp'),
                        message_id=msg_data['message_id'],
                        title_preview='',
                        content_preview=msg_data.get('content', '')[:500],
                        timeline_metadata=json.dumps({
                            'role': msg_data.get('role'),
                            'model': msg_data.get('model'),
                            'source': 'grok_html_export'
                        })
                    )
                    db.add(timeline_entry)
            except:
                continue
        
        # Create conversation creation timeline entry
        if messages:
            timeline_entry = ChatGPTTimeline(
                conversation_id=conversation_id,
                event_type='conversation_created',
                timestamp=messages[0].get('timestamp', file_mtime),
                title_preview=f"[Grok] {title}",
                timeline_metadata=json.dumps({'source': 'grok_html_export', 'title': title})
            )
            db.add(timeline_entry)
        
        db.commit()
        return {'conversations': 1, 'messages': message_count}
    
    def _import_anthropic_file(self, db: Session, html_path: str, html_filename: str, soup: BeautifulSoup, html_content: str, relative_path: str) -> Dict[str, Any]:
        """Import Anthropic/Claude conversation from HTML"""
        conversation_id = f"anthropic_{hashlib.md5(html_filename.encode()).hexdigest()[:32]}"
        
        title = html_filename.replace('.html', '')
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        
        existing = db.query(ChatGPTConversation).filter(
            ChatGPTConversation.conversation_id == conversation_id
        ).first()
        
        if existing:
            return {'conversations': 0, 'messages': 0, 'reason': 'already_exists'}
        
        messages = []
        potential_messages = soup.find_all(['div', 'article'], class_=re.compile('message|chat|user|assistant', re.I))
        file_mtime = os.path.getmtime(html_path) if os.path.exists(html_path) else datetime.utcnow().timestamp()
        
        for idx, elem in enumerate(potential_messages[:50]):
            content = elem.get_text(separator='\n', strip=True)
            if content and len(content) > 10:
                messages.append({
                    'message_id': f"anthropic_msg_{idx}",
                    'parent_id': f"anthropic_msg_{idx-1}" if idx > 0 else None,
                    'role': 'user' if idx % 2 == 0 else 'assistant',
                    'model': 'claude',
                    'content': content,
                    'timestamp': file_mtime - (len(potential_messages) - idx) * 60,
                    'index': idx
                })
        
        if not messages:
            return {'conversations': 0, 'messages': 0, 'reason': 'no_messages'}
        
        conversation = ChatGPTConversation(
            conversation_id=conversation_id,
            title=f"[Anthropic] {title}",
            create_time=file_mtime - len(messages) * 60,
            update_time=file_mtime,
            export_folder=f'HTMLS/{relative_path}',
            raw_data=json.dumps({'source': 'anthropic_html_export', 'filename': html_filename})
        )
        
        db.add(conversation)
        db.flush()
        
        message_count = 0
        for msg_data in messages:
            try:
                message = ChatGPTMessage(
                    conversation_id=conversation_id,
                    message_id=msg_data['message_id'],
                    parent_id=msg_data['parent_id'],
                    role=msg_data['role'],
                    author=msg_data['role'],
                    content=msg_data['content'],
                    model=msg_data['model'],
                    create_time=msg_data['timestamp'],
                    status='finished_successfully',
                    raw_data=json.dumps({'source': 'anthropic_html_export', 'message_data': msg_data})
                )
                db.add(message)
                message_count += 1
                
                # Create timeline entry
                if msg_data.get('timestamp'):
                    timeline_entry = ChatGPTTimeline(
                        conversation_id=conversation_id,
                        event_type='message_sent',
                        timestamp=msg_data.get('timestamp'),
                        message_id=msg_data['message_id'],
                        title_preview='',
                        content_preview=msg_data.get('content', '')[:500],
                        timeline_metadata=json.dumps({
                            'role': msg_data.get('role'),
                            'model': msg_data.get('model'),
                            'source': 'anthropic_html_export'
                        })
                    )
                    db.add(timeline_entry)
            except:
                continue
        
        # Create conversation creation timeline entry
        if messages:
            timeline_entry = ChatGPTTimeline(
                conversation_id=conversation_id,
                event_type='conversation_created',
                timestamp=messages[0].get('timestamp', file_mtime),
                title_preview=f"[Anthropic] {title}",
                timeline_metadata=json.dumps({'source': 'anthropic_html_export', 'title': title})
            )
            db.add(timeline_entry)
        
        db.commit()
        return {'conversations': 1, 'messages': message_count}
    
    def _import_perplexity_file(self, db: Session, html_path: str, html_filename: str, soup: BeautifulSoup, html_content: str, relative_path: str) -> Dict[str, Any]:
        """Import Perplexity conversation from HTML"""
        conversation_id = f"perplexity_{hashlib.md5(html_filename.encode()).hexdigest()[:32]}"
        
        title = html_filename.replace('.html', '')
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        
        existing = db.query(ChatGPTConversation).filter(
            ChatGPTConversation.conversation_id == conversation_id
        ).first()
        
        if existing:
            return {'conversations': 0, 'messages': 0, 'reason': 'already_exists'}
        
        messages = []
        potential_messages = soup.find_all(['div', 'article'], class_=re.compile('message|chat|user|assistant', re.I))
        file_mtime = os.path.getmtime(html_path) if os.path.exists(html_path) else datetime.utcnow().timestamp()
        
        for idx, elem in enumerate(potential_messages[:50]):
            content = elem.get_text(separator='\n', strip=True)
            if content and len(content) > 10:
                messages.append({
                    'message_id': f"perplexity_msg_{idx}",
                    'parent_id': f"perplexity_msg_{idx-1}" if idx > 0 else None,
                    'role': 'user' if idx % 2 == 0 else 'assistant',
                    'model': 'perplexity',
                    'content': content,
                    'timestamp': file_mtime - (len(potential_messages) - idx) * 60,
                    'index': idx
                })
        
        if not messages:
            return {'conversations': 0, 'messages': 0, 'reason': 'no_messages'}
        
        conversation = ChatGPTConversation(
            conversation_id=conversation_id,
            title=f"[Perplexity] {title}",
            create_time=file_mtime - len(messages) * 60,
            update_time=file_mtime,
            export_folder=f'HTMLS/{relative_path}',
            raw_data=json.dumps({'source': 'perplexity_html_export', 'filename': html_filename})
        )
        
        db.add(conversation)
        db.flush()
        
        message_count = 0
        for msg_data in messages:
            try:
                message = ChatGPTMessage(
                    conversation_id=conversation_id,
                    message_id=msg_data['message_id'],
                    parent_id=msg_data['parent_id'],
                    role=msg_data['role'],
                    author=msg_data['role'],
                    content=msg_data['content'],
                    model=msg_data['model'],
                    create_time=msg_data['timestamp'],
                    status='finished_successfully',
                    raw_data=json.dumps({'source': 'perplexity_html_export', 'message_data': msg_data})
                )
                db.add(message)
                message_count += 1
                
                # Create timeline entry
                if msg_data.get('timestamp'):
                    timeline_entry = ChatGPTTimeline(
                        conversation_id=conversation_id,
                        event_type='message_sent',
                        timestamp=msg_data.get('timestamp'),
                        message_id=msg_data['message_id'],
                        title_preview='',
                        content_preview=msg_data.get('content', '')[:500],
                        timeline_metadata=json.dumps({
                            'role': msg_data.get('role'),
                            'model': msg_data.get('model'),
                            'source': 'perplexity_html_export'
                        })
                    )
                    db.add(timeline_entry)
            except:
                continue
        
        # Create conversation creation timeline entry
        if messages:
            timeline_entry = ChatGPTTimeline(
                conversation_id=conversation_id,
                event_type='conversation_created',
                timestamp=messages[0].get('timestamp', file_mtime),
                title_preview=f"[Perplexity] {title}",
                timeline_metadata=json.dumps({'source': 'perplexity_html_export', 'title': title})
            )
            db.add(timeline_entry)
        
        db.commit()
        return {'conversations': 1, 'messages': message_count}

