/* Step 9: rich-editor shell (ported from the editor half of app.js plus the
 * math-modal wiring from notes-list-tags.js). Single document-level wiring
 * for [data-rich-notes-editor] toolbars; loaded on pages with editable rich
 * surfaces (recorder, note detail). Blocking link/table prompts are now
 * async shared dialogs; rich-editor.js toolkit itself is untouched. */
import { promptDialog } from '../ui/dialog.js';
import { toast } from '../ui/toast.js';
import { escapeHtml } from '../utils.js';

const richEditor = window;
const promptTableDimension = (...args) => richEditor.promptTableDimension(...args);

document.addEventListener('click', async (event) => {
    const commandButton = event.target.closest('.rich-command');
    const rtlButton = event.target.closest('.rich-rtl-btn');
    const linkButton = event.target.closest('.rich-link-btn');
    const tableButton = event.target.closest('.rich-table-btn');
    const tableCommandButton = event.target.closest('.rich-table-command');
    const imageButton = event.target.closest('.rich-image-btn');
    const videoButton = event.target.closest('.rich-video-btn');
    const mathButton = event.target.closest('.rich-math-btn');
    const checklistButton = event.target.closest('.rich-checklist-btn');
    const checklistBox = event.target.closest('.rich-checklist-box');
    const blockquoteButton = event.target.closest('.rich-blockquote-btn');
    const codeBlockButton = event.target.closest('.rich-code-block-btn');
    const existingMath = event.target.closest('span.math-field[data-latex]');

    if (checklistBox) {
        const item = checklistBox.closest('li[data-checked]');
        const editor = checklistBox.closest('.rich-notes-surface');
        if (item && editor && editor.isContentEditable) {
            item.dataset.checked = item.dataset.checked === 'true' ? 'false' : 'true';
            richEditor.dispatchRichEditorInput(editor);
        }
        return;
    }

    if (existingMath) {
        const editor = existingMath.closest('.rich-notes-surface');
        if (editor && editor.isContentEditable) {
            richEditor.openMathEditor(editor, existingMath);
        }
        return;
    }

    if (mathButton) {
        richEditor.openMathEditor(richEditor.getRichEditorSurface(mathButton.closest('[data-rich-notes-editor]')));
        return;
    }

    if (rtlButton) {
        richEditor.toggleRtlBlock(rtlButton.closest('[data-rich-notes-editor]'));
        return;
    }

    if (checklistButton) {
        richEditor.insertChecklist(checklistButton.closest('[data-rich-notes-editor]'));
        return;
    }

    if (blockquoteButton) {
        richEditor.runRichCommand(blockquoteButton.closest('[data-rich-notes-editor]'), 'formatBlock', 'blockquote');
        return;
    }

    if (codeBlockButton) {
        richEditor.insertCodeBlock(codeBlockButton.closest('[data-rich-notes-editor]'));
        return;
    }

    if (tableCommandButton) {
        richEditor.runTableCommand(
            tableCommandButton.closest('[data-rich-notes-editor]'),
            tableCommandButton.dataset.tableCommand
        );
        return;
    }

    if (commandButton) {
        richEditor.runRichCommand(
            commandButton.closest('[data-rich-notes-editor]'),
            commandButton.dataset.command,
            commandButton.dataset.value || null
        );
        return;
    }

    if (linkButton) {
        const wrapper = linkButton.closest('[data-rich-notes-editor]');
        const url = await promptDialog({ title: 'Insert link', label: 'Link URL', confirmText: 'Insert' });
        if (url && url.trim()) {
            richEditor.runRichCommand(wrapper, 'createLink', url.trim());
        }
        return;
    }

    if (tableButton) {
        const editor = richEditor.getRichEditorSurface(tableButton.closest('[data-rich-notes-editor]'));
        if (editor) {
            const rows = await promptTableDimension('Rows', 3, 1, 20);
            if (rows === null) {
                return;
            }
            const columns = await promptTableDimension('Columns', 3, 1, 10);
            if (columns === null) {
                return;
            }
            if (rows && columns) {
                richEditor.insertHtmlAtCursor(editor, richEditor.buildTableHtml(rows, columns));
            }
        }
        return;
    }

    if (videoButton) {
        await richEditor.insertVideoEmbed(videoButton.closest('[data-rich-notes-editor]'));
        return;
    }

    if (imageButton) {
        const input = imageButton.closest('[data-rich-notes-editor]').querySelector('.rich-image-input');
        input.click();
    }
});

