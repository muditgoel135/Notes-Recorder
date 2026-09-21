/* Step 6: note detail page glue. Owns everything on pages/note_detail.html:
 * audio<->transcript sync, bookmark seeks, tab deep-links, header/tag/rich/
 * key-points editing, pin/delete/retries, speaker rename via modal.
 * Shared fetch/toast/escape helpers are imported (Step 9). */
import { getJSON, setJSON } from '../store.js';
import { fetchJSON } from '../api.js';
import { toast } from '../ui/toast.js';
import { confirmDialog } from '../ui/dialog.js';
import { escapeHtml as esc } from '../utils.js';

const root = document.getElementById('note-detail');
if (!root) {
    throw new Error('note-detail: missing #note-detail root');
}
const noteId = Number(root.dataset.noteId);
const SYNC_KEY = 'syncTranscriptEnabled';

/* ---- badge colors + math (rendering via the shared rich-editor global) ---- */
root.querySelectorAll('.tag-badge[data-color], .speaker-badge[data-color]').forEach((b) => {
    b.style.backgroundColor = b.dataset.color;
});

const renderMathFields = (...args) => window.renderMathFields(...args);
renderMathFields(root);

/* ---- tab deep-links (#tab-transcript etc.) ---- */
const tabButtons = Array.from(document.querySelectorAll('#detail-tabs [data-bs-toggle="tab"]'));
function activateTabFromHash() {
    const hash = window.location.hash;
    const match = tabButtons.find((b) => b.dataset.bsTarget === hash);
    const target = match || tabButtons[0];
    if (target && window.bootstrap && window.bootstrap.Tab) {
        window.bootstrap.Tab.getOrCreateInstance(target).show();
    }
}
tabButtons.forEach((btn) => {
    btn.addEventListener('shown.bs.tab', () => {
        window.history.replaceState(null, '', btn.dataset.bsTarget);
    });
});
activateTabFromHash();

/* ---- audio <-> transcript sync (preference shared with legacy key) ---- */
const syncToggle = document.getElementById('sync-toggle');
function syncEnabled() {
    return getJSON(SYNC_KEY, true) !== false;
}
if (syncToggle) {
    syncToggle.checked = syncEnabled();
    document.body.classList.toggle('sync-enabled', syncToggle.checked);
    syncToggle.addEventListener('change', () => {
        setJSON(SYNC_KEY, syncToggle.checked);
        document.body.classList.toggle('sync-enabled', syncToggle.checked);
    });
}
const audio = root.querySelector('audio[data-note-id]');
const wordsContainer = root.querySelector('.transcript-words[data-note-id]');
function highlightForTime(currentTime) {
    if (!wordsContainer) return;
    const words = wordsContainer.querySelectorAll('.transcript-word');
    let active = null;
    for (const word of words) {
        if (Number(word.dataset.start) <= currentTime) active = word;
        else break;
    }
    const current = wordsContainer.querySelector('.transcript-word.active-word');
    if (current && current !== active) current.classList.remove('active-word');
    if (active) active.classList.add('active-word');
}
if (audio) {
    audio.addEventListener('timeupdate', () => {
        if (syncEnabled()) highlightForTime(audio.currentTime);
    });
    wordsContainer?.addEventListener('click', (event) => {
        const word = event.target.closest('.transcript-word');
        if (!word || !syncEnabled()) return;
        audio.currentTime = Number(word.dataset.start);
        audio.play();
    });
    // Keyboard access: Enter/Space on a word seeks just like a click.
    wordsContainer?.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const word = event.target.closest('.transcript-word');
        if (!word || !syncEnabled()) return;
        event.preventDefault();
        audio.currentTime = Number(word.dataset.start);
        audio.play();
    });
}
root.querySelectorAll('.bookmark-chip[data-time]').forEach((chip) => {
    chip.addEventListener('click', () => {
        if (!audio) return;
        audio.currentTime = Number(chip.dataset.time);
        audio.play();
    });
});

