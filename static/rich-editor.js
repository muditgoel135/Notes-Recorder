const EMPTY_RICH_NOTE_HTML = "<p><br></p>";

let activeMathEditor = null;
let editingMathSpan = null;
let savedMathEditorRange = null;
let mathQuillInterface = null;
let modalMathField = null;
let isSyncingMathLatex = false;

// --- Shared helpers ---

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value);
    return div.innerHTML;
}

function debounce(fn, delayMs) {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), delayMs);
    };
}

function closestElement(node, selector, boundary) {
    let current = node && node.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    while (current && current !== boundary) {
        if (current.matches(selector)) {
            return current;
        }
        current = current.parentElement;
    }
    return current && current.matches(selector) ? current : null;
}

function normalizeRichNoteHtml(html) {
    const value = (html || "").trim();
    return value && value !== EMPTY_RICH_NOTE_HTML ? value : "";
}

// --- Rich editor commands ---

function getRichEditorSurface(wrapper) {
    return wrapper ? wrapper.querySelector(".rich-notes-surface") : null;
}

function focusRichEditor(editor) {
    editor.focus();
}

function runRichCommand(wrapper, command, value = null) {
    const editor = getRichEditorSurface(wrapper);
    if (!editor) {
        return;
    }
    focusRichEditor(editor);
    document.execCommand(command, false, value);
    editor.dispatchEvent(new Event("input", { bubbles: true }));
}

function insertHtmlAtCursor(editor, html) {
    focusRichEditor(editor);
    document.execCommand("insertHTML", false, html);
    editor.dispatchEvent(new Event("input", { bubbles: true }));
}

function dispatchRichEditorInput(editor) {
    editor.dispatchEvent(new Event("input", { bubbles: true }));
}

function selectionRangeInEditor(editor) {
    const selection = window.getSelection();
    if (!editor || !selection || selection.rangeCount === 0) {
        return null;
    }

    const range = selection.getRangeAt(0);
    const container = range.commonAncestorContainer;
    const element = container.nodeType === Node.ELEMENT_NODE ? container : container.parentElement;
    return element && editor.contains(element) ? range : null;
}

function wrapSelectionWithElement(editor, element) {
    const range = selectionRangeInEditor(editor);
    if (!range || range.collapsed) {
        alert("Select text to format first.");
        return false;
    }

    element.appendChild(range.extractContents());
    range.insertNode(element);
    const selection = window.getSelection();
    selection.removeAllRanges();
    const nextRange = document.createRange();
    nextRange.selectNodeContents(element);
    selection.addRange(nextRange);
    dispatchRichEditorInput(editor);
    return true;
}

function applyInlineStyle(wrapper, styles) {
    const editor = getRichEditorSurface(wrapper);
    if (!editor) {
        return;
    }
    focusRichEditor(editor);
    const span = document.createElement("span");
    Object.entries(styles).forEach(([property, value]) => {
        if (value) {
            span.style[property] = value;
        }
    });
    wrapSelectionWithElement(editor, span);
}

function selectedBlockInEditor(editor) {
    const range = selectionRangeInEditor(editor);
    if (!range) {
        return null;
    }
    const node = range.startContainer.nodeType === Node.ELEMENT_NODE
        ? range.startContainer
        : range.startContainer.parentElement;
    return closestElement(node, "p, div, h1, h2, h3, h4, h5, h6, li, blockquote, pre", editor) || editor;
}

function toggleRtlBlock(wrapper) {
    const editor = getRichEditorSurface(wrapper);
    const block = selectedBlockInEditor(editor);
    if (!editor || !block) {
        return;
    }
    const isRtl = block.style.direction === "rtl" || block.getAttribute("dir") === "rtl";
    if (isRtl) {
        block.style.direction = "";
        block.style.unicodeBidi = "";
        block.removeAttribute("dir");
    } else {
        block.style.direction = "rtl";
        block.style.unicodeBidi = "plaintext";
        block.setAttribute("dir", "rtl");
    }
    dispatchRichEditorInput(editor);
}

function insertChecklist(wrapper) {
    const editor = getRichEditorSurface(wrapper);
    if (!editor) {
        return;
    }
    insertHtmlAtCursor(
        editor,
        '<ul class="rich-checklist"><li data-checked="false"><span class="rich-checklist-box" contenteditable="false"></span>Task</li></ul><p><br></p>'
    );
}

