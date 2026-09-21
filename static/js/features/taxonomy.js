/* Step 8: Manage page glue (taxonomy CRUD + prefs). Shared fetch, toast,
 * dialog and escape helpers are imported (Step 9). */
import { getTheme, setTheme, getJSON, setJSON } from '../store.js';

import { fetchJSON } from '../api.js';
import { toast } from '../ui/toast.js';
import { confirmDialog } from '../ui/dialog.js';
import { escapeHtml as esc } from '../utils.js';
const SYNC_KEY = 'syncTranscriptEnabled';
const DENSITY_KEY = 'nr-density';

let allSubjects = [];
let allUnits = [];
let allTags = [];

/* ---------------- subjects & units ---------------- */
function renderSubjects() {
    const list = document.getElementById('subject-list-manage');
    const unitsBySubject = new Map();
    allUnits.forEach((u) => {
        if (!unitsBySubject.has(u.subject_id)) unitsBySubject.set(u.subject_id, []);
        unitsBySubject.get(u.subject_id).push(u);
    });
    list.innerHTML = allSubjects.length ? allSubjects.map((s) => {
        const units = unitsBySubject.get(s.id) || [];
        return `
        <li class="list-group-item" data-subject-id="${s.id}">
            <div class="d-flex justify-content-between align-items-center gap-2">
                <strong>${esc(s.name)}</strong>
                <button type="button" class="btn btn-sm btn-outline-danger subject-delete-btn"
                    data-subject-id="${s.id}">Delete</button>
            </div>
            <ul class="list-unstyled ms-3 mt-2 mb-0">
                ${units.map((u) => `
                <li class="d-flex justify-content-between align-items-center gap-2 mb-1">
                    <span class="small">${esc(u.name)}</span>
                    <button type="button" class="btn btn-sm btn-link text-danger p-0 unit-delete-btn"
                        data-unit-id="${u.id}" aria-label="Delete unit ${esc(u.name)}">Delete</button>
                </li>`).join('')}
                <li class="d-flex gap-2 mt-2">
                    <input type="text" class="form-control form-control-sm new-unit-name"
                        placeholder="New unit" maxlength="100" aria-label="New unit name">
                    <button type="button" class="btn btn-sm btn-outline-primary add-unit-btn text-nowrap"
                        data-subject-id="${s.id}">Add unit</button>
                </li>
            </ul>
        </li>`;
    }).join('') : '<li class="list-group-item text-muted small">No subjects yet.</li>';
}

async function loadSubjects() {
    try {
        const [s, u] = await Promise.all([
            fetchJSON('/api/subjects', { toastOnError: false }),
            fetchJSON('/api/units', { toastOnError: false }),
        ]);
        allSubjects = s.subjects || [];
        allUnits = u.units || [];
        renderSubjects();
        const storageSubjects = document.getElementById('storage-subjects');
        if (storageSubjects) storageSubjects.textContent = String(allSubjects.length);
        const storageUnits = document.getElementById('storage-units');
        if (storageUnits) storageUnits.textContent = String(allUnits.length);
    } catch (e) {
        document.getElementById('subject-list-manage').innerHTML =
            '<li class="list-group-item text-danger small">Could not load subjects.</li>';
        toast.error(e.message);
    }
}

function subjectError(message = '') {
    const box = document.getElementById('subject-manage-error');
    box.textContent = message;
    box.classList.toggle('d-none', !message);
}

document.getElementById('add-subject-btn').addEventListener('click', async () => {
    const input = document.getElementById('new-subject-name');
    subjectError('');
    try {
        await fetchJSON('/api/subjects', { method: 'POST', body: JSON.stringify({ name: input.value }) });
        input.value = '';
        await loadSubjects();
        toast.success('Subject added.');
    } catch (e) {
        subjectError(e.message);
    }
});

