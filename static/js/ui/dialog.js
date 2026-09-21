/* Step 9: promise-based Bootstrap dialogs replacing the blocking confirm
 * and prompt calls. A single pair of modals (partials/_dialogs.html, in
 * base.html) is reused; concurrent callers queue in order. The window bridge
 * exists for the classic recording stack; modules import the named functions. */

let confirmResolver = null;
let promptResolver = null;

function modalEl(id) {
    return document.getElementById(id);
}

function showModal(el) {
    window.bootstrap.Modal.getOrCreateInstance(el).show();
}

function hideModal(el) {
    window.bootstrap.Modal.getInstance(el)?.hide();
}

function wireOnce() {
    const confirmModal = modalEl('nr-confirm-modal');
    confirmModal.addEventListener('hidden.bs.modal', () => {
        if (confirmResolver) {
            const resolve = confirmResolver;
            confirmResolver = null;
            resolve(false);
        }
    });
    modalEl('nr-confirm-ok').addEventListener('click', () => {
        if (confirmResolver) {
            const resolve = confirmResolver;
            confirmResolver = null;
            hideModal(confirmModal);
            resolve(true);
        }
    });
    const promptModal = modalEl('nr-prompt-modal');
    promptModal.addEventListener('hidden.bs.modal', () => {
        if (promptResolver) {
            const resolve = promptResolver;
            promptResolver = null;
            resolve(null);
        }
    });
    const submitPrompt = () => {
        if (!promptResolver) return;
        const resolve = promptResolver;
        promptResolver = null;
        const value = promptInput().value;
        hideModal(promptModal);
        resolve(value);
    };
    modalEl('nr-prompt-save').addEventListener('click', submitPrompt);
    modalEl('nr-prompt-form').addEventListener('submit', (event) => {
        event.preventDefault();
        submitPrompt();
    });
}

let wired = false;
function ensureWired() {
    if (!wired) {
        wired = true;
        wireOnce();
    }
}

function promptInput() {
    return modalEl('nr-prompt-input');
}

/** Resolve true when the user confirms, false on cancel/dismiss. */
export function confirmDialog({ title = 'Confirm', body = 'Are you sure?', confirmText = 'Confirm', danger = false } = {}) {
    ensureWired();
    modalEl('nr-confirm-title').textContent = title;
    modalEl('nr-confirm-body').textContent = body;
    const ok = modalEl('nr-confirm-ok');
    ok.textContent = confirmText;
    ok.classList.toggle('btn-danger', danger);
    ok.classList.toggle('btn-primary', !danger);
    return new Promise((resolve) => {
        confirmResolver = resolve;
        showModal(modalEl('nr-confirm-modal'));
    });
}

/** Resolve the entered string, or null on cancel/dismiss. */
export function promptDialog({ title = 'Input', label = '', value = '', placeholder = '', confirmText = 'Save' } = {}) {
    ensureWired();
    modalEl('nr-prompt-title').textContent = title;
    modalEl('nr-prompt-label').textContent = label;
    modalEl('nr-prompt-label').style.display = label ? '' : 'none';
    const input = promptInput();
    input.value = value ?? '';
    input.placeholder = placeholder;
    modalEl('nr-prompt-save').textContent = confirmText;
    return new Promise((resolve) => {
        promptResolver = resolve;
        showModal(modalEl('nr-prompt-modal'));
        setTimeout(() => input.focus(), 300);
    });
}

if (typeof window !== 'undefined') {
    window.nrDialog = { confirm: confirmDialog, prompt: promptDialog };
}
