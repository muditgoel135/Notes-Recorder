/* Step 9: library listing module (ported from notes-list.js with identical
 * behavior). Owns selection state, filter collection, full list renders and
 * the lightweight status poller. Cross-file sharing is via imports; the only
 * classic global used is renderMathFields from rich-editor.js (loaded first).
 * Math rendering now lives in rich-editor.js; badge/progress styling in utils.
 */
import { debounce, applyDynamicNoteStyles } from '../utils.js';
import { fetchJSON } from '../api.js';
import {
    selectedFilterTagIds,
    selectedFilterSubjects,
    selectedFilterUnits,
    selectedTranscriptionStatuses,
    selectedKeyPointsStatuses,
    renderFilterTagTree,
    updateTagFilterCount,
    renderFilterSubjectList,
    updateSubjectFilterCount,
    syncTranscriptionStatusCheckboxes,
    updateTranscriptionStatusFilterCount,
    syncKeyPointsStatusCheckboxes,
    updateKeyPointsStatusFilterCount,
} from './library-taxonomy.js';

export let currentPage = 1;
export let selectedNoteIds = new Set();

const syncToggle = document.getElementById("sync-toggle");

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

if (syncToggle) {
    syncToggle.checked = isSyncEnabled();
    applySyncEnabled(syncToggle.checked);

    syncToggle.addEventListener("change", () => {
        localStorage.setItem("syncTranscriptEnabled", String(syncToggle.checked));
        applySyncEnabled(syncToggle.checked);
    });
}

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
        if (window.bootstrap && window.bootstrap.Collapse) {
            window.bootstrap.Collapse.getOrCreateInstance(el).show();
        } else {
            el.classList.add("show");
        }
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

let statusPollTimer = null;
const knownTranscriptionStates = new Map();
const STATUS_POLL_INTERVAL_MS = 5000;

function statusPillClass(status) {
    if (status === "completed") {
        return "bg-success";
    }
    if (status === "failed") {
        return "bg-danger";
    }
    if (status === "processing") {
        return "bg-info";
    }
    return "bg-secondary";
}

function setPillClass(pill, status) {
    pill.classList.remove("bg-success", "bg-danger", "bg-info", "bg-secondary");
    pill.classList.add(statusPillClass(status));
}

/** Patch a card's pills + progress bar in place (no re-render, no playback loss). */
function patchCard(article, state) {
    const tPill = article.querySelector("[data-tstatus-pill]");
    if (tPill) {
        tPill.textContent = state.transcription_status;
        setPillClass(tPill, state.transcription_status);
    }
    const kPill = article.querySelector("[data-kstatus-pill]");
    if (kPill) {
        kPill.textContent = `key points: ${state.key_points_status}`;
        setPillClass(kPill, state.key_points_status);
    }
    const bar = article.querySelector(".transcript-progress-bar[data-progress]");
    if (bar) {
        const value = Number(state.transcription_progress) || 0;
        bar.dataset.progress = String(value);
        bar.style.width = `${value}%`;
        bar.setAttribute("aria-valuenow", String(value));
    }
}

function visibleCardIds() {
    return Array.from(
        document.querySelectorAll("#recordings-list .note-card[data-note-id]")
    )
        .map((el) => Number(el.dataset.noteId))
        .filter((id) => Number.isFinite(id));
}

function rebuildKnownStates() {
    knownTranscriptionStates.clear();
    document
        .querySelectorAll("#recordings-list .note-card[data-note-id]")
        .forEach((el) => {
            const pill = el.querySelector("[data-tstatus-pill]");
            if (pill) {
                knownTranscriptionStates.set(Number(el.dataset.noteId), pill.textContent.trim());
            }
        });
}

function anyActiveCards() {
    return Array.from(knownTranscriptionStates.values()).some(
        (status) => status === "pending" || status === "processing"
    );
}

function updateWorkerDot(active) {
    const dot = document.getElementById("worker-status-dot");
    if (!dot) {
        return;
    }
    dot.classList.toggle("active", Boolean(active));
    dot.title = active ? "Transcription in progress" : "Background worker idle";
    dot.setAttribute("aria-label", active ? "Background worker active" : "Background worker idle");
}