/* ---- speaker rename modal (the legacy blocking prompt is gone) ---- */
let renameCtx = null;
const renameModalEl = document.getElementById('speaker-rename-modal');
const renameInput = document.getElementById('speaker-rename-input');
const renameError = document.getElementById('speaker-rename-error');
root.addEventListener('click', (event) => {
    const badge = event.target.closest('.speaker-badge');
    if (!badge) return;
    openSpeakerRename(badge);
});
root.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const badge = event.target.closest?.('.speaker-badge');
    if (!badge) return;
    event.preventDefault();
    openSpeakerRename(badge);
});
function openSpeakerRename(badge) {
    renameCtx = { noteId: badge.dataset.noteId, speakerId: badge.dataset.speakerId };
    renameInput.value = badge.textContent.trim();
    renameError.classList.add('d-none');
    window.bootstrap.Modal.getOrCreateInstance(renameModalEl).show();
    setTimeout(() => renameInput.focus(), 300);
}
document.getElementById('speaker-rename-save')?.addEventListener('click', async () => {
    if (!renameCtx) return;
    const name = renameInput.value.trim();
    if (!name) {
        renameError.textContent = 'A speaker name is required.';
        renameError.classList.remove('d-none');
        return;
    }
    try {
        await fetchJSON(`/notes/${renameCtx.noteId}/speakers/${renameCtx.speakerId}/rename`, {
            method: 'POST', body: JSON.stringify({ name }),
        });
        root.querySelectorAll(
            `.speaker-badge[data-note-id="${renameCtx.noteId}"][data-speaker-id="${renameCtx.speakerId}"]`
        ).forEach((b) => { b.textContent = name; });
        window.bootstrap.Modal.getInstance(renameModalEl)?.hide();
        toast.success('Speaker renamed.');
    } catch (e) {
        renameError.textContent = e.message;
        renameError.classList.remove('d-none');
    }
});

/* ---- header: title ---- */
const titleText = document.getElementById('detail-title-text');
const titleForm = document.getElementById('detail-title-form');
const titleInput = document.getElementById('detail-title-input');
document.getElementById('detail-title-edit')?.addEventListener('click', () => {
    const current = titleText.textContent.trim();
    titleInput.value = current === 'Untitled' ? '' : current;
    titleForm.classList.remove('d-none');
    titleInput.focus();
});
document.getElementById('detail-title-cancel')?.addEventListener('click', () => {
    titleForm.classList.add('d-none');
});
document.getElementById('detail-title-save')?.addEventListener('click', async () => {
    try {
        await fetchJSON(`/update_note/${noteId}`, {
            method: 'POST', body: JSON.stringify({ title: titleInput.value }),
        });
        const next = titleInput.value.trim() || 'Untitled';
        titleText.textContent = next;
        document.title = next;
        titleForm.classList.add('d-none');
        toast.success('Title saved.');
    } catch (e) { /* api.js already toasted */ }
});

