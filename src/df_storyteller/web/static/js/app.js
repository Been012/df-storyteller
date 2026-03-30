/* df-storyteller frontend */

async function switchWorld(world) {
    await fetch('/api/worlds/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ world: world })
    });
    window.location.reload();
}

/* ========== Keyboard Shortcuts ========== */

document.addEventListener('keydown', (e) => {
    // Don't trigger shortcuts when typing in inputs/textareas
    const tag = document.activeElement.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    switch (e.key) {
        case '/':
            e.preventDefault();
            // Focus search bar on current page
            const search = document.getElementById('lore-search') || document.getElementById('event-filter');
            if (search) { search.focus(); search.select(); }
            break;
        case '?':
            // Toggle shortcut help
            let help = document.getElementById('shortcut-help');
            if (help) {
                help.style.display = help.style.display === 'none' ? '' : 'none';
            } else {
                help = document.createElement('div');
                help.id = 'shortcut-help';
                help.className = 'shortcut-help';
                help.innerHTML = '<h3>Keyboard Shortcuts</h3>' +
                    '<div><kbd>/</kbd> Focus search</div>' +
                    '<div><kbd>?</kbd> Toggle this help</div>' +
                    '<div><kbd>Esc</kbd> Close / clear search</div>' +
                    '<div><kbd>1-4</kbd> Switch legend tabs</div>' +
                    '<div><kbd>P</kbd> Toggle pinned lore</div>' +
                    '<div><kbd>Alt+&larr;</kbd> Go back</div>' +
                    '<div style="margin-top:0.5rem;font-size:0.8rem;color:var(--ink-faded);">Click anywhere to dismiss</div>';
                help.onclick = () => help.style.display = 'none';
                document.body.appendChild(help);
            }
            break;
        case 'Escape':
            // Clear search or close overlays
            const searchInput = document.getElementById('lore-search');
            if (searchInput && searchInput.value) {
                searchInput.value = '';
                if (typeof filterLore === 'function') filterLore('');
            }
            document.activeElement.blur();
            const helpEl = document.getElementById('shortcut-help');
            if (helpEl) helpEl.style.display = 'none';
            break;
        case '1': case '2': case '3': case '4':
            // Switch legends tabs (if on legends page)
            const tabs = document.querySelectorAll('.legends-tab');
            const idx = parseInt(e.key) - 1;
            if (tabs.length > idx) tabs[idx].click();
            break;
        case 'p': case 'P':
            togglePinsSidebar();
            break;
    }
});

/* ========== Global Pins Sidebar ========== */

const PIN_TYPE_URLS = { figure: '/lore/figure/', civilization: '/lore/civ/', site: '/lore/site/', artifact: '/lore/artifact/', war: '/lore/war/' };
const PIN_TYPE_ICONS = { figure: '\u2694', civilization: '\u2655', site: '\u2302', artifact: '\u2736', war: '\u2620' };

function togglePinsSidebar() {
    const sidebar = document.getElementById('pins-sidebar');
    if (sidebar) sidebar.classList.toggle('open');
}

function loadPinsSidebar() {
    fetch('/api/lore/pins')
        .then(r => r.json())
        .then(pins => {
            const list = document.getElementById('pins-sidebar-list');
            const empty = document.getElementById('pins-sidebar-empty');
            const countEl = document.getElementById('pins-toggle-count');
            if (!list) return;

            list.innerHTML = '';

            if (!pins.length) {
                empty.style.display = '';
                if (countEl) countEl.textContent = '';
                return;
            }

            empty.style.display = 'none';
            if (countEl) countEl.textContent = pins.length;

            for (const pin of pins) {
                const div = document.createElement('div');
                div.className = 'pin-item';

                const icon = PIN_TYPE_ICONS[pin.entity_type] || '\u25CF';
                const url = (PIN_TYPE_URLS[pin.entity_type] || '/lore/figure/') + pin.entity_id;

                let html = '<div class="pin-item-header">';
                html += '<span class="pin-item-icon">' + icon + '</span>';
                html += '<a href="' + url + '" class="pin-item-link">' + pin.name + '</a>';
                html += '<span class="pin-item-type">' + (pin.entity_type || '') + '</span>';
                html += '<button class="pin-item-remove" onclick="removeGlobalPin(\'' + pin.id + '\')" title="Unpin">&times;</button>';
                html += '</div>';
                if (pin.note) {
                    html += '<div class="pin-item-note">' + pin.note + '</div>';
                }

                div.innerHTML = html;
                list.appendChild(div);
            }
        })
        .catch(() => {});
}

async function removeGlobalPin(pinId) {
    await fetch('/api/lore/pins/' + pinId, { method: 'DELETE' });
    loadPinsSidebar();
}

async function pinFromList(entityType, entityId, name) {
    const resp = await fetch('/api/lore/pins', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity_type: entityType, entity_id: entityId, name: name, note: '' }),
    });
    if (resp.ok) {
        loadPinsSidebar();
        // Flash the toggle to indicate success
        const toggle = document.getElementById('pins-toggle');
        if (toggle) {
            toggle.style.background = 'rgba(201, 168, 76, 0.3)';
            setTimeout(() => toggle.style.background = '', 600);
        }
    }
}

// Load pins on page load
document.addEventListener('DOMContentLoaded', loadPinsSidebar);
