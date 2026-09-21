/* Step 9: library taxonomy module (ported from notes-list-tags.js). Owns tag /
 * subject / unit filter state, filter trees, the manage modals and the
 * recorder subject radios. Tree rendering comes from ui/tree.js; deletes
 * confirm via ui/dialog.js. Pages drive loading explicitly (no work at
 * import beyond wiring present elements).
 */
import { escapeHtml } from '../utils.js';
import {
    buildTagTree,
    flattenWithDepth,
    renderCheckboxTree as renderCheckboxNodes,
} from '../ui/tree.js';
import { confirmDialog } from '../ui/dialog.js';
import {
    fetchAndRenderNotes,
    currentPage,
    selectedNoteIds,
    updateSelectionUI,
} from './library-list.js';

export let allTags = [];
export let selectedFilterTagIds = new Set();
let activeNoteTagsId = null;
export let allSubjects = [];
export let allUnits = [];
export let selectedFilterSubjects = new Set();
export let selectedFilterUnits = new Set();
export let selectedTranscriptionStatuses = new Set();
export let selectedKeyPointsStatuses = new Set();

export function setActiveNoteTagsId(id) {
    activeNoteTagsId = id;
}

export const DEFAULT_UNIT = "General";

function buildUnitsBySubjectName() {
    const map = {};
    allSubjects.forEach((subject) => {
        map[subject.name] = allUnits
            .filter((unit) => unit.subject_id === subject.id)
            .map((unit) => unit.name)
            .sort((a, b) => a.localeCompare(b));
    });
    return map;
}

export function updateTranscriptionStatusFilterCount() {
    const badge = document.getElementById("transcription-status-filter-count");
    if (!badge) {
        return;
    }
    badge.textContent = String(selectedTranscriptionStatuses.size);
    badge.classList.toggle("d-none", selectedTranscriptionStatuses.size === 0);
}

export function updateKeyPointsStatusFilterCount() {
    const badge = document.getElementById("key-points-status-filter-count");
    if (!badge) {
        return;
    }
    badge.textContent = String(selectedKeyPointsStatuses.size);
    badge.classList.toggle("d-none", selectedKeyPointsStatuses.size === 0);
}

export function syncTranscriptionStatusCheckboxes() {
    document.querySelectorAll(".transcription-status-checkbox").forEach((checkbox) => {
        checkbox.checked = selectedTranscriptionStatuses.has(checkbox.value);
    });
}

export function syncKeyPointsStatusCheckboxes() {
    document.querySelectorAll(".key-points-status-checkbox").forEach((checkbox) => {
        checkbox.checked = selectedKeyPointsStatuses.has(checkbox.value);
    });
}

export function renderFilterTagTree() {
    const tree = buildTagTree(allTags);
    const container = document.getElementById("filter-tag-tree");
    if (!container) {
        return;
    }
    container.innerHTML = tree.length
        ? `<ul class="tag-tree">${renderCheckboxNodes(tree, selectedFilterTagIds, "filter-tag")}</ul>`
        : '<p class="text-muted small mb-0">No tags yet.</p>';
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
                <input type="text" class="form-control form-control-sm tag-edit-name" style="width:140px" value="${escapeHtml(node.name)}" aria-label="Tag name">
                <input type="color" class="form-control form-control-color form-control-sm tag-edit-color" value="${node.color}" aria-label="Tag color">
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
    if (!container) {
        return;
    }
    container.innerHTML = tree.length
        ? `<ul class="tag-tree">${renderManageNodes(tree)}</ul>`
        : '<p class="text-muted small">No tags yet.</p>';
}

function renderParentOptions() {
    const select = document.getElementById("new-tag-parent");
    if (!select) {
        return;
    }
    const previousValue = select.value;
    const flat = flattenWithDepth(buildTagTree(allTags));
    select.innerHTML = '<option value="">(top-level)</option>' +
        flat.map((tag) => `<option value="${tag.id}">${"— ".repeat(tag.depth)}${escapeHtml(tag.name)}</option>`).join("");
    select.value = previousValue;
}

export function renderNoteTagTree(checkedIds) {
    const tree = buildTagTree(allTags);
    const container = document.getElementById("note-tag-tree");
    if (!container) {
        return;
    }
    container.innerHTML = tree.length
        ? `<ul class="tag-tree">${renderCheckboxNodes(tree, checkedIds, "note-tag")}</ul>`
        : '<p class="text-muted small mb-0">No tags yet. Create some via Manage Tags.</p>';
}

export function updateTagFilterCount() {
    const badge = document.getElementById("tag-filter-count");
    if (!badge) {
        return;
    }
    badge.textContent = String(selectedFilterTagIds.size);
    badge.classList.toggle("d-none", selectedFilterTagIds.size === 0);
}

