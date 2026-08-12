let mediaRecorder;
let mediaStream;
let recordingStartTime;
let activeRecordingSession = null;
let currentSegmentIndex = 0;
let nextChunkIndex = 0;
let pendingChunkUploads = [];
let isStoppingRecording = false;
let hasChunkUploadError = false;
let isRecordingPaused = false;
let pauseRequested = false;
let pausedSinceMs = 0;
let bookmarkSaveTimer = null;

const ACTIVE_RECORDING_STORAGE_KEY = "activeRecordingSession";
const RECORDING_CHUNK_INTERVAL_MS = 2000;
const BOOKMARK_SAVE_DEBOUNCE_MS = 500;

// --- Recording controls / session helpers ---

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

function setActiveNotesVisible(visible) {
    activeNotesPanel.classList.toggle("d-none", !visible);
}

function setActiveNotesHtml(html) {
    activeNotesEditor.innerHTML = html || "";
    renderMathFields(activeNotesEditor);
}

async function saveActiveRecordingNotesNow() {
    if (!activeRecordingSession) {
        return;
    }
    const notesHtml = normalizeRichNoteHtml(activeNotesEditor.innerHTML);
    activeRecordingSession.notesHtml = notesHtml;
    saveActiveRecordingSession();
    activeNotesSaveStatus.textContent = "Saving...";
    const response = await fetch(`/api/recording_sessions/${getActiveSessionKey()}/notes`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes_html: notesHtml }),
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        activeNotesSaveStatus.textContent = "Save failed";
        throw new Error(data.error || "Could not save notes.");
    }
    const data = await response.json();
    activeRecordingSession.notesHtml = data.notes_html || "";
    saveActiveRecordingSession();
    activeNotesSaveStatus.textContent = "Saved";
}

const debouncedSaveActiveRecordingNotes = debounce(() => {
    saveActiveRecordingNotesNow().catch(() => { });
}, 600);

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
    setActiveNotesVisible(false);
    setActiveNotesHtml("");
    activeNotesSaveStatus.textContent = "";
    isRecordingPaused = false;
    pauseRequested = false;
    pausedSinceMs = 0;
    if (bookmarkSaveTimer) {
        clearTimeout(bookmarkSaveTimer);
        bookmarkSaveTimer = null;
    }
    if (recordingBookmarksBox) {
        recordingBookmarksBox.classList.add("d-none");
        recordingBookmarksBox.innerHTML = "";
    }
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
    pauseButton.disabled = !isRecording;
    markButton.disabled = !isRecording;
    if (!isRecording) {
        isRecordingPaused = false;
        pauseRequested = false;
        pausedSinceMs = 0;
        updatePauseButtonUI();
    }
}

function updatePauseButtonUI() {
    pauseButton.textContent = isRecordingPaused ? "Resume" : "Pause";
    pauseButton.classList.toggle("btn-warning", !isRecordingPaused);
    pauseButton.classList.toggle("btn-success", isRecordingPaused);
}

function getSessionStartBaseMs() {
    if (activeRecordingSession && activeRecordingSession.startBaseMs) {
        return activeRecordingSession.startBaseMs;
    }
    return recordingStartTime ? recordingStartTime.getTime() : Date.now();
}

function getRecordedElapsedMs() {
    const baseMs = getSessionStartBaseMs();
    let elapsed = Date.now() - baseMs;
    const pausedTotalMs = (activeRecordingSession && activeRecordingSession.pausedTotalMs) || 0;
    if (pausedSinceMs > 0) {
        elapsed -= Date.now() - pausedSinceMs;
    }
    elapsed -= pausedTotalMs;
    return Math.max(0, elapsed);
}

function formatBookmarkTime(seconds) {
    const totalSeconds = Math.max(0, Math.round(seconds));
    const minutes = Math.floor(totalSeconds / 60);
    const remainingSeconds = totalSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}

function getActiveSessionBookmarks() {
    if (!activeRecordingSession) {
        return [];
    }
    if (!Array.isArray(activeRecordingSession.bookmarks)) {
        activeRecordingSession.bookmarks = [];
    }
    return activeRecordingSession.bookmarks;
}

function renderActiveRecordingBookmarks() {
    if (!recordingBookmarksBox) {
        return;
    }
    const bookmarks = getActiveSessionBookmarks();
    if (!bookmarks.length) {
        recordingBookmarksBox.classList.add("d-none");
        recordingBookmarksBox.innerHTML = "";
        return;
    }
    recordingBookmarksBox.classList.remove("d-none");
    recordingBookmarksBox.innerHTML =
        '<span class="small text-muted me-1">Bookmarks:</span>' +
        bookmarks
            .map(
                (bookmark) =>
                    `<span class="bookmark-chip recording-bookmark-chip">${formatBookmarkTime(bookmark.t)}</span>`
            )
            .join("");
}

function addBookmark() {
    if (!activeRecordingSession || !mediaRecorder || mediaRecorder.state !== "recording") {
        return;
    }
    const bookmarks = getActiveSessionBookmarks();
    const timeSeconds = getRecordedElapsedMs() / 1000;
    bookmarks.push({ t: timeSeconds });
    bookmarks.sort((a, b) => a.t - b.t);
    saveActiveRecordingSession();
    renderActiveRecordingBookmarks();
    setStatus(`Recording... Bookmark ${bookmarks.length} dropped at ${formatBookmarkTime(timeSeconds)}.`);
    scheduleBookmarkSave();
}