document.addEventListener('mousedown', (event) => {
    if (event.target.closest('.rich-notes-toolbar button')) {
        event.preventDefault();
    }
});

document.addEventListener('change', async (event) => {
    const colorInput = event.target.closest('.rich-color-input');
    const imageInput = event.target.closest('.rich-image-input');
    const formatSelect = event.target.closest('.rich-format-select');
    const fontSizeSelect = event.target.closest('.rich-font-size-select');
    const fontFamilySelect = event.target.closest('.rich-font-family-select');

    if (formatSelect) {
        richEditor.runRichCommand(
            formatSelect.closest('[data-rich-notes-editor]'),
            'formatBlock',
            formatSelect.value || 'p'
        );
        formatSelect.value = 'p';
        return;
    }

    if (fontSizeSelect) {
        if (fontSizeSelect.value) {
            richEditor.applyInlineStyle(
                fontSizeSelect.closest('[data-rich-notes-editor]'),
                { fontSize: fontSizeSelect.value }
            );
        }
        fontSizeSelect.value = '';
        return;
    }

    if (fontFamilySelect) {
        if (fontFamilySelect.value) {
            richEditor.applyInlineStyle(
                fontFamilySelect.closest('[data-rich-notes-editor]'),
                { fontFamily: fontFamilySelect.value }
            );
        }
        fontFamilySelect.value = '';
        return;
    }

    if (colorInput) {
        richEditor.runRichCommand(
            colorInput.closest('[data-rich-notes-editor]'),
            colorInput.dataset.command,
            colorInput.value
        );
        return;
    }

    if (imageInput && imageInput.files.length) {
        const wrapper = imageInput.closest('[data-rich-notes-editor]');
        const editor = richEditor.getRichEditorSurface(wrapper);
        try {
            const data = await richEditor.uploadRichNoteImage(imageInput.files[0]);
            richEditor.insertHtmlAtCursor(editor, `<img src="${data.url}" alt="">`);
        } catch (error) {
            toast.error(error.message);
        } finally {
            imageInput.value = '';
        }
    }
});

/* ---- math modal wiring (ported from notes-list-tags.js) ---- */
(function initMathModal() {
    const mathModalEl = document.getElementById('math-editor-modal');
    if (!mathModalEl) return;

    const latexInput = document.getElementById('math-editor-latex');
    const insertBtn = document.getElementById('insert-math-btn');
    if (!richEditor.initModalMathField()) {
        document.querySelectorAll('.rich-math-btn').forEach((button) => {
            button.disabled = true;
            button.title = 'MathQuill could not be loaded.';
        });
        return;
    }

    mathModalEl.addEventListener('shown.bs.modal', () => {
        setTimeout(() => {
            richEditor.modalMathField.focus();
            richEditor.modalMathField.reflow();
        }, 100);
    });

    latexInput.addEventListener('input', richEditor.syncModalFieldFromLatexInput);

    insertBtn.addEventListener('click', () => {
        const latex = richEditor.modalMathField.latex().trim();
        if (richEditor.editingMathSpan) {
            const editor = richEditor.editingMathSpan.closest('.rich-notes-surface');
            if (latex) {
                richEditor.editingMathSpan.dataset.latex = latex;
                window.renderMathFields(richEditor.editingMathSpan.parentElement);
            } else {
                richEditor.editingMathSpan.remove();
            }
            if (editor) editor.dispatchEvent(new Event('input', { bubbles: true }));
        } else if (richEditor.activeMathEditor && latex) {
            const id = `math-${Date.now()}-${Math.random().toString(36).slice(2)}`;
            const html = `<span id="${id}" class="math-field" data-latex="${escapeHtml(latex)}" contenteditable="false"></span>`;
            richEditor.restoreMathEditorSelection(richEditor.activeMathEditor);
            richEditor.insertHtmlAtCursor(richEditor.activeMathEditor, html + '&nbsp;');
            window.renderMathFields(richEditor.activeMathEditor);
        }
        window.bootstrap.Modal.getInstance(mathModalEl).hide();
        richEditor.editingMathSpan = null;
        richEditor.activeMathEditor = null;
        richEditor.savedMathEditorRange = null;
    });
})();
