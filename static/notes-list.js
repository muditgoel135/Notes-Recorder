const syncToggle = document.getElementById("sync-toggle");

let selectedNoteIds = new Set();

function updateSelectionUI() {
    const countLabel = document.getElementById("selection-count");
    const buttons = document.querySelectorAll(
        "#bulk-subject-btn, #bulk-add-tag-btn, #bulk-export-btn, #bulk-delete-btn, #clear-selection-btn"
    );
    const count = selectedNoteIds.size;
    if (countLabel) {
        countLabel.textContent =
            count === 1 ? "1 recording selected" : `${count} recordings selected`;
    }
    buttons.forEach((button) => {
        button.disabled = count === 0;
    });

    const selectPageCheckbox = document.getElementById("select-page-checkbox");
    if (!selectPageCheckbox) {
        return;
    }
    const pageCheckboxes = Array.from(
        document.querySelectorAll(".note-select-checkbox")
    );
    const pageSelected = pageCheckboxes.filter((checkbox) =>
        selectedNoteIds.has(Number(checkbox.dataset.noteId))
    ).length;
    if (pageCheckboxes.length === 0) {
        selectPageCheckbox.checked = false;
        selectPageCheckbox.indeterminate = false;
        selectPageCheckbox.disabled = true;
        return;
    }
    selectPageCheckbox.disabled = false;
    selectPageCheckbox.checked = pageSelected === pageCheckboxes.length;
    selectPageCheckbox.indeterminate = pageSelected > 0 && pageSelected < pageCheckboxes.length;
}

function restoreNoteSelection() {
    document.querySelectorAll(".note-select-checkbox").forEach((checkbox) => {
        checkbox.checked = selectedNoteIds.has(Number(checkbox.dataset.noteId));
    });
    updateSelectionUI();
}

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
        let existingMath = null;
        try {
            existingMath = MQ(el);
        } catch (error) {
            // Markup references MathQuill nodes never registered on this page;
            // treat as stale and re-render below.
            existingMath = null;
        }
        if (existingMath && existingMath.el() === el) {
            existingMath.latex(latex);
            return;
        }
        el.querySelectorAll('[mathquill-block-id], [mathquill-command-id]').forEach((node) => {
            node.removeAttribute("mathquill-block-id");
            node.removeAttribute("mathquill-command-id");
        });
        el.querySelectorAll(".mq-selectable, .mq-root-block").forEach((node) => node.remove());
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
        units: Array.from(selectedFilterUnits).join(","),
        transcription_statuses: Array.from(selectedTranscriptionStatuses).join(","),
        key_points_statuses: Array.from(selectedKeyPointsStatuses).join(","),
        empty_notes: document.getElementById("empty-notes-filter").checked,
        sort: document.getElementById("sort-select").value,
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
    if (filters.units) params.set("units", filters.units);
    if (filters.transcription_statuses) params.set("transcription_statuses", filters.transcription_statuses);
    if (filters.key_points_statuses) params.set("key_points_statuses", filters.key_points_statuses);
    if (filters.empty_notes) params.set("empty_notes", "1");
    params.set("sort", filters.sort);
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
    restoreNoteSelection();
    schedulePolling(data.has_active_transcription);
}

const debouncedSearch = debounce(() => fetchAndRenderNotes(1), 300);
document.getElementById("search-input").addEventListener("input", debouncedSearch);

["date-from-input", "date-to-input", "time-from-input", "time-to-input"].forEach((id) => {
    document.getElementById(id).addEventListener("change", () => fetchAndRenderNotes(1));
});

document.getElementById("sort-select").addEventListener("change", () => fetchAndRenderNotes(1));

document.getElementById("clear-filters-btn").addEventListener("click", () => {
    document.getElementById("search-input").value = "";
    document.getElementById("date-from-input").value = "";
    document.getElementById("date-to-input").value = "";
    document.getElementById("time-from-input").value = "";
    document.getElementById("time-to-input").value = "";
    document.getElementById("sort-select").value = "date_desc";
    selectedFilterTagIds.clear();
    renderFilterTagTree();
    updateTagFilterCount();
    selectedFilterSubjects.clear();
    selectedFilterUnits.clear();
    renderFilterSubjectList();
    updateSubjectFilterCount();
    selectedTranscriptionStatuses.clear();
    updateTranscriptionStatusFilterCount();
    syncTranscriptionStatusCheckboxes();
    selectedKeyPointsStatuses.clear();
    updateKeyPointsStatusFilterCount();
    syncKeyPointsStatusCheckboxes();
    document.getElementById("empty-notes-filter").checked = false;
    fetchAndRenderNotes(1);
});

bindAudioSync();
applyDynamicNoteStyles(document.getElementById("recordings-list"));
renderMathFields(document.getElementById("recordings-list"));
restoreNoteSelection();
schedulePolling(document.body.dataset.hasActiveTranscription === "true");
