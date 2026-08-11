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
    const pinButton = event.target.closest(".pin-note-btn");
    const selectAllButton = event.target.closest("#select-all-btn");
    const clearSelectionButton = event.target.closest("#clear-selection-btn");
    const bulkSubjectButton = event.target.closest("#bulk-subject-btn");
    const bulkAddTagButton = event.target.closest("#bulk-add-tag-btn");
    const bulkExportButton = event.target.closest("#bulk-export-btn");
    const bulkDeleteButton = event.target.closest("#bulk-delete-btn");

    if (selectAllButton) {
        selectAllButton.disabled = true;
        try {
            const params = new URLSearchParams();
            const filters = getCurrentFilters();
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

            const response = await fetch(`/api/notes/ids?${params.toString()}`);
            if (!response.ok) {
                throw new Error("Could not list matching recordings.");
            }
            const data = await response.json();
            (data.ids || []).forEach((id) => selectedNoteIds.add(id));
            updateSelectionUI();
        } catch (error) {
            alert(error.message);
        } finally {
            selectAllButton.disabled = false;
        }
        return;
    }

    if (clearSelectionButton) {
        selectedNoteIds.clear();
        updateSelectionUI();
        return;
    }

    if (bulkSubjectButton) {
        openBulkSubjectModal();
        return;
    }

    if (bulkAddTagButton) {
        openBulkAddTagModal();
        return;
    }

    if (bulkExportButton) {
        exportSelectedNotes();
        return;
    }

    if (bulkDeleteButton) {
        bulkDeleteNotes();
        return;
    }

    if (pinButton) {
        const noteId = pinButton.dataset.noteId;
        pinButton.disabled = true;
        try {
            const response = await fetch(`/notes/${noteId}/pin`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not update pin.");
            }
            const data = await response.json();
            fetchAndRenderNotes(data.pinned ? 1 : currentPage);
        } catch (error) {
            pinButton.disabled = false;
            alert(error.message);
        }
        return;
    }

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
        const unitInput = editRow.querySelector(".note-unit-input");
        const unit = unitInput ? unitInput.value : DEFAULT_UNIT;
        saveSubjectButton.disabled = true;
        try {
            const response = await fetch(`/notes/${noteId}/subject`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ subject, unit }),
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
document.getElementById("recordings-list").addEventListener("change", (event) => {
    const subjectInput = event.target.closest(".note-subject-input");
    if (subjectInput) {
        const editRow = subjectInput.closest(".note-subject-edit");
        const unitSelect = editRow ? editRow.querySelector(".note-unit-input") : null;
        if (unitSelect) {
            const units = (buildUnitsBySubjectName()[subjectInput.value] || []);
            unitSelect.innerHTML =
                `<option value="${escapeHtml(DEFAULT_UNIT)}">${escapeHtml(DEFAULT_UNIT)}</option>` +
                units.map((unit) =>
                    `<option value="${escapeHtml(unit)}">${escapeHtml(unit)}</option>`
                ).join("");
        }
        return;
    }

    const selectPageCheckbox = event.target.closest("#select-page-checkbox");
    if (selectPageCheckbox) {
        document.querySelectorAll(".note-select-checkbox").forEach((checkbox) => {
            const noteId = Number(checkbox.dataset.noteId);
            if (selectPageCheckbox.checked) {
                selectedNoteIds.add(noteId);
            } else {
                selectedNoteIds.delete(noteId);
            }
        });
        updateSelectionUI();
        return;
    }

    const checkbox = event.target.closest(".note-select-checkbox");
    if (!checkbox) {
        return;
    }
    const noteId = Number(checkbox.dataset.noteId);
    if (checkbox.checked) {
        selectedNoteIds.add(noteId);
    } else {
        selectedNoteIds.delete(noteId);
    }
    updateSelectionUI();
});
