/* Step 3: thin recorder page entry. Legacy recording.js + app.js own the
 * record lifecycle; this module only adds additive glue:
 * - re-apply the stored theme (covers back/forward-cache restores),
 * - keep the Recording-notes tab in sync with the notes panel visibility,
 * - load subjects for the record card radios + resume an interrupted
 *   recording (Step 9: shared taxonomy loader; the classic recording stack
 *   exposes restoreActiveRecordingIfNeeded as a global).
 */
import { refreshTheme } from '../store.js';
import { loadSubjects } from '../features/library-taxonomy.js';

refreshTheme();

loadSubjects().then(() => {
    if (typeof window.restoreActiveRecordingIfNeeded === 'function') {
        window.restoreActiveRecordingIfNeeded();
    }
});

const panel = document.getElementById('active-notes-panel');
const hint = document.getElementById('notes-tab-empty');
const notesTabBtn = document.getElementById('tab-notes-btn');

function syncNotesTab() {
    if (!panel) return;
    const visible = !panel.classList.contains('d-none');
    if (hint) hint.classList.toggle('d-none', visible);
    if (visible && notesTabBtn && !notesTabBtn.classList.contains('active')) {
        if (window.bootstrap && window.bootstrap.Tab) {
            window.bootstrap.Tab.getOrCreateInstance(notesTabBtn).show();
        } else {
            notesTabBtn.click();
        }
    }
}

if (panel) {
    new MutationObserver(syncNotesTab).observe(panel, {
        attributes: true,
        attributeFilter: ['class'],
    });
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', syncNotesTab);
    } else {
        syncNotesTab();
    }
}
