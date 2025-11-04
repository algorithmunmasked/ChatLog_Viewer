// ChatGPT Viewer Frontend JavaScript

let currentPage = 1;
let currentTimelinePage = 1;
let pageSize = 20;
let timelinePageSize = 50;
let currentView = 'list';
let timelineEventType = '';
let timelineStartDate = null;
let timelineEndDate = null;
let timelineSortOrder = 'newest';
let conversationsSortOrder = 'newest';
let searchInMessages = false;
let timelineSearch = '';

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    loadStats();
    loadConversations();
    
    // Initialize export button state
    const exportBtn = document.getElementById('export-selected');
    if (exportBtn) {
        exportBtn.disabled = true;
        exportBtn.textContent = 'Export Selected (0)';
    }
    setupEventListeners();
});

function setupEventListeners() {
    // Tab switching
    document.getElementById('tab-list').addEventListener('click', () => switchView('list'));
    document.getElementById('tab-timeline').addEventListener('click', () => switchView('timeline'));
    document.getElementById('tab-ttl').addEventListener('click', () => switchView('ttl'));
    document.getElementById('tab-filtered').addEventListener('click', () => switchView('filtered'));
    
    // Search
    const searchInput = document.getElementById('search-input');
    const searchInMessagesCheckbox = document.getElementById('search-in-messages');
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentPage = 1;
            loadConversations();
        }, 500);
    });
    
    searchInMessagesCheckbox.addEventListener('change', (e) => {
        searchInMessages = e.target.checked;
        currentPage = 1;
        loadConversations();
    });
    
    // Conversations sort order
    document.getElementById('conversations-sort-order').addEventListener('change', (e) => {
        conversationsSortOrder = e.target.value;
        currentPage = 1;
        loadConversations();
    });
    
    // Page size
    document.getElementById('page-size').addEventListener('change', (e) => {
        pageSize = parseInt(e.target.value);
        currentPage = 1;
        loadConversations();
    });
    
    document.getElementById('ttl-page-size').addEventListener('change', (e) => {
        ttlPageSize = parseInt(e.target.value);
        currentTTLPage = 1;
        loadTTLSessions();
    });
    
    // Timeline filters
    document.getElementById('timeline-event-type').addEventListener('change', (e) => {
        timelineEventType = e.target.value;
        currentTimelinePage = 1;
        loadTimeline();
    });
    
    document.getElementById('timeline-sort-order').addEventListener('change', (e) => {
        timelineSortOrder = e.target.value;
        currentTimelinePage = 1;
        loadTimeline();
    });
    
    document.getElementById('timeline-start-date').addEventListener('change', (e) => {
        timelineStartDate = e.target.value;
        currentTimelinePage = 1;
        loadTimeline();
    });
    
    document.getElementById('timeline-end-date').addEventListener('change', (e) => {
        timelineEndDate = e.target.value;
        currentTimelinePage = 1;
        loadTimeline();
    });
    
    document.getElementById('timeline-clear-dates').addEventListener('click', () => {
        document.getElementById('timeline-start-date').value = '';
        document.getElementById('timeline-end-date').value = '';
        timelineStartDate = null;
        timelineEndDate = null;
        currentTimelinePage = 1;
        loadTimeline();
    });
    
    // Timeline search button
    document.getElementById('timeline-search-btn').addEventListener('click', () => {
        const searchInput = document.getElementById('timeline-search-input');
        timelineSearch = searchInput.value.trim();
        currentTimelinePage = 1;
        loadTimeline();
    });
    
    // Timeline search input - Enter key
    document.getElementById('timeline-search-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const searchInput = document.getElementById('timeline-search-input');
            timelineSearch = searchInput.value.trim();
            currentTimelinePage = 1;
            loadTimeline();
        }
    });
    
    document.getElementById('timeline-page-size').addEventListener('change', (e) => {
        timelinePageSize = parseInt(e.target.value);
        currentTimelinePage = 1;
        loadTimeline();
    });
    
    // Buttons
    document.getElementById('importBtn').addEventListener('click', startImport);
    
    // Export Selected button
    document.getElementById('export-selected').addEventListener('click', async () => {
        if (selectedConversations.size === 0) {
            alert('Please select at least one conversation to export');
            return;
        }
        
        const button = document.getElementById('export-selected');
        button.disabled = true;
        button.textContent = 'Exporting...';
        
        try {
            const response = await fetch('/api/chatgpt-viewer/export', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    conversation_ids: Array.from(selectedConversations)
                })
            });
            
            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `chatgpt_export_${new Date().toISOString().split('T')[0]}.json`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                alert(`Exported ${selectedConversations.size} conversation(s)`);
            } else {
                const data = await response.json();
                alert('Error exporting: ' + (data.detail || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error exporting:', error);
            alert('Error exporting conversations: ' + error.message);
        } finally {
            button.disabled = false;
            button.textContent = `Export Selected (${selectedConversations.size})`;
        }
    });
    
    // HTML Import button
    document.getElementById('import-html').addEventListener('click', async () => {
        const button = document.getElementById('import-html');
        button.disabled = true;
        button.textContent = 'Importing HTML...';
        
        try {
            const response = await fetch('/api/chatgpt-viewer/import/html', {
                method: 'POST'
            });
            const data = await response.json();
            
            if (data.success) {
                let message = `HTML Import Complete!\n\nFiles found: ${data.results.html_files_found}\nConversations imported: ${data.results.conversations_imported}\nMessages imported: ${data.results.messages_imported}\nErrors: ${data.results.errors.length}`;
                
                if (data.results.skipped && data.results.skipped.length > 0) {
                    message += `\nSkipped: ${data.results.skipped.length}`;
                    const alreadyExists = data.results.skipped.filter(s => s.reason === 'already_exists').length;
                    const notChatGPT = data.results.skipped.filter(s => s.reason === 'not_chatgpt').length;
                    if (alreadyExists > 0) {
                        message += ` (${alreadyExists} already imported)`;
                    }
                    if (notChatGPT > 0) {
                        message += ` (${notChatGPT} not ChatGPT files)`;
                    }
                }
                
                if (data.results.errors.length > 0) {
                    message += '\n\nErrors:\n';
                    data.results.errors.forEach((err, idx) => {
                        message += `\n${idx + 1}. ${err.file}: ${err.error}`;
                    });
                }
                
                if (data.error_details && data.error_details.length > 0) {
                    message += '\n\nDetailed Errors:\n';
                    data.error_details.forEach((err, idx) => {
                        message += `\n${idx + 1}. ${err.file}: ${err.error}`;
                    });
                }
                
                alert(message);
                loadStats();
                if (currentView === 'list') {
                    loadConversations();
                }
            } else {
                let errorMsg = `Error importing HTML files: ${data.error || 'Unknown error'}`;
                if (data.traceback) {
                    errorMsg += `\n\nDetails:\n${data.traceback}`;
                }
                alert(errorMsg);
            }
        } catch (error) {
            console.error('Error importing HTML:', error);
            alert('Error importing HTML files: ' + error.message);
        } finally {
            button.disabled = false;
            button.textContent = 'Import HTML Files';
        }
    });
    document.getElementById('refreshBtn').addEventListener('click', () => {
        loadStats();
        if (currentView === 'list') {
            loadConversations();
        } else if (currentView === 'timeline') {
            loadTimeline();
        } else if (currentView === 'ttl') {
            loadTTLSessions();
        } else if (currentView === 'filtered') {
            loadFilteredMessages();
        }
    });
    
    // Modal close
    document.getElementById('close-detail').addEventListener('click', () => {
        document.getElementById('detail-modal').classList.add('hidden');
    });
    
    document.getElementById('close-import').addEventListener('click', () => {
        document.getElementById('import-modal').classList.add('hidden');
    });
    
    // Close modal on outside click
    document.getElementById('detail-modal').addEventListener('click', (e) => {
        if (e.target.id === 'detail-modal') {
            document.getElementById('detail-modal').classList.add('hidden');
        }
    });
}

