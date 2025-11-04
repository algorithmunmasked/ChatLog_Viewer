"""
TTL import functions - extracted to separate file to avoid conflicts
"""
import os
import json
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from .models import ChatGPTTTLAuth, ChatGPTTTLBilling, ChatGPTTTLSession


def import_ttl_folder(db: Session, folder_path: str, folder_name: str, related_export_folder: Optional[str] = None) -> Dict[str, Any]:
    """Import TTL folder with auth/billing/session data"""
    result = {
        'auth_count': 0,
        'billing_count': 0,
        'sessions_count': 0
    }
    
    # Look for export_data subdirectories
    export_data_base = os.path.join(folder_path, '30d', 'export_data')
    if not os.path.exists(export_data_base):
        return result
    
    # Find all UUID subdirectories
    for item in os.listdir(export_data_base):
        item_path = os.path.join(export_data_base, item)
        if os.path.isdir(item_path):
            # Import auth.json
            auth_path = os.path.join(item_path, 'prod-mc-auth.json')
            if os.path.exists(auth_path):
                auth_result = import_ttl_auth(db, auth_path, folder_name, related_export_folder)
                result['auth_count'] += auth_result.get('count', 0)
                result['sessions_count'] += auth_result.get('sessions_count', 0)
            
            # Import billing.json
            billing_path = os.path.join(item_path, 'prod-mc-billing.json')
            if os.path.exists(billing_path):
                billing_result = import_ttl_billing(db, billing_path, folder_name, related_export_folder)
                result['billing_count'] += billing_result.get('count', 0)
    
    return result


def import_ttl_auth(db: Session, auth_path: str, folder_name: str, related_export_folder: Optional[str] = None) -> Dict[str, Any]:
    """Import TTL auth.json with all metadata"""
    with open(auth_path, 'r', encoding='utf-8') as f:
        auth_data = json.load(f)
    
    user = auth_data.get('user', {})
    user_id = user.get('userId')
    
    if not user_id:
        return {'count': 0, 'sessions_count': 0}
    
    # Create a unique identifier: combine folder_name with related_export_folder if provided
    # This prevents overwriting when multiple TTL folders have the same name
    unique_folder_id = f"{folder_name}"
    if related_export_folder:
        unique_folder_id = f"{related_export_folder}|{folder_name}"
    
    # Check if already exists - match on user_id and the unique folder identifier
    existing = db.query(ChatGPTTTLAuth).filter(
        ChatGPTTTLAuth.user_id == user_id,
        ChatGPTTTLAuth.export_folder == unique_folder_id
    ).first()
    
    if existing:
        return {'count': 0, 'sessions_count': 0}
    
    # Create auth record
    auth = ChatGPTTTLAuth(
        user_id=user_id,
        export_folder=unique_folder_id,
        email=user.get('email'),
        given_name=user.get('givenName'),
        family_name=user.get('familyName'),
        profile_image=user.get('profileImage'),
        subscription_type=user.get('xSubscriptionType'),
        api_keys=json.dumps(auth_data.get('api_keys', [])),
        invitations=json.dumps(auth_data.get('invitations', [])),
        sessions=json.dumps(auth_data.get('sessions', [])),
        teams=json.dumps(auth_data.get('teams', [])),
        team_roles=json.dumps(auth_data.get('team_roles', {})),
        raw_data=json.dumps(auth_data)
    )
    
    db.add(auth)
    db.flush()
    
    # Extract and import individual sessions with geolocation
    sessions_count = 0
    for session_data in auth_data.get('sessions', []):
        session_id = session_data.get('sessionId')
        if not session_id:
            continue
        
        # Check if session already exists
        existing_session = db.query(ChatGPTTTLSession).filter(
            ChatGPTTTLSession.session_id == session_id
        ).first()
        
        if existing_session:
            continue
        
        # Extract cfMetadata (Cloudflare metadata with geo/IP)
        cf_meta = session_data.get('cfMetadata', {})
        
        session = ChatGPTTTLSession(
            user_id=user_id,
            session_id=session_id,
            create_time=session_data.get('createTime'),
            expiration_time=session_data.get('expirationTime'),
            last_auth_time=session_data.get('lastAuthTime'),
            status=session_data.get('status'),
            ip_address=cf_meta.get('ipAddress'),
            city=cf_meta.get('city'),
            country=cf_meta.get('country'),
            region=cf_meta.get('region'),
            region_code=cf_meta.get('regionCode'),
            postal_code=cf_meta.get('postalCode'),
            latitude=cf_meta.get('latitude'),
            longitude=cf_meta.get('longitude'),
            timezone=cf_meta.get('timezone'),
            metro=cf_meta.get('metro'),
            continent=cf_meta.get('continent'),
            user_agent=session_data.get('userAgent'),
            raw_data=json.dumps(session_data)
        )
        
        db.add(session)
        sessions_count += 1
    
    db.commit()
    return {'count': 1, 'sessions_count': sessions_count}


def import_ttl_billing(db: Session, billing_path: str, folder_name: str, related_export_folder: Optional[str] = None) -> Dict[str, Any]:
    """Import TTL billing.json"""
    with open(billing_path, 'r', encoding='utf-8') as f:
        billing_data = json.load(f)
    
    # Extract user_id if present
    user_id = billing_data.get('userId') or billing_data.get('user_id')
    
    if not user_id:
        # Try to infer from folder structure or skip
        return {'count': 0}
    
    # Create a unique identifier: combine folder_name with related_export_folder if provided
    unique_folder_id = f"{folder_name}"
    if related_export_folder:
        unique_folder_id = f"{related_export_folder}|{folder_name}"
    
    # Check if already exists
    existing = db.query(ChatGPTTTLBilling).filter(
        ChatGPTTTLBilling.user_id == user_id,
        ChatGPTTTLBilling.export_folder == unique_folder_id
    ).first()
    
    if existing:
        return {'count': 0}
    
    billing = ChatGPTTTLBilling(
        user_id=user_id,
        export_folder=unique_folder_id,
        billing_data=json.dumps(billing_data),
        raw_data=json.dumps(billing_data)
    )
    
    db.add(billing)
    db.commit()
    return {'count': 1}