function insertCodeBlock(wrapper) {
    const editor = getRichEditorSurface(wrapper);
    if (!editor) {
        return;
    }
    const range = selectionRangeInEditor(editor);
    if (range && !range.collapsed) {
        const text = range.toString();
        range.deleteContents();
        range.insertNode(document.createRange().createContextualFragment(`<pre><code>${escapeHtml(text)}</code></pre><p><br></p>`));
        dispatchRichEditorInput(editor);
        return;
    }
    insertHtmlAtCursor(editor, "<pre><code><br></code></pre><p><br></p>");
}

function normalizeVideoEmbed(input) {
    const value = (input || "").trim();
    if (!value) {
        return null;
    }

    const iframeMatch = value.match(/<iframe\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/i);
    const source = iframeMatch ? iframeMatch[1] : value;

    let url;
    try {
        url = new URL(source, window.location.origin);
    } catch (error) {
        return null;
    }

    const host = url.hostname.toLowerCase().replace(/^www\./, "");
    let embedUrl = "";
    let title = "Embedded video";

    if (host === "youtu.be") {
        const id = url.pathname.split("/").filter(Boolean)[0];
        if (id) {
            embedUrl = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}`;
            title = "YouTube video";
        }
    } else if (host === "youtube.com" || host === "m.youtube.com" || host === "youtube-nocookie.com") {
        const pathParts = url.pathname.split("/").filter(Boolean);
        const id = url.searchParams.get("v")
            || (pathParts[0] === "embed" ? pathParts[1] : "")
            || (pathParts[0] === "shorts" ? pathParts[1] : "");
        if (id) {
            embedUrl = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}`;
            title = "YouTube video";
        }
    } else if (host === "vimeo.com" || host === "player.vimeo.com") {
        const pathParts = url.pathname.split("/").filter(Boolean);
        const id = host === "player.vimeo.com" && pathParts[0] === "video" ? pathParts[1] : pathParts[0];
        if (id && /^\d+$/.test(id)) {
            embedUrl = `https://player.vimeo.com/video/${encodeURIComponent(id)}`;
            title = "Vimeo video";
        }
    }

    if (!embedUrl) {
        return null;
    }

    return `<div class="rich-video-embed"><iframe src="${embedUrl}" title="${title}" width="560" height="315" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe></div><p><br></p>`;
}

function insertVideoEmbed(wrapper) {
    const editor = getRichEditorSurface(wrapper);
    if (!editor) {
        return;
    }
    const embedInput = prompt("Paste a YouTube or Vimeo URL/embed code:");
    if (embedInput === null) {
        return;
    }
    const html = normalizeVideoEmbed(embedInput);
    if (!html) {
        alert("Use a YouTube or Vimeo URL/embed code.");
        return;
    }
    insertHtmlAtCursor(editor, html);
}

// --- MathQuill editor ---

function getMathModal() {
    return document.getElementById("math-editor-modal");
}

function getMathInput() {
    return document.getElementById("math-editor-latex");
}

function getMathFieldElement() {
    return document.getElementById("math-editor-field");
}

function setModalMathLatex(latex) {
    const input = getMathInput();
    if (!input) {
        return;
    }

    isSyncingMathLatex = true;
    input.value = latex || "";
    if (modalMathField) {
        modalMathField.latex(latex || "");
    }
    isSyncingMathLatex = false;
}

function syncLatexFromModalField() {
    const input = getMathInput();
    if (!input || !modalMathField || isSyncingMathLatex) {
        return;
    }
    input.value = modalMathField.latex();
}

function syncModalFieldFromLatexInput() {
    const input = getMathInput();
    if (!input || !modalMathField || isSyncingMathLatex) {
        return;
    }
    isSyncingMathLatex = true;
    modalMathField.latex(input.value);
    isSyncingMathLatex = false;
}

function initMathQuill() {
    if (mathQuillInterface || typeof MathQuill === "undefined") {
        return mathQuillInterface;
    }
    mathQuillInterface = MathQuill.getInterface(2);
    return mathQuillInterface;
}

