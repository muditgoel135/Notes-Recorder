/* Step 9: library card actions (fresh slim module replacing the live subset of
 * notes-list-actions.js). Only handlers for elements the card UI renders:
 * selection, bulk entry points, pin, delete, tag editing, pagination.
 * Inline editing lives on the Step 6 detail page, so the legacy edit-form,
 * transcript and retry branches are intentionally gone. All delegation hangs
 * off #recordings-list, which always exists on the library page. */
import {
    fetchAndRenderNotes,
    selectedNoteIds,
    updateSelectionUI,
    currentPage,
    getCurrentFilters,
} from './library-list.js';
import {
    openBulkSubjectModal,
    openBulkAddTagModal,
    exportSelectedNotes,
    bulkDeleteNotes,
} from './library-bulk.js';
import { setActiveNoteTagsId, renderNoteTagTree } from './library-taxonomy.js';
import { confirmDialog } from '../ui/dialog.js';
import { toast } from '../ui/toast.js';
import { fetchJSON } from '../api.js';

document.getElementById('recordings-list').addEventListener('click', async (event) => {
    const selectAllButton = event.target.closest('#select-all-btn');
    const clearSelectionButton = event.target.closest('#clear-selection-btn');
    const bulkSubjectButton = event.target.closest('#bulk-subject-btn');
    const bulkAddTagButton = event.target.closest('#bulk-add-tag-btn');
    const bulkExportButton = event.target.closest('#bulk-export-btn');
    const bulkDeleteButton = event.target.closest('#bulk-delete-btn');
    const pinButton = event.target.closest('.pin-note-btn');
    const deleteButton = event.target.closest('.delete-note-btn');
    const editTagsButton = event.target.closest('.edit-tags-btn');
    const pageButton = event.target.closest('#prev-page-btn, #next-page-btn');

    if (selectAllButton) {
        selectAllButton.disabled = true;
        try {
            const filters = getCurrentFilters();
            const params = new URLSearchParams();
            if (filters.q) params.set('q', filters.q);
            if (filters.date_from) params.set('date_from', filters.date_from);
            if (filters.date_to) params.set('date_to', filters.date_to);
            if (filters.time_from) params.set('time_from', filters.time_from);
            if (filters.time_to) params.set('time_to', filters.time_to);
            if (filters.tags) params.set('tags', filters.tags);
            if (filters.subjects) params.set('subjects', filters.subjects);
            if (filters.units) params.set('units', filters.units);
            if (filters.transcription_statuses) params.set('transcription_statuses', filters.transcription_statuses);
            if (filters.key_points_statuses) params.set('key_points_statuses', filters.key_points_statuses);
            if (filters.empty_notes) params.set('empty_notes', '1');
            params.set('sort', filters.sort);
            const data = await fetchJSON(`/api/notes/ids?${params.toString()}`, { toastOnError: false });
            (data.ids || []).forEach((id) => selectedNoteIds.add(id));
            updateSelectionUI();
        } catch (error) {
            toast.error(error.message);
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
            const data = await fetchJSON(`/notes/${noteId}/pin`, { method: 'POST' });
            fetchAndRenderNotes(data.pinned ? 1 : currentPage);
        } catch (error) {
            pinButton.disabled = false;
        }
        return;
    }

    if (deleteButton) {
        const noteId = deleteButton.dataset.noteId;
        if (!await confirmDialog({
            title: 'Delete recording',
            body: 'Delete this recording?',
            confirmText: 'Delete',
            danger: true,
        })) {
            return;
        }
        deleteButton.disabled = true;
        try {
            await fetchJSON(`/delete/${noteId}`, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            fetchAndRenderNotes(currentPage);
        } catch (error) {
            deleteButton.disabled = false;
        }
        return;
    }

    if (editTagsButton) {
        setActiveNoteTagsId(editTagsButton.dataset.noteId);
        const checkedIds = new Set(JSON.parse(editTagsButton.dataset.tagIds || '[]'));
        renderNoteTagTree(checkedIds);
        document.getElementById('note-tags-error').classList.add('d-none');
        window.bootstrap.Modal.getOrCreateInstance(document.getElementById('note-tags-modal')).show();
        return;
    }

    if (pageButton && !pageButton.disabled) {
        fetchAndRenderNotes(Number(pageButton.dataset.page));
    }
});

document.getElementById('recordings-list').addEventListener('change', (event) => {
    const selectPageCheckbox = event.target.closest('#select-page-checkbox');
    if (selectPageCheckbox) {
        document.querySelectorAll('.note-select-checkbox').forEach((checkbox) => {
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

    const checkbox = event.target.closest('.note-select-checkbox');
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