/* ---- header: subject/unit + datetime (legacy class names, scoped) ---- */
let subjectCache = null;
let unitsCache = [];
async function loadTaxonomy() {
    if (subjectCache) return;
    const [s, u] = await Promise.all([
        fetchJSON('/api/subjects', { toastOnError: false }),
        fetchJSON('/api/units', { toastOnError: false }),
    ]);
    subjectCache = s.subjects || [];
    unitsCache = u.units || [];
}
function unitsForSubject(name) {
    const subj = subjectCache.find((x) => x.name === name);
    if (!subj) return [];
    return unitsCache.filter((u) => u.subject_id === subj.id).map((u) => u.name);
}
root.querySelector('.edit-subject-btn')?.addEventListener('click', async () => {
    try { await loadTaxonomy(); } catch (e) { return; }
    const display = root.querySelector('.note-subject-display');
    const form = root.querySelector('.note-subject-edit');
    const subjectSel = form.querySelector('.note-subject-input');
    const unitSel = form.querySelector('.note-unit-input');
    const [curSubject, curUnit] = display.querySelector('strong')
        ? [display.querySelector('strong').textContent.trim(),
           (display.querySelector('.text-muted')?.textContent || '').replace('·', '').trim()]
        : ['', 'General'];
    subjectSel.innerHTML = subjectCache.map((s) =>
        `<option value="${esc(s.name)}"${s.name === curSubject ? ' selected' : ''}>${esc(s.name)}</option>`).join('');
    const fillUnits = () => {
        const names = ['General', ...unitsForSubject(subjectSel.value)];
        unitSel.innerHTML = names.map((n) =>
            `<option value="${esc(n)}"${n === curUnit ? ' selected' : ''}>${esc(n)}</option>`).join('');
    };
    subjectSel.onchange = fillUnits;
    fillUnits();
    display.classList.add('d-none');
    form.classList.remove('d-none');
});
root.querySelector('.cancel-subject-btn')?.addEventListener('click', () => {
    root.querySelector('.note-subject-edit').classList.add('d-none');
    root.querySelector('.note-subject-display').classList.remove('d-none');
});
root.querySelector('.save-subject-btn')?.addEventListener('click', async (event) => {
    const form = root.querySelector('.note-subject-edit');
    const subject = form.querySelector('.note-subject-input').value;
    const unit = form.querySelector('.note-unit-input').value;
    event.target.disabled = true;
    try {
        const data = await fetchJSON(`/notes/${noteId}/subject`, {
            method: 'POST', body: JSON.stringify({ subject, unit }),
        });
        const display = root.querySelector('.note-subject-display');
        display.querySelector('strong').textContent = data.subject;
        display.querySelector('.text-muted').innerHTML = `&middot; ${esc(data.unit)}`;
        document.getElementById('detail-meta-subject').textContent = `${data.subject} / ${data.unit}`;
        form.classList.add('d-none');
        display.classList.remove('d-none');
        toast.success('Subject saved.');
    } catch (e) { /* toasted */ }
    event.target.disabled = false;
});
root.querySelector('.edit-datetime-btn')?.addEventListener('click', () => {
    root.querySelector('.note-datetime-display').classList.add('d-none');
    root.querySelector('.note-datetime-edit').classList.remove('d-none');
});
root.querySelector('.cancel-datetime-btn')?.addEventListener('click', () => {
    root.querySelector('.note-datetime-edit').classList.add('d-none');
    root.querySelector('.note-datetime-display').classList.remove('d-none');
});
root.querySelector('.save-datetime-btn')?.addEventListener('click', async (event) => {
    const form = root.querySelector('.note-datetime-edit');
    const date = form.querySelector('.note-date-input').value;
    const startTime = form.querySelector('.note-start-time-input').value;
    event.target.disabled = true;
    try {
        const data = await fetchJSON(`/notes/${noteId}/datetime`, {
            method: 'POST', body: JSON.stringify({ date, start_time: startTime }),
        });
        document.getElementById('detail-datetime-text').textContent =
            `${data.date} ${data.start_time} - ${data.end_time}`;
        document.getElementById('detail-meta-datetime').textContent =
            `${data.date} ${data.start_time} – ${data.end_time}`;
        form.classList.add('d-none');
        root.querySelector('.note-datetime-display').classList.remove('d-none');
        toast.success('Date saved.');
    } catch (e) { /* toasted */ }
    event.target.disabled = false;
});

/* ---- tags (checkbox tree in the shared note-tags modal) ---- */
function tagTreeHtml(tags, checked) {
    const nested = (pid) => tags.filter((t) => t.parent_id === pid).map((t) => `
        <li>
            <label class="d-flex align-items-center gap-2">
                <input type="checkbox" class="detail-tag-checkbox" value="${t.id}"
                    ${checked.has(t.id) ? 'checked' : ''}>
                <span class="tag-badge" style="background-color:${esc(t.color)}">${esc(t.name)}</span>
            </label>
            ${nested(t.id) ? `<ul class="tag-children">${nested(t.id)}</ul>` : ''}
        </li>`).join('');
    const html = nested(null);
    return html ? `<ul class="tag-tree">${html}</ul>` : '<p class="text-muted small mb-0">No tags yet.</p>';
}
root.querySelector('.edit-tags-btn')?.addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    const checked = new Set(JSON.parse(btn.dataset.tagIds || '[]'));
    try {
        const data = await fetchJSON('/api/tags', { toastOnError: false });
        document.getElementById('note-tag-tree').innerHTML = tagTreeHtml(data.tags || [], checked);
    } catch (e) { return; }
    document.getElementById('note-tags-error').classList.add('d-none');
    window.bootstrap.Modal.getOrCreateInstance(document.getElementById('note-tags-modal')).show();
    document.getElementById('save-note-tags-btn').onclick = async () => {
        const ids = Array.from(document.querySelectorAll('#note-tag-tree .detail-tag-checkbox:checked'))
            .map((c) => Number(c.value));
        try {
            const saved = await fetchJSON(`/notes/${noteId}/tags`, {
                method: 'POST', body: JSON.stringify({ tag_ids: ids }),
            });
            const list = document.getElementById('detail-tags-list');
            list.innerHTML = (saved.tags || []).map((t) =>
                `<span class="tag-badge" style="background-color:${esc(t.color)}">${esc(t.name)}</span>`).join('')
                || '<span class="small text-muted">No tags.</span>';
            btn.dataset.tagIds = JSON.stringify((saved.tags || []).map((t) => t.id));
            window.bootstrap.Modal.getInstance(document.getElementById('note-tags-modal'))?.hide();
            toast.success('Tags saved.');
        } catch (e) { /* toasted */ }
    };
});