document.getElementById('subject-list-manage').addEventListener('click', async (event) => {
    const delSubject = event.target.closest('.subject-delete-btn');
    const delUnit = event.target.closest('.unit-delete-btn');
    const addUnit = event.target.closest('.add-unit-btn');
    if (delSubject) {
        if (!await confirmDialog({ title: 'Delete subject', body: 'Delete this subject and its units?', confirmText: 'Delete', danger: true })) return;
        try {
            await fetchJSON(`/api/subjects/${delSubject.dataset.subjectId}/delete`, { method: 'POST' });
            await loadSubjects();
            toast.success('Subject deleted.');
        } catch (e) { /* toasted */ }
        return;
    }
    if (delUnit) {
        if (!await confirmDialog({ title: 'Delete unit', body: 'Delete this unit?', confirmText: 'Delete', danger: true })) return;
        try {
            await fetchJSON(`/api/units/${delUnit.dataset.unitId}/delete`, { method: 'POST' });
            await loadSubjects();
            toast.success('Unit deleted.');
        } catch (e) { /* toasted */ }
        return;
    }
    if (addUnit) {
        const row = addUnit.closest('li');
        const input = row.querySelector('.new-unit-name');
        try {
            await fetchJSON('/api/units', {
                method: 'POST',
                body: JSON.stringify({ name: input.value, subject_id: Number(addUnit.dataset.subjectId) }),
            });
            await loadSubjects();
            toast.success('Unit added.');
        } catch (e) {
            subjectError(e.message);
        }
    }
});

/* ---------------- tags ---------------- */
function tagSubtree(parentId, checked = new Set()) {
    return allTags.filter((t) => t.parent_id === parentId).map((t) => `
        <li data-tag-id="${t.id}">
            <div class="tag-row-display d-flex align-items-center gap-2 mb-1">
                <span class="tag-badge" style="background-color:${esc(t.color)}">${esc(t.name)}</span>
                <button type="button" class="btn btn-link btn-sm p-0 tag-edit-btn"
                    data-tag-id="${t.id}">Edit</button>
                <button type="button" class="btn btn-link btn-sm p-0 tag-sub-btn"
                    data-tag-id="${t.id}" title="Add a sub-tag under ${esc(t.name)}">Sub</button>
                <button type="button" class="btn btn-link btn-sm p-0 text-danger tag-delete-btn"
                    data-tag-id="${t.id}">Delete</button>
            </div>
            <div class="tag-row-edit d-none align-items-center gap-2 mb-1 flex-wrap" data-tag-id="${t.id}">
                <input type="text" class="form-control form-control-sm tag-edit-name" value="${esc(t.name)}"
                    maxlength="100" aria-label="Tag name">
                <input type="color" class="form-control form-control-color form-control-sm tag-edit-color"
                    value="${esc(t.color)}" aria-label="Tag color">
                <button type="button" class="btn btn-sm btn-primary tag-save-btn"
                    data-tag-id="${t.id}">Save</button>
                <button type="button" class="btn btn-sm btn-secondary tag-cancel-btn">Cancel</button>
            </div>
            ${tagSubtree(t.id) ? `<ul class="tag-children">${tagSubtree(t.id)}</ul>` : ''}
        </li>`).join('');
}

function renderTags() {
    const container = document.getElementById('tag-tree-manage');
    const html = tagSubtree(null);
    container.innerHTML = html ? `<ul class="tag-tree">${html}</ul>`
        : '<p class="text-muted small mb-0">No tags yet.</p>';
    const parentSel = document.getElementById('new-tag-parent');
    const current = parentSel.value;
    parentSel.innerHTML = '<option value="">(top-level)</option>' + allTags.map((t) =>
        `<option value="${t.id}">${esc(t.name)}</option>`).join('');
    if (allTags.some((t) => String(t.id) === current)) parentSel.value = current;
    const storageTags = document.getElementById('storage-tags');
    if (storageTags) storageTags.textContent = String(allTags.length);
}

async function loadTags() {
    try {
        const data = await fetchJSON('/api/tags', { toastOnError: false });
        allTags = data.tags || [];
        renderTags();
    } catch (e) {
        document.getElementById('tag-tree-manage').innerHTML =
            '<p class="text-danger small">Could not load tags.</p>';
        toast.error(e.message);
    }
}

