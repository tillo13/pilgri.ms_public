/**
 * brainstorm-comments.js — Per-section comment annotations for brainstorm pages.
 *
 * Set window.BRAINSTORM_PAGE_KEY before loading this script.
 * Each .brainstorm-container > .section element gets a comment thread.
 */
(function() {
    const PAGE_KEY = window.BRAINSTORM_PAGE_KEY;
    if (!PAGE_KEY) return;

    const sections = document.querySelectorAll('.brainstorm-container > .section');
    if (!sections.length) return;

    const containers = [];

    sections.forEach(function(section, idx) {
        const el = document.createElement('div');
        el.className = 'bs-comments';
        el.dataset.idx = idx;
        el.innerHTML =
            '<div class="bs-comments-toggle" role="button" tabindex="0">' +
                '<span class="bs-comments-count">0 notes</span>' +
            '</div>' +
            '<div class="bs-comments-body">' +
                '<div class="bs-comments-feed"></div>' +
                '<form class="bs-comments-form">' +
                    '<textarea class="bs-comments-input" placeholder="Add a note..." rows="2" maxlength="2000"></textarea>' +
                    '<button type="submit" class="bs-comments-submit">Post</button>' +
                '</form>' +
            '</div>';
        section.appendChild(el);
        containers.push(el);

        el.querySelector('.bs-comments-toggle').addEventListener('click', function() {
            var body = el.querySelector('.bs-comments-body');
            body.hidden = !body.hidden;
        });

        el.querySelector('.bs-comments-form').addEventListener('submit', function(e) {
            e.preventDefault();
            var input = el.querySelector('.bs-comments-input');
            var text = input.value.trim();
            if (!text) return;

            var btn = el.querySelector('.bs-comments-submit');
            btn.disabled = true;

            apiPost('/api/brainstorm/comments/' + PAGE_KEY, {section_idx: idx, text: text})
            .then(function(data) {
                if (data.success) {
                    input.value = '';
                    appendComment(el, data.comment);
                    updateCount(el);
                }
            })
            .finally(function() { btn.disabled = false; });
        });
    });

    // Load existing comments
    fetch('/api/brainstorm/comments/' + PAGE_KEY)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            data.comments.forEach(function(c) {
                var container = containers[c.section_idx];
                if (container) appendComment(container, c);
            });
            containers.forEach(updateCount);
        });

    function appendComment(container, c) {
        var feed = container.querySelector('.bs-comments-feed');
        var div = document.createElement('div');
        div.className = 'bs-comment' + (c.author_type === 'user' ? ' bs-comment-user' : ' bs-comment-anon');
        var time = c.created_at ? timeAgo(new Date(c.created_at)) : '';
        div.innerHTML =
            '<span class="bs-comment-author">' + escapeHtml(c.author_name) + '</span> ' +
            '<span class="bs-comment-time">' + time + '</span>' +
            '<div class="bs-comment-text">' + escapeHtml(c.comment_text) + '</div>';
        feed.appendChild(div);
    }

    function updateCount(container) {
        var count = container.querySelectorAll('.bs-comment').length;
        var label = count === 1 ? '1 note' : count + ' notes';
        container.querySelector('.bs-comments-count').textContent = label;
    }

    function escapeHtml(text) {
        var d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }

    function timeAgo(date) {
        var s = Math.floor((Date.now() - date.getTime()) / 1000);
        if (s < 60) return 'just now';
        if (s < 3600) return Math.floor(s / 60) + 'm ago';
        if (s < 86400) return Math.floor(s / 3600) + 'h ago';
        return Math.floor(s / 86400) + 'd ago';
    }
})();
