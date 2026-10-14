/**
 * contract-route.js — блок «Согласование» (маршрут по этапам) и лента
 * «История» для карточек контракта и проекта.
 *
 * Usage:
 *   <div x-data="routeBlock('contract')" x-init="init()"> ... </div>
 *   <div x-data="historyFeed()" x-init="init()"> ... </div>
 *
 * Идентификатор проекта берётся из ?id= адреса страницы. После решения
 * компонент шлёт событие `route-updated` (карточка перезагружает контракт).
 */

const ROUTE_STEP_STATUS = {
    not_started: { label: 'Ожидает отправки', cls: 'rs-wait', icon: 'fa-circle' },
    waiting: { label: 'В очереди', cls: 'rs-wait', icon: 'fa-hourglass-start' },
    active: { label: 'На согласовании', cls: 'rs-active', icon: 'fa-hourglass-half' },
    approved: { label: 'Согласовано', cls: 'rs-ok', icon: 'fa-check' },
    rework: { label: 'На доработку', cls: 'rs-rework', icon: 'fa-rotate-left' },
    cancelled: { label: 'Отменён', cls: 'rs-wait', icon: 'fa-ban' },
};

function _routeProjectId() {
    return new URLSearchParams(window.location.search).get('id');
}

function fmtDateTime(iso) {
    if (!iso) return '';
    const d = new Date(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z');
    return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function routeBlock(route = 'contract') {
    return {
        route,
        state: null,
        loading: true,
        comment: '',
        navRate: null,
        busy: false,
        error: '',
        statusMeta: ROUTE_STEP_STATUS,

        async init() {
            await this.load();
            window.addEventListener('route-reload', () => this.load());
        },
        async load() {
            const id = _routeProjectId();
            if (!id) { this.loading = false; return; }
            try {
                const res = await authFetch(`/api/v1/projects/${id}/route?route=${this.route}`);
                if (res.ok) this.state = await res.json();
            } catch (e) {}
            this.loading = false;
        },
        get current() { return this.state && this.state.current; },
        get canDecide() { return !!(this.current && this.current.can_decide); },
        get isTreasurerStep() { return this.current && this.current.role === 'treasurer'; },
        meta(st) { return ROUTE_STEP_STATUS[st.status] || ROUTE_STEP_STATUS.waiting; },
        fmt(iso) { return fmtDateTime(iso); },
        stateLabel() {
            const s = this.state && this.state.state;
            return {
                not_started: 'Не отправлен', in_progress: 'Идёт согласование',
                approved: 'Согласован всеми', rework: 'Возвращён на доработку', cancelled: 'Маршрут остановлен',
            }[s] || '';
        },
        async decide(decision) {
            this.error = '';
            if (decision === 'rework' && !this.comment.trim()) {
                this.error = 'Напишите, что нужно доработать';
                return;
            }
            this.busy = true;
            try {
                const body = { decision, comment: this.comment };
                if (decision === 'approve' && this.isTreasurerStep && this.navRate > 0) body.nav_rate = this.navRate;
                const res = await authFetch(`/api/v1/projects/${_routeProjectId()}/route/steps/${this.current.id}/decision`, {
                    method: 'POST', body: JSON.stringify(body),
                });
                if (!res.ok) {
                    const e = await res.json().catch(() => ({}));
                    this.error = e.detail || 'Не удалось сохранить решение';
                    return;
                }
                this.state = await res.json();
                this.comment = '';
                this.navRate = null;
                window.dispatchEvent(new CustomEvent('route-updated', { detail: { route: this.route } }));
            } catch (e) {
                if (e.message !== 'Unauthorized') this.error = 'Ошибка сети';
            } finally {
                this.busy = false;
            }
        },
    };
}

function historyFeed() {
    return {
        events: [],
        loading: true,
        async init() {
            await this.load();
            window.addEventListener('route-updated', () => this.load());
        },
        async load() {
            const id = _routeProjectId();
            if (!id) { this.loading = false; return; }
            try {
                const res = await authFetch(`/api/v1/projects/${id}/history`);
                if (res.ok) this.events = await res.json();
            } catch (e) {}
            this.loading = false;
        },
        fmt(iso) { return fmtDateTime(iso); },
        icon(e) {
            return {
                created: 'fa-plus', status: 'fa-flag', route_sent: 'fa-paper-plane',
                route_approved: 'fa-check', route_rework: 'fa-rotate-left', change: 'fa-pen',
            }[e.kind] || 'fa-circle';
        },
        tone(e) {
            return {
                route_approved: 'h-ok', route_rework: 'h-rework', route_sent: 'h-info',
                status: 'h-info', change: 'h-muted', created: 'h-muted',
            }[e.kind] || 'h-muted';
        },
    };
}

/**
 * Блок «Проект приказа (ЛНА)»: формирование .docx по согласованному
 * документу, скачивание, загрузка исправленной версии.
 * Маршрут согласования приказа показывает вложенный routeBlock('order').
 */
function orderBlock() {
    return {
        state: null,
        loading: true,
        busy: false,
        error: '',
        async init() {
            await this.load();
            window.addEventListener('route-updated', () => this.load());
            window.addEventListener('order-generate', () => this.generate());
        },
        async load() {
            const id = _routeProjectId();
            if (!id) { this.loading = false; return; }
            try {
                const res = await authFetch(`/api/v1/projects/${id}/order`);
                if (res.ok) this.state = await res.json();
            } catch (e) {}
            this.loading = false;
        },
        get order() { return this.state && this.state.order; },
        get routeState() { return this.state && this.state.route && this.state.route.state; },
        get canGenerate() {
            return this.state && this.state.can_generate && this.routeState !== 'in_progress';
        },
        sourceLabel() {
            return { ai: 'AI-ассистент по скиллу', template: 'шаблон (AI выключен)', upload: 'загружен вручную' }[this.order && this.order.source] || '';
        },
        fmt(iso) { return fmtDateTime(iso); },
        async generate() {
            if (!this.canGenerate || this.busy) return;
            if (this.order && !confirm('Сформировать новый проект приказа? Согласование начнётся заново.')) return;
            this.busy = true; this.error = '';
            try {
                const res = await authFetch(`/api/v1/projects/${_routeProjectId()}/order`, { method: 'POST' });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) { this.error = data.detail || 'Не удалось сформировать проект приказа'; return; }
                this.state = data;
                window.dispatchEvent(new CustomEvent('route-reload'));
                window.dispatchEvent(new CustomEvent('attachments-reload'));
            } catch (e) {
                if (e.message !== 'Unauthorized') this.error = 'Ошибка сети';
            } finally { this.busy = false; }
        },
        async upload(event) {
            const file = event.target.files[0];
            if (!file) return;
            this.busy = true; this.error = '';
            const fd = new FormData();
            fd.append('file', file);
            try {
                const res = await fetch(`/api/v1/projects/${_routeProjectId()}/order/upload`, {
                    method: 'POST', headers: { Authorization: 'Bearer ' + getToken() }, body: fd,
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) { this.error = data.detail || 'Не удалось загрузить файл'; return; }
                this.state = data;
                window.dispatchEvent(new CustomEvent('route-reload'));
                window.dispatchEvent(new CustomEvent('attachments-reload'));
            } catch (e) { this.error = 'Ошибка сети'; }
            finally { this.busy = false; event.target.value = ''; }
        },
        async download() {
            const att = this.state && this.state.attachment;
            if (!att) return;
            const res = await authFetch(`/api/v1/attachments/${att.id}/download`);
            if (!res.ok) { this.error = 'Не удалось скачать файл'; return; }
            const url = URL.createObjectURL(await res.blob());
            const a = document.createElement('a');
            a.href = url; a.download = att.name;
            document.body.appendChild(a); a.click(); document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        },
    };
}