function tagError(message = '') {
    const box = document.getElementById('tag-manage-error');
    box.textContent = message;
    box.classList.toggle('d-none', !message);
}

document.getElementById('add-tag-btn').addEventListener('click', async () => {
    tagError('');
    const parentVal = document.getElementById('new-tag-parent').value;
    try {
        await fetchJSON('/api/tags', {
            method: 'POST',
            body: JSON.stringify({
                name: document.getElementById('new-tag-name').value,
                color: document.getElementById('new-tag-color').value,
                ...(parentVal ? { parent_id: Number(parentVal) } : {}),
            }),
        });
        document.getElementById('new-tag-name').value = '';
        await loadTags();
        toast.success('Tag added.');
    } catch (e) {
        tagError(e.message);
    }
});

document.getElementById('tag-tree-manage').addEventListener('click', async (event) => {
    const editBtn = event.target.closest('.tag-edit-btn');
    const delBtn = event.target.closest('.tag-delete-btn');
    const subBtn = event.target.closest('.tag-sub-btn');
    const saveBtn = event.target.closest('.tag-save-btn');
    const cancelBtn = event.target.closest('.tag-cancel-btn');
    if (editBtn) {
        const row = editBtn.closest('li');
        row.querySelector('.tag-row-display').classList.add('d-none');
        const form = row.querySelector('.tag-row-edit');
        form.classList.remove('d-none');
        form.classList.add('d-flex');
        return;
    }
    if (cancelBtn) {
        const row = cancelBtn.closest('li');
        const form = row.querySelector('.tag-row-edit');
        form.classList.add('d-none');
        form.classList.remove('d-flex');
        row.querySelector('.tag-row-display').classList.remove('d-none');
        return;
    }
    if (saveBtn) {
        const row = saveBtn.closest('li');
        try {
            await fetchJSON(`/api/tags/${saveBtn.dataset.tagId}`, {
                method: 'POST',
                body: JSON.stringify({
                    name: row.querySelector('.tag-edit-name').value,
                    color: row.querySelector('.tag-edit-color').value,
                }),
            });
            await loadTags();
            toast.success('Tag saved.');
        } catch (e) {
            tagError(e.message);
        }
        return;
    }
    if (delBtn) {
        if (!await confirmDialog({ title: 'Delete tag', body: 'Delete this tag and its sub-tags?', confirmText: 'Delete', danger: true })) return;
        try {
            await fetchJSON(`/api/tags/${delBtn.dataset.tagId}/delete`, { method: 'POST' });
            await loadTags();
            toast.success('Tag deleted.');
        } catch (e) { /* toasted */ }
        return;
    }
    if (subBtn) {
        document.getElementById('new-tag-parent').value = subBtn.dataset.tagId;
        document.getElementById('new-tag-name').focus();
        toast.info('Parent selected — enter a name and press Add.');
    }
});

/* ---------------- prefs ---------------- */
const syncBox = document.getElementById('prefs-sync');
syncBox.checked = getJSON(SYNC_KEY, true) !== false;
syncBox.addEventListener('change', () => {
    setJSON(SYNC_KEY, syncBox.checked);
    document.body.classList.toggle('sync-enabled', syncBox.checked);
});

const themeRadios = Array.from(document.querySelectorAll('input[name="prefs-theme"]'));
themeRadios.forEach((r) => { r.checked = r.value === getTheme(); });
themeRadios.forEach((r) => {
    r.addEventListener('change', () => {
        if (r.checked) setTheme(r.value);
    });
});

const densityBox = document.getElementById('prefs-density-compact');
densityBox.checked = getJSON(DENSITY_KEY, 'comfortable') === 'compact';
densityBox.addEventListener('change', () => {
    const mode = densityBox.checked ? 'compact' : 'comfortable';
    setJSON(DENSITY_KEY, mode);
    document.body.dataset.density = mode;
});

loadSubjects();
loadTags();
