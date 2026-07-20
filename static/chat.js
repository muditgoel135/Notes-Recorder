let allTags = [];
let allSubjects = [];
let selectedFilterTagIds = new Set();
let selectedFilterSubjects = new Set();
let activeChatSessionId = null;
let chatSelectedNoteIds = new Set();

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value);
    return div.innerHTML;
}

function debounce(fn, delayMs) {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), delayMs);
    };
}

function buildTagTree(flatTags) {
    const byId = new Map(flatTags.map((tag) => [tag.id, { ...tag, children: [] }]));
    const roots = [];
    byId.forEach((node) => {
        if (node.parent_id && byId.has(node.parent_id)) {
            byId.get(node.parent_id).children.push(node);
        } else {
            roots.push(node);
        }
    });
    return roots;
}

function renderCheckboxNodes(nodes, checkedIds) {
    return nodes.map((node) => `
        <li>
            <label class="d-flex align-items-center gap-2">
                <input type="checkbox" class="filter-tag-checkbox" value="${node.id}"
                    ${checkedIds.has(node.id) ? "checked" : ""}>
                <span class="tag-badge" style="background-color:${node.color}">${escapeHtml(node.name)}</span>
            </label>
            ${node.children.length ? `<ul class="tag-children">${renderCheckboxNodes(node.children, checkedIds)}</ul>` : ""}
        </li>
    `).join("");
}

function renderFilterTagTree() {
    const tree = buildTagTree(allTags);
    const container = document.getElementById("filter-tag-tree");
    container.innerHTML = tree.length
        ? `<ul class="tag-tree">${renderCheckboxNodes(tree, selectedFilterTagIds)}</ul>`
        : '<p class="text-muted small mb-0">No tags yet.</p>';
}

function renderFilterSubjectList() {
    const container = document.getElementById("filter-subject-list");
    container.innerHTML = allSubjects.length
        ? `<ul class="tag-tree">${allSubjects.map((subject) => `
            <li>
                <label class="d-flex align-items-center gap-2">
                    <input type="checkbox" class="filter-subject-checkbox" value="${escapeHtml(subject.name)}"
                        ${selectedFilterSubjects.has(subject.name) ? "checked" : ""}>
                    ${escapeHtml(subject.name)}
                </label>
            </li>
        `).join("")}</ul>`
        : '<p class="text-muted small mb-0">No subjects yet.</p>';
}

function updateTagFilterCount() {
    const badge = document.getElementById("tag-filter-count");
    badge.textContent = String(selectedFilterTagIds.size);
    badge.classList.toggle("d-none", selectedFilterTagIds.size === 0);
}

function updateSubjectFilterCount() {
    const badge = document.getElementById("subject-filter-count");
    badge.textContent = String(selectedFilterSubjects.size);
    badge.classList.toggle("d-none", selectedFilterSubjects.size === 0);
}

function getCurrentFilters() {
    return {
        q: document.getElementById("search-input").value.trim(),
        date_from: document.getElementById("date-from-input").value,
        date_to: document.getElementById("date-to-input").value,
        time_from: document.getElementById("time-from-input").value,
        time_to: document.getElementById("time-to-input").value,
        tags: Array.from(selectedFilterTagIds).join(","),
        subjects: Array.from(selectedFilterSubjects).join(","),
    };
}

function setChatPickerError(message = "") {
    const errorBox = document.getElementById("chat-picker-error");
    errorBox.textContent = message;
    errorBox.classList.toggle("d-none", !message);
}

function setChatMessageError(message = "") {
    const errorBox = document.getElementById("chat-message-error");
    errorBox.textContent = message;
    errorBox.classList.toggle("d-none", !message);
}

function formatChatNoteLabel(note) {
    const name = note.title || note.subject || "Untitled";
    const when = [note.date, note.start_time].filter(Boolean).join(" ");
    return when ? `${name} (${when})` : name;
}

function renderChatSessions(sessions = []) {
    const list = document.getElementById("chat-session-list");
    list.innerHTML = sessions.length
        ? sessions.map((session) => `
            <button type="button" class="list-group-item list-group-item-action chat-session-btn
                ${session.id === activeChatSessionId ? "active" : ""}" data-session-id="${session.id}">
                <div class="fw-semibold text-truncate">${escapeHtml(session.title)}</div>
                <div class="small ${session.id === activeChatSessionId ? "" : "text-muted"}">
                    ${session.message_count} message${session.message_count === 1 ? "" : "s"}
                </div>
            </button>
        `).join("")
        : '<div class="text-muted small">No saved chats yet.</div>';
}

