/* Step 9: single tag-tree implementation. Replaces the copies in
 * notes-list-tags.js, notes-list-bulk.js and chat.js. Dependency-free except
 * utils (escapeHtml); no DOM access at load. */

import { escapeHtml } from '../utils.js';

export function buildTagTree(flatTags) {
    const byId = new Map(flatTags.map((tag) => [tag.id, { ...tag, children: [] }]));
    const roots = [];
    byId.forEach((node) => {
        if (node.parent_id && byId.has(node.parent_id)) {
            byId.get(node.parent_id).children.push(node);
        } else {
            roots.push(node);
        }
    });
    return roots;
}

export function flattenWithDepth(nodes, depth = 0, out = []) {
    nodes.forEach((node) => {
        out.push({ id: node.id, name: node.name, depth });
        flattenWithDepth(node.children, depth + 1, out);
    });
    return out;
}

/** Checkbox tree; cssPrefix yields `<prefix>-checkbox` input classes. */
export function renderCheckboxTree(nodes, checkedIds, cssPrefix) {
    return nodes.map((node) => `
        <li>
            <label class="d-flex align-items-center gap-2">
                <input type="checkbox" class="${cssPrefix}-checkbox" value="${node.id}"
                    ${checkedIds.has(node.id) ? 'checked' : ''}>
                <span class="tag-badge" style="background-color:${node.color}">${escapeHtml(node.name)}</span>
            </label>
            ${node.children.length ? `<ul class="tag-children">${renderCheckboxTree(node.children, checkedIds, cssPrefix)}</ul>` : ''}
        </li>
    `).join('');
}

/** Single-select radio tree; defaults match the legacy bulk-tag tree. */
export function renderRadioTree(nodes, inputName = 'bulk-tag-radio') {
    return nodes.map((node) => `
        <li>
            <label class="d-flex align-items-center gap-2">
                <input type="radio" class="bulk-tag-radio" name="${inputName}" value="${node.id}">
                <span class="tag-badge" style="background-color:${node.color}">${escapeHtml(node.name)}</span>
            </label>
            ${node.children.length ? `<ul class="tag-children">${renderRadioTree(node.children, inputName)}</ul>` : ''}
        </li>
    `).join('');
}
