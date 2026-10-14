/**
 * auth.js — shared authentication helpers for all pages.
 *
 * Storage keys in localStorage:
 *   invest_token    — JWT bearer token
 *   invest_user_id  — numeric user id
 *   invest_role     — 'ceo' | 'cfo' | 'manager' | 'owner'
 *   invest_name     — full name of the current user
 */

const ROLE_LABELS = {
    ceo: 'CEO',
    cfo: 'CFO',
    manager: 'Менеджер',
    owner: 'Заявитель',
};

/**
 * Escape HTML special characters so a string renders as plain text.
 */
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/**
 * Sanitize rich-text (Quill) HTML before injecting it into the DOM via x-html.
 * Prevents stored XSS. Uses DOMPurify when loaded; if the sanitizer is missing
 * it fails safe by escaping the content as plain text (never injects raw HTML).
 */
function sanitizeRichText(content) {
    if (!content) return '';
    const looksLikeHtml = /<[a-z][\s\S]*>/i.test(content);
    if (looksLikeHtml) {
        if (window.DOMPurify) {
            return window.DOMPurify.sanitize(content);
        }
        // No sanitizer available — do NOT inject untrusted HTML.
        return escapeHtml(content).replace(/\n/g, '<br>');
    }
    // Plain text — escape and preserve line breaks.
    return escapeHtml(content).replace(/\n/g, '<br>');
}

function getToken()      { return localStorage.getItem('invest_token'); }
function getUserId()     { return parseInt(localStorage.getItem('invest_user_id') || '0', 10); }
function getUserRole()   { return localStorage.getItem('invest_role') || ''; }
function getUserName()   { return localStorage.getItem('invest_name') || ''; }
function getUserAvatar() { return localStorage.getItem('invest_avatar') || ''; }

function isLoggedIn() { return !!getToken(); }

/** Роли согласования текущего пользователя (cb, treasurer, cfo, lawyer, ceo). */
function getApprovalRoles() {
    try { return JSON.parse(localStorage.getItem('invest_approval_roles') || '[]'); }
    catch (e) { return []; }
}
function hasApprovalRole(role) { return getApprovalRoles().includes(role); }

/** Обновить роли согласования из API (кэш в localStorage для меню). */
async function refreshApprovalRoles() {
    if (!isLoggedIn()) return [];
    try {
        const res = await authFetch('/api/v1/approval-roles/me');
        if (!res.ok) return getApprovalRoles();
        const data = await res.json();
        localStorage.setItem('invest_approval_roles', JSON.stringify(data.roles || []));
        document.dispatchEvent(new CustomEvent('approval-roles-updated'));
        return data.roles || [];
    } catch (e) { return getApprovalRoles(); }
}

/** Save login result from /api/v1/auth/token response. */
function saveAuth(data) {
    localStorage.setItem('invest_token',   data.access_token);
    localStorage.setItem('invest_user_id', data.user_id);
    localStorage.setItem('invest_role',    data.role);
    localStorage.setItem('invest_name',    data.full_name);
    if (data.avatar_url !== undefined) {
        if (data.avatar_url) {
            localStorage.setItem('invest_avatar', data.avatar_url);
        } else {
            localStorage.removeItem('invest_avatar');
        }
    }
}

/** Clear all auth data and redirect to login. */
function logout() {
    localStorage.removeItem('invest_token');
    localStorage.removeItem('invest_user_id');
    localStorage.removeItem('invest_role');
    localStorage.removeItem('invest_name');
    localStorage.removeItem('invest_avatar');
    localStorage.removeItem('invest_approval_roles');
    window.location.href = '/login';
}

/**
 * Redirect to /login if not logged in.
 * Call at the top of every protected page's init().
 */
function redirectIfNotLoggedIn() {
    if (!isLoggedIn()) {
        window.location.href = '/login';
        return false;
    }
    return true;
}

/**
 * fetch() wrapper that automatically injects Authorization header.
 * On 401 response, logs out and redirects to login.
 */