function renderSubjectRadios() {
    const container = document.getElementById("subject-radio-group");
    if (!container) {
        return; // recorder-only element; absent on pages without the record card.
    }
    const previous = container.querySelector("input[name='subject']:checked");
    const previousValue = previous ? previous.value : "";
    container.innerHTML = allSubjects.map((subject, index) => `
        <div class="form-check form-check-inline mb-0">
            <input class="form-check-input" type="radio" name="subject" id="subject-${index}"
                value="${escapeHtml(subject.name)}" required>
            <label class="form-check-label small" for="subject-${index}">${escapeHtml(subject.name)}</label>
        </div>
    `).join("") + "<button type='reset' class='btn btn-sm btn-outline-secondary'>Clear</button>";
    const safePrevious = previousValue.replace(/["\\]/g, '\\$&');
    const toReselect = container.querySelector(`input[value="${safePrevious}"]`);
    if (toReselect) {
        toReselect.checked = true;
    }
}

export function renderFilterSubjectList() {
    const container = document.getElementById("filter-subject-list");
    if (!container) {
        return;
    }
    if (!allSubjects.length) {
        container.innerHTML = '<p class="text-muted small mb-0">No subjects yet.</p>';
        return;
    }
    const unitsBySubjectName = buildUnitsBySubjectName();
    container.innerHTML = `<ul class="tag-tree">${allSubjects.map((subject) => {
        const units = [DEFAULT_UNIT, ...(unitsBySubjectName[subject.name] || [])]
            .filter((name, index, arr) => arr.indexOf(name) === index);
        const childrenHtml = units.map((unit) => {
            const key = `${subject.name}::${unit}`;
            return `
            <li>
                <label class="d-flex align-items-center gap-2">
                    <input type="checkbox" class="filter-unit-checkbox" value="${escapeHtml(key)}"
                        ${selectedFilterUnits.has(key) ? "checked" : ""}>
                    ${escapeHtml(unit)}
                </label>
            </li>`;
        }).join("");
        return `
            <li>
                <label class="d-flex align-items-center gap-2">
                    <input type="checkbox" class="filter-subject-checkbox" value="${escapeHtml(subject.name)}"
                        ${selectedFilterSubjects.has(subject.name) ? "checked" : ""}>
                    ${escapeHtml(subject.name)}
                </label>
                ${childrenHtml ? `<ul class="tag-children">${childrenHtml}</ul>` : ""}
            </li>`;
    }).join("")}</ul>`;
}

export function updateSubjectFilterCount() {
    const badge = document.getElementById("subject-filter-count");
    if (!badge) {
        return;
    }
    const count = selectedFilterSubjects.size + selectedFilterUnits.size;
    badge.textContent = String(count);
    badge.classList.toggle("d-none", count === 0);
}

function renderSubjectManageList() {
    const list = document.getElementById("subject-list-manage");
    if (!list) {
        return;
    }
    list.innerHTML = allSubjects.length
        ? allSubjects.map((subject) => {
            const units = allUnits
                .filter((unit) => unit.subject_id === subject.id)
                .sort((a, b) => a.name.localeCompare(b.name));
            return `
            <li class="list-group-item">
                <div class="d-flex justify-content-between align-items-center gap-2">
                    ${escapeHtml(subject.name)}
                    <div class="d-flex gap-2 align-items-center">
                        <button type="button" class="btn btn-link btn-sm p-0 toggle-subject-units-btn"
                            data-subject-id="${subject.id}" aria-expanded="false">
                            Units (${units.length})
                        </button>
                        <button type="button" class="btn btn-link btn-sm p-0 text-danger subject-delete-btn"
                            data-subject-id="${subject.id}">Delete</button>
                    </div>
                </div>
                <div class="subject-units-manage d-none mt-2" data-subject-id="${subject.id}">
                    <ul class="list-unstyled subject-unit-list mb-2">
                        ${units.length ? units.map((unit) => `
                            <li class="d-flex justify-content-between align-items-center small">
                                ${escapeHtml(unit.name)}
                                <button type="button" class="btn btn-link btn-sm p-0 text-danger unit-delete-btn"
                                    data-unit-id="${unit.id}">Delete</button>
                            </li>`).join("") : '<li class="small text-muted">No units yet.</li>'}
                    </ul>
                    <div class="d-flex gap-2 align-items-end">
                        <input type="text" class="form-control form-control-sm new-unit-name"
                            data-subject-id="${subject.id}" placeholder="Unit name">
                        <button type="button" class="btn btn-sm btn-primary add-unit-btn text-nowrap"
                            data-subject-id="${subject.id}">Add</button>
                    </div>
                </div>
            </li>`;
        }).join("")
        : '<li class="list-group-item text-muted small">No subjects yet.</li>';
}

export async function loadSubjects() {
    const [subjectsResponse, unitsResponse] = await Promise.all([
        fetch("/api/subjects"),
        fetch("/api/units"),
    ]);
    if (!subjectsResponse.ok) {
        return;
    }
    const subjectsData = await subjectsResponse.json();
    allSubjects = subjectsData.subjects || [];
    if (unitsResponse.ok) {
        const unitsData = await unitsResponse.json();
        allUnits = unitsData.units || [];
    } else {
        allUnits = [];
    }
    renderSubjectRadios();
    renderSubjectManageList();
    renderFilterSubjectList();
}

document.getElementById("manage-subjects-modal")?.addEventListener("click", async (event) => {
    const deleteBtn = event.target.closest(".subject-delete-btn");
    const addBtn = event.target.closest("#add-subject-btn");
    const toggleUnitsBtn = event.target.closest(".toggle-subject-units-btn");
    const addUnitBtn = event.target.closest(".add-unit-btn");
    const unitDeleteBtn = event.target.closest(".unit-delete-btn");
    const errorBox = document.getElementById("subject-manage-error");

    if (deleteBtn) {
        const subjectId = deleteBtn.dataset.subjectId;
        if (!await confirmDialog({
            title: "Delete subject",
            body: "Delete this subject?",
            confirmText: "Delete",
            danger: true,
        })) {
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

    if (toggleUnitsBtn) {
        const subjectId = toggleUnitsBtn.dataset.subjectId;
        const panel = document.querySelector(`.subject-units-manage[data-subject-id="${subjectId}"]`);
        if (panel) {
            const expanded = panel.classList.toggle("d-none") === false;
            toggleUnitsBtn.setAttribute("aria-expanded", String(expanded));
        }
        return;
    }

    if (addUnitBtn) {
        const subjectId = addUnitBtn.dataset.subjectId;
        const input = document.querySelector(`.new-unit-name[data-subject-id="${subjectId}"]`);
        const name = input ? input.value.trim() : "";
        errorBox.classList.add("d-none");
        try {
            const response = await fetch("/api/units", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ subject_id: Number(subjectId), name }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || "Could not create unit.");
            }
            await loadSubjects();
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.classList.remove("d-none");
        }
        return;
    }

    if (unitDeleteBtn) {
        const unitId = unitDeleteBtn.dataset.unitId;
        if (!await confirmDialog({
            title: "Delete unit",
            body: "Delete this unit? Recordings assigned to it will keep the unit name.",
            confirmText: "Delete",
            danger: true,
        })) {
            return;
        }
        await fetch(`/api/units/${unitId}/delete`, { method: "POST" });
        await loadSubjects();
        return;
    }
});

export async function loadTags() {
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

document.getElementById("filter-tag-tree")?.addEventListener("change", (event) => {
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

document.getElementById("filter-subject-list")?.addEventListener("change", (event) => {
    const subjectCheckbox = event.target.closest(".filter-subject-checkbox");
    const unitCheckbox = event.target.closest(".filter-unit-checkbox");

    if (subjectCheckbox) {
        if (subjectCheckbox.checked) {
            selectedFilterSubjects.add(subjectCheckbox.value);
        } else {
            selectedFilterSubjects.delete(subjectCheckbox.value);
        }
        updateSubjectFilterCount();
        fetchAndRenderNotes(1);
        return;
    }

    if (unitCheckbox) {
        if (unitCheckbox.checked) {
            selectedFilterUnits.add(unitCheckbox.value);
        } else {
            selectedFilterUnits.delete(unitCheckbox.value);
        }
        updateSubjectFilterCount();
        fetchAndRenderNotes(1);
        return;
    }
});

document.getElementById("transcription-status-filter-list")?.addEventListener("change", (event) => {
    const checkbox = event.target.closest(".transcription-status-checkbox");
    if (!checkbox) {
        return;
    }
    if (checkbox.checked) {
        selectedTranscriptionStatuses.add(checkbox.value);
    } else {
        selectedTranscriptionStatuses.delete(checkbox.value);
    }
    updateTranscriptionStatusFilterCount();
    fetchAndRenderNotes(1);
});

document.getElementById("key-points-status-filter-list")?.addEventListener("change", (event) => {
    const checkbox = event.target.closest(".key-points-status-checkbox");
    if (!checkbox) {
        return;
    }
    if (checkbox.checked) {
        selectedKeyPointsStatuses.add(checkbox.value);
    } else {
        selectedKeyPointsStatuses.delete(checkbox.value);
    }
    updateKeyPointsStatusFilterCount();
    fetchAndRenderNotes(1);
});

document.getElementById("empty-notes-filter")?.addEventListener("change", () => {
    fetchAndRenderNotes(1);
});

document.getElementById("manage-tags-modal")?.addEventListener("click", async (event) => {
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
        if (!await confirmDialog({
            title: "Delete tag",
            body: "Delete this tag and all of its subtags?",
            confirmText: "Delete",
            danger: true,
        })) {
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

document.getElementById("save-note-tags-btn")?.addEventListener("click", async () => {
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