async function loadChatSessions() {
    const response = await fetch("/api/chat/sessions");
    if (!response.ok) {
        return;
    }
    const data = await response.json();
    renderChatSessions(data.sessions || []);
}

function renderChatRecordings(recordings = []) {
    const list = document.getElementById("chat-recording-list");
    list.innerHTML = recordings.length
        ? recordings.map((note) => `
            <label class="chat-recording-row">
                <input type="checkbox" class="chat-recording-checkbox" value="${note.id}"
                    ${chatSelectedNoteIds.has(note.id) ? "checked" : ""}>
                <span>
                    <span class="fw-semibold d-block">${escapeHtml(formatChatNoteLabel(note))}</span>
                    <span class="small text-muted d-block">${escapeHtml(note.preview || "")}</span>
                </span>
            </label>
        `).join("")
        : '<div class="text-muted small">No transcript-ready recordings match the current filters.</div>';
}

async function loadChatRecordings() {
    setChatPickerError("");
    const filters = getCurrentFilters();
    const params = new URLSearchParams();
    if (filters.q) params.set("q", filters.q);
    if (filters.date_from) params.set("date_from", filters.date_from);
    if (filters.date_to) params.set("date_to", filters.date_to);
    if (filters.time_from) params.set("time_from", filters.time_from);
    if (filters.time_to) params.set("time_to", filters.time_to);
    if (filters.tags) params.set("tags", filters.tags);
    if (filters.subjects) params.set("subjects", filters.subjects);

    const response = await fetch(`/api/chat/recordings?${params.toString()}`);
    if (!response.ok) {
        let message = "Could not load recordings for chat.";
        const data = await response.json().catch(() => ({}));
        if (data.error) {
            message = data.error;
        } else if (response.status === 404) {
            message = "Chat routes are not loaded yet. Restart the Flask server and reopen this page.";
        }
        setChatPickerError(message);
        return;
    }
    const data = await response.json();
    renderChatRecordings(data.recordings || []);
}

function renderChatMessageBody(message) {
    if (message.role === "assistant" && message.html) {
        return `<div class="markdown-content">${message.html}</div>`;
    }
    return `<div>${escapeHtml(message.content)}</div>`;
}

function renderChatMessages(messages = []) {
    const container = document.getElementById("chat-messages");
    container.innerHTML = messages.length
        ? messages.map((message) => `
            <div class="chat-message chat-message-${message.role}">
                <div class="small text-muted mb-1">${message.role === "user" ? "You" : "Ollama"}</div>
                ${renderChatMessageBody(message)}
            </div>
        `).join("")
        : '<div class="text-muted small">Ask a question to start this chat.</div>';
    container.scrollTop = container.scrollHeight;
}

function updateChatComposerState() {
    const hasActiveSession = Boolean(activeChatSessionId);
    const hasDraftSelection = chatSelectedNoteIds.size > 0;
    document.getElementById("chat-message-input").disabled = !hasActiveSession && !hasDraftSelection;
    document.getElementById("send-chat-message-btn").disabled = !hasActiveSession && !hasDraftSelection;
}

function renderDraftChatState() {
    if (activeChatSessionId) {
        return;
    }
    const count = chatSelectedNoteIds.size;
    document.getElementById("active-chat-title").textContent = count ? "New chat" : "No chat selected";
    document.getElementById("active-chat-recordings").textContent = count
        ? `${count} selected recording${count === 1 ? "" : "s"}`
        : "";
    renderChatMessages([]);
    updateChatComposerState();
}

function renderActiveChat(session) {
    activeChatSessionId = session ? session.id : null;
    document.getElementById("active-chat-title").textContent = session ? session.title : "No chat selected";
    document.getElementById("active-chat-recordings").textContent = session
        ? session.notes.map(formatChatNoteLabel).join(", ")
        : "";
    document.getElementById("rename-chat-btn").classList.toggle("d-none", !session);
    renderChatMessages(session ? session.messages : []);
    updateChatComposerState();
}

async function openChatSession(sessionId) {
    setChatMessageError("");
    const response = await fetch(`/api/chat/sessions/${sessionId}`);
    if (!response.ok) {
        setChatMessageError("Could not open that chat.");
        return;
    }
    const data = await response.json();
    renderActiveChat(data.session);
    await loadChatSessions();
}

async function createChatSessionFromSelection() {
    setChatPickerError("");
    if (chatSelectedNoteIds.size === 0) {
        setChatPickerError("Choose at least one recording.");
        return null;
    }

    const response = await fetch("/api/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note_ids: Array.from(chatSelectedNoteIds) }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || "Could not start chat.");
    }
    renderActiveChat(data.session);
    await loadChatSessions();
    return data.session;
}

