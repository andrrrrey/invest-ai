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

function getToken()      { return localStorage.getItem('invest_token'); }
function getUserId()     { return parseInt(localStorage.getItem('invest_user_id') || '0', 10); }
function getUserRole()   { return localStorage.getItem('invest_role') || ''; }
function getUserName()   { return localStorage.getItem('invest_name') || ''; }
function getUserAvatar() { return localStorage.getItem('invest_avatar') || ''; }

function isLoggedIn() { return !!getToken(); }

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
}
