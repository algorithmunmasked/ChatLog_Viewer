"""
API Endpoints for ChatGPT Viewer
"""
from fastapi import APIRouter, HTTPException, Query, Depends, Request
from fastapi.responses import JSONResponse
from starlette.requests import Request
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import json

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
    db: Session = Depends(get_db)
):
    """List all conversations with pagination and search"""
    try:
        query = db.query(ChatGPTConversation)
        
        # Search by title or message content
        if search:
            if search_in_messages:
                # Search in both conversation titles and message content
                # Find conversation IDs that match title OR have messages matching search
                from sqlalchemy import or_
                
                # Get conversation IDs with matching titles
                title_conv_ids = [row[0] for row in db.query(ChatGPTConversation.conversation_id).filter(
                    ChatGPTConversation.title.contains(search)
                ).all()]
                
                # Get conversation IDs with matching message content
                message_conv_ids = [row[0] for row in db.query(ChatGPTMessage.conversation_id).filter(
                    ChatGPTMessage.content.contains(search)
                ).distinct().all()]
                
                # Combine both sets
                all_conv_ids = list(set(title_conv_ids + message_conv_ids))
                
                if all_conv_ids:
                    query = query.filter(ChatGPTConversation.conversation_id.in_(all_conv_ids))
                else:
                    # No matches, return empty result
                    query = query.filter(ChatGPTConversation.conversation_id == '')
            else:
                # Just search titles (default behavior)
                query = query.filter(ChatGPTConversation.title.contains(search))
        
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
        
        # Get message counts for each conversation
        results = []
        for conv in conversations:
            msg_count = db.query(ChatGPTMessage).filter(
                ChatGPTMessage.conversation_id == conv.conversation_id
            ).count()
            
            results.append({
                'conversation_id': conv.conversation_id,
                'title': conv.title,
                'create_time': conv.create_time,
                'update_time': conv.update_time,
                'message_count': msg_count,
                'model': conv.default_model_slug,
                'is_archived': conv.is_archived,
                'has_moderation_results': bool(conv.moderation_results),
                'has_blocked_urls': bool(conv.blocked_urls)
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
                'message_type': msg.message_type
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
        
        # Filter by search term (in conversation titles and content)
        if search:
            # First, find matching conversation IDs by title
            title_conv_ids = [row[0] for row in db.query(ChatGPTConversation.conversation_id).filter(
                ChatGPTConversation.title.contains(search)
            ).distinct().all()]
            
            # Find matching conversation IDs by message content
            message_conv_ids = [row[0] for row in db.query(ChatGPTMessage.conversation_id).filter(
                ChatGPTMessage.content.contains(search)
            ).distinct().all()]
            
            # Find matching timeline items by content preview or title preview
            timeline_conv_ids = [row[0] for row in db.query(ChatGPTTimeline.conversation_id).filter(
                (ChatGPTTimeline.content_preview.contains(search)) | 
                (ChatGPTTimeline.title_preview.contains(search))
            ).distinct().all() if row[0]]
            
            # Combine all matching conversation IDs
            all_conv_ids = list(set(title_conv_ids + message_conv_ids + timeline_conv_ids))
            
            if all_conv_ids:
                query = query.filter(ChatGPTTimeline.conversation_id.in_(all_conv_ids))
            else:
                # No matches, return empty result
                query = query.filter(ChatGPTTimeline.conversation_id == '')
        
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