async function authFetch(url, options = {}) {
    const token = getToken();
    const headers = {
        ...(options.headers || {}),
    };
    if (token) {
        headers['Authorization'] = 'Bearer ' + token;
    }
    if (options.body && typeof options.body === 'string' && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }

    const res = await fetch(url, { ...options, headers });

    if (res.status === 401) {
        logout();
        throw new Error('Unauthorized');
    }

    return res;
}

/**
 * Returns an Alpine.js data mixin with auth state.
 * Usage: x-data="{ ...authMixin(), ... }"
 * or just call authMixin() to get role/name in plain JS.
 */
function authMixin() {
    return {
        authRole: getUserRole(),
        authName: getUserName(),
        authUserId: getUserId(),

        get isCeo()     { return this.authRole === 'ceo'; },
        get isCfo()     { return this.authRole === 'cfo'; },
        get isManager() { return this.authRole === 'manager'; },
        get isOwner()   { return this.authRole === 'owner'; },
        get canApprove(){ return this.authRole === 'cfo' || this.authRole === 'manager'; },
        get canEdit()   { return this.authRole === 'cfo' || this.authRole === 'manager'; },
        get canCreate() { return this.authRole !== 'ceo'; },
        get canDelete() { return this.authRole === 'cfo' || this.authRole === 'manager'; },
        get canSettings(){ return this.authRole === 'cfo'; },
        get roleLabelText() { return ROLE_LABELS[this.authRole] || this.authRole; },

        logout() { logout(); },
    };
}

/**
 * Patch the sidebar on every page: show name + role, wire up logout.
 * Call after DOM is ready.
 */
function patchSidebar() {
    const nameEl = document.getElementById('sidebar-name');
    const roleEl = document.getElementById('sidebar-role');
    const logoutEl = document.getElementById('sidebar-logout');
    const avatarEl = document.getElementById('sidebar-avatar');

    if (nameEl) nameEl.textContent = getUserName() || 'Пользователь';
    if (roleEl) roleEl.textContent = ROLE_LABELS[getUserRole()] || getUserRole();
    if (logoutEl) logoutEl.addEventListener('click', (e) => { e.preventDefault(); logout(); });

    // Show avatar image or fallback to first letter
    if (avatarEl) {
        const avatarUrl = getUserAvatar();
        if (avatarUrl) {
            avatarEl.innerHTML = `<img src="${avatarUrl}" style="width:100%;height:100%;object-fit:cover;border-radius:50%;" onerror="this.parentElement.innerHTML='${(getUserName() || '?').charAt(0).toUpperCase()}'">`;
        } else {
            avatarEl.textContent = (getUserName() || '?').charAt(0).toUpperCase();
        }
    }

    // Inject the CFO-only nav links ("База знаний" and "Аудит") on every page
    // (centralised so we don't edit every page's sidebar). Guarded against
    // duplicates on pages that already include them statically (settings,
    // knowledge, audit). Both links are inserted before "Пользователи" and in
    // the canonical order: База знаний → Аудит.
    const sidebarEl = document.getElementById('sidebar');
    const navMenu = sidebarEl && sidebarEl.querySelector('.nav-menu');
    if (navMenu && getUserRole() === 'cfo') {
        const usersLink = document.getElementById('nav-users');
        const insertNav = (id, href, iconClass, label) => {
            if (document.getElementById(id)) return;
            const link = document.createElement('a');
            link.href = href;
            link.className = 'nav-link';
            link.id = id;
            link.innerHTML = `<i class="${iconClass}"></i> ${label}`;
            if (usersLink) navMenu.insertBefore(link, usersLink);
            else navMenu.appendChild(link);
        };
        insertNav('nav-knowledge', '/knowledge', 'fas fa-brain', 'База знаний');
        insertNav('nav-audit', '/audit', 'fas fa-clipboard-list', 'Аудит');
    }

    // Раздел «Контракты»: два отдельных реестра — смарт-контракты (Coin) и
    // лидерские контракты. Статичная ссылка /smart-contracts есть на каждой
    // странице; здесь добавляем заголовок группы и ссылку на лидерские.
    patchContractsNav();
    refreshApprovalRoles();

    // Inject collapse toggle button as sibling of sidebar (outside sidebar's overflow)
    const sidebar = document.getElementById('sidebar');
    const appWindow = sidebar && sidebar.parentElement;
    if (sidebar && appWindow && !document.getElementById('sidebar-toggle')) {
        const btn = document.createElement('button');
        btn.id = 'sidebar-toggle';
        btn.className = 'sidebar-toggle-btn';
        btn.innerHTML = '<i class="fas fa-chevron-left"></i>';
        btn.title = 'Свернуть меню';
        btn.addEventListener('click', toggleSidebarCollapse);
        appWindow.appendChild(btn);

        // Restore collapsed state from localStorage
        if (localStorage.getItem('sidebarCollapsed') === 'true') {
            sidebar.classList.add('collapsed');
            btn.classList.add('collapsed');
            btn.innerHTML = '<i class="fas fa-chevron-right"></i>';
            btn.title = 'Развернуть меню';
        }
    }
}

