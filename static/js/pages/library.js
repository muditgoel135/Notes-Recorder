/* Step 9: library page entry. Imports the feature modules (their top-level
 * wiring runs on import), then adds page glue: density toggle, '/' shortcut,
 * numbered pagination, header count + filter badge sync. */
import '../features/library-list.js';
import '../features/library-actions.js';
import '../features/library-bulk.js';
import { loadTags, loadSubjects } from '../features/library-taxonomy.js';
import { fetchAndRenderNotes, initLibraryList } from '../features/library-list.js';
import { getJSON, setJSON } from '../store.js';

const DENSITY_KEY = 'nr-density';

function applyDensity(mode) {
    const compact = mode === 'compact';
    document.body.dataset.density = compact ? 'compact' : 'comfortable';
    const btn = document.getElementById('density-toggle');
    if (btn) {
        btn.setAttribute('aria-pressed', String(compact));
        btn.textContent = compact ? 'Comfortable' : 'Compact';
    }
}

applyDensity(getJSON(DENSITY_KEY, 'comfortable'));

document.getElementById('density-toggle')?.addEventListener('click', () => {
    const next = document.body.dataset.density === 'compact' ? 'comfortable' : 'compact';
    setJSON(DENSITY_KEY, next);
    applyDensity(next);
});

document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (target && (target.isContentEditable || target.closest('input, textarea, select'))) return;
    const search = document.getElementById('search-input');
    if (search) {
        event.preventDefault();
        search.focus();
    }
});

function currentTotal() {
    const label = document.querySelector('#pagination-controls .text-muted');
    const match = label ? label.textContent.match(/\((\d+) results?\)/) : null;
    return match ? Number(match[1]) : null;
}

function syncHeaderCount() {
    const count = document.getElementById('library-count');
    const total = currentTotal();
    if (count && total !== null) {
        count.textContent = `${total} recording${total === 1 ? '' : 's'}`;
    }
}

function activeFilterCount() {
    const rail = document.getElementById('filters-rail');
    if (!rail) return 0;
    let n = 0;
    const search = document.getElementById('search-input');
    if (search && search.value.trim()) n += 1;
    rail.querySelectorAll('input[type="date"], input[type="time"]').forEach((el) => {
        if (el.value) n += 1;
    });
    n += rail.querySelectorAll('input[type="checkbox"]:checked').length;
    const sort = document.getElementById('sort-select');
    if (sort && sort.value !== 'date_desc') n += 1;
    return n;
}

function syncFilterBadge() {
    const badge = document.getElementById('filters-active-count');
    if (!badge) return;
    const n = activeFilterCount();
    badge.textContent = String(n);
    badge.classList.toggle('d-none', n === 0);
}

document.getElementById('recordings-list')?.addEventListener('click', (event) => {
    const pageBtn = event.target.closest('.page-number-btn');
    if (!pageBtn || pageBtn.disabled) return;
    event.preventDefault();
    fetchAndRenderNotes(Number(pageBtn.dataset.page));
    document.getElementById('recordings-list')?.scrollIntoView({ block: 'start' });
});

document.getElementById('filters-rail')?.addEventListener('input', syncFilterBadge);
document.getElementById('search-input')?.addEventListener('input', syncFilterBadge);
document.getElementById('sort-select')?.addEventListener('change', syncFilterBadge);

new MutationObserver(() => {
    syncHeaderCount();
    syncFilterBadge();
}).observe(document.getElementById('recordings-list'), { childList: true });

syncHeaderCount();
syncFilterBadge();
initLibraryList();
loadTags();
loadSubjects();