function switchView(view) {
    currentView = view;
    
    // Update tabs - reset all
    ['tab-list', 'tab-timeline', 'tab-ttl', 'tab-filtered'].forEach(tabId => {
        const tab = document.getElementById(tabId);
        tab.classList.remove('active', 'text-blue-600', 'border-blue-600');
        tab.classList.add('text-gray-500');
    });
    
    // Hide all views
    ['view-list', 'view-timeline', 'view-ttl', 'view-filtered'].forEach(viewId => {
        document.getElementById(viewId).classList.add('hidden');
    });
    
    // Show selected view and activate tab
    if (view === 'list') {
        document.getElementById('view-list').classList.remove('hidden');
        document.getElementById('tab-list').classList.add('active', 'text-blue-600', 'border-blue-600');
        document.getElementById('tab-list').classList.remove('text-gray-500');
        loadConversations();
    } else if (view === 'timeline') {
        document.getElementById('view-timeline').classList.remove('hidden');
        document.getElementById('tab-timeline').classList.add('active', 'text-blue-600', 'border-blue-600');
        document.getElementById('tab-timeline').classList.remove('text-gray-500');
        loadTimeline();
        } else if (view === 'ttl') {
        document.getElementById('view-ttl').classList.remove('hidden');
        document.getElementById('tab-ttl').classList.add('active', 'text-blue-600', 'border-blue-600');
        document.getElementById('tab-ttl').classList.remove('text-gray-500');
        loadTTLSessions();
    } else if (view === 'filtered') {
        document.getElementById('view-filtered').classList.remove('hidden');
        document.getElementById('tab-filtered').classList.add('active', 'text-blue-600', 'border-blue-600');
        document.getElementById('tab-filtered').classList.remove('text-gray-500');
        loadFilteredMessages();
    }
}

