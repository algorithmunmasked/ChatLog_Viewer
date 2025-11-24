"""
Import service for ChatGPT Viewer
Scans chatlog folder and imports all data into SQLite database
"""
import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from .database_service import ChatGPTDatabaseService
from .models import (
    ChatGPTUser, ChatGPTConversation, ChatGPTMessage,
    ChatGPTMessageFeedback, ChatGPTModelComparison,
    ChatGPTTimeline, ChatGPTImportLog,
    ChatGPTTTLAuth, ChatGPTTTLBilling, ChatGPTTTLSession
)
from .ttl_import import import_ttl_folder, import_ttl_auth, import_ttl_billing


class ChatGPTImportService:
    """Service for importing ChatGPT export data"""
    
    def __init__(self, chatlog_path: Optional[str] = None):
        """
        Initialize import service
        
        Args:
            chatlog_path: Path to chatlog folder. If None, uses chatlog/ in project root
        """
        self.db_service = ChatGPTDatabaseService()
        
        if chatlog_path is None:
            # Get project root (parent of app directory)
            # __file__ is at: app/import_service.py
            # dirname once: app/
            # dirname twice: ChatLog_standalone/ (project root)
            project_root = os.path.dirname(os.path.dirname(__file__))
            chatlog_path = os.path.join(project_root, 'chatlog')
        
        self.chatlog_path = chatlog_path
    
    def scan_folders(self) -> List[str]:
        """Scan chatlog folder for subfolders"""
        if not os.path.exists(self.chatlog_path):
            return []
        
        folders = []
        ttl_folders = {}  # Track TTL folders separately
        
        for item in os.listdir(self.chatlog_path):
            folder_path = os.path.join(self.chatlog_path, item)
            if os.path.isdir(folder_path):
                # Check if this is a TTL folder - either ends with ' - ttl' or is just 'ttl'
                if item.endswith(' - ttl'):
                    # Try to match with conversation folder
                    base_name = item.replace(' - ttl', '')
                    ttl_folders[base_name] = item
                elif item.lower() == 'ttl':
                    # Standalone 'ttl' folder
                    ttl_folders['_standalone'] = item
                else:
                    folders.append(item)
        
        # Add TTL folders to the list (they'll be processed with their conversation folders)
        # But also add standalone TTL folders (ones without matching conversation folders)
        for ttl_base, ttl_folder in ttl_folders.items():
            if ttl_base == '_standalone' or ttl_base not in folders:
                # Standalone TTL folder, add it
                folders.append(ttl_folder)
        
        return sorted(folders)
    
    def import_all(self) -> Dict[str, Any]:
        """Import all folders from chatlog"""
        folders = self.scan_folders()
        results = {
            'total_folders': len(folders),
            'processed': 0,
            'skipped': 0,
            'errors': 0,
            'conversations': 0,
            'messages': 0,
            'feedback': 0,
            'comparisons': 0,
            'ttl_auth': 0,
            'ttl_billing': 0,
            'ttl_sessions': 0,
            'errors_list': []
        }
        
        db = self.db_service.get_session()
        try:
            for folder in folders:
                try:
                    result = self.import_folder(db, folder)
                    if result['status'] == 'completed':
                        results['processed'] += 1
                        results['conversations'] += result.get('conversations', 0)
                        results['messages'] += result.get('messages', 0)
                        results['feedback'] += result.get('feedback', 0)
                        results['comparisons'] += result.get('comparisons', 0)
                        results['ttl_auth'] += result.get('ttl_auth', 0)
                        results['ttl_billing'] += result.get('ttl_billing', 0)
                        results['ttl_sessions'] += result.get('ttl_sessions', 0)
                    elif result['status'] == 'skipped':
                        results['skipped'] += 1
                    else:
                        results['errors'] += 1
                        results['errors_list'].append(f"{folder}: {result.get('error', 'Unknown error')}")
                except Exception as e:
                    results['errors'] += 1
                    results['errors_list'].append(f"{folder}: {str(e)}")
            
            db.commit()
        except Exception as e:
            db.rollback()
            results['errors_list'].append(f"Import failed: {str(e)}")
        finally:
            db.close()
        
        return results
    
    def import_folder(self, db: Session, folder_name: str) -> Dict[str, Any]:
        """Import a single folder"""
        folder_path = os.path.join(self.chatlog_path, folder_name)
        
        # Check if already imported
        existing_log = db.query(ChatGPTImportLog).filter(
            ChatGPTImportLog.export_folder == folder_name
        ).first()
        
        if existing_log and existing_log.import_status == 'completed':
            return {'status': 'skipped', 'message': 'Already imported'}
        
        # Create or update import log
        if existing_log:
            import_log = existing_log
            import_log.import_status = 'in_progress'
            import_log.import_started_at = datetime.utcnow()
        else:
            import_log = ChatGPTImportLog(
                export_folder=folder_name,
                import_status='in_progress',
                import_started_at=datetime.utcnow()
            )
            db.add(import_log)
        
        db.commit()
        
        result = {
            'status': 'in_progress',
            'conversations': 0,
            'messages': 0,
            'feedback': 0,
            'comparisons': 0
        }
        
        try:
            # Import user.json
            user_path = os.path.join(folder_path, 'user.json')
            if os.path.exists(user_path):
                self._import_user(db, user_path, folder_name)
            
            # Import conversations.json
            conversations_path = os.path.join(folder_path, 'conversations.json')
            if os.path.exists(conversations_path):
                conv_result = self._import_conversations(db, conversations_path, folder_name)
                result['conversations'] = conv_result.get('count', 0)
                result['messages'] = conv_result.get('messages', 0)
            
            # Import message_feedback.json
            feedback_path = os.path.join(folder_path, 'message_feedback.json')
            if os.path.exists(feedback_path):
                feedback_result = self._import_feedback(db, feedback_path)
                result['feedback'] = feedback_result.get('count', 0)
            
            # Import model_comparisons.json (optional)
            comparisons_path = os.path.join(folder_path, 'model_comparisons.json')
            if os.path.exists(comparisons_path):
                comp_result = self._import_comparisons(db, comparisons_path)
                result['comparisons'] = comp_result.get('count', 0)
            
            # Check if this is a TTL folder (ends with " - ttl" or is just "ttl")
            if folder_name.endswith(' - ttl') or folder_name.lower() == 'ttl':
                # Extract base name to potentially match with conversation folder
                if folder_name.endswith(' - ttl'):
                    base_name = folder_name.replace(' - ttl', '')
                else:
                    base_name = None  # Standalone 'ttl' folder
                ttl_result = import_ttl_folder(db, folder_path, folder_name, base_name)
                result['ttl_auth'] = ttl_result.get('auth_count', 0)
                result['ttl_billing'] = ttl_result.get('billing_count', 0)
                result['ttl_sessions'] = ttl_result.get('sessions_count', 0)
            
            # Also check if there's a matching TTL folder for this conversation folder
            if not folder_name.endswith(' - ttl'):
                ttl_folder_name = f"{folder_name} - ttl"
                ttl_folder_path = os.path.join(os.path.dirname(folder_path), ttl_folder_name)
                if os.path.exists(ttl_folder_path) and os.path.isdir(ttl_folder_path):
                    # Import TTL folder associated with this conversation folder
                    ttl_result = import_ttl_folder(db, ttl_folder_path, ttl_folder_name, folder_name)
                    result['ttl_auth'] = (result.get('ttl_auth', 0) + ttl_result.get('auth_count', 0))
                    result['ttl_billing'] = (result.get('ttl_billing', 0) + ttl_result.get('billing_count', 0))
                    result['ttl_sessions'] = (result.get('ttl_sessions', 0) + ttl_result.get('sessions_count', 0))
            
            # Update import log
            import_log.import_status = 'completed'
            import_log.import_completed_at = datetime.utcnow()
            import_log.conversations_count = result.get('conversations', 0)
            import_log.messages_count = result.get('messages', 0)
            import_log.feedback_count = result.get('feedback', 0)
            import_log.comparisons_count = result.get('comparisons', 0)
            import_log.ttl_auth_count = result.get('ttl_auth', 0)
            import_log.ttl_billing_count = result.get('ttl_billing', 0)
            import_log.ttl_sessions_count = result.get('ttl_sessions', 0)
            
            db.commit()
            result['status'] = 'completed'
            
        except Exception as e:
            db.rollback()
            import_log.import_status = 'error'
            import_log.error_log = str(e)
            db.commit()
            result['status'] = 'error'
            result['error'] = str(e)
        
        return result
    
    def _import_user(self, db: Session, user_path: str, folder_name: str):
        """Import user.json"""
        with open(user_path, 'r', encoding='utf-8') as f:
            user_data = json.load(f)
        
        # Check if user already exists for this export folder
        existing = db.query(ChatGPTUser).filter(
            ChatGPTUser.export_folder == folder_name
        ).first()
        
        if existing:
            return
        
        user = ChatGPTUser(
            email=user_data.get('email'),
            chatgpt_plus_user=user_data.get('chatgpt_plus_user', False),
            phone_number=user_data.get('phone_number'),
            export_folder=folder_name,
            raw_data=json.dumps(user_data)
        )
        
        db.add(user)
        db.commit()
    
    def _import_conversations(self, db: Session, conversations_path: str, folder_name: str) -> Dict[str, Any]:
        """Import conversations.json"""
        with open(conversations_path, 'r', encoding='utf-8') as f:
            conversations = json.load(f)
        
        if not isinstance(conversations, list):
            return {'count': 0, 'messages': 0}
        
        count = 0
        message_count = 0
        
        for conv_data in conversations:
            conversation_id = conv_data.get('conversation_id')
            if not conversation_id:
                continue
            
            # Check if conversation already exists
            existing_conv = db.query(ChatGPTConversation).filter(
                ChatGPTConversation.conversation_id == conversation_id
            ).first()
            
            is_new_conversation = existing_conv is None
            
            if is_new_conversation:
                # Create new conversation
                conversation = ChatGPTConversation(
                    conversation_id=conversation_id,
                    title=conv_data.get('title'),
                    create_time=conv_data.get('create_time'),
                    update_time=conv_data.get('update_time'),
                    current_node=conv_data.get('current_node'),
                    gizmo_id=conv_data.get('gizmo_id'),
                    gizmo_type=conv_data.get('gizmo_type'),
                    default_model_slug=conv_data.get('default_model_slug'),
                    conversation_template_id=conv_data.get('conversation_template_id'),
                    is_archived=conv_data.get('is_archived', False),
                    is_starred=conv_data.get('is_starred'),
                    conversation_origin=conv_data.get('conversation_origin'),
                    voice=conv_data.get('voice'),
                    async_status=conv_data.get('async_status'),
                    workspace_id=conv_data.get('workspace_id'),
                    export_folder=folder_name,
                    raw_data=json.dumps(conv_data)
                )
                
                # Store arrays as JSON strings
                if conv_data.get('plugin_ids'):
                    conversation.plugin_ids = json.dumps(conv_data['plugin_ids'])
                if conv_data.get('safe_urls'):
                    conversation.safe_urls = json.dumps(conv_data['safe_urls'])
                if conv_data.get('blocked_urls'):
                    conversation.blocked_urls = json.dumps(conv_data['blocked_urls'])
                if conv_data.get('disabled_tool_ids'):
                    conversation.disabled_tool_ids = json.dumps(conv_data['disabled_tool_ids'])
                if conv_data.get('moderation_results'):
                    conversation.moderation_results = json.dumps(conv_data['moderation_results'])
                
                db.add(conversation)
                db.flush()
                
                # Add to timeline for new conversation
                if conversation.create_time:
                    timeline_entry = ChatGPTTimeline(
                        timestamp=conversation.create_time,
                        event_type='conversation_created',
                        conversation_id=conversation_id,
                        title_preview=conversation.title or 'Untitled',
                        content_preview='',
                        timeline_metadata=json.dumps({'folder': folder_name})
                    )
                    db.add(timeline_entry)
                
                count += 1
            else:
                # Update existing conversation metadata (update_time, title, etc.)
                # Only update if the new data is more recent or different
                if conv_data.get('update_time') and (not existing_conv.update_time or conv_data.get('update_time') > existing_conv.update_time):
                    existing_conv.update_time = conv_data.get('update_time')
                if conv_data.get('title') and conv_data.get('title') != existing_conv.title:
                    existing_conv.title = conv_data.get('title')
                if conv_data.get('current_node'):
                    existing_conv.current_node = conv_data.get('current_node')
                if conv_data.get('is_archived') is not None:
                    existing_conv.is_archived = conv_data.get('is_archived')
                if conv_data.get('is_starred') is not None:
                    existing_conv.is_starred = conv_data.get('is_starred')
                db.flush()
            
            # Import messages from mapping - check each message by message_id
            messages = self._extract_messages(conv_data.get('mapping', {}), conversation_id)
            for msg_data in messages:
                message_id = msg_data.get('message_id') or msg_data.get('id')
                if not message_id:
                    continue
                
                # Check if message already exists
                existing_msg = db.query(ChatGPTMessage).filter(
                    ChatGPTMessage.message_id == message_id,
                    ChatGPTMessage.conversation_id == conversation_id
                ).first()
                
                if existing_msg:
                    # Message already exists, skip it
                    continue
                
                # Create new message
                message, timeline_entry = self._create_message(msg_data, conversation_id)
                db.add(message)
                if timeline_entry:
                    db.add(timeline_entry)
                message_count += 1
        
        db.commit()
        return {'count': count, 'messages': message_count}
    
    def _extract_messages(self, mapping: Dict[str, Any], conversation_id: str) -> List[Dict[str, Any]]:
        """Extract all messages from mapping structure using iterative approach (avoids recursion issues)"""
        messages = []
        processed = set()
        
        # Use iterative approach with a stack to avoid recursion depth issues
        # Find root nodes (nodes without parents or with null parents)
        root_nodes = []
        for node_id, node in mapping.items():
            parent = node.get('parent')
            if not parent or parent not in mapping or parent == node_id:
                root_nodes.append(node_id)
        
        # Stack-based traversal starting from root nodes
        stack = list(root_nodes) if root_nodes else list(mapping.keys())[:1]  # Start with first node if no roots
        
        while stack:
            node_id = stack.pop()
            
            # Skip if already processed
            if node_id in processed or node_id not in mapping:
                continue
            
            processed.add(node_id)
            node = mapping[node_id]
            
            # Extract message if present
            message_data = node.get('message')
            if message_data:
                msg = {
                    'message_id': node_id,
                    'parent_id': node.get('parent'),
                    'conversation_id': conversation_id,
                    **message_data
                }
                messages.append(msg)
            
            # Add children to stack (reverse order so we process left-to-right)
            children = node.get('children', [])
            if children and isinstance(children, list):
                # Filter out invalid references
                valid_children = [c for c in children if c and c != node_id and c not in processed]
                stack.extend(reversed(valid_children))
        
        # Process any orphaned nodes that weren't reached
        for node_id in mapping.keys():
            if node_id not in processed:
                processed.add(node_id)
                node = mapping[node_id]
                message_data = node.get('message')
                if message_data:
                    msg = {
                        'message_id': node_id,
                        'parent_id': node.get('parent'),
                        'conversation_id': conversation_id,
                        **message_data
                    }
                    messages.append(msg)
        
        return messages
    
    def _create_message(self, msg_data: Dict[str, Any], conversation_id: str) -> tuple[ChatGPTMessage, Optional[ChatGPTTimeline]]:
        """Create a message record from message data"""
        # Extract content (could be text, parts array, etc.)
        content = ''
        if isinstance(msg_data.get('content'), str):
            content = msg_data['content']
        elif isinstance(msg_data.get('content'), dict):
            # Content might be in content.content.parts or similar
            content_obj = msg_data['content']
            if 'parts' in content_obj:
                parts = content_obj['parts']
                if isinstance(parts, list):
                    content = '\n'.join(str(p) for p in parts if p)
            else:
                content = json.dumps(content_obj)
        elif isinstance(msg_data.get('content'), list):
            content = '\n'.join(str(p) for p in msg_data['content'] if p)
        
        # Extract metadata - look for browser, geo, IP info
        metadata = {}
        browser_info = {}
        geo_data = {}
        
        # Check for any metadata fields
        for key, value in msg_data.items():
            if key in ['content', 'id', 'parent', 'conversation_id', 'message_id']:
                continue
            if isinstance(value, (dict, list)):
                # Store complex objects in metadata
                metadata[key] = value
                # Check for browser/geo keywords
                key_lower = key.lower()
                if 'browser' in key_lower or 'user_agent' in key_lower or 'client' in key_lower:
                    browser_info[key] = value
                if 'geo' in key_lower or 'location' in key_lower or 'lat' in key_lower or 'lon' in key_lower or 'ip' in key_lower:
                    geo_data[key] = value
            else:
                metadata[key] = value
        
        message = ChatGPTMessage(
            conversation_id=conversation_id,
            message_id=msg_data.get('message_id') or msg_data.get('id'),
            parent_id=msg_data.get('parent_id') or msg_data.get('parent'),
            role=msg_data.get('role') or msg_data.get('author', {}).get('role'),
            author=msg_data.get('author', {}).get('role') if isinstance(msg_data.get('author'), dict) else str(msg_data.get('author', '')),
            content=content[:100000] if content else '',  # Limit content length
            recipient=msg_data.get('recipient'),
            model=msg_data.get('model') or (msg_data.get('metadata', {}) or {}).get('model_slug') if isinstance(msg_data.get('metadata'), dict) else None,
            model_slug=msg_data.get('model_slug') or (msg_data.get('metadata', {}) or {}).get('model_slug') if isinstance(msg_data.get('metadata'), dict) else None,
            finish_reason=msg_data.get('finish_reason'),
            create_time=msg_data.get('create_time'),
            update_time=msg_data.get('update_time'),
            status=msg_data.get('status'),
            weight=msg_data.get('weight'),
            message_type=msg_data.get('message_type'),
            raw_data=json.dumps(msg_data)
        )
        
        # Store metadata as JSON
        if metadata:
            message.message_metadata = json.dumps(metadata)
        if browser_info:
            message.browser_info = json.dumps(browser_info)
        if geo_data:
            message.geo_data = json.dumps(geo_data)
        
        # Extract token info if present
        if 'usage' in msg_data:
            message.tokens = json.dumps(msg_data['usage'])
        elif 'tokens' in msg_data:
            message.tokens = str(msg_data['tokens']) if not isinstance(msg_data['tokens'], (dict, list)) else json.dumps(msg_data['tokens'])
        
        # Create timeline entry
        timeline_entry = None
        if message.create_time:
            timeline_entry = ChatGPTTimeline(
                timestamp=message.create_time,
                event_type='message_sent',
                conversation_id=conversation_id,
                message_id=message.message_id,
                title_preview='',
                content_preview=content[:500] if content else '',
                timeline_metadata=json.dumps({
                    'role': message.role,
                    'author': message.author,
                    'model': message.model
                })
            )
        
        return message, timeline_entry
    
    def _import_feedback(self, db: Session, feedback_path: str) -> Dict[str, Any]:
        """Import message_feedback.json"""
        with open(feedback_path, 'r', encoding='utf-8') as f:
            feedback_list = json.load(f)
        
        if not isinstance(feedback_list, list):
            return {'count': 0}
        
        count = 0
        for fb_data in feedback_list:
            feedback_id = fb_data.get('id')
            if not feedback_id:
                continue
            
            # Check if already exists by feedback_id from JSON
            existing = db.query(ChatGPTMessageFeedback).filter(
                ChatGPTMessageFeedback.feedback_id == feedback_id
            ).first()
            
            if existing:
                continue
            
            feedback = ChatGPTMessageFeedback(
                feedback_id=feedback_id,
                conversation_id=fb_data.get('conversation_id'),
                message_id=fb_data.get('message_id'),
                user_id=fb_data.get('user_id'),
                rating=fb_data.get('rating'),
                create_time=fb_data.get('create_time'),
                update_time=fb_data.get('update_time'),
                evaluation_name=fb_data.get('evaluation_name'),
                evaluation_treatment=fb_data.get('evaluation_treatment'),
                workspace_id=fb_data.get('workspace_id'),
                content=json.dumps(fb_data.get('content', {})),
                raw_data=json.dumps(fb_data)
            )
            
            db.add(feedback)
            
            # Add to timeline
            if fb_data.get('create_time'):
                # Parse ISO timestamp (format: "2023-06-21T18:45:36.953760Z")
                try:
                    time_str = fb_data['create_time']
                    # Remove Z and parse
                    if time_str.endswith('Z'):
                        time_str = time_str[:-1] + '+00:00'
                    dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    timestamp = dt.timestamp()
                except:
                    timestamp = None
                
                if timestamp:
                    timeline_entry = ChatGPTTimeline(
                        timestamp=timestamp,
                        event_type='feedback_given',
                        conversation_id=fb_data.get('conversation_id'),
                        message_id=fb_data.get('message_id'),
                        title_preview='',
                        content_preview=f"Rating: {fb_data.get('rating', 'unknown')}",
                        timeline_metadata=json.dumps({
                            'user_id': fb_data.get('user_id'),
                            'rating': fb_data.get('rating')
                        })
                    )
                    db.add(timeline_entry)
            
            count += 1
        
        db.commit()
        return {'count': count}
    
    def _import_comparisons(self, db: Session, comparisons_path: str) -> Dict[str, Any]:
        """Import model_comparisons.json"""
        with open(comparisons_path, 'r', encoding='utf-8') as f:
            comparisons_data = json.load(f)
        
        count = 0
        
        # Comparisons might be a dict keyed by conversation_id or a list
        if isinstance(comparisons_data, dict):
            for conversation_id, comp_data in comparisons_data.items():
                comparison = ChatGPTModelComparison(
                    conversation_id=conversation_id,
                    comparison_data=json.dumps(comp_data),
                    raw_data=json.dumps({conversation_id: comp_data})
                )
                db.add(comparison)
                count += 1
        elif isinstance(comparisons_data, list):
            for comp_data in comparisons_data:
                conversation_id = comp_data.get('conversation_id')
                if conversation_id:
                    comparison = ChatGPTModelComparison(
                        conversation_id=conversation_id,
                        comparison_data=json.dumps(comp_data),
                        raw_data=json.dumps(comp_data)
                    )
                    db.add(comparison)
                    count += 1
        
        db.commit()
        return {'count': count}

