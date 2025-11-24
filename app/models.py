"""
Standalone models for ChatGPT Viewer
Completely independent from existing models to avoid breaking anything
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import json

# SQLite supports JSON via TEXT with JSON functions
# For SQLite, we'll use Text columns and handle JSON serialization in Python
Base = declarative_base()

class ChatGPTUser(Base):
    """User info from user.json"""
    __tablename__ = "chatgpt_users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255))
    chatgpt_plus_user = Column(Boolean, default=False)
    phone_number = Column(String(50))
    export_folder = Column(String(500), index=True)
    raw_data = Column(Text)  # Complete user.json as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatGPTConversation(Base):
    """Main conversation metadata - extract ALL fields"""
    __tablename__ = "chatgpt_conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(255), unique=True, nullable=False, index=True)
    title = Column(Text)
    create_time = Column(Float)  # Unix timestamp
    update_time = Column(Float)  # Unix timestamp
    current_node = Column(String(255))
    
    # Gizmo/Custom GPT fields
    gizmo_id = Column(String(255))
    gizmo_type = Column(String(100))
    
    # Model and template
    default_model_slug = Column(String(255))
    conversation_template_id = Column(String(255))
    
    # Status flags
    is_archived = Column(Boolean, default=False)
    is_starred = Column(Boolean)
    conversation_origin = Column(String(255))
    is_hidden = Column(Boolean, default=False, index=True)  # User can hide conversations they've reviewed
    
    # Audio/async
    voice = Column(String(255))
    async_status = Column(String(255))
    
    # Lists/arrays stored as JSON strings
    plugin_ids = Column(Text)  # JSON array
    safe_urls = Column(Text)  # JSON array
    blocked_urls = Column(Text)  # JSON array
    disabled_tool_ids = Column(Text)  # JSON array
    moderation_results = Column(Text)  # JSON array
    
    # Additional fields
    workspace_id = Column(String(255))
    
    # Storage
    export_folder = Column(String(500), index=True)
    raw_data = Column(Text)  # Complete conversation object as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatGPTMessage(Base):
    """Individual messages - extract ALL metadata possible"""
    __tablename__ = "chatgpt_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(255), ForeignKey('chatgpt_conversations.conversation_id'), nullable=False, index=True)
    message_id = Column(String(255), nullable=False, index=True)
    parent_id = Column(String(255), index=True)
    
    # Message content
    role = Column(String(50))  # user, assistant, system
    author = Column(String(50))  # user, assistant, system
    content = Column(Text)  # Main message content
    recipient = Column(String(50))
    
    # Model and completion
    model = Column(String(255))
    model_slug = Column(String(255))
    finish_reason = Column(String(100))
    
    # Timing
    create_time = Column(Float)  # Unix timestamp
    update_time = Column(Float)  # Unix timestamp
    
    # Status and metadata
    status = Column(String(100))
    weight = Column(Float)
    message_type = Column(String(100))
    
    # Token info (stored as JSON if it's an object)
    tokens = Column(Text)  # JSON or number as string
    
    # Metadata stored as JSON strings
    message_metadata = Column(Text)  # JSON object (renamed from 'metadata' - reserved in SQLAlchemy)
    browser_info = Column(Text)  # JSON object (if present)
    geo_data = Column(Text)  # JSON object (if present)
    
    # Complete raw message object
    raw_data = Column(Text)  # Complete message object as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # User preferences
    is_hidden = Column(Boolean, default=False, index=True)  # User can hide messages they've reviewed


class ChatGPTMessageFeedback(Base):
    """Feedback/ratings from message_feedback.json"""
    __tablename__ = "chatgpt_message_feedback"
    
    id = Column(Integer, primary_key=True, index=True)
    feedback_id = Column(String(255), unique=True, index=True)  # ID from JSON file
    conversation_id = Column(String(255), ForeignKey('chatgpt_conversations.conversation_id'), index=True)
    message_id = Column(String(255), index=True)
    user_id = Column(String(255), index=True)
    rating = Column(String(50))  # thumbs_up, thumbs_down
    
    create_time = Column(String(255))  # ISO format string
    update_time = Column(String(255))  # ISO format string
    
    evaluation_name = Column(String(255))
    evaluation_treatment = Column(String(100))
    workspace_id = Column(String(255))
    
    # JSON fields
    content = Column(Text)  # JSON object
    raw_data = Column(Text)  # Complete feedback object as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatGPTModelComparison(Base):
    """Model comparison data (if exists)"""
    __tablename__ = "chatgpt_model_comparisons"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(255), ForeignKey('chatgpt_conversations.conversation_id'), index=True)
    comparison_data = Column(Text)  # JSON object
    raw_data = Column(Text)  # Complete comparison object as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatGPTTimeline(Base):
    """Denormalized timeline view for all events"""
    __tablename__ = "chatgpt_timeline"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Float, nullable=False, index=True)  # Unix timestamp for sorting
    event_type = Column(String(100), nullable=False, index=True)  # conversation_created, message_sent, feedback_given, etc.
    
    conversation_id = Column(String(255), ForeignKey('chatgpt_conversations.conversation_id'), index=True)
    message_id = Column(String(255), index=True)
    
    title_preview = Column(Text)
    content_preview = Column(Text)  # First 500 chars
    
    timeline_metadata = Column(Text)  # JSON object with all relevant metadata (renamed from 'metadata' - reserved in SQLAlchemy)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatGPTTTLAuth(Base):
    """TTL authentication data with geolocation/IP metadata"""
    __tablename__ = "chatgpt_ttl_auth"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), index=True)
    export_folder = Column(String(500), index=True)
    
    # User info
    email = Column(String(255))
    given_name = Column(String(255))
    family_name = Column(String(255))
    profile_image = Column(String(500))
    subscription_type = Column(String(100))
    
    # Sessions array stored as JSON
    sessions = Column(Text)  # JSON array with geolocation/IP/browser data
    api_keys = Column(Text)  # JSON array
    invitations = Column(Text)  # JSON array
    teams = Column(Text)  # JSON array
    team_roles = Column(Text)  # JSON object
    
    # Complete raw data
    raw_data = Column(Text)  # Complete auth.json as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatGPTTTLBilling(Base):
    """TTL billing data"""
    __tablename__ = "chatgpt_ttl_billing"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), index=True)
    export_folder = Column(String(500), index=True)
    billing_data = Column(Text)  # JSON object
    raw_data = Column(Text)  # Complete billing.json as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatGPTTTLSession(Base):
    """TTL session data with geolocation/IP extracted from auth sessions"""
    __tablename__ = "chatgpt_ttl_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), index=True)
    session_id = Column(String(255), unique=True, index=True)
    
    # Timestamps
    create_time = Column(String(255))  # ISO format
    expiration_time = Column(String(255))
    last_auth_time = Column(String(255))
    
    # Status
    status = Column(String(100))
    
    # Geolocation data
    ip_address = Column(String(100))
    city = Column(String(255))
    country = Column(String(100))
    region = Column(String(255))
    region_code = Column(String(50))
    postal_code = Column(String(50))
    latitude = Column(Float)
    longitude = Column(Float)
    timezone = Column(String(100))
    metro = Column(String(50))
    continent = Column(String(10))
    
    # Browser/Device
    user_agent = Column(Text)
    
    # Complete raw data
    raw_data = Column(Text)  # Complete session object as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatGPTImportLog(Base):
    """Track which folders have been imported"""
    __tablename__ = "chatgpt_import_log"
    
    id = Column(Integer, primary_key=True, index=True)
    export_folder = Column(String(500), unique=True, nullable=False, index=True)
    import_status = Column(String(50), default='pending')  # pending, in_progress, completed, error
    conversations_count = Column(Integer, default=0)
    messages_count = Column(Integer, default=0)
    feedback_count = Column(Integer, default=0)
    comparisons_count = Column(Integer, default=0)
    ttl_auth_count = Column(Integer, default=0)
    ttl_billing_count = Column(Integer, default=0)
    ttl_sessions_count = Column(Integer, default=0)
    import_started_at = Column(DateTime)
    import_completed_at = Column(DateTime)
    error_log = Column(Text)  # Error details if failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

