/**
 * mentions.js — теги сотрудников в комментариях.
 *
 *  - attachMentions(textarea): автодополнение по «@» из справочника сотрудников
 *    (вставляет «@Фамилия Имя »; x-model обновляется через событие input);
 *  - mentionHtml(comment): безопасный HTML текста с подсветкой упоминаний;
 *  - focusCommentFromHash(): прокрутка и подсветка комментария по #comment-ID
 *    (ссылка из уведомления Баффета).
 */

let _mentionDirectory = null;

async function loadMentionDirectory() {
    if (_mentionDirectory) return _mentionDirectory;
    try {
        const res = await authFetch('/api/v1/users/directory');
        _mentionDirectory = res.ok ? await res.json() : [];
    } catch (e) {
        _mentionDirectory = [];
    }
    return _mentionDirectory;
}

(function injectMentionStyles() {
    if (document.getElementById('mention-styles')) return;
    const st = document.createElement('style');
    st.id = 'mention-styles';
    st.textContent = `
        .mention-pop { position: absolute; z-index: 5000; background: #fff; border: 1.5px solid #E5E5ED; border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0,0,0,.12); min-width: 240px; max-height: 240px; overflow-y: auto; padding: 4px; }
        .mention-pop .mi { padding: 8px 10px; border-radius: 8px; cursor: pointer; font-size: 13px; display: flex; gap: 8px; align-items: center; }
        .mention-pop .mi.active, .mention-pop .mi:hover { background: #F0EFFF; color: #5E5CE6; }
        .mention-pop .mi .av { width: 24px; height: 24px; border-radius: 50%; background: #5E5CE6; color: #fff; font-size: 11px;
            font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .mention-pop .hint { font-size: 11px; color: #8E8E93; padding: 6px 10px; }
        .mention-tag { background: #EEEDFF; color: #5E5CE6; font-weight: 700; border-radius: 6px; padding: 0 4px; }
        .comment-focus { box-shadow: 0 0 0 3px rgba(94,92,230,.35) !important; transition: box-shadow .3s; }
    `;
    document.head.appendChild(st);
})();

function attachMentions(textarea) {
    if (!textarea || textarea._mentionsAttached) return;
    textarea._mentionsAttached = true;
    const pop = document.createElement('div');
    pop.className = 'mention-pop';
    pop.style.display = 'none';
    document.body.appendChild(pop);
    let items = [], active = 0, start = -1;

    const close = () => { pop.style.display = 'none'; start = -1; items = []; };

    const query = () => {
        const pos = textarea.selectionStart;
        const before = textarea.value.slice(0, pos);
        const m = before.match(/(^|[\s(])@([^\s@]{0,30}(?:\s[^\s@]{0,30})?)$/);
        if (!m) return null;
        return { q: m[2], at: pos - m[2].length - 1 };
    };

    const render = () => {
        pop.innerHTML = '';
        if (!items.length) {
            pop.innerHTML = '<div class="hint">Сотрудник не найден</div>';
            return;
        }
        items.forEach((u, i) => {
            const el = document.createElement('div');
            el.className = 'mi' + (i === active ? ' active' : '');
            el.innerHTML = `<span class="av">${escapeHtml((u.full_name || '?').charAt(0))}</span><span>${escapeHtml(u.full_name)}</span>`;
            el.addEventListener('mousedown', (e) => { e.preventDefault(); pick(i); });
            pop.appendChild(el);
        });
    };

    const pick = (i) => {
        const u = items[i];
        if (!u || start < 0) return;
        const pos = textarea.selectionStart;
        const insert = '@' + u.full_name + ' ';
        textarea.value = textarea.value.slice(0, start) + insert + textarea.value.slice(pos);
        const caret = start + insert.length;
        textarea.setSelectionRange(caret, caret);
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        close();
        textarea.focus();
    };

    const update = async () => {
        const q = query();
        if (!q) { close(); return; }
        const dir = await loadMentionDirectory();
        const needle = q.q.toLowerCase().replace(/ё/g, 'е');
        items = dir.filter(u => {
            const name = (u.full_name || '').toLowerCase().replace(/ё/g, 'е');
            return !needle || name.split(/\s+/).some(t => t.startsWith(needle)) || name.startsWith(needle);
        }).slice(0, 8);
        start = q.at;
        active = 0;
        render();
        const r = textarea.getBoundingClientRect();
        pop.style.left = (window.scrollX + r.left) + 'px';
        pop.style.top = (window.scrollY + r.bottom + 4) + 'px';
        pop.style.display = 'block';
    };

    textarea.addEventListener('input', update);
    textarea.addEventListener('click', update);
    textarea.addEventListener('blur', () => setTimeout(close, 150));
    textarea.addEventListener('keydown', (e) => {
        if (pop.style.display === 'none' || !items.length) return;
        if (e.key === 'ArrowDown') { active = (active + 1) % items.length; render(); e.preventDefault(); }
        else if (e.key === 'ArrowUp') { active = (active - 1 + items.length) % items.length; render(); e.preventDefault(); }
        else if (e.key === 'Enter' || e.key === 'Tab') { pick(active); e.preventDefault(); e.stopPropagation(); }
        else if (e.key === 'Escape') { close(); }
    });
}

function _escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function mentionHtml(comment) {
    let html = escapeHtml(comment.text || '');
    const names = (comment.mentions || []).map(m => m.full_name).filter(Boolean)
        .sort((a, b) => b.length - a.length);
    for (const name of names) {
        const parts = name.split(/\s+/).map(p => _escapeRegExp(escapeHtml(p)));
        // «@Фамилия Имя», «@Имя Фамилия» или «@Фамилия»
        const variants = [parts.join('\\s+'), parts.slice().reverse().join('\\s+'), ...parts];
        const re = new RegExp('([@#])(' + variants.join('|') + ')(?![\\wА-Яа-яЁё])', 'giu');
        html = html.replace(re, '<span class="mention-tag">$1$2</span>');
    }
    return html.replace(/\n/g, '<br>');
}

function focusCommentFromHash() {
    const m = (window.location.hash || '').match(/^#comment-(\d+)$/);
    if (!m) return;
    setTimeout(() => {
        const el = document.getElementById('comment-' + m[1]);
        if (!el) return;
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('comment-focus');
        setTimeout(() => el.classList.remove('comment-focus'), 4000);
    }, 150);
}
