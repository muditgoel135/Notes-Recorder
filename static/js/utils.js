/* Step 9: shared dependency-free utilities. Imported by feature modules;
 * no DOM access at load, safe to import anywhere (including Node harnesses). */

export function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = String(value);
    return div.innerHTML;
}

export function debounce(fn, delayMs) {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), delayMs);
    };
}

/** Format seconds as m:ss (e.g. 75 -> "1:15"). */
export function fmtTime(totalSeconds) {
    const total = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/** Paint badge colors + progress widths inside root (moved from notes-list.js). */
export function applyDynamicNoteStyles(root = document) {
    root.querySelectorAll('.tag-badge[data-color], .speaker-badge[data-color]').forEach((badge) => {
        badge.style.backgroundColor = badge.dataset.color;
    });
    root.querySelectorAll('.transcript-progress-bar[data-progress]').forEach((bar) => {
        const value = Number(bar.dataset.progress) || 0;
        bar.style.width = `${value}%`;
        bar.setAttribute('aria-valuenow', String(value));
    });
}
