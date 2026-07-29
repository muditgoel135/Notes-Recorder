document.getElementById("recordings-list").addEventListener("click", async (event) => {
    const editButton = event.target.closest(".edit-note-btn");
    const cancelButton = event.target.closest(".cancel-note-btn");
    const saveButton = event.target.closest(".save-note-btn");
    const editRichNotesButton = event.target.closest(".edit-rich-notes-btn");
    const cancelRichNotesButton = event.target.closest(".cancel-rich-notes-btn");
    const saveRichNotesButton = event.target.closest(".save-rich-notes-btn");
    const editTagsButton = event.target.closest(".edit-tags-btn");
    const editSubjectButton = event.target.closest(".edit-subject-btn");
    const cancelSubjectButton = event.target.closest(".cancel-subject-btn");
    const saveSubjectButton = event.target.closest(".save-subject-btn");
    const editDatetimeButton = event.target.closest(".edit-datetime-btn");
    const cancelDatetimeButton = event.target.closest(".cancel-datetime-btn");
    const saveDatetimeButton = event.target.closest(".save-datetime-btn");
    const pageButton = event.target.closest("#prev-page-btn, #next-page-btn");
    const wordSpan = event.target.closest(".transcript-word");
    const speakerBadge = event.target.closest(".speaker-badge");
    const retryTranscriptionButton = event.target.closest(".retry-transcription-btn");
    const retryKeyPointsButton = event.target.closest(".retry-key-points-btn");
    const deleteButton = event.target.closest(".delete-note-btn");

    if (deleteButton) {
        event.preventDefault();
        if (!confirm("Delete this recording?")) {
            return;
        }
        const noteId = deleteButton.dataset.noteId;
        deleteButton.disabled = true;
        try {
            const response = await fetch(`/delete/${noteId}`, {
                method: "POST",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not delete recording.");
            }
            fetchAndRenderNotes(currentPage);
        } catch (error) {
            deleteButton.disabled = false;
            alert(error.message);
        }
        return;
    }

    if (speakerBadge) {
        const name = prompt("Rename speaker:", speakerBadge.textContent.trim());
        if (name && name.trim() && name.trim() !== speakerBadge.textContent.trim()) {
            const noteId = speakerBadge.dataset.noteId;
            const speakerId = speakerBadge.dataset.speakerId;
            try {
                const response = await fetch(`/notes/${noteId}/speakers/${speakerId}/rename`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name: name.trim() }),
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.error || "Rename failed.");
                }
                document.querySelectorAll(
                    `.speaker-badge[data-note-id="${noteId}"][data-speaker-id="${speakerId}"]`
                ).forEach((badge) => {
                    badge.textContent = name.trim();
                });
            } catch (error) {
                alert(error.message);
            }
        }
        return;
    }

    if (retryTranscriptionButton || retryKeyPointsButton) {
        const button = retryTranscriptionButton || retryKeyPointsButton;
        const noteId = button.dataset.noteId;
        const url = retryTranscriptionButton
            ? `/notes/${noteId}/retry_transcription`
            : `/notes/${noteId}/retry_key_points`;
        button.disabled = true;
        try {
            const response = await fetch(url, { method: "POST" });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Retry failed.");
            }
            fetchAndRenderNotes(currentPage);
        } catch (error) {
            button.disabled = false;
            alert(error.message);
        }
        return;
    }

    if (editTagsButton) {
        activeNoteTagsId = editTagsButton.dataset.noteId;
        const checkedIds = new Set(JSON.parse(editTagsButton.dataset.tagIds || "[]"));
        renderNoteTagTree(checkedIds);
        document.getElementById("note-tags-error").classList.add("d-none");
        bootstrap.Modal.getOrCreateInstance(document.getElementById("note-tags-modal")).show();
        return;
    }

    if (editSubjectButton) {
        const noteId = editSubjectButton.dataset.noteId;
        document.querySelector(`.note-subject-display[data-note-id="${noteId}"]`).classList.add("d-none");
        document.querySelector(`.note-subject-edit[data-note-id="${noteId}"]`).classList.remove("d-none");
        return;
    }

    if (cancelSubjectButton) {
        const noteId = cancelSubjectButton.dataset.noteId;
        document.querySelector(`.note-subject-edit[data-note-id="${noteId}"]`).classList.add("d-none");
        document.querySelector(`.note-subject-display[data-note-id="${noteId}"]`).classList.remove("d-none");
        return;
    }

    if (saveSubjectButton) {
        const noteId = saveSubjectButton.dataset.noteId;
        const editRow = document.querySelector(`.note-subject-edit[data-note-id="${noteId}"]`);
        const subject = editRow.querySelector(".note-subject-input").value;
        saveSubjectButton.disabled = true;
        try {
            const response = await fetch(`/notes/${noteId}/subject`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ subject }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not save subject.");
            }
            fetchAndRenderNotes(currentPage);
        } catch (error) {
            saveSubjectButton.disabled = false;
            alert(error.message);
        }
        return;
    }

    if (editDatetimeButton) {
        const noteId = editDatetimeButton.dataset.noteId;
        document.querySelector(`.note-datetime-display[data-note-id="${noteId}"]`).classList.add("d-none");
        document.querySelector(`.note-datetime-edit[data-note-id="${noteId}"]`).classList.remove("d-none");
        return;
    }

    if (cancelDatetimeButton) {
        const noteId = cancelDatetimeButton.dataset.noteId;
        document.querySelector(`.note-datetime-edit[data-note-id="${noteId}"]`).classList.add("d-none");
        document.querySelector(`.note-datetime-display[data-note-id="${noteId}"]`).classList.remove("d-none");
        return;
    }

    if (saveDatetimeButton) {
        const noteId = saveDatetimeButton.dataset.noteId;
        const editRow = document.querySelector(`.note-datetime-edit[data-note-id="${noteId}"]`);
        const date = editRow.querySelector(".note-date-input").value;
        const startTime = editRow.querySelector(".note-start-time-input").value;
        saveDatetimeButton.disabled = true;
        try {
            const response = await fetch(`/notes/${noteId}/datetime`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ date, start_time: startTime }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not save date/time.");
            }
            fetchAndRenderNotes(currentPage);
        } catch (error) {
            saveDatetimeButton.disabled = false;
            alert(error.message);
        }
        return;
    }

    if (pageButton && !pageButton.disabled) {
        fetchAndRenderNotes(Number(pageButton.dataset.page));
        return;
    }

    if (wordSpan) {
        if (!isSyncEnabled()) {
            return;
        }
        const noteId = wordSpan.closest(".transcript-words").dataset.noteId;
        const audio = document.getElementById(`audio-${noteId}`);
        if (audio) {
            audio.currentTime = Number(wordSpan.dataset.start);
            audio.play();
        }
        return;
    }

    if (editRichNotesButton) {
        const noteId = editRichNotesButton.dataset.noteId;
        document.querySelector(`.note-rich-notes-display[data-note-id="${noteId}"]`).classList.add("d-none");
        document.querySelector(`.note-rich-notes-edit[data-note-id="${noteId}"]`).classList.remove("d-none");
        return;
    }

    if (cancelRichNotesButton) {
        const form = cancelRichNotesButton.closest(".note-rich-notes-edit");
        const noteId = form.dataset.noteId;
        const display = document.querySelector(`.note-rich-notes-display[data-note-id="${noteId}"]`);
        const content = display.querySelector(".rich-notes-content");
        form.querySelector(".rich-notes-surface").innerHTML = content ? content.innerHTML : "";
        form.classList.add("d-none");
        display.classList.remove("d-none");
        return;
    }

    if (saveRichNotesButton) {
        const noteId = saveRichNotesButton.dataset.noteId;
        const form = document.querySelector(`.note-rich-notes-edit[data-note-id="${noteId}"]`);
        const editor = form.querySelector(".rich-notes-surface");
        const errorBox = form.querySelector(".rich-notes-edit-error");
        errorBox.classList.add("d-none");
        saveRichNotesButton.disabled = true;

        try {
            const response = await fetch(`/notes/${noteId}/notes`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ notes_html: normalizeRichNoteHtml(editor.innerHTML) }),
            });

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not save notes.");
            }

            fetchAndRenderNotes(currentPage);
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.classList.remove("d-none");
            saveRichNotesButton.disabled = false;
        }
        return;
    }

    if (editButton) {
        const noteId = editButton.dataset.noteId;
        document.querySelector(`.note-display[data-note-id="${noteId}"]`).classList.add("d-none");
        document.querySelector(`.note-edit-form[data-note-id="${noteId}"]`).classList.remove("d-none");
        return;
    }

    if (cancelButton) {
        const form = cancelButton.closest(".note-edit-form");
        const noteId = form.dataset.noteId;
        form.classList.add("d-none");
        document.querySelector(`.note-display[data-note-id="${noteId}"]`).classList.remove("d-none");
        return;
    }

    if (saveButton) {
        const noteId = saveButton.dataset.noteId;
        const form = document.querySelector(`.note-edit-form[data-note-id="${noteId}"]`);
        const title = form.querySelector(".note-title-input").value;
        const keyPoints = form.querySelector(".note-keypoints-input").value;
        const errorBox = form.querySelector(".note-edit-error");
        errorBox.classList.add("d-none");
        saveButton.disabled = true;

        try {
            const response = await fetch(`/update_note/${noteId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title, key_points: keyPoints })
            });

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not save note.");
            }

            fetchAndRenderNotes(currentPage);
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.classList.remove("d-none");
            saveButton.disabled = false;
        }
    }
});

const syncToggle = document.getElementById("sync-toggle");

function isSyncEnabled() {
    return localStorage.getItem("syncTranscriptEnabled") !== "false";
}

function applySyncEnabled(enabled) {
    document.body.classList.toggle("sync-enabled", enabled);
}

syncToggle.checked = isSyncEnabled();
applySyncEnabled(syncToggle.checked);

syncToggle.addEventListener("change", () => {
    localStorage.setItem("syncTranscriptEnabled", String(syncToggle.checked));
    applySyncEnabled(syncToggle.checked);
});

function highlightActiveWord(audio) {
    const noteId = audio.dataset.noteId;
    const container = document.querySelector(`.transcript-words[data-note-id="${noteId}"]`);
    if (!container) {
        return;
    }
    const words = container.querySelectorAll(".transcript-word");
    let activeWord = null;
    for (const word of words) {
        if (Number(word.dataset.start) <= audio.currentTime) {
            activeWord = word;
        } else {
            break;
        }
    }
    const currentlyActive = container.querySelector(".transcript-word.active-word");
    if (currentlyActive && currentlyActive !== activeWord) {
        currentlyActive.classList.remove("active-word");
    }
    if (activeWord) {
        activeWord.classList.add("active-word");
    }
}

function bindAudioSync() {
    document.querySelectorAll("audio[data-note-id]").forEach((audio) => {
        audio.addEventListener("timeupdate", () => {
            if (isSyncEnabled()) {
                highlightActiveWord(audio);
            }
        });
    });
}

function renderMathFields(root = document) {
    const MQ = initMathQuill();
    root.querySelectorAll('span.math-field[data-latex]').forEach(el => {
        const latex = el.dataset.latex || "";
        el.title = `LaTeX: ${latex}\n(Click to edit)`;
        if (!MQ) {
            el.textContent = `$${latex}$`;
            return;
        }
        const existingMath = MQ(el);
        if (existingMath) {
            existingMath.latex(latex);
            return;
        }
        el.textContent = latex;
        MQ.StaticMath(el);
    });
}


function snapshotPlayback() {
    const snapshots = [];
    document.querySelectorAll("audio[data-note-id]").forEach((audio) => {
        if (!audio.paused) {
            snapshots.push({
                noteId: audio.dataset.noteId,
                currentTime: audio.currentTime,
            });
        }
    });
    return snapshots;
}

function restorePlayback(snapshots) {
    snapshots.forEach(({ noteId, currentTime }) => {
        const audio = document.getElementById(`audio-${noteId}`);
        if (audio) {
            audio.currentTime = currentTime;
            audio.play();
        }
    });
}

function snapshotOpenCollapses() {
    return Array.from(document.querySelectorAll("#recordings-list .collapse.show"))
        .map((el) => el.id)
        .filter(Boolean);
}

function restoreOpenCollapses(ids) {
    ids.forEach((id) => {
        const el = document.getElementById(id);
        if (!el) {
            return;
        }
        el.classList.add("show");
        document.querySelectorAll(`[data-bs-target="#${id}"]`).forEach((toggle) => {
            toggle.setAttribute("aria-expanded", "true");
        });
    });
}

function snapshotRichNotesEdits() {
    return Array.from(document.querySelectorAll(".note-rich-notes-edit:not(.d-none)"))
        .map((form) => {
            const editor = form.querySelector(".rich-notes-surface");
            const activeElement = document.activeElement;
            return {
                noteId: form.dataset.noteId,
                html: editor ? editor.innerHTML : "",
                wasFocused: Boolean(editor && editor.contains(activeElement)),
            };
        })
        .filter((snapshot) => snapshot.noteId);
}

function restoreRichNotesEdits(snapshots) {
    snapshots.forEach(({ noteId, html, wasFocused }) => {
        const display = document.querySelector(`.note-rich-notes-display[data-note-id="${noteId}"]`);
        const form = document.querySelector(`.note-rich-notes-edit[data-note-id="${noteId}"]`);
        if (!display || !form) {
            return;
        }

        const editor = form.querySelector(".rich-notes-surface");
        display.classList.add("d-none");
        form.classList.remove("d-none");
        if (editor) {
            editor.innerHTML = html;
            if (wasFocused) {
                editor.focus();
            }
        }
    });
}

function hasOpenRichNotesEdit() {
    return Boolean(document.querySelector(".note-rich-notes-edit:not(.d-none)"));
}

function applyDynamicNoteStyles(root = document) {
    root.querySelectorAll(".tag-badge[data-color], .speaker-badge[data-color]").forEach((badge) => {
        badge.style.backgroundColor = badge.dataset.color;
    });
    root.querySelectorAll(".transcript-progress-bar[data-progress]").forEach((bar) => {
        const value = Number(bar.dataset.progress) || 0;
        bar.style.width = `${value}%`;
        bar.setAttribute("aria-valuenow", String(value));
    });
}

let currentPage = 1;
let pollTimer = null;

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

function schedulePolling(shouldPoll) {
    if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
    }
    if (shouldPoll) {
        pollTimer = setTimeout(() => {
            if (hasOpenRichNotesEdit()) {
                schedulePolling(true);
                return;
            }
            fetchAndRenderNotes(currentPage);
        }, 10000);
    }
}

async function fetchAndRenderNotes(page = 1) {
    const filters = getCurrentFilters();
    const params = new URLSearchParams();
    if (filters.q) params.set("q", filters.q);
    if (filters.date_from) params.set("date_from", filters.date_from);
    if (filters.date_to) params.set("date_to", filters.date_to);
    if (filters.time_from) params.set("time_from", filters.time_from);
    if (filters.time_to) params.set("time_to", filters.time_to);
    if (filters.tags) params.set("tags", filters.tags);
    if (filters.subjects) params.set("subjects", filters.subjects);
    params.set("page", String(page));

    const response = await fetch(`/api/notes?${params.toString()}`);
    if (!response.ok) {
        return;
    }
    const data = await response.json();
    currentPage = data.page;
    const playbackSnapshots = snapshotPlayback();
    const openCollapseIds = snapshotOpenCollapses();
    const richNotesEditSnapshots = snapshotRichNotesEdits();
    const listEl = document.getElementById("recordings-list");
    listEl.innerHTML = data.html;
    renderMathFields(listEl);
    bindAudioSync();
    applyDynamicNoteStyles(document.getElementById("recordings-list"));
    restorePlayback(playbackSnapshots);
    restoreOpenCollapses(openCollapseIds);
    restoreRichNotesEdits(richNotesEditSnapshots);
    schedulePolling(data.has_active_transcription);
}

const debouncedSearch = debounce(() => fetchAndRenderNotes(1), 300);
document.getElementById("search-input").addEventListener("input", debouncedSearch);

["date-from-input", "date-to-input", "time-from-input", "time-to-input"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => fetchAndRenderNotes(1));
});

document.getElementById("clear-filters-btn").addEventListener("click", () => {
    document.getElementById("search-input").value = "";
    document.getElementById("date-from-input").value = "";
    document.getElementById("date-to-input").value = "";
    document.getElementById("time-from-input").value = "";
    document.getElementById("time-to-input").value = "";
    selectedFilterTagIds.clear();
    renderFilterTagTree();
    updateTagFilterCount();
    selectedFilterSubjects.clear();
    renderFilterSubjectList();
    updateSubjectFilterCount();
    fetchAndRenderNotes(1);
});

bindAudioSync();
applyDynamicNoteStyles(document.getElementById("recordings-list"));
renderMathFields(document.getElementById("recordings-list"));
schedulePolling(document.body.dataset.hasActiveTranscription === "true");

// --- Tag management ---

let allTags = [];
let selectedFilterTagIds = new Set();
let activeNoteTagsId = null;
let allSubjects = [];
let selectedFilterSubjects = new Set();

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

function flattenWithDepth(nodes, depth = 0, out = []) {
    nodes.forEach((node) => {
        out.push({ id: node.id, name: node.name, depth });
        flattenWithDepth(node.children, depth + 1, out);
    });
    return out;
}

function renderCheckboxNodes(nodes, checkedIds, cssPrefix) {
    return nodes.map((node) => `
        <li>
            <label class="d-flex align-items-center gap-2">
                <input type="checkbox" class="${cssPrefix}-checkbox" value="${node.id}"
                    ${checkedIds.has(node.id) ? "checked" : ""}>
                <span class="tag-badge" style="background-color:${node.color}">${escapeHtml(node.name)}</span>
            </label>
            ${node.children.length ? `<ul class="tag-children">${renderCheckboxNodes(node.children, checkedIds, cssPrefix)}</ul>` : ""}
        </li>
    `).join("");
}

function renderManageNodes(nodes) {
    return nodes.map((node) => `
        <li data-tag-id="${node.id}">
            <div class="tag-row-display" data-tag-id="${node.id}">
                <span class="tag-badge" style="background-color:${node.color}">${escapeHtml(node.name)}</span>
                <button type="button" class="btn btn-link btn-sm p-0 tag-add-child-btn" data-tag-id="${node.id}">+ subtag</button>
                <button type="button" class="btn btn-link btn-sm p-0 tag-edit-btn" data-tag-id="${node.id}">Edit</button>
                <button type="button" class="btn btn-link btn-sm p-0 text-danger tag-delete-btn" data-tag-id="${node.id}">Delete</button>
            </div>
            <div class="tag-row-edit d-none" data-tag-id="${node.id}">
                <input type="text" class="form-control form-control-sm tag-edit-name" style="width:140px" value="${escapeHtml(node.name)}">
                <input type="color" class="form-control form-control-color form-control-sm tag-edit-color" value="${node.color}">
                <button type="button" class="btn btn-sm btn-primary tag-save-btn" data-tag-id="${node.id}">Save</button>
                <button type="button" class="btn btn-sm btn-secondary tag-cancel-btn" data-tag-id="${node.id}">Cancel</button>
            </div>
            ${node.children.length ? `<ul class="tag-children">${renderManageNodes(node.children)}</ul>` : ""}
        </li>
    `).join("");
}

function renderManageTagTree() {
    const tree = buildTagTree(allTags);
    const container = document.getElementById("tag-tree-manage");
    container.innerHTML = tree.length
        ? `<ul class="tag-tree">${renderManageNodes(tree)}</ul>`
        : '<p class="text-muted small">No tags yet.</p>';
}

function renderParentOptions() {
    const select = document.getElementById("new-tag-parent");
    const previousValue = select.value;
    const flat = flattenWithDepth(buildTagTree(allTags));
    select.innerHTML = '<option value="">(top-level)</option>' +
        flat.map((tag) => `<option value="${tag.id}">${"— ".repeat(tag.depth)}${escapeHtml(tag.name)}</option>`).join("");
    select.value = previousValue;
}

function renderFilterTagTree() {
    const tree = buildTagTree(allTags);
    const container = document.getElementById("filter-tag-tree");
    container.innerHTML = tree.length
        ? `<ul class="tag-tree">${renderCheckboxNodes(tree, selectedFilterTagIds, "filter-tag")}</ul>`
        : '<p class="text-muted small mb-0">No tags yet.</p>';
}

function renderNoteTagTree(checkedIds) {
    const tree = buildTagTree(allTags);
    const container = document.getElementById("note-tag-tree");
    container.innerHTML = tree.length
        ? `<ul class="tag-tree">${renderCheckboxNodes(tree, checkedIds, "note-tag")}</ul>`
        : '<p class="text-muted small mb-0">No tags yet. Create some via Manage Tags.</p>';
}

function updateTagFilterCount() {
    const badge = document.getElementById("tag-filter-count");
    badge.textContent = String(selectedFilterTagIds.size);
    badge.classList.toggle("d-none", selectedFilterTagIds.size === 0);
}

function renderSubjectRadios() {
    const container = document.getElementById("subject-radio-group");
    const previousValue = getSelectedSubject();
    container.innerHTML = allSubjects.map((subject) => `
        <label>
            <input type="radio" name="subject" value="${escapeHtml(subject.name)}" required>
            ${escapeHtml(subject.name)} &nbsp; &nbsp;
        </label>
    `).join("");
    const toReselect = container.querySelector(`input[value="${CSS.escape(previousValue)}"]`);
    if (toReselect) {
        toReselect.checked = true;
    }
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

function updateSubjectFilterCount() {
    const badge = document.getElementById("subject-filter-count");
    badge.textContent = String(selectedFilterSubjects.size);
    badge.classList.toggle("d-none", selectedFilterSubjects.size === 0);
}

function renderSubjectManageList() {
    const list = document.getElementById("subject-list-manage");
    list.innerHTML = allSubjects.length
        ? allSubjects.map((subject) => `
            <li class="list-group-item d-flex justify-content-between align-items-center">
                ${escapeHtml(subject.name)}
                <button type="button" class="btn btn-link btn-sm text-danger subject-delete-btn"
                    data-subject-id="${subject.id}">Delete</button>
            </li>
        `).join("")
        : '<li class="list-group-item text-muted small">No subjects yet.</li>';
}

async function loadSubjects() {
    const response = await fetch("/api/subjects");
    if (!response.ok) {
        return;
    }
    const data = await response.json();
    allSubjects = data.subjects;
    renderSubjectRadios();
    renderSubjectManageList();
    renderFilterSubjectList();
}

document.getElementById("manage-subjects-modal").addEventListener("click", async (event) => {
    const deleteBtn = event.target.closest(".subject-delete-btn");
    const addBtn = event.target.closest("#add-subject-btn");
    const errorBox = document.getElementById("subject-manage-error");

    if (deleteBtn) {
        const subjectId = deleteBtn.dataset.subjectId;
        if (!confirm("Delete this subject?")) {
            return;
        }
        await fetch(`/api/subjects/${subjectId}/delete`, { method: "POST" });
        await loadSubjects();
        return;
    }

    if (addBtn) {
        const name = document.getElementById("new-subject-name").value.trim();
        errorBox.classList.add("d-none");
        try {
            const response = await fetch("/api/subjects", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not create subject.");
            }
            document.getElementById("new-subject-name").value = "";
            await loadSubjects();
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.classList.remove("d-none");
        }
        return;
    }
});

async function loadTags() {
    const response = await fetch("/api/tags");
    if (!response.ok) {
        return;
    }
    const data = await response.json();
    allTags = data.tags;
    renderManageTagTree();
    renderParentOptions();
    renderFilterTagTree();
}

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
    fetchAndRenderNotes(1);
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
    fetchAndRenderNotes(1);
});

document.getElementById("manage-tags-modal").addEventListener("click", async (event) => {
    const addChildBtn = event.target.closest(".tag-add-child-btn");
    const editBtn = event.target.closest(".tag-edit-btn");
    const cancelBtn = event.target.closest(".tag-cancel-btn");
    const saveBtn = event.target.closest(".tag-save-btn");
    const deleteBtn = event.target.closest(".tag-delete-btn");
    const addBtn = event.target.closest("#add-tag-btn");
    const errorBox = document.getElementById("tag-manage-error");

    if (addChildBtn) {
        document.getElementById("new-tag-parent").value = addChildBtn.dataset.tagId;
        document.getElementById("new-tag-name").focus();
        return;
    }

    if (editBtn) {
        const tagId = editBtn.dataset.tagId;
        document.querySelector(`.tag-row-display[data-tag-id="${tagId}"]`).classList.add("d-none");
        document.querySelector(`.tag-row-edit[data-tag-id="${tagId}"]`).classList.remove("d-none");
        return;
    }

    if (cancelBtn) {
        const tagId = cancelBtn.dataset.tagId;
        document.querySelector(`.tag-row-edit[data-tag-id="${tagId}"]`).classList.add("d-none");
        document.querySelector(`.tag-row-display[data-tag-id="${tagId}"]`).classList.remove("d-none");
        return;
    }

    if (saveBtn) {
        const tagId = saveBtn.dataset.tagId;
        const row = document.querySelector(`.tag-row-edit[data-tag-id="${tagId}"]`);
        const name = row.querySelector(".tag-edit-name").value.trim();
        const color = row.querySelector(".tag-edit-color").value;
        errorBox.classList.add("d-none");
        try {
            const response = await fetch(`/api/tags/${tagId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, color })
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not save tag.");
            }
            await loadTags();
            fetchAndRenderNotes(currentPage);
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.classList.remove("d-none");
        }
        return;
    }

    if (deleteBtn) {
        const tagId = deleteBtn.dataset.tagId;
        if (!confirm("Delete this tag and all of its subtags?")) {
            return;
        }
        await fetch(`/api/tags/${tagId}/delete`, { method: "POST" });
        await loadTags();
        fetchAndRenderNotes(currentPage);
        return;
    }

    if (addBtn) {
        const name = document.getElementById("new-tag-name").value.trim();
        const color = document.getElementById("new-tag-color").value;
        const parentValue = document.getElementById("new-tag-parent").value;
        errorBox.classList.add("d-none");
        try {
            const response = await fetch("/api/tags", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, color, parent_id: parentValue || null })
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not create tag.");
            }
            document.getElementById("new-tag-name").value = "";
            document.getElementById("new-tag-parent").value = "";
            await loadTags();
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.classList.remove("d-none");
        }
    }
});

