const startForm = document.getElementById("start-recording-form");
const stopForm = document.getElementById("stop-recording-form");
const startButton = document.getElementById("start-button");
const stopButton = document.getElementById("stop-button");
const cancelButton = document.getElementById("cancel-button");
const statusBox = document.getElementById("recording-status");

let mediaRecorder;
let mediaStream;
let recordingStartTime;
let activeRecordingSession = null;
let currentSegmentIndex = 0;
let nextChunkIndex = 0;
let pendingChunkUploads = [];
let isStoppingRecording = false;
let hasChunkUploadError = false;

const ACTIVE_RECORDING_STORAGE_KEY = "activeRecordingSession";
const RECORDING_CHUNK_INTERVAL_MS = 2000;

function setStatus(message, isError = false) {
    statusBox.textContent = message;
    statusBox.className = isError ? "mt-3 text-danger" : "mt-3 text-muted";
}

function getSelectedSubject() {
    const selected = startForm.querySelector("input[name='subject']:checked");
    return selected ? selected.value : "";
}

function getTimeString(date) {
    return date.toTimeString().slice(0, 8);
}

function getSupportedMimeType() {
    const mimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
        "audio/mp4"
    ];
    return mimeTypes.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function getExtension(mimeType) {
    if (mimeType.includes("ogg")) {
        return "ogg";
    }
    if (mimeType.includes("mp4")) {
        return "mp4";
    }
    return "webm";
}

async function uploadRecording(blob, extension) {
    const endTime = new Date();
    const formData = new FormData();
    formData.append("audio", blob, `recording.${extension}`);
    formData.append("subject", getSelectedSubject());
    formData.append("start_time", getTimeString(recordingStartTime));
    formData.append("end_time", getTimeString(endTime));

    const response = await fetch(document.body.dataset.saveRecordingUrl, {
        method: "POST",
        body: formData
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Could not save recording.");
    }
}

function saveActiveRecordingSession() {
    if (activeRecordingSession) {
        localStorage.setItem(ACTIVE_RECORDING_STORAGE_KEY, JSON.stringify(activeRecordingSession));
    }
}

function clearActiveRecordingSession() {
    activeRecordingSession = null;
    localStorage.removeItem(ACTIVE_RECORDING_STORAGE_KEY);
}

function loadActiveRecordingSession() {
    const storedValue = localStorage.getItem(ACTIVE_RECORDING_STORAGE_KEY);
    if (!storedValue) {
        return null;
    }
    try {
        return JSON.parse(storedValue);
    } catch (error) {
        localStorage.removeItem(ACTIVE_RECORDING_STORAGE_KEY);
        return null;
    }
}

function setRecordingControls(isRecording) {
    startButton.disabled = isRecording;
    stopButton.disabled = !isRecording;
    cancelButton.disabled = !isRecording;
}

function stopMediaStream() {
    if (mediaStream) {
        mediaStream.getTracks().forEach((track) => track.stop());
        mediaStream = null;
    }
}

function getActiveSessionKey() {
    return activeRecordingSession ? activeRecordingSession.sessionKey : "";
}

async function createRecordingSession(mimeType, extension) {
    recordingStartTime = new Date();
    const response = await fetch("/api/recording_sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            subject: getSelectedSubject(),
            mime_type: mimeType,
            extension,
            start_time: getTimeString(recordingStartTime),
        }),
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Could not start recording session.");
    }

    const data = await response.json();
    return {
        sessionKey: data.session.session_key,
        subject: data.session.subject,
        startTime: data.session.start_time,
        mimeType: data.session.mime_type || mimeType,
        extension: data.session.extension || extension,
        nextSegmentIndex: 0,
    };
}

