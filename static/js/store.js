/* Step 2: tiny localStorage-backed UI store. No dependencies.
 * Theme helpers are used by theme-toggle.js; storage helpers will be
 * reused by later steps (density, sync toggle, filters). */

export const THEME_KEY = 'nr-theme';
export const THEME_MODES = ['light', 'dark', 'auto'];

function mediaQuery() {
    return window.matchMedia('(prefers-color-scheme: dark)');
}

export function getTheme() {
    try {
        const raw = localStorage.getItem(THEME_KEY) || 'auto';
        return THEME_MODES.includes(raw) ? raw : 'auto';
    } catch (e) {
        return 'auto';
    }
}

export function setTheme(mode) {
    if (!THEME_MODES.includes(mode)) {
        throw new Error('Unknown theme mode: ' + mode);
    }
    try {
        localStorage.setItem(THEME_KEY, mode);
    } catch (e) {
        /* private mode: theme just won't persist */
    }
    return applyTheme(mode);
}

/** Resolve a stored mode to the effective 'light' | 'dark' value. */
export function resolveTheme(mode) {
    if (mode === 'dark') return 'dark';
    if (mode === 'light') return 'light';
    try {
        return mediaQuery().matches ? 'dark' : 'light';
    } catch (e) {
        return 'light';
    }
}

/** Apply a mode to <html data-bs-theme> and return the effective theme. */
export function applyTheme(mode) {
    const effective = resolveTheme(mode);
    document.documentElement.setAttribute('data-bs-theme', effective);
    try {
        document.documentElement.style.colorScheme = effective;
    } catch (e) { /* ignore */ }
    return effective;
}

/** Re-apply the stored theme (used when the OS theme changes in auto mode). */
export function refreshTheme() {
    return applyTheme(getTheme());
}

/** Subscribe to OS theme changes; returns an unsubscribe function. */
export function onSystemThemeChange(callback) {
    try {
        const mq = mediaQuery();
        const handler = () => callback(mq.matches ? 'dark' : 'light');
        if (mq.addEventListener) mq.addEventListener('change', handler);
        else mq.addListener(handler);
        return () => {
            if (mq.removeEventListener) mq.removeEventListener('change', handler);
            else mq.removeListener(handler);
        };
    } catch (e) {
        return () => {};
    }
}

export function cycleTheme() {
    const order = ['light', 'dark', 'auto'];
    const next = order[(order.indexOf(getTheme()) + 1) % order.length];
    setTheme(next);
    return next;
}

export function getJSON(key, fallback) {
    try {
        const raw = localStorage.getItem(key);
        return raw === null ? fallback : JSON.parse(raw);
    } catch (e) {
        return fallback;
    }
}

export function setJSON(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { /* ignore */ }
}
