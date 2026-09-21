/* Step 2: navbar theme toggle wiring. Imports the store module; no other deps. */
import { getTheme, setTheme, cycleTheme, applyTheme, onSystemThemeChange } from './store.js';

const LABELS = { light: 'Theme: Light', dark: 'Theme: Dark', auto: 'Theme: Auto' };

function paintButton(btn, mode) {
    const label = LABELS[mode] || LABELS.auto;
    const text = btn.querySelector('[data-theme-label]');
    if (text) text.textContent = label;
    else btn.textContent = label;
    btn.setAttribute('title', 'Color theme (' + mode + ') — activate to change');
    btn.setAttribute('aria-label', 'Color theme, current: ' + mode + '. Activate to change.');
}

function init() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const mode = getTheme();
    applyTheme(mode);
    paintButton(btn, mode);
    btn.addEventListener('click', () => {
        paintButton(btn, cycleTheme());
    });
    // In auto mode, follow the OS without a reload.
    onSystemThemeChange(() => applyTheme(getTheme()));
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