function scheduleBookmarkSave() {
    if (bookmarkSaveTimer) {
        clearTimeout(bookmarkSaveTimer);
    }
    bookmarkSaveTimer = setTimeout(() => {
        bookmarkSaveTimer = null;
        saveBookmarksToServerNow().catch(() => { });
    }, BOOKMARK_SAVE_DEBOUNCE_MS);
}

async function saveBookmarksToServerNow() {
    if (!activeRecordingSession) {
        return;
    }
    const response = await fetch(`/api/recording_sessions/${getActiveSessionKey()}/bookmarks`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bookmarks: getActiveSessionBookmarks() }),
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Could not save bookmarks.");
    }
}

function stopMediaStream() {
    if (mediaStream) {
        mediaStream.getTracks().forEach((track) => track.stop());
        mediaStream = null;
    }
}

function pauseRecording() {
    if (!mediaRecorder || mediaRecorder.state !== "recording" || pauseRequested || isStoppingRecording) {
        return;
    }
    // Flush the current buffer so the partial chunk closes out the current
    // segment; the dataavailable handler then starts a fresh segment (like
    // a reload recovery does) and pauses the recorder. This keeps the
    // resumed audio in its own WebM segment that ffmpeg can concatenate.
    pauseRequested = true;
    setStatus("Pausing...");
    mediaRecorder.requestData();
}

function resumeRecording() {
    if (!mediaRecorder || mediaRecorder.state !== "paused" || isStoppingRecording) {
        return;
    }
    if (pausedSinceMs > 0 && activeRecordingSession) {
        activeRecordingSession.pausedTotalMs =
            (activeRecordingSession.pausedTotalMs || 0) + (Date.now() - pausedSinceMs);
        saveActiveRecordingSession();
    }
    pausedSinceMs = 0;
    isRecordingPaused = false;
    mediaRecorder.resume();
    updatePauseButtonUI();
    setStatus("Recording...");
}

function togglePauseRecording() {
    if (isRecordingPaused) {
        resumeRecording();
    } else {
        pauseRecording();
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
        notesHtml: data.session.notes_html || "",
        bookmarks: data.session.bookmarks_json ? JSON.parse(data.session.bookmarks_json) : [],
        startBaseMs: recordingStartTime.getTime(),
        pausedTotalMs: 0,
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
    await saveActiveRecordingNotesNow();
    await saveBookmarksToServerNow();
    const body = { end_time: getTimeString(new Date()) };
    // Wall-clock start/end includes paused stretches; the assembled media
    // only contains recorded (non-paused) audio, so report the true recorded
    // duration so the webm duration metadata stays accurate.
    const recordedSeconds = getRecordedElapsedMs() / 1000;
    if (recordedSeconds > 0) {
        body.recording_duration = Math.round(recordedSeconds);
    }
    const response = await fetch(`/api/recording_sessions/${getActiveSessionKey()}/finish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
    isRecordingPaused = false;
    pauseRequested = false;
    pausedSinceMs = 0;
    activeRecordingSession.nextSegmentIndex = currentSegmentIndex + 1;
    saveActiveRecordingSession();

    mediaRecorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0 && activeRecordingSession) {
            queueChunkUpload(event.data);
        }
        if (pauseRequested && mediaRecorder && mediaRecorder.state === "recording") {
            pauseRequested = false;
            pausedSinceMs = Date.now();
            currentSegmentIndex += 1;
            nextChunkIndex = 0;
            activeRecordingSession.nextSegmentIndex = currentSegmentIndex + 1;
            saveActiveRecordingSession();
            isRecordingPaused = true;
            mediaRecorder.pause();
            updatePauseButtonUI();
            setStatus("Paused. Click Resume to continue.");
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
    updatePauseButtonUI();
    setActiveNotesHtml(activeRecordingSession.notesHtml || "");
    setActiveNotesVisible(true);
    renderActiveRecordingBookmarks();
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

        const serverBookmarks = data.session.bookmarks_json
            ? JSON.parse(data.session.bookmarks_json)
            : [];
        const localBookmarks = Array.isArray(storedSession.bookmarks) ? storedSession.bookmarks : [];
        const mergedBookmarks = [];
        const seenTimes = new Set();
        // Prefer the newest bookmark list; dedupe by timestamp.
        [...localBookmarks, ...serverBookmarks].forEach((bookmark) => {
            if (bookmark && typeof bookmark.t === "number" && !seenTimes.has(bookmark.t)) {
                seenTimes.add(bookmark.t);
                mergedBookmarks.push(bookmark);
            }
        });
        mergedBookmarks.sort((a, b) => a.t - b.t);

        activeRecordingSession = {
            ...storedSession,
            notesHtml: data.session.notes_html || storedSession.notesHtml || "",
            bookmarks: mergedBookmarks,
        };
        recordingStartTime = new Date(activeRecordingSession.startBaseMs || Date.now());
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
