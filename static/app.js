/* Recorder controls wiring (Step 9: rich-editor delegation moved to
 * js/features/editor-shell.js; the blocking cancel confirmation now uses
 * the shared dialog bridge). Depends on recording.js globals (loaded first). */
const startForm = document.getElementById("start-recording-form");
const stopForm = document.getElementById("stop-recording-form");
const startButton = document.getElementById("start-button");
const stopButton = document.getElementById("stop-button");
const pauseButton = document.getElementById("pause-button");
const markButton = document.getElementById("mark-button");
const cancelButton = document.getElementById("cancel-button");
const statusBox = document.getElementById("recording-status");
const activeNotesPanel = document.getElementById("active-notes-panel");
const activeNotesSaveStatus = document.getElementById("active-notes-save-status");
const activeNotesEditor = document.getElementById("active-recording-notes-editor");
const recordingBookmarksBox = document.getElementById("recording-bookmarks");

function setStatus(message, isError = false) {
    statusBox.textContent = message;
    statusBox.className = isError ? "mt-3 text-danger" : "mt-3 text-muted";
}

startForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await startRecording();
});

stopForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (mediaRecorder && (mediaRecorder.state === "recording" || mediaRecorder.state === "paused")) {
        isStoppingRecording = true;
        setRecordingControls(true);
        stopButton.disabled = true;
        setStatus("Stopping recording...");
        if (mediaRecorder.state === "paused") {
            mediaRecorder.resume();
        }
        mediaRecorder.requestData();
        mediaRecorder.stop();
    } else if (activeRecordingSession) {
        stopButton.disabled = true;
        finishRecoveredSessionWithoutRecorder();
    }
});

pauseButton.addEventListener("click", () => {
    togglePauseRecording();
});

markButton.addEventListener("click", () => {
    addBookmark();
});

document.addEventListener("keydown", (event) => {
    if (event.key.toLowerCase() !== "m" || event.ctrlKey || event.metaKey || event.altKey) {
        return;
    }
    const target = event.target;
    if (target && (target.isContentEditable || target.closest("input, textarea, select"))) {
        return;
    }
    if (mediaRecorder && mediaRecorder.state === "recording" && activeRecordingSession) {
        event.preventDefault();
        addBookmark();
    }
});

cancelButton.addEventListener("click", async () => {
    if (!activeRecordingSession || !await window.nrDialog.confirm({
        title: "Cancel recording",
        body: "Cancel this recording?",
        confirmText: "Cancel recording",
        danger: true,
    })) {
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
        if (pausedSinceMs > 0) {
            activeRecordingSession.pausedTotalMs =
                (activeRecordingSession.pausedTotalMs || 0) + (Date.now() - pausedSinceMs);
            pausedSinceMs = 0;
            saveActiveRecordingSession();
        }
        event.preventDefault();
        event.returnValue = "";
    }
});

activeNotesEditor.addEventListener("input", () => {
    if (!activeRecordingSession) {
        return;
    }
    activeRecordingSession.notesHtml = normalizeRichNoteHtml(activeNotesEditor.innerHTML);
    saveActiveRecordingSession();
    activeNotesSaveStatus.textContent = "Unsaved";
    debouncedSaveActiveRecordingNotes();
});
