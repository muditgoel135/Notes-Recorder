/* Step 7: chat page glue. Same API contracts and control IDs; shared fetch,
 * toast, escape, debounce and tree helpers are imported (Step 9); chat
 * rename uses a Bootstrap modal instead of a blocking prompt.
 */
import '../store.js';
import { fetchJSON } from '../api.js';
import { toast } from '../ui/toast.js';
import { escapeHtml, debounce } from '../utils.js';
import { buildTagTree, renderCheckboxTree } from '../ui/tree.js';




let allTags = [];
let allSubjects = [];
let selectedFilterTagIds = new Set();
let selectedFilterSubjects = new Set();
let activeChatSessionId = null;
let chatSelectedNoteIds = new Set();

function renderFilterTagTree() {
    const tree = buildTagTree(allTags);
    const container = document.getElementById('filter-tag-tree');
    if (!container) return;
    container.innerHTML = tree.length
        ? `<ul class="tag-tree">${renderCheckboxTree(tree, selectedFilterTagIds, 'filter-tag')}</ul>`
        : '<p class="text-muted small mb-0">No tags yet.</p>';
}

function renderFilterSubjectList() {
    const container = document.getElementById('filter-subject-list');
    if (!container) return;
    container.innerHTML = allSubjects.length
        ? `<ul class="tag-tree">${allSubjects.map((subject) => `
            <li>
                <label class="d-flex align-items-center gap-2">
                    <input type="checkbox" class="filter-subject-checkbox" value="${escapeHtml(subject.name)}"
                        ${selectedFilterSubjects.has(subject.name) ? 'checked' : ''}>
                    ${escapeHtml(subject.name)}
                </label>
            </li>
        `).join('')}</ul>`
        : '<p class="text-muted small mb-0">No subjects yet.</p>';
}

function updateTagFilterCount() {
    const badge = document.getElementById('tag-filter-count');
    if (!badge) return;
    badge.textContent = String(selectedFilterTagIds.size);
    badge.classList.toggle('d-none', selectedFilterTagIds.size === 0);
}

function updateSubjectFilterCount() {
    const badge = document.getElementById('subject-filter-count');
    if (!badge) return;
    badge.textContent = String(selectedFilterSubjects.size);
    badge.classList.toggle('d-none', selectedFilterSubjects.size === 0);
}

function getCurrentFilters() {
    return {
        q: document.getElementById('search-input').value.trim(),
        date_from: document.getElementById('date-from-input').value,
        date_to: document.getElementById('date-to-input').value,
        time_from: document.getElementById('time-from-input').value,
        time_to: document.getElementById('time-to-input').value,
        tags: Array.from(selectedFilterTagIds).join(','),
        subjects: Array.from(selectedFilterSubjects).join(','),
    };
}

function setChatPickerError(message = '') {
    const errorBox = document.getElementById('chat-picker-error');
    if (!errorBox) return;
    errorBox.textContent = message;
    errorBox.classList.toggle('d-none', !message);
}

function setChatMessageError(message = '') {
    const errorBox = document.getElementById('chat-message-error');
    if (!errorBox) return;
    errorBox.textContent = message;
    errorBox.classList.toggle('d-none', !message);
}