async function uploadRecordingChunk(blob, segmentIndex, chunkIndex) {
    const formData = new FormData();
    formData.append("audio", blob, `chunk.${activeRecordingSession.extension}`);
    formData.append("segment_index", String(segmentIndex));
    formData.append("chunk_index", String(chunkIndex));

    const response = await fetch(`/api/recording_sessions/${getActiveSessionKey()}/chunks`, {
        method: "POST",
        body: formData,
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Could not save recording chunk.");
    }
}

function queueChunkUpload(blob) {
    const segmentIndex = currentSegmentIndex;
    const chunkIndex = nextChunkIndex;
    nextChunkIndex += 1;

    const uploadPromise = uploadRecordingChunk(blob, segmentIndex, chunkIndex)
        .catch((error) => {
            hasChunkUploadError = true;
            setStatus(`${error.message} Recording is still recoverable.`, true);
            throw error;
        })
        .finally(() => {
            pendingChunkUploads = pendingChunkUploads.filter((promise) => promise !== uploadPromise);
        });
    pendingChunkUploads.push(uploadPromise);
}

async function waitForPendingChunkUploads() {
    const results = await Promise.allSettled(pendingChunkUploads);
    const failed = results.find((result) => result.status === "rejected");
    if (failed) {
        throw failed.reason;
    }
    if (hasChunkUploadError) {
        throw new Error("Some recording chunks were not saved.");
    }
}

async function finishRecordingSession() {
    const response = await fetch(`/api/recording_sessions/${getActiveSessionKey()}/finish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ end_time: getTimeString(new Date()) }),
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Could not finish recording.");
    }
}

async function finishRecoveredSessionWithoutRecorder() {
    try {
        setStatus("Saving recovered recording...");
        await finishRecordingSession();
        clearActiveRecordingSession();
        setRecordingControls(false);
        setStatus("Recovered recording saved.");
        fetchAndRenderNotes(currentPage);
    } catch (error) {
        setRecordingControls(true);
        setStatus(error.message, true);
    }
}

async function startRecorderForActiveSession(isRecovered = false) {
    if (!mediaStream) {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }
    const recorderOptions = activeRecordingSession.mimeType ? { mimeType: activeRecordingSession.mimeType } : {};
    mediaRecorder = new MediaRecorder(mediaStream, recorderOptions);
    currentSegmentIndex = Number(activeRecordingSession.nextSegmentIndex || 0);
    nextChunkIndex = 0;
    pendingChunkUploads = [];
    hasChunkUploadError = false;
    isStoppingRecording = false;
    activeRecordingSession.nextSegmentIndex = currentSegmentIndex + 1;
    saveActiveRecordingSession();

    mediaRecorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0 && activeRecordingSession) {
            queueChunkUpload(event.data);
        }
    });

    mediaRecorder.addEventListener("stop", async () => {
        stopMediaStream();
        if (!isStoppingRecording) {
            return;
        }

        try {
            setStatus("Saving recording...");
            await waitForPendingChunkUploads();
            await finishRecordingSession();
            clearActiveRecordingSession();
            setRecordingControls(false);
            setStatus("Recording saved.");
            fetchAndRenderNotes(currentPage);
        } catch (error) {
            setRecordingControls(true);
            setStatus(`${error.message} Reload recovery is still available.`, true);
        } finally {
            isStoppingRecording = false;
        }
    });

    mediaRecorder.start(RECORDING_CHUNK_INTERVAL_MS);
    setRecordingControls(true);
    setStatus(isRecovered ? "Recording resumed after reload..." : "Recording...");
}

async function startRecording() {
    if (!startForm.checkValidity()) {
        startForm.reportValidity();
        return;
    }

    if (!navigator.mediaDevices || !window.MediaRecorder) {
        setStatus("Recording is not supported in this browser.", true);
        return;
    }

    try {
        const mimeType = getSupportedMimeType();
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        activeRecordingSession = await createRecordingSession(mimeType, getExtension(mimeType));
        saveActiveRecordingSession();
        await startRecorderForActiveSession(false);
    } catch (error) {
        stopMediaStream();
        setRecordingControls(false);
        setStatus(error.message || "Microphone access was denied or unavailable.", true);
    }
}

startForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await startRecording();
});

stopForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (mediaRecorder && mediaRecorder.state === "recording") {
        isStoppingRecording = true;
        setRecordingControls(true);
        stopButton.disabled = true;
        setStatus("Stopping recording...");
        mediaRecorder.requestData();
        mediaRecorder.stop();
    } else if (activeRecordingSession) {
        stopButton.disabled = true;
        finishRecoveredSessionWithoutRecorder();
    }
});

cancelButton.addEventListener("click", async () => {
    if (!activeRecordingSession || !confirm("Cancel this recording?")) {
        return;
    }

    isStoppingRecording = false;
    if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
    }
    stopMediaStream();

    try {
        await fetch(`/api/recording_sessions/${getActiveSessionKey()}/cancel`, { method: "POST" });
    } finally {
        clearActiveRecordingSession();
        setRecordingControls(false);
        setStatus("Recording canceled.");
    }
});

window.addEventListener("beforeunload", (event) => {
    if (activeRecordingSession) {
        event.preventDefault();
        event.returnValue = "";
    }
});

async function restoreActiveRecordingIfNeeded() {
    const storedSession = loadActiveRecordingSession();
    if (!storedSession || activeRecordingSession) {
        return;
    }

    try {
        const response = await fetch(`/api/recording_sessions/${storedSession.sessionKey}`);
        if (!response.ok) {
            clearActiveRecordingSession();
            return;
        }
        const data = await response.json();
        if (data.session.status !== "active") {
            clearActiveRecordingSession();
            return;
        }

        activeRecordingSession = storedSession;
        startForm.querySelectorAll("input[name='subject']").forEach((input) => {
            input.checked = input.value === storedSession.subject;
        });
        setRecordingControls(true);
        setStatus("Restoring recording after reload...");
        await startRecorderForActiveSession(true);
    } catch (error) {
        setRecordingControls(true);
        setStatus("Recording can be resumed. Allow microphone access or cancel the session.", true);
    }
}

document.getElementById("recordings-list").addEventListener("click", async (event) => {
    const editButton = event.target.closest(".edit-note-btn");
    const cancelButton = event.target.closest(".cancel-note-btn");
    const saveButton = event.target.closest(".save-note-btn");
    const editTagsButton = event.target.closest(".edit-tags-btn");
    const editSubjectButton = event.target.closest(".edit-subject-btn");
    const cancelSubjectButton = event.target.closest(".cancel-subject-btn");
    const saveSubjectButton = event.target.closest(".save-subject-btn");
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
        pollTimer = setTimeout(() => fetchAndRenderNotes(currentPage), 10000);
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
    document.getElementById("recordings-list").innerHTML = data.html;
    bindAudioSync();
    applyDynamicNoteStyles(document.getElementById("recordings-list"));
    restorePlayback(playbackSnapshots);
    restoreOpenCollapses(openCollapseIds);
    schedulePolling(data.has_active_transcription);
}

function debounce(fn, delayMs) {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), delayMs);
    };
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
schedulePolling(document.body.dataset.hasActiveTranscription === "true");

// --- Tag management ---

let allTags = [];
let selectedFilterTagIds = new Set();
let activeNoteTagsId = null;
let allSubjects = [];
let selectedFilterSubjects = new Set();

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value);
    return div.innerHTML;
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
