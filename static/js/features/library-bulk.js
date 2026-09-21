/* Step 9: library bulk-ops module (ported from notes-list-bulk.js). Shares
 * selection state with library-list.js via imports; tag trees via ui/tree.js.
 */
import { escapeHtml } from '../utils.js';
import { buildTagTree, renderRadioTree } from '../ui/tree.js';
import { confirmDialog } from '../ui/dialog.js';
import { toast } from '../ui/toast.js';
import {
    fetchAndRenderNotes,
    selectedNoteIds,
    currentPage,
} from './library-list.js';
import { allSubjects, allTags } from './library-taxonomy.js';

async function postBulkAction(action, payload) {
    const response = await fetch(`/api/notes/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Operation failed.");
    }
    return response.json();
}

export function openBulkSubjectModal() {
    const select = document.getElementById("bulk-subject-select");
    select.innerHTML = allSubjects
        .map((subject) =>
            `<option value="${escapeHtml(subject.name)}">${escapeHtml(subject.name)}</option>`
        )
        .join("");
    document.getElementById("bulk-subject-error").classList.add("d-none");
    bootstrap.Modal.getOrCreateInstance(document.getElementById("bulk-subject-modal")).show();
}

function renderBulkTagTree() {
    const tree = buildTagTree(allTags);
    const container = document.getElementById("bulk-tag-tree");
    container.innerHTML = tree.length
        ? `<ul class="tag-tree">${renderRadioTree(tree)}</ul>`
        : '<p class="text-muted small mb-0">No tags yet. Create some via Manage Tags.</p>';
}

export function openBulkAddTagModal() {
    renderBulkTagTree();
    document.getElementById("bulk-add-tag-error").classList.add("d-none");
    bootstrap.Modal.getOrCreateInstance(document.getElementById("bulk-add-tag-modal")).show();
}

export async function bulkDeleteNotes() {
    const count = selectedNoteIds.size;
    if (count === 0) {
        return;
    }
    if (!await confirmDialog({
        title: "Delete recordings",
        body: `Delete ${count} recording${count === 1 ? "" : "s"}?`,
        confirmText: "Delete",
        danger: true,
    })) {
        return;
    }
    try {
        await postBulkAction("bulk_delete", { note_ids: Array.from(selectedNoteIds) });
        selectedNoteIds.clear();
        await fetchAndRenderNotes(currentPage);
    } catch (error) {
        toast.error(error.message);
    }
}

export async function exportSelectedNotes() {
    if (selectedNoteIds.size === 0) {
        return;
    }
    try {
        const response = await fetch("/api/notes/bulk_export", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ note_ids: Array.from(selectedNoteIds) }),
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || "Could not export recordings.");
        }
        const blob = await response.blob();
        const disposition = response.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename="?([^"]+)"?/);
        const filename = match ? match[1] : "notes_export.zip";
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
    } catch (error) {
        toast.error(error.message);
    }
}

document.getElementById("save-bulk-subject-btn").addEventListener("click", async () => {
    const subject = document.getElementById("bulk-subject-select").value;
    const errorBox = document.getElementById("bulk-subject-error");
    const saveButton = document.getElementById("save-bulk-subject-btn");
    errorBox.classList.add("d-none");
    saveButton.disabled = true;
    try {
        await postBulkAction("bulk_subject", {
            note_ids: Array.from(selectedNoteIds),
            subject,
        });
        bootstrap.Modal.getInstance(document.getElementById("bulk-subject-modal")).hide();
        await fetchAndRenderNotes(currentPage);
    } catch (error) {
        errorBox.textContent = error.message;
        errorBox.classList.remove("d-none");
    } finally {
        saveButton.disabled = false;
    }
});

document.getElementById("save-bulk-add-tag-btn").addEventListener("click", async () => {
    const checked = document.querySelector("#bulk-tag-tree .bulk-tag-radio:checked");
    const errorBox = document.getElementById("bulk-add-tag-error");
    const saveButton = document.getElementById("save-bulk-add-tag-btn");
    errorBox.classList.add("d-none");
    if (!checked) {
        errorBox.textContent = "Choose a tag to add.";
        errorBox.classList.remove("d-none");
        return;
    }
    saveButton.disabled = true;
    try {
        await postBulkAction("bulk_add_tag", {
            note_ids: Array.from(selectedNoteIds),
            tag_id: Number(checked.value),
        });
        bootstrap.Modal.getInstance(document.getElementById("bulk-add-tag-modal")).hide();
        await fetchAndRenderNotes(currentPage);
    } catch (error) {
        errorBox.textContent = error.message;
        errorBox.classList.remove("d-none");
    } finally {
        saveButton.disabled = false;
    }
});
