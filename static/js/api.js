/* Step 9: shared JSON fetch wrapper (ES module). Same-origin requests satisfy
 * the app's origin-based CSRF check (services/csrf.py); no token header is
 * required. HTTP errors throw with .status/.data attached and, by default,
 * surface a toast unless { toastOnError: false } is passed. The window
 * bridge below exists for the classic recording stack; modules import
 * { fetchJSON } instead. */

import { toast } from './ui/toast.js';

export async function fetchJSON(url, options = {}) {
    const toastOnError = options.toastOnError !== false;
    const fetchOpts = {
        credentials: 'same-origin',
        headers: Object.assign(
            { Accept: 'application/json' },
            options.body ? { 'Content-Type': 'application/json' } : {},
            options.headers || {},
        ),
    };
    ['method', 'body', 'signal'].forEach((key) => {
        if (options[key] !== undefined) {
            fetchOpts[key] = options[key];
        }
    });
    const response = await fetch(url, fetchOpts);
    let data = null;
    try {
        data = await response.json();
    } catch (e) {
        data = null;
    }
    if (!response.ok) {
        const error = new Error(
            (data && data.error) || (`Request failed (${response.status})`),
        );
        error.status = response.status;
        error.data = data;
        if (toastOnError) {
            toast.error(error.message);
        }
        throw error;
    }
    return data;
}

if (typeof window !== 'undefined') {
    window.nrApi = { fetchJSON };
}
