/**
 * Bug Tracker — Admin page interactions
 * Features: ticket #IDs, inline editing, comment threads, #123 bug linking, modal detail
 */
(function() {
    'use strict';

    const PAGE_DATA = JSON.parse(document.getElementById('bugPageData').textContent);
    let activeBugs = PAGE_DATA.active || [];
    let completedBugs = PAGE_DATA.completed || [];
    let ideas = PAGE_DATA.ideas || [];
    var USER_NAME = PAGE_DATA.userName || 'Admin';
    let currentTab = 'active';
    let selectedBugId = null;
    let pendingFile = null;

    // === Helpers ===

    function escapeHtml(s) {
        if (!s) return '';
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function linkifyBugRefs(text) {
        // Convert #123 references to clickable bug links
        // Convert @mentions to highlighted mailto links
        return escapeHtml(text)
            .replace(/#(\d+)/g, function(match, id) {
                return '<a class="bt-bug-link" href="javascript:void(0)" onclick="BT.showDetail(' + id + ')">' + match + '</a>';
            })
            .replace(/@(\w+)/g, function(match, name) {
                return '<a class="bt-mention-link" href="mailto:' + name + '" onclick="return false;" title="Notified via email">' + match + '</a>';
            });
    }

    function formatCommentBody(text) {
        // Linkify #123 bug refs BEFORE markdown (on raw text, not HTML entities)
        var processed = text.replace(/(^|[^&])#(\d+)/g, function(match, prefix, id) {
            return prefix + '[[BUG:' + id + ']]';
        });
        // @mentions on raw text
        processed = processed.replace(/@(\w+)/g, '[[MENTION:$1]]');

        // Use marked.js for full GFM markdown
        var html;
        if (typeof marked !== 'undefined') {
            marked.setOptions({breaks: true, gfm: true});
            html = marked.parse(processed);
        } else {
            html = escapeHtml(processed).replace(/\n/g, '<br>');
        }

        // Restore bug refs and mentions as HTML links
        html = html.replace(/\[\[BUG:(\d+)\]\]/g, function(_, id) {
            return '<a class="bt-bug-link" href="javascript:void(0)" onclick="BT.showDetail(' + id + ')">#' + id + '</a>';
        });
        html = html.replace(/\[\[MENTION:(\w+)\]\]/g, function(_, name) {
            return '<a class="bt-mention-link" href="mailto:' + name + '" onclick="return false;" title="Notified via email">@' + name + '</a>';
        });
        return html;
    }

    function statusClass(status) {
        var map = {
            'New': 'new', 'Backlog': 'backlog', 'Awaiting QA': 'awaiting',
            'ReOpen': 'dev', 'Done': 'done', 'Ready For Dev': 'ready',
            // Legacy statuses still map correctly
            'In Process': 'backlog', 'Todo': 'new', 'In Progress': 'backlog', 'In Review': 'awaiting',
            'Blocked': 'blocked', 'Working On': 'working', 'AWAITING_QA': 'awaiting',
            'DEV_NEEDED': 'dev', 'NEEDS_MORE_INFO': 'info'
        };
        return 'bt-status bt-status-' + (map[status] || 'new');
    }

    function formatDate(d) {
        if (!d) return '';
        return new Date(d).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/Los_Angeles'});
    }

    function formatDateTime(d) {
        if (!d) return '';
        return new Date(d).toLocaleString('en-US', {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/Los_Angeles'});
    }

    // === Bug List Rendering ===

    function getSearchText() {
        var el = document.getElementById('btSearch');
        return el ? el.value.toLowerCase().trim() : '';
    }

    function matchesSearch(item, search) {
        if (!search) return true;
        var searchNum = parseInt(search.replace('#', ''));
        if (!isNaN(searchNum) && item.id === searchNum) return true;
        // Split search into words for loose matching — ALL words must match somewhere
        var words = search.split(/\s+/).filter(function(w) { return w.length > 0; });
        var blob = [item.name, item.description, item.to_validate, item.qa_notes,
                     item.extra_notes, item.notes, item.category, item.status,
                     item.priority, item.type, String(item.id)].join(' ').toLowerCase();
        return words.every(function(w) { return blob.indexOf(w) !== -1; });
    }

    function renderBugList() {
        var list = document.getElementById('btBugList');
        var filters = document.getElementById('btFilters');
        var search = getSearchText();

        if (currentTab === 'ideas') {
            // Show only the search box, hide status/priority/sort dropdowns
            filters.style.display = 'flex';
            var dropdowns = filters.querySelectorAll('select');
            dropdowns.forEach(function(d) { d.style.display = 'none'; });
            document.getElementById('btSearch').style.display = '';
            renderIdeas(list, search);
            return;
        }

        // Active/Completed: show all filters
        filters.style.display = 'flex';
        var dropdowns = filters.querySelectorAll('select');
        dropdowns.forEach(function(d) { d.style.display = currentTab === 'active' ? '' : 'none'; });
        var bugs = currentTab === 'active' ? getFilteredBugs() : completedBugs.filter(function(b) { return matchesSearch(b, search); });

        if (!bugs.length) {
            list.innerHTML = '<div class="bt-empty">No ' + currentTab + ' bugs</div>';
            return;
        }

        list.innerHTML = bugs.map(function(b) {
            var qaCheck = b.qa_approved ? '<span class="bt-qa-check">QA</span>' : '';
            var thumb = b.screenshot_url
                ? '<img src="' + escapeHtml(b.screenshot_url) + '" class="bt-thumb" loading="lazy">'
                : '';
            return '<div class="bt-row" data-id="' + b.id + '" onclick="BT.showDetail(' + b.id + ')">' +
                '<span class="bt-ticket">#' + b.id + '</span>' +
                '<span class="bt-badge bt-badge-' + b.priority + '">' + b.priority + '</span>' +
                '<span class="bt-row-name">' + escapeHtml(b.name) + '</span>' +
                '<span class="' + statusClass(b.status) + '">' + escapeHtml(b.status) + '</span>' +
                '<span style="color:rgba(255,255,255,0.4);font-size:12px;">' + escapeHtml(b.type) + '</span>' +
                '<span>' + qaCheck + '</span>' +
                '<span>' + thumb + '</span>' +
                '</div>';
        }).join('');
    }

    function renderIdeas(list, search) {
        var filtered = ideas.filter(function(i) { return matchesSearch(i, search); });
        if (!filtered.length) {
            list.innerHTML = '<div class="bt-empty">' + (search ? 'No ideas matching "' + escapeHtml(search) + '"' : 'No ideas in the parking lot') + '</div>';
            return;
        }
        list.innerHTML = filtered.map(function(idea) {
            var promoted = idea.promoted_to_bug_id ? ' (promoted)' : '';
            return '<div class="bt-idea-row" onclick="BT.showIdeaDetail(' + idea.id + ')">' +
                '<span class="bt-row-name">' + escapeHtml(idea.name) + promoted + '</span>' +
                '<span class="bt-category bt-cat-' + idea.category + '">' + escapeHtml(idea.category) + '</span>' +
                '<span style="color:rgba(255,255,255,0.4);font-size:12px;">' + formatDate(idea.created_at) + '</span>' +
                '</div>';
        }).join('');
    }

    function getFilteredBugs() {
        var status = document.getElementById('btFilterStatus').value;
        var priority = document.getElementById('btFilterPriority').value;
        var search = getSearchText();
        var sortBy = (document.getElementById('btSort') || {}).value || 'priority';
        var filtered = activeBugs.filter(function(b) {
            if (status && b.status !== status) return false;
            if (priority && b.priority !== priority) return false;
            if (!matchesSearch(b, search)) return false;
            return true;
        });

        // Sort
        var priOrder = {P1:1, P2:2, P3:3, P4:4, P5:5};
        if (sortBy === 'newest') {
            filtered.sort(function(a, b) { return new Date(b.created_at) - new Date(a.created_at); });
        } else if (sortBy === 'oldest') {
            filtered.sort(function(a, b) { return new Date(a.created_at) - new Date(b.created_at); });
        } else if (sortBy === 'updated') {
            filtered.sort(function(a, b) { return new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at); });
        } else if (sortBy === 'id') {
            filtered.sort(function(a, b) { return b.id - a.id; });
        } else {
            // Default: priority then newest
            filtered.sort(function(a, b) {
                var pd = (priOrder[a.priority]||6) - (priOrder[b.priority]||6);
                return pd !== 0 ? pd : new Date(b.created_at) - new Date(a.created_at);
            });
        }
        return filtered;
    }

    // === Detail Modal ===

    function showDetail(bugId) {
        selectedBugId = bugId;
        fetch('/api/admin/bugs/' + bugId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) return;
                renderDetailModal(data.bug, data.history, data.comments || []);
            });
    }

    function renderDetailModal(bug, history, comments) {
        var overlay = document.getElementById('btDetailModal');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'btDetailModal';
            overlay.className = 'bt-modal-overlay';
            // Don't close on backdrop click — prevents losing typed content in comment/edit fields
            // Close only via X button, Cancel, or Escape key
            document.body.appendChild(overlay);
        }

        var isActive = !bug.completed_at;

        // Screenshots
        var screenshots = '';
        if (bug.screenshot_url) {
            screenshots += '<a href="' + escapeHtml(bug.screenshot_url) + '" target="_blank">' +
                '<img src="' + escapeHtml(bug.screenshot_url) + '" class="bt-screenshot-img" loading="lazy"></a>';
        }
        if (bug.screenshot_2_url) {
            screenshots += '<a href="' + escapeHtml(bug.screenshot_2_url) + '" target="_blank">' +
                '<img src="' + escapeHtml(bug.screenshot_2_url) + '" class="bt-screenshot-img" loading="lazy"></a>';
        }

        // Actions bar
        var actions = '';
        if (isActive) {
            actions += '<select class="bt-input" style="width:auto;" onchange="BT.updateField(' + bug.id + ',\'status\',this.value)">';
            ['New','Backlog','Ready For Dev','Awaiting QA','ReOpen'].forEach(function(s) {
                actions += '<option' + (bug.status === s ? ' selected' : '') + '>' + s + '</option>';
            });
            actions += '</select>';
            actions += '<select class="bt-input" style="width:auto;" onchange="BT.updateField(' + bug.id + ',\'priority\',this.value)">';
            ['P1','P2','P3','P4','P5'].forEach(function(p) {
                actions += '<option' + (bug.priority === p ? ' selected' : '') + '>' + p + '</option>';
            });
            actions += '</select>';
            actions += '<button class="bt-btn bt-btn-sm' + (bug.qa_approved ? ' bt-btn-success' : '') + '" onclick="BT.toggleQA(' + bug.id + ',' + !bug.qa_approved + ')">' +
                (bug.qa_approved ? 'QA Passed ✓' : 'Mark QA Passed') + '</button>';
            if (bug.qa_approved) {
                actions += '<button class="bt-btn bt-btn-sm bt-btn-success" onclick="BT.completeBug(' + bug.id + ')">Complete</button>';
            }
            actions += '<button class="bt-btn bt-btn-sm" onclick="BT.uploadScreenshot(' + bug.id + ')">Upload Screenshot</button>';
        } else {
            actions += '<button class="bt-btn bt-btn-sm bt-btn-danger" onclick="BT.reopenBug(' + bug.id + ')">Reopen</button>';
        }
        actions += '<button class="bt-btn bt-btn-sm" style="margin-left:auto;" onclick="BT.copyBugLink(' + bug.id + ',this)">Copy Link</button>';
        actions += '<a href="/pilgrimbot?bug=' + bug.id + '" target="_blank" class="bt-btn bt-btn-sm" style="text-decoration:none;color:rgba(255,255,255,0.5);">Ask PilgrimBot about this</a>';

        // Parent bug link
        var parentLink = bug.parent_bug_id
            ? '<div class="bt-field"><div class="bt-field-label">Parent Bug</div><div class="bt-field-value"><a class="bt-bug-link" href="javascript:void(0)" onclick="BT.showDetail(' + bug.parent_bug_id + ')">#' + bug.parent_bug_id + '</a></div></div>'
            : '';

        // Editable text fields
        function editableField(label, field, value) {
            return '<div class="bt-field">' +
                '<div class="bt-field-label">' + label + '</div>' +
                '<div class="bt-field-value bt-field-editable" data-field="' + field + '" data-bug="' + bug.id + '" onclick="BT.startEdit(this, ' + bug.id + ',\'' + field + '\')">' +
                (value ? linkifyBugRefs(value) : '') +
                '</div></div>';
        }

        // History
        var historyHtml = '';
        if (history && history.length) {
            historyHtml = '<div class="bt-history"><div class="bt-history-title">History (' + history.length + ')</div>' +
                history.map(function(h) {
                    var val = escapeHtml(h.new_value || '');
                    if (val.length > 120) val = val.substring(0, 120) + '...';
                    var old = escapeHtml(h.old_value || '');
                    if (old.length > 60) old = old.substring(0, 60) + '...';
                    return '<div class="bt-history-bubble">' +
                        '<div class="bt-history-bubble-header">' +
                            '<strong>' + escapeHtml(h.changed_by) + '</strong> changed <em>' + escapeHtml(h.field_name) + '</em>' +
                            '<span class="bt-bubble-time">' + formatDateTime(h.created_at) + '</span>' +
                        '</div>' +
                        (old ? '<div class="bt-history-old">' + old + '</div>' : '') +
                        '<div class="bt-history-new">' + val + '</div>' +
                        '</div>';
                }).join('') + '</div>';
        }

        // Comments thread
        var commentsHtml = '<div class="bt-comments">' +
            '<div class="bt-comments-title">Discussion (' + comments.length + ') <span style="font-size:10px;text-transform:none;opacity:0.5;">newest first</span></div>' +
            '<div class="bt-comment-input">' +
                '<textarea id="btCommentBody" placeholder="Add a comment... Use #123 to reference other bugs" rows="2"></textarea>' +
                '<button class="bt-btn bt-btn-sm bt-btn-primary" onclick="BT.addComment(' + bug.id + ')">Post</button>' +
            '</div>';
        if (comments.length) {
            commentsHtml += comments.map(function(c) {
                var isPilgrimBot = c.author === 'PilgrimBot';
                var bubbleClass = isPilgrimBot ? 'bt-bubble bt-bubble-bot' : 'bt-bubble bt-bubble-human';
                return '<div class="' + bubbleClass + '">' +
                    '<div class="bt-bubble-header">' +
                        '<strong>' + escapeHtml(c.author) + '</strong>' +
                        '<span class="bt-bubble-time">' + formatDateTime(c.created_at) + '</span>' +
                    '</div>' +
                    '<div class="bt-bubble-body">' + formatCommentBody(c.body) + '</div>' +
                    '</div>';
            }).join('');
        } else {
            commentsHtml += '<div style="color:rgba(255,255,255,0.3);font-size:13px;margin-bottom:8px;">No comments yet</div>';
        }
        commentsHtml += '</div>';

        overlay.innerHTML =
            '<div class="bt-modal">' +
                '<div class="bt-detail-header">' +
                    '<div class="bt-detail-title"><span class="bt-ticket-header">#' + bug.id + '</span>' +
                        '<span class="bt-name-editable" onclick="BT.startNameEdit(this,' + bug.id + ')" title="Click to edit name">' + escapeHtml(bug.name) + '</span>' +
                    '</div>' +
                    '<button class="bt-detail-close" onclick="BT.closeDetail()">&times;</button>' +
                '</div>' +
                '<div style="font-size:12px;color:rgba(255,255,255,0.35);margin-bottom:12px;">Created ' + formatDateTime(bug.created_at) +
                    (bug.completed_at ? ' &middot; Completed ' + formatDateTime(bug.completed_at) : '') +
                    ' &middot; Source: ' + escapeHtml(bug.source) + '</div>' +
                '<div class="bt-actions">' + actions + '</div>' +
                '<div class="bt-detail-desc">' +
                    editableField('Description', 'description', bug.description) +
                '</div>' +
                (function() {
                    var notes = '';
                    if (bug.to_validate) notes += editableField('To Validate', 'to_validate', bug.to_validate);
                    if (bug.qa_notes) notes += editableField('QA Notes', 'qa_notes', bug.qa_notes);
                    if (bug.extra_notes) notes += editableField('Extra Notes', 'extra_notes', bug.extra_notes);
                    return notes;
                })() +
                parentLink +
                (screenshots ? '<div class="bt-screenshots">' + screenshots + '</div>' : '') +
                commentsHtml +
                historyHtml +
            '</div>';

        overlay.style.display = 'flex';

        // Focus comment box shortcut + @mention autocomplete
        var commentBox = document.getElementById('btCommentBody');
        if (commentBox) {
            commentBox.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    addComment(bug.id);
                }
            });
            setupMentionAutocomplete(commentBox);
        }
    }

    // @mention autocomplete dropdown
    var mentionUsers = PAGE_DATA.mentionUsers || [];
    function setupMentionAutocomplete(textarea) {
        var dropdown = document.createElement('div');
        dropdown.className = 'bt-mention-dropdown';
        dropdown.style.display = 'none';
        textarea.parentNode.style.position = 'relative';
        textarea.parentNode.appendChild(dropdown);

        textarea.addEventListener('input', function() {
            var val = textarea.value, pos = textarea.selectionStart;
            // Find @ before cursor
            var before = val.slice(0, pos);
            var atMatch = before.match(/@(\w*)$/);
            if (!atMatch) { dropdown.style.display = 'none'; return; }
            var query = atMatch[1].toLowerCase();
            var matches = mentionUsers.filter(function(u) {
                return u.name.toLowerCase().indexOf(query) !== -1 || u.handle.indexOf(query) !== -1;
            });
            if (!matches.length) { dropdown.style.display = 'none'; return; }
            dropdown.innerHTML = matches.map(function(u) {
                return '<div class="bt-mention-option" data-handle="' + u.handle + '">' +
                    '<strong>' + escapeHtml(u.name) + '</strong> <span style="opacity:0.5;">@' + u.handle + '</span></div>';
            }).join('');
            dropdown.style.display = 'block';
            // Click handler
            dropdown.querySelectorAll('.bt-mention-option').forEach(function(opt) {
                opt.onclick = function() {
                    var handle = opt.dataset.handle;
                    var atStart = before.lastIndexOf('@');
                    textarea.value = val.slice(0, atStart) + '@' + handle + ' ' + val.slice(pos);
                    textarea.focus();
                    textarea.selectionStart = textarea.selectionEnd = atStart + handle.length + 2;
                    dropdown.style.display = 'none';
                };
            });
        });

        textarea.addEventListener('blur', function() {
            setTimeout(function() { dropdown.style.display = 'none'; }, 200);
        });
    }

    function closeDetail() {
        selectedBugId = null;
        var overlay = document.getElementById('btDetailModal');
        if (overlay) overlay.style.display = 'none';
    }

    function showIdeaDetail(ideaId) {
        var idea = ideas.find(function(i) { return i.id === ideaId; });
        if (!idea) return;

        var overlay = document.getElementById('btDetailModal');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'btDetailModal';
            overlay.className = 'bt-modal-overlay';
            // Don't close on backdrop click — prevents losing typed content in comment/edit fields
            // Close only via X button, Cancel, or Escape key
            document.body.appendChild(overlay);
        }

        var notes = (idea.notes || '').split('|').filter(Boolean);
        var notesHtml = notes.length ? notes.map(function(n) {
            return '<div class="bt-history-item">' + escapeHtml(n) + '</div>';
        }).join('') : '<div style="color:rgba(255,255,255,0.3)">No notes yet</div>';

        overlay.innerHTML =
            '<div class="bt-modal">' +
                '<div class="bt-detail-header">' +
                    '<div class="bt-detail-title">' + escapeHtml(idea.name) + '</div>' +
                    '<button class="bt-detail-close" onclick="BT.closeDetail()">&times;</button>' +
                '</div>' +
                '<div class="bt-field"><div class="bt-field-label">Description</div><div class="bt-field-value">' + escapeHtml(idea.description) + '</div></div>' +
                '<div class="bt-field"><div class="bt-field-label">Category</div><div class="bt-field-value"><span class="bt-category bt-cat-' + idea.category + '">' + escapeHtml(idea.category) + '</span></div></div>' +
                '<div class="bt-field"><div class="bt-field-label">Notes</div>' + notesHtml + '</div>' +
                '<div class="bt-actions">' +
                    (idea.promoted_to_bug_id ? '<span style="color:#4ade80;font-size:13px;">Promoted to bug <a class="bt-bug-link" href="javascript:void(0)" onclick="BT.showDetail(' + idea.promoted_to_bug_id + ')">#' + idea.promoted_to_bug_id + '</a></span>' :
                        '<button class="bt-btn bt-btn-sm bt-btn-primary" onclick="BT.promoteIdea(' + idea.id + ')">Promote to Active Bug</button>') +
                '</div>' +
            '</div>';

        overlay.style.display = 'flex';
    }

    // === Inline Field Editing ===

    function startEdit(el, bugId, field) {
        if (el.querySelector('textarea')) return; // already editing
        var currentValue = '';
        // Find current value from data
        var allBugs = activeBugs.concat(completedBugs);
        var bug = allBugs.find(function(b) { return b.id === bugId; });
        if (bug) currentValue = bug[field] || '';

        el.innerHTML = '<textarea class="bt-edit-textarea">' + escapeHtml(currentValue) + '</textarea>' +
            '<div class="bt-edit-actions">' +
            '<button class="bt-btn bt-btn-sm bt-btn-primary" onclick="BT.saveEdit(' + bugId + ',\'' + field + '\',this)">Save</button>' +
            '<button class="bt-btn bt-btn-sm" onclick="BT.showDetail(' + bugId + ')">Cancel</button>' +
            '</div>';
        var ta = el.querySelector('textarea');
        ta.focus();
        ta.setSelectionRange(ta.value.length, ta.value.length);
        // Ctrl/Cmd+Enter to save
        ta.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                saveEdit(bugId, field, ta);
            }
            if (e.key === 'Escape') showDetail(bugId);
        });
    }

    function startNameEdit(el, bugId) {
        if (el.querySelector('input')) return; // already editing
        var allBugs = activeBugs.concat(completedBugs);
        var bug = allBugs.find(function(b) { return b.id === bugId; });
        var currentName = bug ? bug.name : el.textContent;
        el.innerHTML = '<input type="text" class="bt-input bt-name-input" maxlength="200" value="' + escapeHtml(currentName) + '">' +
            '<div class="bt-edit-actions">' +
            '<button class="bt-btn bt-btn-sm bt-btn-primary" onclick="BT.saveNameEdit(' + bugId + ',this)">Save</button>' +
            '<button class="bt-btn bt-btn-sm" onclick="BT.showDetail(' + bugId + ')">Cancel</button>' +
            '</div>';
        var inp = el.querySelector('input');
        inp.focus();
        inp.select();
        inp.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); saveNameEdit(bugId, inp); }
            if (e.key === 'Escape') showDetail(bugId);
        });
        // Stop click from propagating back to the parent onclick
        inp.addEventListener('click', function(e) { e.stopPropagation(); });
    }

    function saveNameEdit(bugId, btnOrInp) {
        var container = btnOrInp.closest('.bt-name-editable');
        var inp = container.querySelector('input');
        if (!inp) return;
        var newVal = inp.value.trim();
        if (!newVal) return; // name cannot be empty
        apiPut('/api/admin/bugs/' + bugId, {name: newVal, changed_by: USER_NAME})
            .then(function() { refreshData(); });
    }

    function saveEdit(bugId, field, btnOrTa) {
        var container = btnOrTa.closest('.bt-field-editable') || btnOrTa.closest('.bt-field-value');
        var ta = container.querySelector('textarea');
        if (!ta) return;
        var newVal = ta.value;
        apiPut('/api/admin/bugs/' + bugId, {[field]: newVal, changed_by: USER_NAME})
            .then(function() { refreshData(); });
    }

    // === Comments ===

    function addComment(bugId) {
        var ta = document.getElementById('btCommentBody');
        if (!ta) return;
        var body = ta.value.trim();
        if (!body) return;
        ta.disabled = true;
        apiPost('/api/admin/bugs/' + bugId + '/comments', {body: body, author: USER_NAME})
            .then(function(data) {
                ta.disabled = false;
                if (data.success) showDetail(bugId); // refresh the modal
            });
    }

    // === API Actions ===

    function apiPost(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        }).then(function(r) { return r.json(); });
    }

    function apiPut(url, body) {
        return fetch(url, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        }).then(function(r) { return r.json(); });
    }

    function refreshData() {
        fetch('/api/admin/bugs?tab=' + currentTab)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) return;
                activeBugs = data.active || activeBugs;
                completedBugs = data.completed || completedBugs;
                ideas = data.ideas || ideas;
                if (data.stats) updateStats(data.stats);
                renderBugList();
                if (selectedBugId) showDetail(selectedBugId);
            });
    }

    function updateStats(s) {
        document.getElementById('btStatActive').textContent = s.active_count || 0;
        document.getElementById('btStatQA').textContent = s.awaiting_qa || 0;
        document.getElementById('btStatP1').textContent = s.p1_count || 0;
        document.getElementById('btStatP2').textContent = s.p2_count || 0;
        document.getElementById('btStatDone').textContent = s.completed_count || 0;
    }

    function updateField(bugId, field, value) {
        apiPut('/api/admin/bugs/' + bugId, {[field]: value, changed_by: USER_NAME})
            .then(function() { refreshData(); });
    }

    function toggleQA(bugId, approved) {
        apiPut('/api/admin/bugs/' + bugId, {qa_approved: approved, changed_by: USER_NAME})
            .then(function() { refreshData(); });
    }

    function completeBug(bugId) {
        apiPost('/api/admin/bugs/' + bugId + '/complete', {changed_by: USER_NAME})
            .then(function(data) {
                if (!data.success) { alert(data.error || 'Failed'); return; }
                refreshData();
            });
    }

    function reopenBug(bugId) {
        apiPost('/api/admin/bugs/' + bugId + '/reopen', {changed_by: USER_NAME})
            .then(function() { refreshData(); });
    }

    function promoteIdea(ideaId) {
        apiPost('/api/admin/bugs/ideas/' + ideaId + '/promote', {})
            .then(function(data) {
                if (data.success) { closeDetail(); refreshData(); }
            });
    }

    // === Screenshot Upload ===

    function uploadScreenshot(bugId) {
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*,video/*';
        input.onchange = function() {
            if (!input.files[0]) return;
            doUpload(bugId, input.files[0]);
        };
        input.click();
    }

    function doUpload(bugId, file) {
        var fd = new FormData();
        fd.append('file', file);
        fetch('/api/admin/bugs/' + bugId + '/screenshot', {method: 'POST', body: fd})
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) refreshData();
                else alert(data.error || 'Upload failed');
            });
    }

    // === Add Bug Modal ===

    function searchRelated() {
        var name = document.getElementById('btModalName').value.trim().toLowerCase();
        var el = document.getElementById('btRelatedBugs');
        if (name.length < 3) { el.style.display = 'none'; return; }

        var words = name.split(/\s+/).filter(function(w) { return w.length > 2; });
        var allBugs = activeBugs.concat(completedBugs);
        var scored = [];
        allBugs.forEach(function(b) {
            var text = (b.name + ' ' + (b.description || '')).toLowerCase();
            var hits = words.filter(function(w) { return text.indexOf(w) !== -1; }).length;
            if (hits > 0) scored.push({bug: b, score: hits});
        });
        scored.sort(function(a, b) { return b.score - a.score; });
        var top = scored.slice(0, 5);

        if (!top.length) { el.style.display = 'none'; return; }
        el.style.display = 'block';
        el.innerHTML = '<div style="color:rgba(255,255,255,0.4);margin-bottom:4px;">Related bugs:</div>' +
            top.map(function(s) {
                return '<div style="padding:2px 0;"><a class="bt-bug-link" href="javascript:void(0)" onclick="BT.closeModal();BT.showDetail(' + s.bug.id + ')">#' + s.bug.id + '</a> ' +
                    '<span style="color:rgba(255,255,255,0.7);">' + escapeHtml(s.bug.name) + '</span> ' +
                    '<span class="' + statusClass(s.bug.status) + '" style="font-size:10px;">' + escapeHtml(s.bug.status) + '</span></div>';
            }).join('');
    }

    function openAddModal() {
        document.getElementById('btModal').style.display = 'flex';
        document.getElementById('btModalTitle').textContent = 'Add Bug';
        document.getElementById('btModalBugId').value = '';
        document.getElementById('btModalName').value = '';
        document.getElementById('btModalDesc').value = '';
        document.getElementById('btModalType').value = 'Bug';
        document.getElementById('btModalPriority').value = 'P3';
        document.getElementById('btModalStatus').textContent = '';
        document.getElementById('btUploadPreview').style.display = 'none';
        document.getElementById('btUploadText').style.display = '';
        document.getElementById('btRelatedBugs').style.display = 'none';
        pendingFile = null;
        document.getElementById('btModalName').focus();
    }

    function closeModal() {
        document.getElementById('btModal').style.display = 'none';
        pendingFile = null;
    }

    function submitBug() {
        var name = document.getElementById('btModalName').value.trim();
        var desc = document.getElementById('btModalDesc').value.trim();
        var type = document.getElementById('btModalType').value;
        var priority = document.getElementById('btModalPriority').value;
        var status = document.getElementById('btModalStatus');

        if (!name) { status.textContent = 'Name is required'; status.style.color = '#f87171'; return; }

        var btn = document.getElementById('btModalSubmit');
        btn.disabled = true;
        btn.textContent = 'Saving...';

        apiPost('/api/admin/bugs', {name: name, description: desc, type: type, priority: priority})
            .then(function(data) {
                if (!data.success) {
                    status.textContent = data.error || 'Failed';
                    status.style.color = '#f87171';
                    btn.disabled = false;
                    btn.textContent = 'Save';
                    return;
                }
                if (pendingFile && data.bug && data.bug.id) {
                    doUpload(data.bug.id, pendingFile);
                }
                closeModal();
                refreshData();
            })
            .catch(function() {
                status.textContent = 'Connection error';
                status.style.color = '#f87171';
                btn.disabled = false;
                btn.textContent = 'Save';
            });
    }

    // === Upload Zone (paste, drag, click) ===

    function setupUploadZone() {
        var zone = document.getElementById('btUploadZone');
        var fileInput = document.getElementById('btFileInput');
        var preview = document.getElementById('btUploadPreview');
        var text = document.getElementById('btUploadText');

        zone.addEventListener('click', function() { fileInput.click(); });
        zone.addEventListener('dragover', function(e) { e.preventDefault(); zone.classList.add('dragover'); });
        zone.addEventListener('dragleave', function() { zone.classList.remove('dragover'); });
        zone.addEventListener('drop', function(e) {
            e.preventDefault();
            zone.classList.remove('dragover');
            if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
        });
        fileInput.addEventListener('change', function() {
            if (fileInput.files[0]) handleFile(fileInput.files[0]);
        });
        document.getElementById('btModal').addEventListener('paste', function(e) {
            var items = e.clipboardData && e.clipboardData.items;
            if (!items) return;
            for (var i = 0; i < items.length; i++) {
                if (items[i].type.indexOf('image') !== -1 || items[i].type.indexOf('video') !== -1) {
                    handleFile(items[i].getAsFile());
                    break;
                }
            }
        });

        function handleFile(file) {
            pendingFile = file;
            text.style.display = 'none';
            if (file.type.startsWith('image/')) {
                var reader = new FileReader();
                reader.onload = function(e) { preview.src = e.target.result; preview.style.display = 'block'; };
                reader.readAsDataURL(file);
            } else {
                preview.style.display = 'none';
                text.style.display = '';
                text.textContent = file.name + ' (' + (file.size / 1024 / 1024).toFixed(1) + ' MB)';
            }
        }
    }

    // === Tab Switching ===

    function switchTab(tab) {
        currentTab = tab;
        document.querySelectorAll('.bt-tab').forEach(function(t) {
            t.classList.toggle('active', t.dataset.tab === tab);
        });
        renderBugList();
    }

    // === Init ===

    renderBugList();
    setupUploadZone();

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            var detailModal = document.getElementById('btDetailModal');
            if (detailModal && detailModal.style.display !== 'none') { closeDetail(); return; }
            if (document.getElementById('btModal').style.display !== 'none') closeModal();
        }
    });
    // Don't close create modal on backdrop click — prevents losing typed content
    // Close only via X button, Cancel, or Escape key

    // Auto-open bug modal if ?open=ID in URL (e.g. from PilgrimBot)
    var openParam = new URLSearchParams(window.location.search).get('open');
    if (openParam) {
        showDetail(parseInt(openParam, 10));
        // Clean URL without reload
        history.replaceState(null, '', window.location.pathname);
    }

    // Public API
    window.BT = {
        switchTab: switchTab,
        applyFilters: renderBugList,
        showDetail: showDetail,
        showIdeaDetail: showIdeaDetail,
        closeDetail: closeDetail,
        openAddModal: openAddModal,
        closeModal: closeModal,
        submitBug: submitBug,
        updateField: updateField,
        toggleQA: toggleQA,
        completeBug: completeBug,
        reopenBug: reopenBug,
        promoteIdea: promoteIdea,
        uploadScreenshot: uploadScreenshot,
        startEdit: startEdit,
        saveEdit: saveEdit,
        startNameEdit: startNameEdit,
        saveNameEdit: saveNameEdit,
        addComment: addComment,
        searchRelated: searchRelated,
        copyBugLink: function(bugId, btn) {
            var url = window.location.origin + '/admin/bugs?open=' + bugId;
            navigator.clipboard.writeText('#' + bugId + ' — ' + url).then(function() {
                var orig = btn.textContent;
                btn.textContent = 'Copied!';
                setTimeout(function() { btn.textContent = orig; }, 1500);
            });
        }
    };
})();
