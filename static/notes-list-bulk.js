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

function openBulkSubjectModal() {
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
        ? `<ul class="tag-tree">${renderRadioNodes(tree)}</ul>`
        : '<p class="text-muted small mb-0">No tags yet. Create some via Manage Tags.</p>';
}

function renderRadioNodes(nodes, name = "bulk-tag-radio") {
    return nodes.map((node) => `
        <li>
            <label class="d-flex align-items-center gap-2">
                <input type="radio" class="bulk-tag-radio" name="${name}" value="${node.id}">
                <span class="tag-badge" style="background-color:${node.color}">${escapeHtml(node.name)}</span>
            </label>
            ${node.children.length ? `<ul class="tag-children">${renderRadioNodes(node.children, name)}</ul>` : ""}
        </li>
    `).join("");
}

function openBulkAddTagModal() {
    renderBulkTagTree();
    document.getElementById("bulk-add-tag-error").classList.add("d-none");
    bootstrap.Modal.getOrCreateInstance(document.getElementById("bulk-add-tag-modal")).show();
}

async function bulkDeleteNotes() {
    const count = selectedNoteIds.size;
    if (count === 0) {
        return;
    }
    if (!confirm(`Delete ${count} recording${count === 1 ? "" : "s"}?`)) {
        return;
    }
    try {
        await postBulkAction("bulk_delete", { note_ids: Array.from(selectedNoteIds) });
        selectedNoteIds.clear();
        await fetchAndRenderNotes(currentPage);
    } catch (error) {
        alert(error.message);
    }
}

async function exportSelectedNotes() {
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
        alert(error.message);
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