/**
 * Превращает пункт «Смарт-контракты» в группу «Контракты» с двумя
 * подразделами. Активный подраздел определяется по адресу страницы или
 * явно через setContractNav('smart'|'leadership') (карточка, мастер).
 */
function patchContractsNav() {
    const sidebar = document.getElementById('sidebar');
    const navMenu = sidebar && sidebar.querySelector('.nav-menu');
    if (!navMenu) return;
    const smartLink = navMenu.querySelector('a[href="/smart-contracts"]');
    if (!smartLink || document.getElementById('nav-leader-contracts')) return;

    smartLink.id = 'nav-smart-contracts';
    smartLink.innerHTML = '<i class="fas fa-coins"></i> Смарт-контракты';

    const group = document.createElement('div');
    group.className = 'nav-group-label';
    group.textContent = 'Контракты';
    group.style.cssText = 'font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:rgba(255,255,255,.45);padding:12px 20px 4px';
    if (!document.getElementById('nav-group-style')) {
        const st = document.createElement('style');
        st.id = 'nav-group-style';
        st.textContent = '.sidebar.collapsed .nav-group-label{display:none}';
        document.head.appendChild(st);
    }
    navMenu.insertBefore(group, smartLink);

    const leader = document.createElement('a');
    leader.href = '/leader-contracts';
    leader.className = 'nav-link';
    leader.id = 'nav-leader-contracts';
    leader.innerHTML = '<i class="fas fa-user-tie"></i> Лидерские контракты';
    smartLink.insertAdjacentElement('afterend', leader);

    const path = window.location.pathname.replace(/\.html$/, '');
    if (path === '/leader-contracts') setContractNav('leadership');
    else if (path === '/smart-contracts') setContractNav('smart');
}

function setContractNav(scType) {
    const smart = document.getElementById('nav-smart-contracts');
    const leader = document.getElementById('nav-leader-contracts');
    if (!smart || !leader) return;
    smart.classList.toggle('active', scType !== 'leadership');
    leader.classList.toggle('active', scType === 'leadership');
}

function toggleSidebarCollapse() {
    const sidebar = document.getElementById('sidebar');
    const btn = document.getElementById('sidebar-toggle');
    if (!sidebar) return;
    const isCollapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('sidebarCollapsed', isCollapsed ? 'true' : 'false');
    if (btn) {
        btn.classList.toggle('collapsed', isCollapsed);
        btn.innerHTML = isCollapsed
            ? '<i class="fas fa-chevron-right"></i>'
            : '<i class="fas fa-chevron-left"></i>';
        btn.title = isCollapsed ? 'Развернуть меню' : 'Свернуть меню';
    }
}