async function loadTags() {
    const response = await fetch("/api/tags");
    if (!response.ok) {
        return;
    }
    const data = await response.json();
    allTags = data.tags || [];
    renderFilterTagTree();
}

async function loadSubjects() {
    const response = await fetch("/api/subjects");
    if (!response.ok) {
        return;
    }
    const data = await response.json();
    allSubjects = data.subjects || [];
    renderFilterSubjectList();
}

const debouncedRecordingSearch = debounce(loadChatRecordings, 300);

document.getElementById("search-input").addEventListener("input", debouncedRecordingSearch);
["date-from-input", "date-to-input", "time-from-input", "time-to-input"].forEach((id) => {
    document.getElementById(id).addEventListener("change", loadChatRecordings);
});

document.getElementById("clear-filters-btn").addEventListener("click", () => {
    document.getElementById("search-input").value = "";
    document.getElementById("date-from-input").value = "";
    document.getElementById("date-to-input").value = "";
    document.getElementById("time-from-input").value = "";
    document.getElementById("time-to-input").value = "";
    selectedFilterTagIds.clear();
    selectedFilterSubjects.clear();
    renderFilterTagTree();
    renderFilterSubjectList();
    updateTagFilterCount();
    updateSubjectFilterCount();
    loadChatRecordings();
});

document.getElementById("filter-tag-tree").addEventListener("change", (event) => {
    const checkbox = event.target.closest(".filter-tag-checkbox");
    if (!checkbox) {
        return;
    }
    const tagId = Number(checkbox.value);
    if (checkbox.checked) {
        selectedFilterTagIds.add(tagId);
    } else {
        selectedFilterTagIds.delete(tagId);
    }
    updateTagFilterCount();
    loadChatRecordings();
});

document.getElementById("filter-subject-list").addEventListener("change", (event) => {
    const checkbox = event.target.closest(".filter-subject-checkbox");
    if (!checkbox) {
        return;
    }
    if (checkbox.checked) {
        selectedFilterSubjects.add(checkbox.value);
    } else {
        selectedFilterSubjects.delete(checkbox.value);
    }
    updateSubjectFilterCount();
    loadChatRecordings();
});

document.getElementById("refresh-chat-recordings-btn").addEventListener("click", loadChatRecordings);

document.getElementById("new-chat-btn").addEventListener("click", () => {
    activeChatSessionId = null;
    chatSelectedNoteIds.clear();
    renderActiveChat(null);
    loadChatRecordings();
    loadChatSessions();
});

document.getElementById("chat-recording-list").addEventListener("change", (event) => {
    const checkbox = event.target.closest(".chat-recording-checkbox");
    if (!checkbox) {
        return;
    }
    const noteId = Number(checkbox.value);
    if (checkbox.checked) {
        chatSelectedNoteIds.add(noteId);
    } else {
        chatSelectedNoteIds.delete(noteId);
    }
    renderDraftChatState();
});

document.getElementById("create-chat-session-btn").addEventListener("click", async () => {
    const button = document.getElementById("create-chat-session-btn");
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

document.getElementById("chat-session-list").addEventListener("click", (event) => {
    const button = event.target.closest(".chat-session-btn");
    if (button) {
        openChatSession(Number(button.dataset.sessionId));
    }
});

document.getElementById("chat-message-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    setChatMessageError("");
    const input = document.getElementById("chat-message-input");
    const sendButton = document.getElementById("send-chat-message-btn");
    const message = input.value.trim();
    if (!message) {
        setChatMessageError("Enter a message first.");
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
        const response = await fetch(`/api/chat/sessions/${activeChatSessionId}/messages`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            if (data.user_message) {
                await openChatSession(activeChatSessionId);
            }
            throw new Error(data.error || "Could not send message.");
        }
        input.value = "";
        await openChatSession(activeChatSessionId);
    } catch (error) {
        setChatMessageError(error.message);
    } finally {
        input.disabled = false;
        sendButton.disabled = false;
        input.focus();
    }
});

document.getElementById("rename-chat-btn").addEventListener("click", async () => {
    if (!activeChatSessionId) {
        return;
    }
    const currentTitle = document.getElementById("active-chat-title").textContent.trim();
    const title = prompt("Rename chat:", currentTitle);
    if (!title || !title.trim() || title.trim() === currentTitle) {
        return;
    }
    try {
        const response = await fetch(`/api/chat/sessions/${activeChatSessionId}/title`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: title.trim() }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Could not rename chat.");
        }
        renderActiveChat(data.session);
        await loadChatSessions();
    } catch (error) {
        setChatMessageError(error.message);
    }
});

loadTags();
loadSubjects();
loadChatSessions();
loadChatRecordings();
