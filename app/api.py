"""
API Endpoints for ChatGPT Viewer
"""
from fastapi import APIRouter, HTTPException, Query, Depends, Request, UploadFile, File
from fastapi.responses import JSONResponse
from starlette.requests import Request
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import json
import os
import tempfile

from .database_service import ChatGPTDatabaseService
from .import_service import ChatGPTImportService
from .models import (
    ChatGPTConversation, ChatGPTMessage, ChatGPTMessageFeedback,
    ChatGPTModelComparison, ChatGPTTimeline, ChatGPTImportLog,
    ChatGPTTTLAuth, ChatGPTTTLBilling, ChatGPTTTLSession
)

router = APIRouter(prefix="/api/chatgpt-viewer", tags=["chatgpt-viewer"])

# Initialize services
db_service = ChatGPTDatabaseService()
import_service = ChatGPTImportService()


def get_db():
    """Dependency to get database session"""
    db = db_service.get_session()
    try:
        yield db
    finally:
        db.close()


@router.get("/messages/filtered")
async def get_filtered_messages(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Get messages that may have triggered content filters"""
    try:
        # Search for messages that actually triggered content filters
        # Look for specific indicators:
        # 1. finish_details.type == "content_filter" (in metadata.finish_details)
        # 2. Actual content_filter objects in the message
        # 3. finish_reason indicating content filtering
        # Note: We'll parse raw_data to check these conditions properly
        query = db.query(ChatGPTMessage).filter(
            # Check for content_filter in raw_data (but be more specific)
            (ChatGPTMessage.raw_data.contains('"content_filter"')) |
            (ChatGPTMessage.raw_data.contains('\"type\": \"content_filter\"')) |
            (ChatGPTMessage.finish_reason.ilike('%content_filter%')) |
            (ChatGPTMessage.finish_reason.ilike('%filter%')) |
            # Also check for moderation_results in the message
            (ChatGPTMessage.raw_data.contains('\"moderation_results\"'))
        )
        
        total = query.count()
        
        messages = query.order_by(
            desc(ChatGPTMessage.create_time)
        ).offset((page - 1) * per_page).limit(per_page).all()
        
        results = []
        for msg in messages:
            msg_dict = {
                'id': msg.id,
                'message_id': msg.message_id,
                'conversation_id': msg.conversation_id,
                'role': msg.role,
                'content': msg.content,  # Full content
                'model': msg.model,
                'finish_reason': msg.finish_reason,
                'create_time': msg.create_time
            }
            
            # Parse raw_data to extract ALL filter-related information
            if msg.raw_data:
                try:
                    raw = json.loads(msg.raw_data)
                    # Look for content filter fields
                    filter_info = {}
                    metadata_info = {}
                    
                    # Check in main message object
                    for key in raw.keys():
                        key_lower = key.lower()
                        if any(term in key_lower for term in ['content_filter', 'moderation_results', 'blocked']):
                            filter_info[key] = raw[key]
                    
                    # Check in metadata - especially finish_details
                    if 'metadata' in raw and isinstance(raw['metadata'], dict):
                        metadata = raw['metadata']
                        
                        # Check finish_details - this is key indicator
                        if 'finish_details' in metadata:
                            finish_details = metadata['finish_details']
                            if isinstance(finish_details, dict):
                                finish_type = finish_details.get('type', '')
                                if finish_type == 'content_filter' or 'filter' in finish_type.lower():
                                    metadata_info['finish_details'] = finish_details
                                    metadata_info['_flagged_reason'] = f"Message finished due to content filter: {finish_type}"
                        
                        # Check for other filter-related fields
                        for key in metadata.keys():
                            key_lower = key.lower()
                            if any(term in key_lower for term in ['content_filter', 'moderation', 'blocked', 'safety']):
                                metadata_info[key] = metadata[key]
                    
                    # Also check message_metadata column if available
                    if msg.message_metadata:
                        try:
                            msg_meta = json.loads(msg.message_metadata)
                            if isinstance(msg_meta, dict):
                                for key in msg_meta.keys():
                                    key_lower = key.lower()
                                    if any(term in key_lower for term in ['filter', 'safety', 'moderation', 'content_filter', 'blocked']):
                                        metadata_info[key] = msg_meta[key]
                        except:
                            pass
                    
                    if filter_info:
                        msg_dict['filter_info'] = filter_info
                    if metadata_info:
                        msg_dict['metadata_filter_info'] = metadata_info
                    
                    # Include full raw_data so user can inspect everything
                    msg_dict['raw_data'] = raw
                except:
                    pass
            
            results.append(msg_dict)
        
        return JSONResponse(content={
            'success': True,
            'messages': results,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations")
async def list_conversations(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    search_in_messages: bool = Query(False, description="Search in message content as well as titles"),
    sort_order: str = Query('newest', regex='^(newest|oldest)$'),
    show_hidden: bool = Query(False, description="Include hidden conversations in results"),
    db: Session = Depends(get_db)
):
    """List all conversations with pagination and search"""
    try:
        query = db.query(ChatGPTConversation)
        
        # Filter out hidden conversations unless show_hidden is True
        if not show_hidden:
            # SQLite uses 0/1 for booleans, so check for False (0) or None
            query = query.filter(
                (ChatGPTConversation.is_hidden == False) | 
                (ChatGPTConversation.is_hidden == None) |
                (ChatGPTConversation.is_hidden == 0)
            )
        
        # Search across all fields: conversation_id, message_id, title, message content
        if search and search.strip():
            from sqlalchemy import or_
            search_term = search.strip()
            
            # Make search case-insensitive by using func.lower() for SQLite
            # Get conversation IDs that match any of these criteria:
            # 1. Conversation ID matches (case-insensitive)
            conv_id_matches = [row[0] for row in db.query(ChatGPTConversation.conversation_id).filter(
                func.lower(ChatGPTConversation.conversation_id).contains(search_term.lower())
            ).all()]
            
            # 2. Conversation title matches (case-insensitive)
            title_conv_ids = [row[0] for row in db.query(ChatGPTConversation.conversation_id).filter(
                func.lower(ChatGPTConversation.title).contains(search_term.lower())
            ).all()]
            
            # 3. Message ID matches (find conversations containing messages with matching IDs, case-insensitive)
            message_id_conv_ids = [row[0] for row in db.query(ChatGPTMessage.conversation_id).filter(
                func.lower(ChatGPTMessage.message_id).contains(search_term.lower())
            ).distinct().all()]
            
            # 4. Message content matches (if search_in_messages is enabled, case-insensitive)
            message_content_conv_ids = []
            if search_in_messages:
                message_content_conv_ids = [row[0] for row in db.query(ChatGPTMessage.conversation_id).filter(
                    func.lower(ChatGPTMessage.content).contains(search_term.lower())
                ).distinct().all()]
            
            # Combine all matching conversation IDs
            all_conv_ids = list(set(conv_id_matches + title_conv_ids + message_id_conv_ids + message_content_conv_ids))
            
            if all_conv_ids:
                query = query.filter(ChatGPTConversation.conversation_id.in_(all_conv_ids))
            else:
                # No matches, return empty result by using an impossible condition
                # Use a condition that will never be true to return 0 results
                query = query.filter(ChatGPTConversation.conversation_id == '___NO_MATCHES___')
        
        # Get total count
        total = query.count()
        
        # Get paginated results with sort order
        if sort_order == 'oldest':
            conversations = query.order_by(
                ChatGPTConversation.create_time.asc()
            ).offset((page - 1) * per_page).limit(per_page).all()
        else:  # newest (default)
            conversations = query.order_by(
                desc(ChatGPTConversation.update_time)
            ).offset((page - 1) * per_page).limit(per_page).all()
        
        # Get message counts and date ranges for each conversation
        results = []
        for conv in conversations:
            msg_count = db.query(ChatGPTMessage).filter(
                ChatGPTMessage.conversation_id == conv.conversation_id
            ).count()
            
            # Get date range (earliest and latest message dates)
            date_range = db.query(
                func.min(ChatGPTMessage.create_time).label('earliest'),
                func.max(ChatGPTMessage.create_time).label('latest')
            ).filter(
                ChatGPTMessage.conversation_id == conv.conversation_id
            ).first()
            
            results.append({
                'conversation_id': conv.conversation_id,
                'title': conv.title,
                'create_time': conv.create_time,
                'update_time': conv.update_time,
                'message_count': msg_count,
                'model': conv.default_model_slug,
                'is_archived': conv.is_archived,
                'has_moderation_results': bool(conv.moderation_results),
                'has_blocked_urls': bool(conv.blocked_urls),
                'is_hidden': conv.is_hidden if hasattr(conv, 'is_hidden') else False,
                'date_range': {
                    'earliest': date_range.earliest if date_range else None,
                    'latest': date_range.latest if date_range else None
                }
            })
        
        return JSONResponse(content={
            'success': True,
            'conversations': results,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """Get full conversation details with ALL metadata"""
    try:
        conversation = db.query(ChatGPTConversation).filter(
            ChatGPTConversation.conversation_id == conversation_id
        ).first()
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Get all messages for this conversation
        messages = db.query(ChatGPTMessage).filter(
            ChatGPTMessage.conversation_id == conversation_id
        ).order_by(ChatGPTMessage.create_time).all()
        
        # Get feedback
        feedback = db.query(ChatGPTMessageFeedback).filter(
            ChatGPTMessageFeedback.conversation_id == conversation_id
        ).all()
        
        # Get model comparisons
        comparisons = db.query(ChatGPTModelComparison).filter(
            ChatGPTModelComparison.conversation_id == conversation_id
        ).all()
        
        # Parse raw_data
        raw_data = {}
        if conversation.raw_data:
            try:
                raw_data = json.loads(conversation.raw_data)
            except:
                pass
        
        # Build response
        result = {
            'conversation_id': conversation.conversation_id,
            'title': conversation.title,
            'create_time': conversation.create_time,
            'update_time': conversation.update_time,
            'current_node': conversation.current_node,
            'gizmo_id': conversation.gizmo_id,
            'gizmo_type': conversation.gizmo_type,
            'default_model_slug': conversation.default_model_slug,
            'conversation_template_id': conversation.conversation_template_id,
            'is_archived': conversation.is_archived,
            'is_starred': conversation.is_starred,
            'conversation_origin': conversation.conversation_origin,
            'voice': conversation.voice,
            'async_status': conversation.async_status,
            'workspace_id': conversation.workspace_id,
            'export_folder': conversation.export_folder,
            'raw_data': raw_data,
            'messages': [],
            'feedback': [],
            'comparisons': []
        }
        
        # Add parsed JSON arrays
        if conversation.plugin_ids:
            try:
                result['plugin_ids'] = json.loads(conversation.plugin_ids)
            except:
                result['plugin_ids'] = []
        if conversation.safe_urls:
            try:
                result['safe_urls'] = json.loads(conversation.safe_urls)
            except:
                result['safe_urls'] = []
        if conversation.blocked_urls:
            try:
                result['blocked_urls'] = json.loads(conversation.blocked_urls)
            except:
                result['blocked_urls'] = []
        if conversation.disabled_tool_ids:
            try:
                result['disabled_tool_ids'] = json.loads(conversation.disabled_tool_ids)
            except:
                result['disabled_tool_ids'] = []
        if conversation.moderation_results:
            try:
                result['moderation_results'] = json.loads(conversation.moderation_results)
            except:
                result['moderation_results'] = []
        
        # Add messages
        for msg in messages:
            msg_dict = {
                'message_id': msg.message_id,
                'parent_id': msg.parent_id,
                'role': msg.role,
                'author': msg.author,
                'content': msg.content,
                'recipient': msg.recipient,
                'model': msg.model,
                'model_slug': msg.model_slug,
                'finish_reason': msg.finish_reason,
                'create_time': msg.create_time,
                'update_time': msg.update_time,
                'status': msg.status,
                'weight': msg.weight,
                'message_type': msg.message_type,
                'is_hidden': msg.is_hidden if hasattr(msg, 'is_hidden') else False
            }
            
            # Parse JSON fields
            if msg.message_metadata:
                try:
                    msg_dict['metadata'] = json.loads(msg.message_metadata)
                except:
                    msg_dict['metadata'] = {}
            if msg.browser_info:
                try:
                    msg_dict['browser_info'] = json.loads(msg.browser_info)
                except:
                    msg_dict['browser_info'] = {}
            if msg.geo_data:
                try:
                    msg_dict['geo_data'] = json.loads(msg.geo_data)
                except:
                    msg_dict['geo_data'] = {}
            if msg.tokens:
                try:
                    msg_dict['tokens'] = json.loads(msg.tokens) if msg.tokens.startswith('{') or msg.tokens.startswith('[') else msg.tokens
                except:
                    msg_dict['tokens'] = msg.tokens
            
            # Add raw data
            if msg.raw_data:
                try:
                    msg_dict['raw_data'] = json.loads(msg.raw_data)
                except:
                    msg_dict['raw_data'] = {}
            
            result['messages'].append(msg_dict)
        
        # Add feedback
        for fb in feedback:
            fb_dict = {
                'feedback_id': fb.feedback_id,
                'message_id': fb.message_id,
                'user_id': fb.user_id,
                'rating': fb.rating,
                'create_time': fb.create_time,
                'update_time': fb.update_time,
                'evaluation_name': fb.evaluation_name,
                'evaluation_treatment': fb.evaluation_treatment,
                'workspace_id': fb.workspace_id
            }
            if fb.content:
                try:
                    fb_dict['content'] = json.loads(fb.content)
                except:
                    fb_dict['content'] = {}
            if fb.raw_data:
                try:
                    fb_dict['raw_data'] = json.loads(fb.raw_data)
                except:
                    fb_dict['raw_data'] = {}
            
            result['feedback'].append(fb_dict)
        
        # Add comparisons
        for comp in comparisons:
            comp_dict = {}
            if comp.comparison_data:
                try:
                    comp_dict = json.loads(comp.comparison_data)
                except:
                    comp_dict = {}
            if comp.raw_data:
                try:
                    comp_dict['raw_data'] = json.loads(comp.raw_data)
                except:
                    comp_dict['raw_data'] = {}
            
            result['comparisons'].append(comp_dict)
        
        return JSONResponse(content={
            'success': True,
            'conversation': result
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeline")
async def get_timeline(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = Query(None),
    start_time: Optional[float] = Query(None),
    end_time: Optional[float] = Query(None),
    sort_order: str = Query('newest', regex='^(newest|oldest)$'),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get chronological timeline of all events"""
    try:
        query = db.query(ChatGPTTimeline)
        
        # Filter by event type
        if event_type:
            query = query.filter(ChatGPTTimeline.event_type == event_type)
        
        # Filter by time range
        if start_time:
            query = query.filter(ChatGPTTimeline.timestamp >= start_time)
        if end_time:
            query = query.filter(ChatGPTTimeline.timestamp <= end_time)
        
        # Debug logging (remove in production if needed)
        if start_time or end_time:
            from datetime import datetime
            start_dt = datetime.fromtimestamp(start_time) if start_time else None
            end_dt = datetime.fromtimestamp(end_time) if end_time else None
            print(f"Timeline filter - Start: {start_time} ({start_dt}), End: {end_time} ({end_dt})")
            print(f"Total timeline items before filter: {db.query(ChatGPTTimeline).count()}")
            
            # Check a sample of actual timestamps in the database
            sample_timestamps = db.query(ChatGPTTimeline.timestamp).order_by(ChatGPTTimeline.timestamp.desc()).limit(5).all()
            print(f"Sample timestamps in DB: {[str(ts[0]) for ts in sample_timestamps]}")
            if sample_timestamps:
                sample_dates = [datetime.fromtimestamp(ts[0]).isoformat() for ts in sample_timestamps]
                print(f"Sample dates: {sample_dates}")
            
            # Check if timestamps might be in milliseconds
            if sample_timestamps:
                first_ts = sample_timestamps[0][0]
                if first_ts > 1000000000000:  # Likely milliseconds
                    print(f"WARNING: Timestamps appear to be in milliseconds (value: {first_ts})")
                    print(f"  If searching with seconds, would need to multiply by 1000")
            
            total_after = query.count()
            print(f"Total timeline items after filter: {total_after}")
        
        # Filter by search term (in timeline content and titles)
        if search and search.strip():
            search_term = search.strip()
            from sqlalchemy import or_
            
            # First, find message IDs that match the search term in their full content
            # This is important because timeline content_preview is only first 500 chars
            matching_message_ids = [row[0] for row in db.query(ChatGPTMessage.message_id).filter(
                func.lower(ChatGPTMessage.content).contains(search_term.lower())
            ).distinct().all() if row[0]]
            
            # Build filter: timeline preview matches OR full message content matches
            timeline_preview_filter = or_(
                func.lower(ChatGPTTimeline.content_preview).contains(search_term.lower()),
                func.lower(ChatGPTTimeline.title_preview).contains(search_term.lower())
            )
            
            if matching_message_ids:
                # Include timeline items where preview matches OR message_id matches a message with full content match
                query = query.filter(
                    timeline_preview_filter |
                    ChatGPTTimeline.message_id.in_(matching_message_ids)
                )
            else:
                # Only filter by timeline preview if no full message matches
                query = query.filter(timeline_preview_filter)
        
        # Get total count
        total = query.count()
        
        # Get paginated results with sort order
        if sort_order == 'oldest':
            timeline_items = query.order_by(
                ChatGPTTimeline.timestamp.asc()
            ).offset((page - 1) * per_page).limit(per_page).all()
        else:  # newest (default)
            timeline_items = query.order_by(
                desc(ChatGPTTimeline.timestamp)
            ).offset((page - 1) * per_page).limit(per_page).all()
        
        # Get conversation titles for all conversation IDs in the results
        conversation_ids = list(set([item.conversation_id for item in timeline_items if item.conversation_id]))
        conversations = {}
        if conversation_ids:
            conv_query = db.query(ChatGPTConversation).filter(
                ChatGPTConversation.conversation_id.in_(conversation_ids)
            )
            for conv in conv_query.all():
                conversations[conv.conversation_id] = conv.title or 'Untitled'
        
        results = []
        for item in timeline_items:
            # Get conversation title
            conversation_title = conversations.get(item.conversation_id, 'Unknown Conversation')
            
            item_dict = {
                'id': item.id,
                'timestamp': item.timestamp,
                'event_type': item.event_type,
                'conversation_id': item.conversation_id,
                'conversation_title': conversation_title,
                'message_id': item.message_id,
                'title_preview': item.title_preview,
                'content_preview': item.content_preview
            }
            
            # Parse metadata
            if item.timeline_metadata:
                try:
                    item_dict['metadata'] = json.loads(item.timeline_metadata)
                except:
                    item_dict['metadata'] = {}
            
            results.append(item_dict)
        
        return JSONResponse(content={
            'success': True,
            'timeline': results,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/{message_id}")
async def get_message(
    message_id: str,
    db: Session = Depends(get_db)
):
    """Get individual message with ALL metadata"""
    try:
        message = db.query(ChatGPTMessage).filter(
            ChatGPTMessage.message_id == message_id
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        result = {
            'message_id': message.message_id,
            'conversation_id': message.conversation_id,
            'parent_id': message.parent_id,
            'role': message.role,
            'author': message.author,
            'content': message.content,
            'recipient': message.recipient,
            'model': message.model,
            'model_slug': message.model_slug,
            'finish_reason': message.finish_reason,
            'create_time': message.create_time,
            'update_time': message.update_time,
            'status': message.status,
            'weight': message.weight,
            'message_type': message.message_type
        }
        
        # Parse JSON fields
        if message.message_metadata:
            try:
                result['metadata'] = json.loads(message.message_metadata)
            except:
                result['metadata'] = {}
        if message.browser_info:
            try:
                result['browser_info'] = json.loads(message.browser_info)
            except:
                result['browser_info'] = {}
        if message.geo_data:
            try:
                result['geo_data'] = json.loads(message.geo_data)
            except:
                result['geo_data'] = {}
        if message.tokens:
            try:
                result['tokens'] = json.loads(message.tokens) if message.tokens.startswith('{') or message.tokens.startswith('[') else message.tokens
            except:
                result['tokens'] = message.tokens
        
        # Add raw data
        if message.raw_data:
            try:
                result['raw_data'] = json.loads(message.raw_data)
            except:
                result['raw_data'] = {}
        
        return JSONResponse(content={
            'success': True,
            'message': result
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/import/status")
async def get_import_status(db: Session = Depends(get_db)):
    """Get import progress/status"""
    try:
        # Get all import logs
        logs = db.query(ChatGPTImportLog).order_by(
            desc(ChatGPTImportLog.import_started_at)
        ).all()
        
        # Get statistics
        total_conversations = db.query(ChatGPTConversation).count()
        total_messages = db.query(ChatGPTMessage).count()
        total_feedback = db.query(ChatGPTMessageFeedback).count()
        total_comparisons = db.query(ChatGPTModelComparison).count()
        
        # Count folders
        folders = import_service.scan_folders()
        
        results = []
        for log in logs:
            results.append({
                'export_folder': log.export_folder,
                'import_status': log.import_status,
                'conversations_count': log.conversations_count,
                'messages_count': log.messages_count,
                'feedback_count': log.feedback_count,
                'comparisons_count': log.comparisons_count,
                'import_started_at': log.import_started_at.isoformat() if log.import_started_at else None,
                'import_completed_at': log.import_completed_at.isoformat() if log.import_completed_at else None,
                'error_log': log.error_log
            })
        
        return JSONResponse(content={
            'success': True,
            'import_logs': results,
            'statistics': {
                'total_folders_found': len(folders),
                'total_conversations': total_conversations,
                'total_messages': total_messages,
                'total_feedback': total_feedback,
                'total_comparisons': total_comparisons
            }
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/html")
async def import_html_files(db: Session = Depends(get_db)):
    """Import HTML conversation files from HTMLS folder"""
    try:
        from .html_import import HTMLImportService
        
        service = HTMLImportService()
        results = service.import_all()
        
        # Include error details in response
        return JSONResponse(content={
            'success': True,
            'results': results,
            'error_details': results.get('errors', [])
        })
    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
        )


@router.post("/import/file")
async def import_single_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Import a single file (JSON or HTML)"""
    try:
        # Read file content
        content = await file.read()
        filename = file.filename or 'unknown'
        
        # Determine file type
        is_html = filename.lower().endswith('.html') or filename.lower().endswith('.htm')
        is_json = filename.lower().endswith('.json')
        
        if not (is_html or is_json):
            raise HTTPException(status_code=400, detail="File must be .json or .html")
        
        # Create temporary file to save uploaded content
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix=os.path.splitext(filename)[1]) as tmp_file:
            tmp_file.write(content)
            tmp_file_path = tmp_file.name
        
        try:
            if is_html:
                # Import HTML file
                from .html_import import HTMLImportService
                import shutil
                import uuid
                
                service = HTMLImportService()
                
                # Copy temp file to HTMLS folder temporarily (HTML import expects files in HTMLS folder)
                # Use a unique temporary filename to avoid conflicts
                project_root = os.path.dirname(os.path.dirname(__file__))
                htmls_folder = os.path.join(project_root, 'chatlog', 'HTMLS')
                os.makedirs(htmls_folder, exist_ok=True)
                
                # Create unique temp filename
                temp_filename = f"temp_{uuid.uuid4().hex[:8]}_{filename}"
                temp_html_path = os.path.join(htmls_folder, temp_filename)
                shutil.copy2(tmp_file_path, temp_html_path)
                
                try:
                    result = service.import_html_file(
                        db,
                        temp_filename,
                        subfolder='',
                        relative_path=temp_filename
                    )
                finally:
                    # Clean up temp file in HTMLS folder
                    if os.path.exists(temp_html_path):
                        os.remove(temp_html_path)
                
                return JSONResponse(content={
                    'success': True,
                    'filename': filename,
                    'file_type': 'html',
                    'conversations': result.get('conversations', 0),
                    'messages': result.get('messages', 0),
                    'reason': result.get('reason'),
                    'message': f"Imported {result.get('conversations', 0)} conversation(s) and {result.get('messages', 0)} message(s)"
                })
            
            else:
                # Import JSON file
                # Detect JSON file type by filename
                filename_lower = filename.lower()
                
                if 'conversation' in filename_lower:
                    # conversations.json - import conversations
                    result = import_service._import_conversations(db, tmp_file_path, f"uploaded_{filename}")
                    return JSONResponse(content={
                        'success': True,
                        'filename': filename,
                        'file_type': 'conversations_json',
                        'conversations': result.get('count', 0),
                        'messages': result.get('messages', 0),
                        'message': f"Imported {result.get('count', 0)} conversation(s) and {result.get('messages', 0)} message(s)"
                    })
                
                elif 'feedback' in filename_lower:
                    # message_feedback.json - import feedback
                    result = import_service._import_feedback(db, tmp_file_path)
                    return JSONResponse(content={
                        'success': True,
                        'filename': filename,
                        'file_type': 'feedback_json',
                        'feedback': result.get('count', 0),
                        'message': f"Imported {result.get('count', 0)} feedback record(s)"
                    })
                
                elif 'comparison' in filename_lower:
                    # model_comparisons.json - import comparisons
                    result = import_service._import_comparisons(db, tmp_file_path)
                    return JSONResponse(content={
                        'success': True,
                        'filename': filename,
                        'file_type': 'comparisons_json',
                        'comparisons': result.get('count', 0),
                        'message': f"Imported {result.get('count', 0)} comparison(s)"
                    })
                
                elif 'user' in filename_lower:
                    # user.json - import user
                    import_service._import_user(db, tmp_file_path, f"uploaded_{filename}")
                    return JSONResponse(content={
                        'success': True,
                        'filename': filename,
                        'file_type': 'user_json',
                        'message': "Imported user data"
                    })
                
                else:
                    # Try to auto-detect by parsing JSON structure
                    with open(tmp_file_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                    
                    # Check if it's a conversations array
                    if isinstance(json_data, list) and len(json_data) > 0:
                        first_item = json_data[0]
                        if 'conversation_id' in first_item and 'mapping' in first_item:
                            # Looks like conversations.json
                            result = import_service._import_conversations(db, tmp_file_path, f"uploaded_{filename}")
                            return JSONResponse(content={
                                'success': True,
                                'filename': filename,
                                'file_type': 'conversations_json',
                                'conversations': result.get('count', 0),
                                'messages': result.get('messages', 0),
                                'message': f"Auto-detected and imported {result.get('count', 0)} conversation(s) and {result.get('messages', 0)} message(s)"
                            })
                        elif 'id' in first_item and ('rating' in first_item or 'message_id' in first_item):
                            # Looks like feedback
                            result = import_service._import_feedback(db, tmp_file_path)
                            return JSONResponse(content={
                                'success': True,
                                'filename': filename,
                                'file_type': 'feedback_json',
                                'feedback': result.get('count', 0),
                                'message': f"Auto-detected and imported {result.get('count', 0)} feedback record(s)"
                            })
                    
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Could not determine JSON file type. Supported types: conversations.json, message_feedback.json, model_comparisons.json, user.json"
                    )
        
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
        )


@router.post("/export")
async def export_conversations(
    request: Request,
    db: Session = Depends(get_db)
):
    """Export selected conversations as JSON"""
    try:
        body = await request.json()
        conversation_ids = body.get('conversation_ids', [])
        
        if not conversation_ids:
            raise HTTPException(status_code=400, detail="No conversation IDs provided")
        
        # Fetch all conversations and their messages
        conversations_data = []
        
        for conv_id in conversation_ids:
            conv = db.query(ChatGPTConversation).filter(
                ChatGPTConversation.conversation_id == conv_id
            ).first()
            
            if not conv:
                continue
            
            # Get messages
            messages = db.query(ChatGPTMessage).filter(
                ChatGPTMessage.conversation_id == conv_id
            ).order_by(ChatGPTMessage.create_time).all()
            
            # Get feedback
            feedback = db.query(ChatGPTMessageFeedback).filter(
                ChatGPTMessageFeedback.conversation_id == conv_id
            ).all()
            
            # Build conversation export
            conv_data = {
                'conversation_id': conv.conversation_id,
                'title': conv.title,
                'create_time': conv.create_time,
                'update_time': conv.update_time,
                'messages': []
            }
            
            # Add raw_data if available
            if conv.raw_data:
                try:
                    conv_data['metadata'] = json.loads(conv.raw_data)
                except:
                    pass
            
            # Add messages
            for msg in messages:
                msg_data = {
                    'message_id': msg.message_id,
                    'role': msg.role,
                    'content': msg.content,
                    'model': msg.model,
                    'create_time': msg.create_time
                }
                
                if msg.raw_data:
                    try:
                        msg_data['metadata'] = json.loads(msg.raw_data)
                    except:
                        pass
                
                conv_data['messages'].append(msg_data)
            
            # Add feedback
            if feedback:
                conv_data['feedback'] = [
                    {
                        'feedback_id': f.feedback_id,
                        'message_id': f.message_id,
                        'rating': f.rating,
                        'content': f.content
                    }
                    for f in feedback
                ]
            
            conversations_data.append(conv_data)
        
        # Return as JSON file
        from fastapi.responses import Response
        return Response(
            content=json.dumps(conversations_data, indent=2, default=str),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=chatgpt_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export/messages")
async def export_messages(
    request: Request,
    db: Session = Depends(get_db)
):
    """Export selected messages as JSON"""
    try:
        body = await request.json()
        message_ids = body.get('message_ids', [])
        
        if not message_ids:
            raise HTTPException(status_code=400, detail="No message IDs provided")
        
        # Fetch all messages with their conversation data
        messages_data = []
        
        for msg_id in message_ids:
            msg = db.query(ChatGPTMessage).filter(
                ChatGPTMessage.message_id == msg_id
            ).first()
            
            if not msg:
                continue
            
            # Get conversation
            conv = db.query(ChatGPTConversation).filter(
                ChatGPTConversation.conversation_id == msg.conversation_id
            ).first()
            
            # Build message export
            msg_data = {
                'message_id': msg.message_id,
                'conversation_id': msg.conversation_id,
                'conversation_title': conv.title if conv else 'Unknown',
                'role': msg.role,
                'content': msg.content,
                'model': msg.model,
                'create_time': msg.create_time,
                'parent_id': msg.parent_id,
                'author': msg.author,
                'status': msg.status
            }
            
            # Add raw_data if available
            if msg.raw_data:
                try:
                    msg_data['metadata'] = json.loads(msg.raw_data)
                except:
                    pass
            
            # Add message metadata
            if msg.message_metadata:
                try:
                    msg_data['message_metadata'] = json.loads(msg.message_metadata)
                except:
                    pass
            
            if msg.browser_info:
                try:
                    msg_data['browser_info'] = json.loads(msg.browser_info)
                except:
                    pass
            
            if msg.geo_data:
                try:
                    msg_data['geo_data'] = json.loads(msg.geo_data)
                except:
                    pass
            
            messages_data.append(msg_data)
        
        # Return as JSON file
        from fastapi.responses import Response
        return Response(
            content=json.dumps(messages_data, indent=2, default=str),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=chatgpt_messages_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/start")
async def start_import(db: Session = Depends(get_db)):
    """Start importing from chatlog folder"""
    try:
        # Run import in background (in production, use background tasks)
        result = import_service.import_all()
        
        return JSONResponse(content={
            'success': True,
            'message': 'Import completed',
            'result': result
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ttl/sessions")
async def get_ttl_sessions(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Get TTL session data with geolocation/IP"""
    try:
        query = db.query(ChatGPTTTLSession)
        total = query.count()
        
        # Sort by created_at (datetime) descending, which is more reliable
        sessions = query.order_by(
            desc(ChatGPTTTLSession.created_at)
        ).offset((page - 1) * per_page).limit(per_page).all()
        
        results = []
        for session in sessions:
            session_dict = {
                'id': session.id,
                'user_id': session.user_id,
                'session_id': session.session_id,
                'create_time': session.create_time,
                'expiration_time': session.expiration_time,
                'last_auth_time': session.last_auth_time,
                'status': session.status,
                'ip_address': session.ip_address,
                'city': session.city,
                'country': session.country,
                'region': session.region,
                'region_code': session.region_code,
                'postal_code': session.postal_code,
                'latitude': session.latitude,
                'longitude': session.longitude,
                'timezone': session.timezone,
                'metro': session.metro,
                'continent': session.continent,
                'user_agent': session.user_agent
            }
            
            if session.raw_data:
                try:
                    session_dict['raw_data'] = json.loads(session.raw_data)
                except:
                    session_dict['raw_data'] = {}
            
            results.append(session_dict)
        
        return JSONResponse(content={
            'success': True,
            'sessions': results,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ttl/auth")
async def get_ttl_auth(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get TTL authentication data"""
    try:
        query = db.query(ChatGPTTTLAuth)
        total = query.count()
        
        auth_records = query.order_by(
            desc(ChatGPTTTLAuth.created_at)
        ).offset((page - 1) * per_page).limit(per_page).all()
        
        results = []
        for auth in auth_records:
            auth_dict = {
                'id': auth.id,
                'user_id': auth.user_id,
                'email': auth.email,
                'given_name': auth.given_name,
                'family_name': auth.family_name,
                'profile_image': auth.profile_image,
                'subscription_type': auth.subscription_type,
                'export_folder': auth.export_folder
            }
            
            # Parse JSON fields
            if auth.sessions:
                try:
                    auth_dict['sessions'] = json.loads(auth.sessions)
                except:
                    auth_dict['sessions'] = []
            if auth.api_keys:
                try:
                    auth_dict['api_keys'] = json.loads(auth.api_keys)
                except:
                    auth_dict['api_keys'] = []
            if auth.raw_data:
                try:
                    auth_dict['raw_data'] = json.loads(auth.raw_data)
                except:
                    auth_dict['raw_data'] = {}
            
            results.append(auth_dict)
        
        return JSONResponse(content={
            'success': True,
            'auth_records': results,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/messages/{message_id}/hidden")
async def update_message_hidden(
    message_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """Update the hidden status of a message"""
    try:
        body = await request.json()
        is_hidden = body.get('is_hidden', False)
        
        message = db.query(ChatGPTMessage).filter(
            ChatGPTMessage.message_id == message_id
        ).first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        message.is_hidden = is_hidden
        db.commit()
        
        return JSONResponse(content={
            'success': True,
            'message_id': message_id,
            'is_hidden': is_hidden
        })
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/conversations/{conversation_id}/hidden")
async def update_conversation_hidden(
    conversation_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """Update the hidden status of a conversation"""
    try:
        body = await request.json()
        is_hidden = body.get('is_hidden', False)
        
        conversation = db.query(ChatGPTConversation).filter(
            ChatGPTConversation.conversation_id == conversation_id
        ).first()
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        conversation.is_hidden = is_hidden
        db.commit()
        
        return JSONResponse(content={
            'success': True,
            'conversation_id': conversation_id,
            'is_hidden': is_hidden
        })
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """Delete a conversation and all its related data (messages, feedback, timeline entries, comparisons)"""
    try:
        # Check if conversation exists
        conversation = db.query(ChatGPTConversation).filter(
            ChatGPTConversation.conversation_id == conversation_id
        ).first()
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Count related data before deletion
        message_count = db.query(ChatGPTMessage).filter(
            ChatGPTMessage.conversation_id == conversation_id
        ).count()
        
        feedback_count = db.query(ChatGPTMessageFeedback).filter(
            ChatGPTMessageFeedback.conversation_id == conversation_id
        ).count()
        
        timeline_count = db.query(ChatGPTTimeline).filter(
            ChatGPTTimeline.conversation_id == conversation_id
        ).count()
        
        comparison_count = db.query(ChatGPTModelComparison).filter(
            ChatGPTModelComparison.conversation_id == conversation_id
        ).count()
        
        # Delete all related data
        db.query(ChatGPTMessage).filter(
            ChatGPTMessage.conversation_id == conversation_id
        ).delete()
        
        db.query(ChatGPTMessageFeedback).filter(
            ChatGPTMessageFeedback.conversation_id == conversation_id
        ).delete()
        
        db.query(ChatGPTTimeline).filter(
            ChatGPTTimeline.conversation_id == conversation_id
        ).delete()
        
        db.query(ChatGPTModelComparison).filter(
            ChatGPTModelComparison.conversation_id == conversation_id
        ).delete()
        
        # Delete the conversation itself
        db.delete(conversation)
        
        db.commit()
        
        return JSONResponse(content={
            'success': True,
            'conversation_id': conversation_id,
            'title': conversation.title,
            'deleted': {
                'messages': message_count,
                'feedback': feedback_count,
                'timeline_entries': timeline_count,
                'comparisons': comparison_count
            },
            'message': f'Deleted conversation "{conversation.title}" and {message_count} message(s), {feedback_count} feedback record(s), {timeline_count} timeline entry/entries, and {comparison_count} comparison(s)'
        })
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Get statistics"""
    try:
        total_conversations = db.query(ChatGPTConversation).count()
        total_messages = db.query(ChatGPTMessage).count()
        total_feedback = db.query(ChatGPTMessageFeedback).count()
        total_comparisons = db.query(ChatGPTModelComparison).count()
        total_timeline_events = db.query(ChatGPTTimeline).count()
        total_ttl_sessions = db.query(ChatGPTTTLSession).count()
        total_ttl_auth = db.query(ChatGPTTTLAuth).count()
        
        # Count by event type
        event_counts = db.query(
            ChatGPTTimeline.event_type,
            func.count(ChatGPTTimeline.id).label('count')
        ).group_by(ChatGPTTimeline.event_type).all()
        
        return JSONResponse(content={
            'success': True,
            'stats': {
                'total_conversations': total_conversations,
                'total_messages': total_messages,
                'total_feedback': total_feedback,
                'total_comparisons': total_comparisons,
                'total_timeline_events': total_timeline_events,
                'total_ttl_sessions': total_ttl_sessions,
                'total_ttl_auth': total_ttl_auth,
                'event_type_counts': {event_type: count for event_type, count in event_counts}
            }
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/database")
async def debug_database(db: Session = Depends(get_db)):
    """Debug endpoint to check database connection and contents"""
    import os
    from sqlalchemy import inspect, text
    
    try:
        # Get database path from the engine (use existing db_service instance)
        db_path = db_service.engine.url.database
        db_file_exists = os.path.exists(db_path) if db_path else False
        db_file_size = os.path.getsize(db_path) if db_file_exists else 0
        
        # Get table names
        inspector = inspect(db_service.engine)
        table_names = inspector.get_table_names()
        
        # Count records in each table
        table_counts = {}
        for table_name in table_names:
            try:
                result = db.query(text(f"SELECT COUNT(*) as count FROM {table_name}")).first()
                table_counts[table_name] = result[0] if result else 0
            except Exception as e:
                table_counts[table_name] = f"Error: {str(e)}"
        
        # Get sample records from key tables
        sample_conversations = db.query(ChatGPTConversation).limit(3).all()
        sample_messages = db.query(ChatGPTMessage).limit(3).all()
        
        # Check if tables exist
        tables_exist = {
            'chatgpt_conversations': inspector.has_table('chatgpt_conversations'),
            'chatgpt_messages': inspector.has_table('chatgpt_messages'),
            'chatgpt_message_feedback': inspector.has_table('chatgpt_message_feedback'),
            'chatgpt_timeline': inspector.has_table('chatgpt_timeline'),
        }
        
        return JSONResponse(content={
            'success': True,
            'database_path': db_path,
            'database_file_exists': db_file_exists,
            'database_file_size_mb': round(db_file_size / (1024 * 1024), 2) if db_file_exists else 0,
            'tables_found': table_names,
            'tables_exist': tables_exist,
            'table_counts': table_counts,
            'sample_conversations': [
                {
                    'conversation_id': c.conversation_id,
                    'title': c.title,
                    'create_time': c.create_time
                } for c in sample_conversations
            ],
            'sample_messages': [
                {
                    'message_id': m.message_id,
                    'conversation_id': m.conversation_id,
                    'role': m.role,
                    'content_preview': (m.content or '')[:100] if m.content else None
                } for m in sample_messages
            ],
            'connection_string': str(db_service.engine.url)
        })
    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
        )


@router.post("/cleanup/html-messages")
async def cleanup_html_messages(
    db: Session = Depends(get_db)
):
    """
    Remove HTML export messages that have JSON counterparts (same message_id).
    Keep HTML messages that don't have JSON versions (merge strategy).
    """
    try:
        # Find all messages from HTML export
        html_messages = db.query(ChatGPTMessage).filter(
            ChatGPTMessage.raw_data.contains('"source": "html_export"')
        ).all()
        
        removed_count = 0
        kept_count = 0
        conversations_affected = set()
        
        for html_msg in html_messages:
            # Check if there's a JSON message with the same message_id in the same conversation
            json_msg = db.query(ChatGPTMessage).filter(
                ChatGPTMessage.conversation_id == html_msg.conversation_id,
                ChatGPTMessage.message_id == html_msg.message_id,
                ~ChatGPTMessage.raw_data.contains('"source": "html_export"')
            ).first()
            
            if json_msg:
                # JSON version exists - remove HTML duplicate
                conversations_affected.add(html_msg.conversation_id)
                db.delete(html_msg)
                removed_count += 1
            else:
                # No JSON version - keep HTML message (it's unique)
                kept_count += 1
        
        db.commit()
        
        return JSONResponse(content={
            'success': True,
            'html_messages_removed': removed_count,
            'html_messages_kept': kept_count,
            'conversations_affected': len(conversations_affected),
            'message': f'Removed {removed_count} duplicate HTML messages. Kept {kept_count} unique HTML messages that have no JSON counterpart.'
        })
    except Exception as e:
        db.rollback()
        import traceback
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
        )


@router.get("/debug/search-messages")
async def debug_search_messages(
    search: str = Query(..., description="Search term to find in message content"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of results to return"),
    db: Session = Depends(get_db)
):
    """Debug endpoint to search for specific text in message content"""
    try:
        search_term = search.strip().lower()
        
        # Search in message content (case-insensitive)
        messages = db.query(ChatGPTMessage).filter(
            func.lower(ChatGPTMessage.content).contains(search_term)
        ).limit(limit).all()
        
        # Also check timeline
        timeline_items = db.query(ChatGPTTimeline).filter(
            func.lower(ChatGPTTimeline.content_preview).contains(search_term)
        ).limit(limit).all()
        
        # Get conversation info for messages
        results = []
        for msg in messages:
            conv = db.query(ChatGPTConversation).filter(
                ChatGPTConversation.conversation_id == msg.conversation_id
            ).first()
            
            # Find the position of the search term in the content
            content_lower = (msg.content or '').lower()
            search_pos = content_lower.find(search_term)
            preview_start = max(0, search_pos - 50)
            preview_end = min(len(msg.content or ''), search_pos + len(search_term) + 50)
            preview = (msg.content or '')[preview_start:preview_end] if msg.content else ''
            
            results.append({
                'type': 'message',
                'message_id': msg.message_id,
                'conversation_id': msg.conversation_id,
                'conversation_title': conv.title if conv else 'Unknown',
                'role': msg.role,
                'create_time': msg.create_time,
                'content_preview': preview,
                'full_content_length': len(msg.content or ''),
                'search_term_position': search_pos if search_pos >= 0 else None
            })
        
        timeline_results = []
        for item in timeline_items:
            conv = db.query(ChatGPTConversation).filter(
                ChatGPTConversation.conversation_id == item.conversation_id
            ).first()
            
            timeline_results.append({
                'type': 'timeline',
                'timeline_id': item.id,
                'message_id': item.message_id,
                'conversation_id': item.conversation_id,
                'conversation_title': conv.title if conv else 'Unknown',
                'event_type': item.event_type,
                'timestamp': item.timestamp,
                'content_preview': item.content_preview[:200] if item.content_preview else '',
                'preview_length': len(item.content_preview or '')
            })
        
        return JSONResponse(content={
            'success': True,
            'search_term': search,
            'message_count': len(results),
            'timeline_count': len(timeline_results),
            'messages': results,
            'timeline_items': timeline_results,
            'note': 'This searches the full message content. If no results, the message may not be in the database.'
        })
    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
        )

