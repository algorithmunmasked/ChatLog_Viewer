# Changelog

All notable changes to the ChatLog Viewer project will be documented in this file.

## [Version 1.2] - 2025-11-23

### Added

#### Single File Import Feature
- **File picker import**: Added ability to import individual files via file picker
  - New "Import Single File" button in the main interface
  - Supports importing `.json` and `.html` files directly
  - Automatically detects file type (conversations.json, message_feedback.json, HTML exports, etc.)
  - Shows import progress and detailed results
  - Useful for importing missing items found in logs without running full folder import

- **API endpoint**: Added `POST /api/chatgpt-viewer/import/file` endpoint
  - Accepts file uploads via multipart/form-data
  - Auto-detects file type by filename and content structure
  - Supports conversations.json, message_feedback.json, model_comparisons.json, user.json, and HTML files
  - Returns detailed import statistics

#### HTML Message Cleanup
- **Cleanup HTML messages**: Added cleanup function to merge HTML and JSON messages intelligently
  - New "Cleanup HTML Messages" button in the main interface
  - Removes duplicate HTML messages that have JSON counterparts (same message_id)
  - Keeps unique HTML messages that don't have JSON versions
  - Ensures all message_ids are preserved with preference for complete JSON data
  - Message-level merge strategy: JSON preferred, HTML kept when unique

- **API endpoint**: Added `POST /api/chatgpt-viewer/cleanup/html-messages` endpoint
  - Identifies HTML export messages by `"source": "html_export"` in raw_data
  - Compares message_ids between HTML and JSON messages
  - Removes duplicates, keeps unique messages
  - Returns statistics on removed and kept messages

#### Delete Conversation Feature
- **Delete conversations**: Added ability to permanently delete conversations
  - "Delete Conversation" button in conversation detail modal
  - Deletes conversation and all related data:
    - All messages
    - All feedback records
    - All timeline entries
    - All model comparisons
  - Shows confirmation dialog with details of what will be deleted
  - Useful for cleaning up mixed/corrupted conversations before re-importing

- **API endpoint**: Added `DELETE /api/chatgpt-viewer/conversations/{conversation_id}` endpoint
  - Permanently deletes conversation and all related data
  - Returns summary of deleted items
  - Cannot be undone

### Changed

#### Improved Duplication Detection
- **Message-level duplicate checking**: Changed import logic to check for duplicates by `message_id` instead of skipping entire conversations
  - Previously: If a conversation existed, the entire import was skipped (including new messages)
  - Now: Checks each message individually by `message_id` before adding
  - Allows importing updated conversations with new messages from intermittent downloads
  - Conversation metadata (title, update_time) is updated if conversation already exists
  - Only new messages are added, preventing duplicates while capturing updates

- **HTML import improvements**: Updated HTML import to also check messages by `message_id`
  - HTML files can now be re-imported to add new messages
  - Existing messages are skipped, only new ones are added
  - HTML import now skips conversations that already have JSON messages (prevents mixed data)
  - Prevents HTML messages from being added when JSON version already exists

#### List View Date Display
- **Date range display**: Changed list view to show message date range instead of conversation created date
  - Removed "Created" column
  - "Date Range" column now shows first and last message dates in M/D/YYYY format (e.g., "3/1/2025 - 3/10/2025")
  - Makes it easier to find items in longer conversations that span multiple days
  - Added `formatDateOnly()` function for date-only formatting

#### UI Improvements
- **Word wrapping for titles**: Added word wrapping to conversation titles in list view
  - Long conversation titles now wrap instead of breaking table layout
  - Added `max-w-md` constraint and `break-words` class
  - Prevents table from becoming unreadable with very long titles

### Fixed

#### Timeline View Date Range Filtering
- **Fixed date range filter**: Resolved issue where date range filters in timeline view were not working
  - Date range inputs were not being read correctly from the UI
  - Now reads date values directly from input fields on each load
  - Properly converts datetime-local inputs to Unix timestamps
  - Date filtering now correctly filters timeline events by timestamp range

### Technical Details

#### Files Modified
- `app/api.py` - Added single file import endpoint, cleanup HTML messages endpoint, delete conversation endpoint, improved date filtering
- `app/import_service.py` - Changed duplicate detection to check by message_id instead of skipping entire conversations
- `app/html_import.py` - Updated to check messages by message_id, skip conversations that already have JSON messages
- `frontend/app.js` - Added file picker handler, cleanup handler, delete conversation handler, fixed date range reading, updated date display, added word wrapping for titles
- `frontend/index.html` - Added "Import Single File" and "Cleanup HTML Messages" buttons

## [Unreleased] - 2024-11-20

### Added

#### Hide Messages Feature
- **Message-level hiding**: Added ability to hide individual messages within conversations
  - Each message now has a "Hide" checkbox to mark messages as reviewed
  - Hidden messages are stored in the database (`is_hidden` column in `chatgpt_messages` table)
  - Hidden messages persist across browser sessions and days
  - Hidden messages are filtered from view by default