function initModalMathField() {
    const MQ = initMathQuill();
    const fieldEl = getMathFieldElement();
    if (!MQ || !fieldEl) {
        return null;
    }
    if (!modalMathField) {
        modalMathField = MQ.MathField(fieldEl, {
            spaceBehavesLikeTab: true,
            restrictMismatchedBrackets: true,
            handlers: {
                edit: syncLatexFromModalField,
            },
        });
    }
    return modalMathField;
}

function openMathEditor(editor, mathSpan = null) {
    const modalEl = getMathModal();
    const input = getMathInput();
    if (!modalEl || !input || !editor) {
        return;
    }
    if (!initModalMathField()) {
        alert("Math editor assets could not be loaded.");
        return;
    }

    const range = selectionRangeInEditor(editor);
    savedMathEditorRange = range ? range.cloneRange() : null;
    activeMathEditor = editor;
    editingMathSpan = mathSpan;
    setModalMathLatex(mathSpan ? mathSpan.dataset.latex || "" : "");
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
}

function restoreMathEditorSelection(editor) {
    if (!editor) {
        return;
    }
    editor.focus();
    if (!savedMathEditorRange) {
        return;
    }
    try {
        if (
            editor.contains(savedMathEditorRange.startContainer) &&
            editor.contains(savedMathEditorRange.endContainer)
        ) {
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(savedMathEditorRange.cloneRange());
        }
    } catch (error) {
        // Range refers to detached nodes; nothing to restore.
    }
}

// --- Tables ---

function clampInteger(value, min, max, fallback) {
    const number = Number.parseInt(value, 10);
    if (Number.isNaN(number)) {
        return fallback;
    }
    return Math.max(min, Math.min(max, number));
}

function promptTableDimension(label, fallback, min, max) {
    const value = prompt(`${label}:`, String(fallback));
    if (value === null) {
        return null;
    }
    return clampInteger(value, min, max, fallback);
}

function buildTableHtml(rows, columns) {
    const headerCells = Array.from({ length: columns }, () => "<th>Header</th>").join("");
    const bodyRows = Array.from({ length: Math.max(0, rows - 1) }, () => {
        const cells = Array.from({ length: columns }, () => "<td>Cell</td>").join("");
        return `<tr>${cells}</tr>`;
    }).join("");
    return `<table><tbody><tr>${headerCells}</tr>${bodyRows}</tbody></table><p><br></p>`;
}

function getSelectedTableCell(wrapper) {
    const editor = getRichEditorSurface(wrapper);
    const selection = window.getSelection();
    if (!editor || !selection || selection.rangeCount === 0) {
        return null;
    }

    const node = selection.anchorNode || selection.getRangeAt(0).startContainer;
    const cell = closestElement(node, "td, th", editor);
    return cell && editor.contains(cell) ? cell : null;
}

function createTableCell(tagName, html = "Cell") {
    const cell = document.createElement(tagName);
    cell.innerHTML = html;
    return cell;
}

function getTableColumnCount(table) {
    return Math.max(
        1,
        ...Array.from(table.rows).map((row) =>
            Array.from(row.cells).reduce((total, cell) => total + (cell.colSpan || 1), 0)
        )
    );
}

function getVisualColumnIndex(cell) {
    let index = 0;
    let current = cell.previousElementSibling;
    while (current) {
        index += current.colSpan || 1;
        current = current.previousElementSibling;
    }
    return index;
}

function getCellAtVisualColumn(row, columnIndex) {
    let index = 0;
    for (const cell of row.cells) {
        const span = cell.colSpan || 1;
        if (columnIndex >= index && columnIndex < index + span) {
            return cell;
        }
        index += span;
    }
    return null;
}

function insertTableRow(cell) {
    const row = cell.closest("tr");
    const table = cell.closest("table");
    if (!row || !table) {
        return;
    }

    const newRow = table.insertRow(row.rowIndex + 1);
    const columnCount = getTableColumnCount(table);
    for (let index = 0; index < columnCount; index += 1) {
        newRow.appendChild(createTableCell("td"));
    }
}

function deleteTableRow(cell) {
    const row = cell.closest("tr");
    const table = cell.closest("table");
    if (!row || !table) {
        return;
    }

    if (table.rows.length <= 1) {
        table.remove();
        return;
    }
    row.remove();
}