function formatDisplayDate(value) {
    if (!value) return value;
    const parts = String(value).split('-');
    if (parts.length !== 3) return value;
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

function formatDisplayTime(value) {
    if (!value) return value;
    const parts = String(value).split(':');
    if (parts.length < 2) return value;
    let hour = Number.parseInt(parts[0], 10);
    if (Number.isNaN(hour)) return value;
    const period = hour < 12 ? 'AM' : 'PM';
    hour = hour % 12;
    if (hour === 0) hour = 12;
    return `${hour}:${parts[1]} ${period}`;
}

function formatChatNoteLabel(note) {
    const name = note.title || note.subject || 'Untitled';
    const when = [formatDisplayDate(note.date), formatDisplayTime(note.start_time)].filter(Boolean).join(' ');
    return when ? `${name} (${when})` : name;
}

function renderChatSessions(sessions = []) {
    const list = document.getElementById('chat-session-list');
    list.innerHTML = sessions.length
        ? sessions.map((session) => `
            <button type="button" class="list-group-item list-group-item-action chat-session-btn
                ${session.id === activeChatSessionId ? 'active' : ''}" data-session-id="${session.id}">
                <div class="fw-semibold text-truncate">${escapeHtml(session.title)}</div>
                <div class="small ${session.id === activeChatSessionId ? '' : 'text-muted'}">
                    ${session.message_count} message${session.message_count === 1 ? '' : 's'}
                </div>
            </button>
        `).join('')
        : '<div class="text-muted small">No saved chats yet. Pick recordings and press Start chat.</div>';
}

async function loadChatSessions() {
    try {
        const data = await fetchJSON('/api/chat/sessions', { toastOnError: false });
        renderChatSessions(data.sessions || []);
    } catch (e) {
        toast.error(e.message);
    }
}

function renderChatRecordings(recordings = []) {
    const list = document.getElementById('chat-recording-list');
    list.innerHTML = recordings.length
        ? recordings.map((note) => `
            <label class="chat-recording-row">
                <input type="checkbox" class="chat-recording-checkbox" value="${note.id}"
                    ${chatSelectedNoteIds.has(note.id) ? 'checked' : ''}>
                <span>
                    <span class="fw-semibold d-block">${escapeHtml(formatChatNoteLabel(note))}</span>
                    <span class="small text-muted d-block">${escapeHtml(note.preview || '')}</span>
                </span>
            </label>
        `).join('')
        : '<div class="text-muted small">No transcript-ready recordings match the current filters.</div>';
}

async function loadChatRecordings() {
    setChatPickerError('');
    const filters = getCurrentFilters();
    const params = new URLSearchParams();
    if (filters.q) params.set('q', filters.q);
    if (filters.date_from) params.set('date_from', filters.date_from);
    if (filters.date_to) params.set('date_to', filters.date_to);
    if (filters.time_from) params.set('time_from', filters.time_from);
    if (filters.time_to) params.set('time_to', filters.time_to);
    if (filters.tags) params.set('tags', filters.tags);
    if (filters.subjects) params.set('subjects', filters.subjects);
    try {
        const data = await fetchJSON(`/api/chat/recordings?${params.toString()}`, { toastOnError: false });
        renderChatRecordings(data.recordings || []);
    } catch (e) {
        const message = e.status === 404
            ? 'Chat routes are not loaded yet. Restart the Flask server and reopen this page.'
            : e.message;
        setChatPickerError(message);
        toast.error(message);
    }
}

function renderChatMessageBody(message) {
    if (message.role === 'assistant' && message.html) {
        return `<div class="markdown-content">${message.html}</div>`;
    }
    return `<div>${escapeHtml(message.content)}</div>`;
}

function renderChatMessages(messages = []) {
    const container = document.getElementById('chat-messages');
    container.innerHTML = messages.length
        ? messages.map((message) => `
            <div class="chat-message chat-message-${message.role}">
                <div class="small text-muted mb-1">${message.role === 'user' ? 'You' : 'Ollama'}</div>
                ${renderChatMessageBody(message)}
            </div>
        `).join('')
        : '<div class="text-muted small">Ask a question to start this chat.</div>';
    container.scrollTop = container.scrollHeight;
}

function updateChatComposerState() {
    const enabled = Boolean(activeChatSessionId) || chatSelectedNoteIds.size > 0;
    document.getElementById('chat-message-input').disabled = !enabled;
    document.getElementById('send-chat-message-btn').disabled = !enabled;
}

function renderDraftChatState() {
    if (activeChatSessionId) return;
    const count = chatSelectedNoteIds.size;
    document.getElementById('active-chat-title').textContent = count ? 'New chat' : 'No chat selected';
    document.getElementById('active-chat-recordings').textContent = count
        ? `${count} selected recording${count === 1 ? '' : 's'}`
        : '';
    renderChatMessages([]);
    updateChatComposerState();
}

function renderActiveChat(session) {
    activeChatSessionId = session ? session.id : null;
    document.getElementById('active-chat-title').textContent = session ? session.title : 'No chat selected';
    document.getElementById('active-chat-recordings').textContent = session
        ? session.notes.map(formatChatNoteLabel).join(', ')
        : '';
    document.getElementById('rename-chat-btn').classList.toggle('d-none', !session);
    renderChatMessages(session ? session.messages : []);
    updateChatComposerState();
}

async function openChatSession(sessionId) {
    setChatMessageError('');
    try {
        const data = await fetchJSON(`/api/chat/sessions/${sessionId}`, { toastOnError: false });
        renderActiveChat(data.session);
        await loadChatSessions();
    } catch (e) {
        setChatMessageError('Could not open that chat.');
        toast.error('Could not open that chat.');
    }
}

async function createChatSessionFromSelection() {
    setChatPickerError('');
    if (chatSelectedNoteIds.size === 0) {
        setChatPickerError('Choose at least one recording.');
        return null;
    }
    const data = await fetchJSON('/api/chat/sessions', {
        method: 'POST',
        body: JSON.stringify({ note_ids: Array.from(chatSelectedNoteIds) }),
    });
    renderActiveChat(data.session);
    await loadChatSessions();
    return data.session;
}

async function loadTags() {
    try {
        const data = await fetchJSON('/api/tags', { toastOnError: false });
        allTags = data.tags || [];
        renderFilterTagTree();
    } catch (e) { /* filters stay empty; recordings still load */ }
}

async function loadSubjects() {
    try {
        const data = await fetchJSON('/api/subjects', { toastOnError: false });
        allSubjects = data.subjects || [];
        renderFilterSubjectList();
    } catch (e) { /* filters stay empty; recordings still load */ }
}

/* ---- rename modal (no blocking prompt) ---- */
const renameModalEl = document.getElementById('chat-rename-modal');
const renameInput = document.getElementById('chat-rename-input');
const renameError = document.getElementById('chat-rename-error');
document.getElementById('rename-chat-btn').addEventListener('click', () => {
    if (!activeChatSessionId) return;
    renameInput.value = document.getElementById('active-chat-title').textContent.trim();
    renameError.classList.add('d-none');
    window.bootstrap.Modal.getOrCreateInstance(renameModalEl).show();
    setTimeout(() => renameInput.focus(), 300);
});
document.getElementById('chat-rename-save').addEventListener('click', async () => {
    if (!activeChatSessionId) return;
    const currentTitle = document.getElementById('active-chat-title').textContent.trim();
    const title = renameInput.value.trim();
    if (!title || title === currentTitle) {
        window.bootstrap.Modal.getInstance(renameModalEl)?.hide();
        return;
    }
    try {
        const data = await fetchJSON(`/api/chat/sessions/${activeChatSessionId}/title`, {
            method: 'POST',
            body: JSON.stringify({ title }),
        });
        renderActiveChat(data.session);
        await loadChatSessions();
        window.bootstrap.Modal.getInstance(renameModalEl)?.hide();
        toast.success('Chat renamed.');
    } catch (e) {
        renameError.textContent = e.message;
        renameError.classList.remove('d-none');
    }
});

/* ---- wiring ---- */
const debouncedRecordingSearch = debounce(loadChatRecordings, 300);
document.getElementById('search-input').addEventListener('input', debouncedRecordingSearch);
['date-from-input', 'date-to-input', 'time-from-input', 'time-to-input'].forEach((id) => {
    document.getElementById(id).addEventListener('change', loadChatRecordings);
});

document.getElementById('clear-filters-btn').addEventListener('click', () => {
    document.getElementById('search-input').value = '';
    document.getElementById('date-from-input').value = '';
    document.getElementById('date-to-input').value = '';
    document.getElementById('time-from-input').value = '';
    document.getElementById('time-to-input').value = '';
    selectedFilterTagIds.clear();
    selectedFilterSubjects.clear();
    renderFilterTagTree();
    renderFilterSubjectList();
    updateTagFilterCount();
    updateSubjectFilterCount();
    loadChatRecordings();
});

document.getElementById('filter-tag-tree').addEventListener('change', (event) => {
    const checkbox = event.target.closest('.filter-tag-checkbox');
    if (!checkbox) return;
    const tagId = Number(checkbox.value);
    if (checkbox.checked) selectedFilterTagIds.add(tagId);
    else selectedFilterTagIds.delete(tagId);
    updateTagFilterCount();
    loadChatRecordings();
});

document.getElementById('filter-subject-list').addEventListener('change', (event) => {
    const checkbox = event.target.closest('.filter-subject-checkbox');
    if (!checkbox) return;
    if (checkbox.checked) selectedFilterSubjects.add(checkbox.value);
    else selectedFilterSubjects.delete(checkbox.value);
    updateSubjectFilterCount();
    loadChatRecordings();
});

document.getElementById('refresh-chat-recordings-btn').addEventListener('click', loadChatRecordings);

document.getElementById('select-chat-all-btn').addEventListener('click', () => {
    document.querySelectorAll('#chat-recording-list .chat-recording-checkbox').forEach((box) => {
        chatSelectedNoteIds.add(Number(box.value));
        box.checked = true;
    });
    renderDraftChatState();
});

document.getElementById('new-chat-btn').addEventListener('click', () => {
    activeChatSessionId = null;
    chatSelectedNoteIds.clear();
    renderActiveChat(null);
    loadChatRecordings();
    loadChatSessions();
});

document.getElementById('chat-recording-list').addEventListener('change', (event) => {
    const checkbox = event.target.closest('.chat-recording-checkbox');
    if (!checkbox) return;
    const noteId = Number(checkbox.value);
    if (checkbox.checked) chatSelectedNoteIds.add(noteId);
    else chatSelectedNoteIds.delete(noteId);
    renderDraftChatState();
});

document.getElementById('create-chat-session-btn').addEventListener('click', async () => {
    const button = document.getElementById('create-chat-session-btn');
    button.disabled = true;
    try {
        await createChatSessionFromSelection();
    } catch (error) {
        setChatPickerError(error.message);
    } finally {
        button.disabled = false;
        updateChatComposerState();
    }
});

document.getElementById('chat-session-list').addEventListener('click', (event) => {
    const button = event.target.closest('.chat-session-btn');
    if (button) {
        openChatSession(Number(button.dataset.sessionId));
    }
});

document.getElementById('chat-message-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    setChatMessageError('');
    const input = document.getElementById('chat-message-input');
    const sendButton = document.getElementById('send-chat-message-btn');
    const message = input.value.trim();
    if (!message) {
        setChatMessageError('Enter a message first.');
        return;
    }
    if (!activeChatSessionId) {
        try {
            await createChatSessionFromSelection();
        } catch (error) {
            setChatMessageError(error.message);
            return;
        }
    }
    input.disabled = true;
    sendButton.disabled = true;
    try {
        await fetchJSON(`/api/chat/sessions/${activeChatSessionId}/messages`, {
            method: 'POST',
            body: JSON.stringify({ message }),
        });
        input.value = '';
        await openChatSession(activeChatSessionId);
    } catch (error) {
        if (!error.data || !error.data.user_message) {
            setChatMessageError(error.message);
        } else {
            await openChatSession(activeChatSessionId);
            setChatMessageError(error.message);
        }
    } finally {
        input.disabled = false;
        sendButton.disabled = false;
        input.focus();
    }
});

document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (target && (target.isContentEditable || target.closest('input, textarea, select'))) return;
    const search = document.getElementById('search-input');
    if (search) {
        event.preventDefault();
        search.focus();
    }
});

loadTags();
loadSubjects();
loadChatSessions();
loadChatRecordings();