- **Show All Hidden toggle**: Added "Show All Hidden" checkbox at the top of each conversation's message list
  - Appears only when a conversation has hidden messages
  - Temporarily reveals all hidden messages for review
  - Allows users to see what they've hidden without permanently unhiding

- **Unhide All Messages button**: Added bulk unhide functionality
  - "Unhide All Messages" button appears when there are hidden messages
  - Allows quick recovery if messages were hidden by accident
  - Confirms action before unhiding all messages
  - Updates database and UI immediately

#### Hide Conversations Feature
- **Conversation-level hiding**: Added ability to hide entire conversations
  - Each conversation in the list has a "Hide" checkbox
  - Hidden conversations are stored in the database (`is_hidden` column in `chatgpt_conversations` table)
  - Hidden conversations persist across sessions
  - Hidden conversations are filtered from the list by default

- **Show Hidden Conversations toggle**: Added "Show Hidden" checkbox in the conversation list filter bar
  - Allows viewing hidden conversations when needed
  - Hidden conversations appear with reduced opacity (60%) for visual distinction

#### Enhanced Search Functionality
- **Comprehensive search**: Expanded search to include all relevant fields
  - **Conversation ID search**: Can now search by conversation ID (e.g., `abc-123-def`)
  - **Message ID search**: Can now search by message ID (e.g., `msg-456-ghi`)
  - **Title search**: Already supported, now part of comprehensive search
  - **Message content search**: Enabled by default for comprehensive results
  - Updated search placeholder to "Search conversations, IDs, messages..." to reflect new capabilities

#### UI Improvements
- **Clickable conversation titles**: Made conversation titles clickable instead of separate "View" button
  - Removed "Actions" column from conversation list
  - Conversation titles now function as the primary action to view details
  - Added hover underline effect for better UX

- **Date Range display**: Added date range column to conversation list
  - Shows earliest and latest message dates for each conversation
  - Helps users understand the time span of conversations at a glance
  - Displays as "earliest - latest" format

#### Database Enhancements
- **Database persistence for hide features**: 
  - Added `is_hidden` column to `chatgpt_messages` table
  - Added `is_hidden` column to `chatgpt_conversations` table
  - Automatic database migration on startup for existing databases
  - Indexed columns for better query performance

#### API Enhancements
- **New endpoints**:
  - `PUT /api/chatgpt-viewer/messages/{message_id}/hidden` - Update message hidden status
  - `PUT /api/chatgpt-viewer/conversations/{conversation_id}/hidden` - Update conversation hidden status
  - `GET /api/chatgpt-viewer/debug/database` - Debug endpoint for database diagnostics

- **Enhanced endpoints**:
  - `GET /api/chatgpt-viewer/conversations` - Added `show_hidden` parameter to include hidden conversations
  - `GET /api/chatgpt-viewer/conversations` - Enhanced search to include conversation IDs and message IDs
  - `GET /api/chatgpt-viewer/conversations/{conversation_id}` - Now includes `is_hidden` status for messages

#### Frontend Improvements
- **Cache-busting**: Added version parameter to JavaScript file loading
  - Prevents browser caching issues when code is updated
  - Uses file modification time as version identifier
  - Ensures users always get the latest JavaScript code

- **Default search behavior**: 
  - "Search in message content" checkbox now checked by default
  - Provides comprehensive search results out of the box

### Technical Details

#### Database Schema Changes
```sql
-- Added to chatgpt_messages table
ALTER TABLE chatgpt_messages ADD COLUMN is_hidden BOOLEAN DEFAULT 0;
CREATE INDEX idx_chatgpt_messages_is_hidden ON chatgpt_messages(is_hidden);

-- Added to chatgpt_conversations table
ALTER TABLE chatgpt_conversations ADD COLUMN is_hidden BOOLEAN DEFAULT 0;
CREATE INDEX idx_chatgpt_conversations_is_hidden ON chatgpt_conversations(is_hidden);
```

#### Files Modified
- `app/models.py` - Added `is_hidden` columns to models
- `app/database_service.py` - Added automatic migration for new columns
- `app/api.py` - Added hide endpoints and enhanced search
- `app/main.py` - Added cache-busting for static files
- `frontend/app.js` - Added hide functionality and UI updates
- `frontend/index.html` - Updated UI elements and search placeholder

### Bug Fixes
- Fixed JavaScript caching issues with cache-busting implementation
- Improved search to handle all ID types correctly
- **Fixed search functionality**: Resolved critical search bug where search results were not properly filtered
  - Search was showing all 181 pages regardless of search query
  - Made search case-insensitive using `func.lower()` for proper matching
  - Fixed empty result handling to correctly return 0 pages when no matches found
  - Added proper whitespace trimming for search terms
  - Applied fixes to both conversations and timeline search endpoints
  - Search now correctly filters results and displays accurate pagination

### Notes
- All hide features use database persistence, not localStorage
- Hidden status persists across browser sessions, devices (if using same database), and days
- Database migrations are automatic and safe for existing databases