function insertTableColumn(cell) {
    const table = cell.closest("table");
    if (!table) {
        return;
    }

    const insertAfter = getVisualColumnIndex(cell) + (cell.colSpan || 1) - 1;
    Array.from(table.rows).forEach((row) => {
        const existingCell = getCellAtVisualColumn(row, insertAfter);
        const tagName = row.rowIndex === 0 ? "th" : "td";
        const newCell = createTableCell(tagName, row.rowIndex === 0 ? "Header" : "Cell");
        if (existingCell && existingCell.parentElement === row) {
            existingCell.after(newCell);
        } else {
            row.appendChild(newCell);
        }
    });
}

function deleteTableColumn(cell) {
    const table = cell.closest("table");
    if (!table) {
        return;
    }

    const columnIndex = getVisualColumnIndex(cell);
    Array.from(table.rows).forEach((row) => {
        const target = getCellAtVisualColumn(row, columnIndex);
        if (!target) {
            return;
        }
        if ((target.colSpan || 1) > 1) {
            target.colSpan -= 1;
        } else {
            target.remove();
        }
    });

    if (!Array.from(table.rows).some((row) => row.cells.length > 0)) {
        table.remove();
    }
}

function mergeTableCellRight(cell) {
    const nextCell = cell.nextElementSibling;
    if (!nextCell || !["TD", "TH"].includes(nextCell.tagName)) {
        alert("Select a cell with another cell to its right.");
        return;
    }

    cell.colSpan = (cell.colSpan || 1) + (nextCell.colSpan || 1);
    cell.innerHTML = `${cell.innerHTML}<br>${nextCell.innerHTML}`;
    nextCell.remove();
}

function mergeTableCellDown(cell) {
    const row = cell.closest("tr");
    const nextRow = row ? row.nextElementSibling : null;
    if (!row || !nextRow) {
        alert("Select a cell with another cell below it.");
        return;
    }

    const belowCell = getCellAtVisualColumn(nextRow, getVisualColumnIndex(cell));
    if (!belowCell || belowCell.colSpan !== cell.colSpan) {
        alert("The cell below must align with the selected cell.");
        return;
    }

    cell.rowSpan = (cell.rowSpan || 1) + (belowCell.rowSpan || 1);
    cell.innerHTML = `${cell.innerHTML}<br>${belowCell.innerHTML}`;
    belowCell.remove();
}

function splitTableCell(cell) {
    const row = cell.closest("tr");
    if (!row) {
        return;
    }

    const colSpan = cell.colSpan || 1;
    const rowSpan = cell.rowSpan || 1;
    if (colSpan === 1 && rowSpan === 1) {
        alert("This cell is not merged.");
        return;
    }

    cell.colSpan = 1;
    cell.rowSpan = 1;
    for (let index = 1; index < colSpan; index += 1) {
        cell.after(createTableCell(cell.tagName.toLowerCase(), "&nbsp;"));
    }
    if (rowSpan > 1) {
        let targetRow = row.nextElementSibling;
        for (let rowOffset = 1; rowOffset < rowSpan && targetRow; rowOffset += 1) {
            targetRow.insertBefore(createTableCell("td", "&nbsp;"), targetRow.cells[cell.cellIndex] || null);
            targetRow = targetRow.nextElementSibling;
        }
    }
}

function runTableCommand(wrapper, command) {
    const cell = getSelectedTableCell(wrapper);
    if (!cell) {
        alert("Place the cursor inside a table cell first.");
        return;
    }

    if (command === "add-row") {
        insertTableRow(cell);
    } else if (command === "delete-row") {
        deleteTableRow(cell);
    } else if (command === "add-column") {
        insertTableColumn(cell);
    } else if (command === "delete-column") {
        deleteTableColumn(cell);
    } else if (command === "merge-right") {
        mergeTableCellRight(cell);
    } else if (command === "merge-down") {
        mergeTableCellDown(cell);
    } else if (command === "split-cell") {
        splitTableCell(cell);
    }

    const editor = getRichEditorSurface(wrapper);
    if (editor) {
        editor.dispatchEvent(new Event("input", { bubbles: true }));
    }
}

// --- Image upload ---

async function uploadRichNoteImage(file) {
    const formData = new FormData();
    formData.append("image", file);
    const response = await fetch("/api/note_images", {
        method: "POST",
        body: formData,
    });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "Could not upload image.");
    }
    return response.json();
}
