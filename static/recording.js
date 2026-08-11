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
        notesHtml: data.session.notes_html || "",
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
    setActiveNotesHtml(activeRecordingSession.notesHtml || "");
    setActiveNotesVisible(true);
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

        activeRecordingSession = {
            ...storedSession,
            notesHtml: data.session.notes_html || storedSession.notesHtml || "",
        };
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