/* ---- pin / delete / retries ---- */
document.getElementById('detail-pin-btn')?.addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    try {
        const data = await fetchJSON(`/notes/${noteId}/pin`, { method: 'POST' });
        btn.dataset.pinned = String(data.pinned);
        btn.setAttribute('aria-pressed', String(data.pinned));
        btn.classList.toggle('pinned', data.pinned);
        btn.textContent = data.pinned ? 'Unpin' : 'Pin';
        toast.success(data.pinned ? 'Pinned.' : 'Unpinned.');
    } catch (e) { /* toasted */ }
    btn.disabled = false;
});
document.getElementById('detail-delete-btn')?.addEventListener('click', async (event) => {
    if (!await confirmDialog({
        title: 'Delete recording',
        body: 'Delete this recording?',
        confirmText: 'Delete',
        danger: true,
    })) return;
    event.target.disabled = true;
    try {
        await fetchJSON(`/delete/${noteId}`, {
            method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        window.location.assign('/notes');
    } catch (e) { event.target.disabled = false; }
});
root.querySelectorAll('.retry-transcription-btn, .retry-key-points-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
        const url = btn.classList.contains('retry-transcription-btn')
            ? `/notes/${noteId}/retry_transcription`
            : `/notes/${noteId}/retry_key_points`;
        btn.disabled = true;
        try {
            const data = await fetchJSON(url, { method: 'POST' });
            toast.success(data.message || 'Re-queued.');
            setTimeout(() => window.location.reload(), 800);
        } catch (e) { btn.disabled = false; }
    });
});

/* ---- rich notes display/edit ---- */
const richDisplay = document.getElementById('detail-rich-display');
const richForm = document.getElementById('detail-rich-form');
const richEditor = document.getElementById('detail-rich-notes-editor');
const richError = document.getElementById('detail-rich-error');
document.getElementById('detail-rich-edit')?.addEventListener('click', () => {
    richDisplay.classList.add('d-none');
    richForm.classList.remove('d-none');
    renderMathFields(richForm);
});
document.getElementById('detail-rich-cancel')?.addEventListener('click', () => {
    richForm.classList.add('d-none');
    richDisplay.classList.remove('d-none');
});
document.getElementById('detail-rich-save')?.addEventListener('click', async (event) => {
    richError.classList.add('d-none');
    event.target.disabled = true;
    try {
        const data = await fetchJSON(`/notes/${noteId}/notes`, {
            method: 'POST', body: JSON.stringify({ notes_html: richEditor.innerHTML }),
        });
        richDisplay.innerHTML = data.notes_html ||
            '<p class="small text-muted">No notes saved for this recording.</p>';
        renderMathFields(richDisplay);
        richForm.classList.add('d-none');
        richDisplay.classList.remove('d-none');
        const kPill = root.querySelector('[data-kstatus-pill]');
        if (kPill && data.key_points_status) {
            kPill.textContent = `key points: ${data.key_points_status}`;
        }
        toast.success(data.message || 'Notes saved.');
    } catch (e) {
        richError.textContent = e.message;
        richError.classList.remove('d-none');
    }
    event.target.disabled = false;
});

/* ---- key points edit (server renders markdown; reload to refresh) ---- */
document.getElementById('detail-keypoints-edit')?.addEventListener('click', () => {
    document.getElementById('detail-keypoints-display')?.classList.add('d-none');
    document.getElementById('detail-keypoints-form')?.classList.remove('d-none');
});
document.getElementById('detail-keypoints-cancel')?.addEventListener('click', () => {
    document.getElementById('detail-keypoints-form')?.classList.add('d-none');
    document.getElementById('detail-keypoints-display')?.classList.remove('d-none');
});
document.getElementById('detail-keypoints-save')?.addEventListener('click', async (event) => {
    const err = document.getElementById('detail-keypoints-error');
    err.classList.add('d-none');
    event.target.disabled = true;
    try {
        await fetchJSON(`/update_note/${noteId}`, {
            method: 'POST',
            body: JSON.stringify({
                title: titleText.textContent.trim() === 'Untitled' ? '' : titleText.textContent.trim(),
                key_points: document.getElementById('detail-keypoints-input').value,
            }),
        });
        window.location.reload();
    } catch (e) {
        err.textContent = e.message;
        err.classList.remove('d-none');
        event.target.disabled = false;
    }
});
