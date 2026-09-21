/* Step 9: toast notifications (ES module). Renders Bootstrap toasts into the
 * #toast-stack container from base.html. The window bridge below exists for
 * the classic recording stack (app.js / recording.js / rich-editor.js);
 * feature modules import { toast } instead. */

const TYPE_CLASS = {
    success: 'text-bg-success',
    info: 'text-bg-primary',
    warning: 'text-bg-warning',
    danger: 'text-bg-danger',
    error: 'text-bg-danger',
};

export function show(message, type = 'info') {
    const stack = typeof document !== 'undefined'
        ? document.getElementById('toast-stack')
        : null;
    if (!stack) {
        return;
    }
    const el = document.createElement('div');
    el.className = 'toast align-items-center border-0 ' + (TYPE_CLASS[type] || TYPE_CLASS.info);
    el.setAttribute('role', 'status');
    const body = document.createElement('div');
    body.className = 'd-flex';
    const text = document.createElement('div');
    text.className = 'toast-body';
    text.textContent = String(message);
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'btn-close btn-close-white me-2 m-auto';
    close.setAttribute('data-bs-dismiss', 'toast');
    close.setAttribute('aria-label', 'Dismiss notification');
    body.appendChild(text);
    body.appendChild(close);
    el.appendChild(body);
    stack.appendChild(el);
    const bootstrap = typeof window !== 'undefined' ? window.bootstrap : null;
    if (bootstrap && bootstrap.Toast) {
        const toast = bootstrap.Toast.getOrCreateInstance(el, { delay: 5000 });
        el.addEventListener('hidden.bs.toast', () => el.remove());
        toast.show();
    } else {
        setTimeout(() => el.remove(), 5000);
    }
}

export const toast = {
    show,
    success: (m) => show(m, 'success'),
    info: (m) => show(m, 'info'),
    warning: (m) => show(m, 'warning'),
    error: (m) => show(m, 'error'),
};

if (typeof window !== 'undefined') {
    window.nrToast = toast;
}