document.getElementById("save-note-tags-btn").addEventListener("click", async () => {
    const checkboxes = document.querySelectorAll("#note-tag-tree .note-tag-checkbox:checked");
    const tagIds = Array.from(checkboxes).map((checkbox) => Number(checkbox.value));
    const errorBox = document.getElementById("note-tags-error");
    errorBox.classList.add("d-none");
    try {
        const response = await fetch(`/notes/${activeNoteTagsId}/tags`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tag_ids: tagIds })
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || "Could not save tags.");
        }
        bootstrap.Modal.getOrCreateInstance(document.getElementById("note-tags-modal")).hide();
        fetchAndRenderNotes(currentPage);
    } catch (error) {
        errorBox.textContent = error.message;
        errorBox.classList.remove("d-none");
    }
});

loadTags();
loadSubjects().then(restoreActiveRecordingIfNeeded);

document.addEventListener('DOMContentLoaded', () => {
    const mathModalEl = document.getElementById('math-editor-modal');
    if (!mathModalEl) return;

    const latexInput = document.getElementById('math-editor-latex');
    const insertBtn = document.getElementById('insert-math-btn');
    if (!initModalMathField()) {
        document.querySelectorAll('.rich-math-btn').forEach((button) => {
            button.disabled = true;
            button.title = "MathQuill could not be loaded.";
        });
        return;
    }

    mathModalEl.addEventListener('shown.bs.modal', () => {
        setTimeout(() => {
            modalMathField.focus();
            modalMathField.reflow();
        }, 100);
    });

    latexInput.addEventListener('input', syncModalFieldFromLatexInput);

    insertBtn.addEventListener('click', () => {
        const latex = modalMathField.latex().trim();
        if (editingMathSpan) {
            const editor = editingMathSpan.closest('.rich-notes-surface');
            if (latex) {
                editingMathSpan.dataset.latex = latex;
                renderMathFields(editingMathSpan.parentElement);
            } else {
                editingMathSpan.remove();
            }
            if (editor) editor.dispatchEvent(new Event("input", { bubbles: true }));
        } else if (activeMathEditor && latex) {
            const id = `math-${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const html = `<span id="${id}" class="math-field" data-latex="${escapeHtml(latex)}" contenteditable="false"></span>`;
            insertHtmlAtCursor(activeMathEditor, html + '&nbsp;');
            renderMathFields(activeMathEditor);
        }
        bootstrap.Modal.getInstance(mathModalEl).hide();
        editingMathSpan = null;
        activeMathEditor = null;
    });
});
