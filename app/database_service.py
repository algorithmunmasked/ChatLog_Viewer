"""
Database service for ChatGPT Viewer
Handles SQLite connection and table initialization
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional
from .models import Base

class ChatGPTDatabaseService:
    """Service for managing ChatGPT Viewer SQLite database"""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database connection
        
        Args:
            db_path: Path to SQLite database file. If None, uses chatgpt_viewer.db in project root
        """
        if db_path is None:
            # Get project root (parent of app directory)
            # __file__ is at: app/database_service.py
            # dirname once: app/
            # dirname twice: ChatLog_standalone/ (project root)
            project_root = os.path.dirname(os.path.dirname(__file__))
            db_path = os.path.join(project_root, 'chatlog_viewer.db')
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # Create SQLite engine
        # Use check_same_thread=False for SQLite to allow multiple threads
        self.database_url = f"sqlite:///{db_path}"
        self.engine = create_engine(
            self.database_url,
            connect_args={"check_same_thread": False},
            echo=False
        )
        
        # Create session factory
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Initialize tables
        self.init_db()
    
    def init_db(self):
        """Initialize database tables"""
        try:
            Base.metadata.create_all(bind=self.engine)
            
            # Add missing TTL columns to import_log table if they don't exist
            try:
                from sqlalchemy import inspect, text
                inspector = inspect(self.engine)
                columns = [col['name'] for col in inspector.get_columns('chatgpt_import_log')]
                
                with self.engine.connect() as conn:
                    if 'ttl_auth_count' not in columns:
                        conn.execute(text('ALTER TABLE chatgpt_import_log ADD COLUMN ttl_auth_count INTEGER DEFAULT 0'))
                    if 'ttl_billing_count' not in columns:
                        conn.execute(text('ALTER TABLE chatgpt_import_log ADD COLUMN ttl_billing_count INTEGER DEFAULT 0'))
                    if 'ttl_sessions_count' not in columns:
                        conn.execute(text('ALTER TABLE chatgpt_import_log ADD COLUMN ttl_sessions_count INTEGER DEFAULT 0'))
                    conn.commit()
            except Exception as e:
                # If table doesn't exist yet or columns already exist, that's fine
                pass
            
            # Add is_hidden column to chatgpt_messages table if it doesn't exist
            try:
                from sqlalchemy import inspect, text
                inspector = inspect(self.engine)
                if inspector.has_table('chatgpt_messages'):
                    columns = [col['name'] for col in inspector.get_columns('chatgpt_messages')]
                    
                    with self.engine.connect() as conn:
                        if 'is_hidden' not in columns:
                            conn.execute(text('ALTER TABLE chatgpt_messages ADD COLUMN is_hidden BOOLEAN DEFAULT 0'))
                            # Create index for better query performance
                            conn.execute(text('CREATE INDEX IF NOT EXISTS idx_chatgpt_messages_is_hidden ON chatgpt_messages(is_hidden)'))
                            conn.commit()
            except Exception as e:
                # If table doesn't exist yet or column already exists, that's fine
                pass
            
            # Add is_hidden column to chatgpt_conversations table if it doesn't exist
            try:
                from sqlalchemy import inspect, text
                inspector = inspect(self.engine)
                if inspector.has_table('chatgpt_conversations'):
                    columns = [col['name'] for col in inspector.get_columns('chatgpt_conversations')]
                    
                    with self.engine.connect() as conn:
                        if 'is_hidden' not in columns:
                            conn.execute(text('ALTER TABLE chatgpt_conversations ADD COLUMN is_hidden BOOLEAN DEFAULT 0'))
                            # Create index for better query performance
                            conn.execute(text('CREATE INDEX IF NOT EXISTS idx_chatgpt_conversations_is_hidden ON chatgpt_conversations(is_hidden)'))
                            conn.commit()
            except Exception as e:
                # If table doesn't exist yet or column already exists, that's fine
                pass
            
            print(f"Database initialized: {self.database_url}")
        except SQLAlchemyError as e:
            print(f"Error initializing database: {e}")
            raise
    
    def get_session(self):
        """Get a database session"""
        return self.SessionLocal()
    
    def close(self):
        """Close database connection"""
        self.engine.dispose()