async function loadStats() {
    try {
        const response = await fetch('/api/chatgpt-viewer/stats');
        const data = await response.json();
        
        if (data.success) {
            document.getElementById('stats-conversations').textContent = data.stats.total_conversations;
            document.getElementById('stats-messages').textContent = data.stats.total_messages;
            document.getElementById('stats-feedback').textContent = data.stats.total_feedback;
            document.getElementById('stats-timeline').textContent = data.stats.total_timeline_events;
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

async function loadConversations() {
    try {
        const search = document.getElementById('search-input').value;
        const params = new URLSearchParams({
            page: currentPage,
            per_page: pageSize,
            sort_order: conversationsSortOrder
        });
        if (search) {
            params.append('search', search);
            if (searchInMessages) {
                params.append('search_in_messages', 'true');
            }
        }
        
        const response = await fetch(`/api/chatgpt-viewer/conversations?${params}`);
        const data = await response.json();
        
        if (data.success) {
            displayConversations(data.conversations);
            displayPagination(data.pagination, 'conversations');
        }
    } catch (error) {
        console.error('Error loading conversations:', error);
        document.getElementById('conversations-list').innerHTML = 
            '<div class="text-center py-8 text-red-600">Error loading conversations</div>';
    }
}

let selectedConversations = new Set();
let selectedMessages = new Set();

function displayConversations(conversations) {
    const container = document.getElementById('conversations-list');
    
    if (conversations.length === 0) {
        container.innerHTML = '<div class="text-center py-8 text-gray-600">No conversations found</div>';
        return;
    }
    
    const html = `
        <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
                <tr>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        <input type="checkbox" id="select-all" class="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer" 
                               onchange="window.toggleSelectAll(this.checked)">
                    </th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Title</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Messages</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Model</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                </tr>
            </thead>
            <tbody class="bg-white divide-y divide-gray-200">
                ${conversations.map(conv => {
                    const isSelected = selectedConversations.has(conv.conversation_id);
                    return `
                    <tr class="hover:bg-gray-50">
                        <td class="px-6 py-4 whitespace-nowrap">
                            <input type="checkbox" class="conversation-checkbox w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer" 
                                   value="${conv.conversation_id}" 
                                   ${isSelected ? 'checked' : ''}
                                   onchange="window.toggleConversationSelection('${conv.conversation_id}', this.checked)">
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap">
                            <div class="text-sm font-medium text-gray-900">${escapeHtml(conv.title || 'Untitled')}</div>
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            ${formatTimestamp(conv.create_time)}
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            ${conv.message_count}
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            ${escapeHtml(conv.model || 'N/A')}
                        </td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                            <button onclick="viewConversation('${conv.conversation_id}')" 
                                    class="text-blue-600 hover:text-blue-900">View</button>
                        </td>
                    </tr>
                `}).join('')}
            </tbody>
        </table>
    `;
    
    container.innerHTML = html;
}

function toggleSelectAll(checked) {
    const checkboxes = document.querySelectorAll('.conversation-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = checked;
        toggleConversationSelection(cb.value, checked);
    });
}

function toggleConversationSelection(conversationId, checked) {
    if (checked) {
        selectedConversations.add(conversationId);
    } else {
        selectedConversations.delete(conversationId);
    }
    
    // Update export button state
    const exportBtn = document.getElementById('export-selected');
    if (exportBtn) {
        exportBtn.disabled = selectedConversations.size === 0;
        exportBtn.textContent = `Export Selected (${selectedConversations.size})`;
    }
}

window.toggleSelectAll = toggleSelectAll;
window.toggleConversationSelection = toggleConversationSelection;

async function loadTimeline() {
    try {
        const params = new URLSearchParams({
            page: currentTimelinePage,
            per_page: timelinePageSize,
            sort_order: timelineSortOrder
        });
        if (timelineEventType) {
            params.append('event_type', timelineEventType);
        }
        if (timelineStartDate) {
            // Convert datetime-local to Unix timestamp
            // datetime-local gives us a string like "2025-05-05T22:00" in LOCAL time
            // JavaScript Date interprets this as local time, and getTime() returns UTC milliseconds
            // So we need to account for timezone offset
            const startDate = new Date(timelineStartDate);
            // getTime() already gives UTC milliseconds, divide by 1000 for seconds
            const startTimestamp = startDate.getTime() / 1000;
            params.append('start_time', startTimestamp);
            console.log('Timeline search - Start date:', timelineStartDate);
            console.log('  Local Date object:', startDate.toString());
            console.log('  UTC Timestamp:', startTimestamp);
            console.log('  UTC Date:', new Date(startTimestamp * 1000).toUTCString());
        }
        if (timelineEndDate) {
            // Convert datetime-local to Unix timestamp
            // Use the exact time selected, not end of day
            const endDate = new Date(timelineEndDate);
            const endTimestamp = endDate.getTime() / 1000;
            params.append('end_time', endTimestamp);
            console.log('Timeline search - End date:', timelineEndDate);
            console.log('  Local Date object:', endDate.toString());
            console.log('  UTC Timestamp:', endTimestamp);
            console.log('  UTC Date:', new Date(endTimestamp * 1000).toUTCString());
        }
        if (timelineSearch) {
            params.append('search', timelineSearch);
        }
        
        const response = await fetch(`/api/chatgpt-viewer/timeline?${params}`);
        const data = await response.json();
        
        if (data.success) {
            displayTimeline(data.timeline);
            displayPagination(data.pagination, 'timeline');
        }
    } catch (error) {
        console.error('Error loading timeline:', error);
        document.getElementById('timeline-list').innerHTML = 
            '<div class="text-center py-8 text-red-600">Error loading timeline</div>';
    }
}

function displayTimeline(timeline) {
    const container = document.getElementById('timeline-list');
    
    if (timeline.length === 0) {
        container.innerHTML = '<div class="text-center py-8 text-gray-600">No timeline events found</div>';
        return;
    }
    
    const html = timeline.map(item => {
        const date = new Date(item.timestamp * 1000);
        const eventTypeLabel = {
            'conversation_created': 'Conversation Created',
            'message_sent': 'Message Sent',
            'feedback_given': 'Feedback Given'
        }[item.event_type] || item.event_type;
        
        // Color code by role if it's a message
        let borderColor = 'border-blue-500';
        let roleLabel = '';
        if (item.event_type === 'message_sent' && item.metadata && item.metadata.role) {
            const role = item.metadata.role;
            if (role === 'user') {
                borderColor = 'border-blue-500';
                roleLabel = '👤 User';
            } else if (role === 'assistant') {
                borderColor = 'border-green-500';
                roleLabel = '🤖 Assistant';
            } else if (role === 'system') {
                borderColor = 'border-purple-500';
                roleLabel = '⚙️ System';
            }
        }
        
        const typeColor = {
            'conversation_created': 'bg-blue-100 text-blue-800',
            'message_sent': 'bg-green-100 text-green-800',
            'feedback_given': 'bg-purple-100 text-purple-800'
        }[item.event_type] || 'bg-gray-100 text-gray-800';
        
        return `
            <div class="border-l-4 ${borderColor} pl-4 py-3 hover:bg-gray-50 cursor-pointer rounded-r" 
                 onclick="viewTimelineItem('${item.conversation_id}', '${item.message_id || ''}')">
                <div class="flex items-start justify-between">
                    <div class="flex-1">
                        <div class="flex items-center space-x-2 mb-1">
                            <span class="px-2 py-1 text-xs font-semibold rounded ${typeColor}">
                                ${eventTypeLabel}
                            </span>
                            ${roleLabel ? `<span class="px-2 py-1 text-xs font-medium rounded bg-gray-200 text-gray-700">${roleLabel}</span>` : ''}
                            <span class="text-xs text-gray-500">${date.toLocaleString()}</span>
                        </div>
                        <div class="text-sm font-semibold text-gray-900 mb-1">
                            ${escapeHtml(item.conversation_title || 'Untitled Conversation')}
                        </div>
                        ${item.content_preview ? `<div class="text-sm text-gray-700 mt-1 pl-2 border-l-2 border-gray-200 break-words whitespace-pre-wrap max-w-full overflow-wrap-anywhere">${escapeHtml(item.content_preview.substring(0, 300))}${item.content_preview.length > 300 ? '...' : ''}</div>` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = html;
}

function displayPagination(pagination, type) {
    const containerId = type === 'timeline' ? 'timeline-pagination' : 'pagination';
    const container = document.getElementById(containerId);
    
    if (pagination.pages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    const html = `
        <div class="flex items-center space-x-2">
            <button onclick="changePage(${pagination.page - 1}, '${type}')" 
                    ${pagination.page <= 1 ? 'disabled' : ''}
                    class="px-4 py-2 border rounded-lg ${pagination.page <= 1 ? 'opacity-50 cursor-not-allowed' : 'hover:bg-gray-50'}">
                Previous
            </button>
            <span class="px-4 py-2 text-sm text-gray-600">
                Page ${pagination.page} of ${pagination.pages}
            </span>
            <button onclick="changePage(${pagination.page + 1}, '${type}')" 
                    ${pagination.page >= pagination.pages ? 'disabled' : ''}
                    class="px-4 py-2 border rounded-lg ${pagination.page >= pagination.pages ? 'opacity-50 cursor-not-allowed' : 'hover:bg-gray-50'}">
                Next
            </button>
        </div>
    `;
    
    container.innerHTML = html;
}

async function loadFilteredMessages() {
    try {
        const params = new URLSearchParams({
            page: currentFilteredPage,
            per_page: filteredPageSize
        });
        
        const response = await fetch(`/api/chatgpt-viewer/messages/filtered?${params}`);
        const data = await response.json();
        
        if (data.success) {
            displayFilteredMessages(data.messages);
            displayPagination(data.pagination, 'filtered');
        }
    } catch (error) {
        console.error('Error loading filtered messages:', error);
        document.getElementById('filtered-messages-list').innerHTML = 
            '<div class="text-center py-8 text-red-600">Error loading filtered messages</div>';
    }
}

function displayFilteredMessages(messages) {
    const container = document.getElementById('filtered-messages-list');
    
    if (messages.length === 0) {
        container.innerHTML = '<div class="text-center py-8 text-gray-600">No filtered messages found</div>';
        return;
    }
    
    const html = messages.map((msg, idx) => {
        const date = msg.create_time ? new Date(msg.create_time * 1000).toLocaleString() : 'N/A';
        const roleColor = msg.role === 'assistant' ? 'bg-green-100 text-green-800' : msg.role === 'user' ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800';
        const rawDataId = `raw-data-${idx}`;
        const filterInfoId = `filter-info-${idx}`;
        const metadataInfoId = `metadata-filter-${idx}`;
        
        return `
            <div class="border-l-4 border-red-500 rounded-lg p-4 hover:bg-gray-50 mb-4">
                <div class="flex justify-between items-start mb-2">
                    <div class="flex-1">
                        <div class="flex items-center space-x-2 mb-2">
                            <span class="px-2 py-1 text-xs font-semibold rounded ${roleColor}">
                                ${escapeHtml(msg.role || 'Unknown')}
                            </span>
                            ${msg.finish_reason ? `<span class="px-2 py-1 text-xs rounded bg-yellow-100 text-yellow-800">Finish: ${escapeHtml(msg.finish_reason)}</span>` : ''}
                            <span class="text-xs text-gray-500">${date}</span>
                        </div>
                        <div class="text-sm text-gray-700 mb-2">
                            <strong>Conversation:</strong> 
                            <a href="#" onclick="viewConversation('${msg.conversation_id}'); return false;" class="text-blue-600 hover:underline">
                                ${escapeHtml(msg.conversation_id.substring(0, 30))}...
                            </a>
                        </div>
                        ${msg.model ? `<div class="text-xs text-gray-500 mb-2">Model: ${escapeHtml(msg.model)}</div>` : ''}
                        
                        ${msg._filter_trigger ? `
                        <div class="bg-yellow-50 border border-yellow-300 rounded p-2 mb-2">
                            <div class="text-xs font-semibold text-yellow-900">🔍 Detection Reason: ${escapeHtml(msg._filter_trigger)}</div>
                        </div>
                        ` : ''}
                        
                        <!-- Filter Information - Show prominently -->
                        ${msg.filter_info || msg.metadata_filter_info ? `
                        <div class="bg-red-50 border-2 border-red-300 rounded p-4 mb-3">
                            <div class="flex items-center justify-between mb-2">
                                <div class="text-base font-bold text-red-900">🔒 Content Filter Flags Detected</div>
                                <button onclick="toggleRawData('${filterInfoId}', event)" class="text-xs text-red-700 hover:text-red-900">
                                    ${(msg.filter_info && Object.keys(msg.filter_info).length > 0) || (msg.metadata_filter_info && Object.keys(msg.metadata_filter_info).length > 0) ? 'Show Details ▼' : ''}
                                </button>
                            </div>
                            <div id="${filterInfoId}" class="${(msg.filter_info && Object.keys(msg.filter_info).length > 0) || (msg.metadata_filter_info && Object.keys(msg.metadata_filter_info).length > 0) ? '' : 'hidden'}">
                                ${msg.filter_info && Object.keys(msg.filter_info).length > 0 ? `
                                <div class="mb-2">
                                    <div class="text-sm font-semibold text-red-800 mb-1">Main Message Filter Fields:</div>
                                    <pre class="text-xs text-red-900 bg-white border border-red-200 rounded p-2 overflow-auto max-h-96">${escapeHtml(JSON.stringify(msg.filter_info, null, 2))}</pre>
                                </div>
                                ` : ''}
                                ${msg.metadata_filter_info && Object.keys(msg.metadata_filter_info).length > 0 ? `
                                <div class="mb-2">
                                    <div class="text-sm font-semibold text-red-800 mb-1">Metadata Filter Fields:</div>
                                    <pre class="text-xs text-red-900 bg-white border border-red-200 rounded p-2 overflow-auto max-h-96">${escapeHtml(JSON.stringify(msg.metadata_filter_info, null, 2))}</pre>
                                </div>
                                ` : ''}
                            </div>
                        </div>
                        ` : ''}
                        
                        <!-- Full Message Content -->
                        ${msg.content ? `
                        <div class="bg-gray-50 border border-gray-200 rounded p-3 mb-2">
                            <div class="flex items-center justify-between mb-1">
                                <div class="text-sm font-semibold text-gray-900">Full Message Content</div>
                                ${msg.content.length > 500 ? `<button onclick="toggleRawData('msg-content-${idx}', event)" class="text-xs text-gray-600 hover:text-gray-900">Show Full ▼</button>` : ''}
                            </div>
                            <div id="msg-content-${idx}" class="${msg.content.length > 500 ? 'hidden' : ''}">
                                <div class="text-sm text-gray-700 whitespace-pre-wrap">${escapeHtml(msg.content.substring(0, 500))}${msg.content.length > 500 ? '...' : ''}</div>
                            </div>
                            ${msg.content.length > 500 ? `
                            <div id="msg-content-full-${idx}" class="hidden">
                                <div class="text-sm text-gray-700 whitespace-pre-wrap">${escapeHtml(msg.content)}</div>
                            </div>
                            ` : ''}
                        </div>
                        ` : ''}
                        
                        <!-- Raw Data (for inspection) -->
                        ${msg.raw_data ? `
                        <div class="bg-blue-50 border border-blue-200 rounded p-3 mb-2">
                            <div class="flex items-center justify-between">
                                <div class="text-sm font-semibold text-blue-900">Raw Message Data (Complete)</div>
                                <button onclick="toggleRawData('${rawDataId}', event)" class="text-xs text-blue-700 hover:text-blue-900">Show ▼</button>
                            </div>
                            <div id="${rawDataId}" class="hidden">
                                <pre class="text-xs text-blue-900 bg-white border border-blue-200 rounded p-2 overflow-auto max-h-96 mt-2">${escapeHtml(JSON.stringify(msg.raw_data, null, 2))}</pre>
                            </div>
                        </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = html;
}

function changePage(page, type) {
    if (type === 'timeline') {
        currentTimelinePage = page;
        loadTimeline();
    } else if (type === 'ttl') {
        currentTTLPage = page;
        loadTTLSessions();
    } else if (type === 'filtered') {
        currentFilteredPage = page;
        loadFilteredMessages();
    } else {
        currentPage = page;
        loadConversations();
    }
}

async function viewConversation(conversationId) {
    try {
        const response = await fetch(`/api/chatgpt-viewer/conversations/${conversationId}`);
        const data = await response.json();
        
        if (data.success) {
            displayConversationDetail(data.conversation);
        }
    } catch (error) {
        console.error('Error loading conversation:', error);
        alert('Error loading conversation details');
    }
}

function viewTimelineItem(conversationId, messageId) {
    viewConversation(conversationId);
    // Scroll to message if messageId is provided
    setTimeout(() => {
        if (messageId) {
            const messageElement = document.getElementById(`message-${messageId}`);
            if (messageElement) {
                messageElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                messageElement.classList.add('ring-2', 'ring-blue-500');
                setTimeout(() => {
                    messageElement.classList.remove('ring-2', 'ring-blue-500');
                }, 2000);
            }
        }
    }, 500);
}

function displayConversationDetail(conversation) {
    const modal = document.getElementById('detail-modal');
    const title = document.getElementById('detail-title');
    const content = document.getElementById('detail-content');
    
    title.textContent = conversation.title || 'Untitled Conversation';
    
    // Create a map of feedback by message_id for quick lookup
    const feedbackByMessageId = {};
    if (conversation.feedback && conversation.feedback.length > 0) {
        conversation.feedback.forEach(fb => {
            if (fb.message_id) {
                if (!feedbackByMessageId[fb.message_id]) {
                    feedbackByMessageId[fb.message_id] = [];
                }
                feedbackByMessageId[fb.message_id].push(fb);
            }
        });
    }
    
    // Build HTML
    let html = `
        <div class="space-y-6">
            <!-- Conversation Metadata -->
            <div class="border-b border-gray-200 pb-4">
                <h3 class="text-lg font-semibold text-gray-800 mb-3">Conversation Metadata</h3>
                <div class="grid grid-cols-2 gap-4 text-sm">
                    <div><span class="font-medium">Created:</span> ${formatTimestamp(conversation.create_time)}</div>
                    <div><span class="font-medium">Updated:</span> ${formatTimestamp(conversation.update_time)}</div>
                    <div><span class="font-medium">Model:</span> ${escapeHtml(conversation.default_model_slug || 'N/A')}</div>
                    <div><span class="font-medium">Gizmo ID:</span> ${escapeHtml(conversation.gizmo_id || 'N/A')}</div>
                    <div><span class="font-medium">Export Folder:</span> ${escapeHtml(conversation.export_folder || 'N/A')}</div>
                    <div><span class="font-medium">Archived:</span> ${conversation.is_archived ? 'Yes' : 'No'}</div>
                </div>
                
                <!-- Expandable Raw Data -->
                <div class="mt-4">
                    <button onclick="window.toggleRawData('conv-raw', event)" class="text-blue-600 hover:text-blue-800 text-sm font-medium">
                        View Raw JSON Data ▼
                    </button>
                    <pre id="conv-raw" class="hidden mt-2 p-4 bg-gray-100 rounded-lg overflow-x-auto text-xs" style="max-height: 400px; overflow-y: auto;"></pre>
                </div>
            </div>
            
            <!-- Messages -->
            <div>
                <div class="flex justify-between items-center mb-3">
                    <h3 class="text-lg font-semibold text-gray-800">Messages (${conversation.messages.length})</h3>
                    <div class="flex items-center space-x-2">
                        <input type="checkbox" id="select-all-messages" class="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer" 
                               onchange="window.toggleSelectAllMessages(this.checked)">
                        <label for="select-all-messages" class="text-sm text-gray-700 cursor-pointer">Select All</label>
                        <button id="export-selected-messages" onclick="window.exportSelectedMessages()" 
                                class="px-4 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
                                disabled>
                            Export Selected Messages (0)
                        </button>
                    </div>
                </div>
                <div class="space-y-4">
    `;
    
    conversation.messages.forEach((msg, index) => {
        // Get feedback for this message
        const messageFeedback = feedbackByMessageId[msg.message_id] || [];
        const roleColor = {
            'user': 'bg-blue-100 border-blue-300',
            'assistant': 'bg-green-100 border-green-300',
            'system': 'bg-purple-100 border-purple-300'
        }[msg.role] || 'bg-gray-100 border-gray-300';
        
        const isSelected = selectedMessages.has(msg.message_id);
        
        html += `
            <div id="message-${msg.message_id}" class="border-l-4 ${roleColor} p-4 rounded">
                <div class="flex justify-between items-start mb-2">
                    <div class="flex items-center space-x-2 flex-1">
                        <input type="checkbox" class="message-checkbox w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer" 
                               value="${msg.message_id}" 
                               ${isSelected ? 'checked' : ''}
                               onchange="window.toggleMessageSelection('${msg.message_id}', this.checked)">
                        <div>
                            <span class="font-semibold text-sm">${escapeHtml(msg.role || 'unknown')}</span>
                            ${msg.model ? `<span class="text-xs text-gray-500 ml-2">(${escapeHtml(msg.model)})</span>` : ''}
                        </div>
                    </div>
                    <div class="text-xs text-gray-500">
                        ${formatTimestamp(msg.create_time)}
                    </div>
                </div>
                <div class="text-sm text-gray-700 whitespace-pre-wrap">${escapeHtml(msg.content || '')}</div>
                
                <!-- Message Metadata Toggle -->
                <div class="mt-2 flex items-center space-x-4">
                    <button onclick="window.toggleMetadata('msg-metadata-${index}', event)" class="text-blue-600 hover:text-blue-800 text-xs font-medium">
                        <span id="msg-metadata-toggle-${index}">▶</span> Metadata
                    </button>
                    <button onclick="window.toggleRawData('msg-raw-${index}', event)" class="text-blue-600 hover:text-blue-800 text-xs font-medium">
                        View Raw JSON ▼
                    </button>
                </div>
                
                <!-- Message Metadata (collapsible - hidden by default) -->
                <div id="msg-metadata-${index}" class="hidden mt-2 text-xs text-gray-600 space-y-1">
                    ${msg.finish_reason ? `<div><span class="font-medium">Finish Reason:</span> ${escapeHtml(msg.finish_reason)}</div>` : ''}
                    ${msg.tokens ? `<div><span class="font-medium">Tokens:</span> ${typeof msg.tokens === 'object' ? JSON.stringify(msg.tokens) : escapeHtml(String(msg.tokens))}</div>` : ''}
                    ${msg.browser_info && Object.keys(msg.browser_info).length > 0 ? `<div><span class="font-medium">Browser Info:</span> <pre class="inline">${JSON.stringify(msg.browser_info, null, 2)}</pre></div>` : ''}
                    ${msg.geo_data && Object.keys(msg.geo_data).length > 0 ? `<div><span class="font-medium">Geo Data:</span> <pre class="inline">${JSON.stringify(msg.geo_data, null, 2)}</pre></div>` : ''}
                    ${msg.metadata && Object.keys(msg.metadata).length > 0 ? `<div><span class="font-medium">Metadata:</span> <pre class="inline text-xs">${JSON.stringify(msg.metadata, null, 2)}</pre></div>` : ''}
                </div>
                
                <!-- Expandable Raw Data -->
                <div class="mt-2">
                    <pre id="msg-raw-${index}" class="hidden mt-2 p-2 bg-gray-100 rounded text-xs overflow-x-auto" style="max-height: 300px; overflow-y: auto;"></pre>
                </div>
                
                <!-- Feedback for this message -->
                ${messageFeedback.length > 0 ? `
                <div class="mt-3 pt-3 border-t border-gray-200">
                    <div class="text-xs font-semibold text-gray-600 mb-2">Feedback (${messageFeedback.length}):</div>
                    <div class="flex flex-wrap gap-2">
                        ${messageFeedback.map(fb => `
                            <span class="inline-flex items-center space-x-1 px-2 py-1 rounded text-xs ${fb.rating === 'thumbs_up' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                                <span>${fb.rating === 'thumbs_up' ? '👍' : '👎'}</span>
                                ${fb.content ? `<span class="text-gray-700">${escapeHtml(fb.content)}</span>` : ''}
                            </span>
                        `).join('')}
                    </div>
                </div>
                ` : ''}
            </div>
        `;
    });
    
    html += `
                </div>
            </div>
        </div>
    `;
    
    content.innerHTML = html;
    modal.classList.remove('hidden');
    
    // Update export button state
    updateMessageExportButton();
    
    // Set raw data content
    setTimeout(() => {
        const convRaw = document.getElementById('conv-raw');
        if (convRaw) {
            convRaw.textContent = JSON.stringify(conversation.raw_data, null, 2);
        }
        conversation.messages.forEach((msg, index) => {
            const msgRaw = document.getElementById(`msg-raw-${index}`);
            if (msgRaw && msg.raw_data) {
                msgRaw.textContent = JSON.stringify(msg.raw_data, null, 2);
            }
        });
    }, 100);
}

function toggleSelectAllMessages(checked) {
    const checkboxes = document.querySelectorAll('.message-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = checked;
        toggleMessageSelection(cb.value, checked);
    });
}

function toggleMessageSelection(messageId, checked) {
    if (checked) {
        selectedMessages.add(messageId);
    } else {
        selectedMessages.delete(messageId);
    }
    updateMessageExportButton();
}

function updateMessageExportButton() {
    const exportBtn = document.getElementById('export-selected-messages');
    if (exportBtn) {
        const count = selectedMessages.size;
        exportBtn.disabled = count === 0;
        exportBtn.textContent = `Export Selected Messages (${count})`;
    }
}

async function exportSelectedMessages() {
    if (selectedMessages.size === 0) {
        alert('Please select at least one message to export');
        return;
    }
    
    // Get conversation ID from the modal
    const modal = document.getElementById('detail-modal');
    if (!modal) return;
    
    // We need to get the conversation ID - let's get it from the API using the first message
    const messageIds = Array.from(selectedMessages);
    
    try {
        const response = await fetch('/api/chatgpt-viewer/export/messages', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message_ids: messageIds
            })
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `chatgpt_messages_export_${new Date().toISOString().split('T')[0]}.json`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            alert(`Exported ${selectedMessages.size} message(s)`);
        } else {
            const data = await response.json();
            alert('Error exporting: ' + (data.detail || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error exporting messages:', error);
        alert('Error exporting messages: ' + error.message);
    }
}

window.toggleSelectAllMessages = toggleSelectAllMessages;
window.toggleMessageSelection = toggleMessageSelection;
window.exportSelectedMessages = exportSelectedMessages;

async function startImport() {
    if (!confirm('Start importing all folders from chatlog? This may take a while.')) {
        return;
    }
    
    try {
        const response = await fetch('/api/chatgpt-viewer/import/start', {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            showImportStatus(data.result);
            loadStats();
            if (currentView === 'list') {
                loadConversations();
            } else {
                loadTimeline();
            }
        }
    } catch (error) {
        console.error('Error starting import:', error);
        alert('Error starting import');
    }
}

async function showImportStatus(result) {
    const modal = document.getElementById('import-modal');
    const content = document.getElementById('import-status-content');
    
    const html = `
        <div class="space-y-4">
            <div class="grid grid-cols-2 gap-4">
                <div><strong>Total Folders:</strong> ${result.total_folders}</div>
                <div><strong>Processed:</strong> ${result.processed}</div>
                <div><strong>Skipped:</strong> ${result.skipped}</div>
                <div><strong>Errors:</strong> ${result.errors}</div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div><strong>Conversations:</strong> ${result.conversations}</div>
                <div><strong>Messages:</strong> ${result.messages}</div>
                <div><strong>Feedback:</strong> ${result.feedback}</div>
                <div><strong>Comparisons:</strong> ${result.comparisons}</div>
            </div>
            ${result.errors_list && result.errors_list.length > 0 ? `
            <div>
                <strong>Errors:</strong>
                <ul class="list-disc list-inside text-sm text-red-600">
                    ${result.errors_list.map(e => `<li>${escapeHtml(e)}</li>`).join('')}
                </ul>
            </div>
            ` : ''}
        </div>
    `;
    
    content.innerHTML = html;
    modal.classList.remove('hidden');
}

function formatTimestamp(timestamp) {
    if (!timestamp) return 'N/A';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString();
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Global function for toggling raw data display
window.toggleMetadata = function(id, event) {
    if (event) {
        event.preventDefault();
    }
    const element = document.getElementById(id);
    const toggleIcon = document.getElementById(id.replace('msg-metadata-', 'msg-metadata-toggle-'));
    
    if (element) {
        if (element.classList.contains('hidden')) {
            element.classList.remove('hidden');
            if (toggleIcon) {
                toggleIcon.textContent = '▼';
            }
        } else {
            element.classList.add('hidden');
            if (toggleIcon) {
                toggleIcon.textContent = '▶';
            }
        }
    }
};

window.toggleRawData = function(id, event) {
    const el = document.getElementById(id);
    const btn = event.target;
    if (el.classList.contains('hidden')) {
        el.classList.remove('hidden');
        btn.textContent = btn.textContent.replace('▼', '▲');
        if (!el.textContent && id === 'conv-raw') {
            // This will be set from the conversation data
        }
    } else {
        el.classList.add('hidden');
        btn.textContent = btn.textContent.replace('▲', '▼');
    }
};

let currentTTLPage = 1;
let ttlPageSize = 50;
let currentFilteredPage = 1;
let filteredPageSize = 50;

async function loadTTLSessions() {
    try {
        const params = new URLSearchParams({
            page: currentTTLPage,
            per_page: ttlPageSize
        });
        
        const response = await fetch(`/api/chatgpt-viewer/ttl/sessions?${params}`);
        const data = await response.json();
        
        if (data.success) {
            displayTTLSessions(data.sessions);
            displayPagination(data.pagination, 'ttl');
        }
    } catch (error) {
        console.error('Error loading TTL sessions:', error);
        document.getElementById('ttl-sessions-list').innerHTML = 
            '<div class="text-center py-8 text-red-600">Error loading TTL sessions</div>';
    }
}

function displayTTLSessions(sessions) {
    const container = document.getElementById('ttl-sessions-list');
    
    if (sessions.length === 0) {
        container.innerHTML = '<div class="text-center py-8 text-gray-600">No TTL sessions found</div>';
        return;
    }
    
    const html = sessions.map(session => {
        const createDate = session.create_time ? new Date(session.create_time).toLocaleString() : 'N/A';
        const expirationDate = session.expiration_time ? new Date(session.expiration_time).toLocaleString() : 'N/A';
        const lastAuthDate = session.last_auth_time ? new Date(session.last_auth_time).toLocaleString() : 'N/A';
        const location = [session.city, session.region, session.country].filter(Boolean).join(', ') || 'Unknown';
        
        // Check if session is expired
        const isExpired = session.expiration_time ? new Date(session.expiration_time) < new Date() : false;
        
        return `
            <div class="border rounded-lg p-4 hover:bg-gray-50">
                <div class="flex justify-between items-start mb-2">
                    <div class="flex-1">
                        <div class="flex items-center space-x-2 mb-2">
                            <span class="text-sm font-semibold text-gray-900">Session: ${escapeHtml(session.session_id || 'N/A')}</span>
                            <span class="px-2 py-1 text-xs rounded ${session.status === 'CONFIRMED' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}">
                                ${escapeHtml(session.status || 'Unknown')}
                            </span>
                            ${isExpired ? '<span class="px-2 py-1 text-xs rounded bg-red-100 text-red-800">Expired</span>' : ''}
                        </div>
                        <div class="text-xs text-gray-500 mb-2 space-y-1">
                            <div><strong>Started:</strong> ${createDate}</div>
                            ${session.expiration_time ? `<div><strong>Expires:</strong> ${expirationDate} ${isExpired ? '<span class="text-red-600">(Expired)</span>' : ''}</div>` : ''}
                            ${session.last_auth_time ? `<div><strong>Last Auth:</strong> ${lastAuthDate}</div>` : ''}
                        </div>
                        
                        <!-- Geolocation Info -->
                        ${session.latitude && session.longitude ? `
                        <div class="bg-blue-50 border border-blue-200 rounded p-3 mb-2">
                            <div class="text-sm font-semibold text-blue-900 mb-1">📍 Location</div>
                            <div class="text-sm text-blue-800">
                                <div><strong>Location:</strong> ${escapeHtml(location)}</div>
                                <div><strong>Coordinates:</strong> ${session.latitude}, ${session.longitude}</div>
                                ${session.postal_code ? `<div><strong>Postal Code:</strong> ${escapeHtml(session.postal_code)}</div>` : ''}
                                ${session.timezone ? `<div><strong>Timezone:</strong> ${escapeHtml(session.timezone)}</div>` : ''}
                            </div>
                        </div>
                        ` : ''}
                        
                        <!-- Network Info -->
                        ${session.ip_address ? `
                        <div class="bg-purple-50 border border-purple-200 rounded p-3 mb-2">
                            <div class="text-sm font-semibold text-purple-900 mb-1">🌐 Network</div>
                            <div class="text-sm text-purple-800">
                                <div><strong>IP Address:</strong> ${escapeHtml(session.ip_address)}</div>
                                ${session.continent ? `<div><strong>Continent:</strong> ${escapeHtml(session.continent)}</div>` : ''}
                            </div>
                        </div>
                        ` : ''}
                        
                        <!-- Browser Info -->
                        ${session.user_agent ? `
                        <div class="bg-orange-50 border border-orange-200 rounded p-3 mb-2">
                            <div class="text-sm font-semibold text-orange-900 mb-1">💻 Browser</div>
                            <div class="text-xs text-orange-800 break-all">${escapeHtml(session.user_agent)}</div>
                        </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = html;
}