/** Swap one card for a fresh server render (e.g. transcription completed). */
async function swapCardForStatus(article, noteId) {
    let resumeAt = null;
    const audio = article.querySelector("audio[data-note-id]");
    if (audio && !audio.paused) {
        resumeAt = audio.currentTime;
    }
    const data = await fetchJSON(`/api/notes/card?id=${noteId}`, {
        toastOnError: false,
    });
    const template = document.createElement("template");
    template.innerHTML = (data.html || "").trim();
    const replacement = template.content.querySelector(".note-card");
    if (!replacement) {
        return;
    }
    article.replaceWith(replacement);
    applyDynamicNoteStyles(replacement);
    if (resumeAt !== null) {
        const fresh = replacement.querySelector("audio[data-note-id]");
        if (fresh) {
            fresh.currentTime = resumeAt;
            const playPromise = fresh.play();
            if (playPromise && playPromise.catch) {
                playPromise.catch(() => {});
            }
        }
    }
    restoreNoteSelection();
}

async function pollNoteStatus() {
    if (document.hidden) {
        return;
    }
    if (document.querySelector(".note-rich-notes-edit:not(.d-none)")) {
        return;
    }
    const ids = visibleCardIds();
    if (!ids.length) {
        stopStatusPolling();
        return;
    }
    let data;
    try {
        data = await fetchJSON(`/api/notes/status?ids=${ids.join(",")}`, {
            toastOnError: false,
        });
    } catch (error) {
        return; // silent: retry on the next tick, never toast-spam.
    }
    updateWorkerDot(data.has_active_transcription);
    for (const state of data.notes || []) {
        const article = document.querySelector(
            `#recordings-list .note-card[data-note-id="${state.id}"]`
        );
        if (!article) {
            continue;
        }
        const prev = knownTranscriptionStates.get(Number(state.id));
        if (prev !== undefined && prev !== state.transcription_status) {
            try {
                await swapCardForStatus(article, state.id);
            } catch (error) {
                patchCard(article, state);
            }
        } else {
            patchCard(article, state);
        }
        const current = document.querySelector(
            `#recordings-list .note-card[data-note-id="${state.id}"] [data-tstatus-pill]`
        );
        knownTranscriptionStates.set(
            Number(state.id),
            current ? current.textContent.trim() : state.transcription_status
        );
    }
    if (!data.has_active_transcription && !anyActiveCards()) {
        stopStatusPolling();
    }
}

function startStatusPolling() {
    stopStatusPolling();
    statusPollTimer = setInterval(pollNoteStatus, STATUS_POLL_INTERVAL_MS);
}

function stopStatusPolling() {
    if (statusPollTimer) {
        clearInterval(statusPollTimer);
        statusPollTimer = null;
    }
}

function updateStatusPolling(serverSaysActive) {
    if (serverSaysActive || anyActiveCards()) {
        startStatusPolling();
    } else {
        stopStatusPolling();
    }
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
        units: Array.from(selectedFilterUnits).join(","),
        transcription_statuses: Array.from(selectedTranscriptionStatuses).join(","),
        key_points_statuses: Array.from(selectedKeyPointsStatuses).join(","),
        empty_notes: document.getElementById("empty-notes-filter").checked,
        sort: document.getElementById("sort-select").value,
    };
}

function schedulePolling(shouldPoll) {
    // Legacy name kept for compatibility; the 10s full-HTML poll is gone
    // (Step 5). Delegates to the lightweight status poller.
    updateStatusPolling(shouldPoll);
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

    let data;
    try {
        data = await fetchJSON(`/api/notes?${params.toString()}`);
    } catch (error) {
        return; // fetchJSON already toasted the failure.
    }
    currentPage = data.page;
    const playbackSnapshots = snapshotPlayback();
    const openCollapseIds = snapshotOpenCollapses();
    const richNotesEditSnapshots = snapshotRichNotesEdits();
    const listEl = document.getElementById("recordings-list");
    listEl.innerHTML = data.html;
    bindAudioSync();
    applyDynamicNoteStyles(document.getElementById("recordings-list"));
    restorePlayback(playbackSnapshots);
    restoreOpenCollapses(openCollapseIds);
    restoreRichNotesEdits(richNotesEditSnapshots);
    restoreNoteSelection();
    rebuildKnownStates();
    updateStatusPolling(data.has_active_transcription);
}

/* Page wiring runs only via initLibraryList() (called by pages/library.js)
 * so importing this module on other pages has no side effects. */
export function initLibraryList() {
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
    restoreNoteSelection();
    rebuildKnownStates();
    updateWorkerDot(document.body.dataset.hasActiveTranscription === "true");
    updateStatusPolling(document.body.dataset.hasActiveTranscription === "true");
}

export { fetchAndRenderNotes, updateSelectionUI, restoreNoteSelection, getCurrentFilters, pollNoteStatus, rebuildKnownStates, statusPillClass };
