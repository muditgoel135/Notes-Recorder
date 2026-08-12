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

document.addEventListener("click", async (event) => {
    const commandButton = event.target.closest(".rich-command");
    const rtlButton = event.target.closest(".rich-rtl-btn");
    const linkButton = event.target.closest(".rich-link-btn");
    const tableButton = event.target.closest(".rich-table-btn");
    const tableCommandButton = event.target.closest(".rich-table-command");
    const imageButton = event.target.closest(".rich-image-btn");
    const videoButton = event.target.closest(".rich-video-btn");
    const mathButton = event.target.closest(".rich-math-btn");
    const checklistButton = event.target.closest(".rich-checklist-btn");
    const checklistBox = event.target.closest(".rich-checklist-box");
    const blockquoteButton = event.target.closest(".rich-blockquote-btn");
    const codeBlockButton = event.target.closest(".rich-code-block-btn");
    const existingMath = event.target.closest("span.math-field[data-latex]");

    if (checklistBox) {
        const item = checklistBox.closest("li[data-checked]");
        const editor = checklistBox.closest(".rich-notes-surface");
        if (item && editor && editor.isContentEditable) {
            item.dataset.checked = item.dataset.checked === "true" ? "false" : "true";
            dispatchRichEditorInput(editor);
        }
        return;
    }

    if (existingMath) {
        const editor = existingMath.closest(".rich-notes-surface");
        if (editor && editor.isContentEditable) {
            openMathEditor(editor, existingMath);
        }
        return;
    }

    if (mathButton) {
        openMathEditor(getRichEditorSurface(mathButton.closest("[data-rich-notes-editor]")));
        return;
    }

    if (rtlButton) {
        toggleRtlBlock(rtlButton.closest("[data-rich-notes-editor]"));
        return;
    }

    if (checklistButton) {
        insertChecklist(checklistButton.closest("[data-rich-notes-editor]"));
        return;
    }

    if (blockquoteButton) {
        runRichCommand(blockquoteButton.closest("[data-rich-notes-editor]"), "formatBlock", "blockquote");
        return;
    }

    if (codeBlockButton) {
        insertCodeBlock(codeBlockButton.closest("[data-rich-notes-editor]"));
        return;
    }

    if (tableCommandButton) {
        runTableCommand(
            tableCommandButton.closest("[data-rich-notes-editor]"),
            tableCommandButton.dataset.tableCommand
        );
        return;
    }

    if (commandButton) {
        runRichCommand(
            commandButton.closest("[data-rich-notes-editor]"),
            commandButton.dataset.command,
            commandButton.dataset.value || null
        );
        return;
    }

    if (linkButton) {
        const wrapper = linkButton.closest("[data-rich-notes-editor]");
        const url = prompt("Link URL:");
        if (url && url.trim()) {
            runRichCommand(wrapper, "createLink", url.trim());
        }
        return;
    }

    if (tableButton) {
        const editor = getRichEditorSurface(tableButton.closest("[data-rich-notes-editor]"));
        if (editor) {
            const rows = promptTableDimension("Rows", 3, 1, 20);
            if (rows === null) {
                return;
            }
            const columns = promptTableDimension("Columns", 3, 1, 10);
            if (columns === null) {
                return;
            }
            insertHtmlAtCursor(editor, buildTableHtml(rows, columns));
        }
        return;
    }

    if (videoButton) {
        insertVideoEmbed(videoButton.closest("[data-rich-notes-editor]"));
        return;
    }

    if (imageButton) {
        const input = imageButton.closest("[data-rich-notes-editor]").querySelector(".rich-image-input");
        input.click();
    }
});

document.addEventListener("mousedown", (event) => {
    if (event.target.closest(".rich-notes-toolbar button")) {
        event.preventDefault();
    }
});

document.addEventListener("change", async (event) => {
    const colorInput = event.target.closest(".rich-color-input");
    const imageInput = event.target.closest(".rich-image-input");
    const formatSelect = event.target.closest(".rich-format-select");
    const fontSizeSelect = event.target.closest(".rich-font-size-select");
    const fontFamilySelect = event.target.closest(".rich-font-family-select");

    if (formatSelect) {
        runRichCommand(
            formatSelect.closest("[data-rich-notes-editor]"),
            "formatBlock",
            formatSelect.value || "p"
        );
        formatSelect.value = "p";
        return;
    }

    if (fontSizeSelect) {
        if (fontSizeSelect.value) {
            applyInlineStyle(
                fontSizeSelect.closest("[data-rich-notes-editor]"),
                { fontSize: fontSizeSelect.value }
            );
        }
        fontSizeSelect.value = "";
        return;
    }

    if (fontFamilySelect) {
        if (fontFamilySelect.value) {
            applyInlineStyle(
                fontFamilySelect.closest("[data-rich-notes-editor]"),
                { fontFamily: fontFamilySelect.value }
            );
        }
        fontFamilySelect.value = "";
        return;
    }

    if (colorInput) {
        runRichCommand(
            colorInput.closest("[data-rich-notes-editor]"),
            colorInput.dataset.command,
            colorInput.value
        );
        return;
    }

    if (imageInput && imageInput.files.length) {
        const wrapper = imageInput.closest("[data-rich-notes-editor]");
        const editor = getRichEditorSurface(wrapper);
        try {
            const data = await uploadRichNoteImage(imageInput.files[0]);
            insertHtmlAtCursor(editor, `<img src="${data.url}" alt="">`);
        } catch (error) {
            alert(error.message);
        } finally {
            imageInput.value = "";
        }
    }
});
