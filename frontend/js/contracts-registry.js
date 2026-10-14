/**
 * contracts-registry.js — общий Alpine-компонент реестров контрактов.
 *
 * Используется двумя страницами:
 *   /smart-contracts   — смарт-контракты с вознаграждением в Coin (scType=smart)
 *   /leader-contracts  — лидерские контракты (scType=leadership)
 *
 * Usage: x-data="contractsRegistryApp('smart')"
 */

const CONTRACT_STATUS_LABELS = {
    draft: 'Черновик',
    pending_approval: 'На согласовании',
    approved: 'Активен',
    rejected: 'Отклонён',
    rework_needed: 'На доработке',
};

const CONTRACT_TYPE_META = {
    smart: {
        title: 'Смарт-контракты (Coin)',
        listTitle: 'Реестр смарт-контрактов',
        createLabel: 'Создать смарт-контракт',
        emptyText: 'Смарт-контрактов пока нет.',
        badge: 'Смарт · Coin',
        icon: 'fas fa-coins',
    },
    leadership: {
        title: 'Лидерские контракты',
        listTitle: 'Реестр лидерских контрактов',
        createLabel: 'Создать лидерский контракт',
        emptyText: 'Лидерских контрактов пока нет.',
        badge: 'Лидерский',
        icon: 'fas fa-user-tie',
    },
};

function contractScType(p) {
    const scd = (p && p.smart_contract_data) || {};
    return scd.scType === 'leadership' ? 'leadership' : 'smart';
}

function fmtRubShort(n) {
    n = Number(n) || 0;
    if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' млрд ₽';
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + ' млн ₽';
    if (Math.abs(n) >= 1e3) return Math.round(n / 1e3) + ' тыс ₽';
    return Math.round(n) + ' ₽';
}

function contractsRegistryApp(scType) {
    return {
        ...authMixin(),
        scType,
        meta: CONTRACT_TYPE_META[scType],
        stats: { total: 0, by_status: {}, nav_rate: 10.1, sc_reward_rub: 0, sc_reward_coins: 0 },
        projects: [],
        loading: true,
        aiActive: false,
        search: '',
        statusFilter: '',
        myDraftsOnly: false,
        statusLabels: CONTRACT_STATUS_LABELS,

        get isLeadership() { return this.scType === 'leadership'; },
        get createUrl() { return '/smart-contract-new?type=' + this.scType; },

        async init() {
            if (!redirectIfNotLoggedIn()) return;
            const q = 'project_type=smart_contract&sc_type=' + this.scType;
            try {
                // Без принудительного фильтра по статусу: бэкенд сам ограничивает
                // заявителя его контрактами, согласующим показывает все.
                const [statsRes, projRes] = await Promise.all([
                    authFetch('/api/v1/stats/?' + q),
                    authFetch('/api/v1/projects/?' + q),
                ]);
                if (statsRes.ok) {
                    this.stats = await statsRes.json();
                    this.aiActive = this.stats.ai_active || false;
                }
                if (projRes.ok) this.projects = await projRes.json();
            } catch (e) {
                if (e.message !== 'Unauthorized') console.error('Ошибка загрузки данных:', e);
            } finally {
                this.loading = false;
            }
        },

        get filtered() {
            const s = this.search.trim().toLowerCase();
            const me = this.authUserId;
            return this.projects.filter(p => {
                if (this.statusFilter && (p.status || 'draft') !== this.statusFilter) return false;
                if (this.myDraftsOnly && !((p.status || 'draft') === 'draft' && p.user_id === me)) return false;
                if (!s) return true;
                const scd = p.smart_contract_data || {};
                return [p.name, p.business_unit, p.owner, scd.curator, scd.customerName]
                    .some(v => (v || '').toLowerCase().includes(s));
            });
        },

        get rewardRubFormatted() { return fmtRubShort(this.stats.sc_reward_rub); },
        get rewardCoinsFormatted() {
            const n = this.stats.sc_reward_coins || 0;
            if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' млн';
            if (Math.abs(n) >= 1e3) return Math.round(n / 1e3) + ' тыс';
            return Math.round(n).toLocaleString('ru-RU');
        },

        milestonesRub(p) {
            const ms = (p.smart_contract_data || {}).milestones || [];
            return ms.reduce((s, m) => s + (parseFloat(m.rewardRub) || 0), 0);
        },
        coinsOf(p) {
            const ms = (p.smart_contract_data || {}).milestones || [];
            const c = ms.reduce((s, m) => s + (parseFloat(m.coins) || 0), 0);
            return c ? Math.round(c).toLocaleString('ru-RU') : '—';
        },
        rewardOf(p) {
            const rub = this.milestonesRub(p);
            return rub ? fmtRubShort(rub) : '—';
        },
        fixedOf(p) {
            const v = parseFloat((p.smart_contract_data || {}).fixedSalaryMonthly) || 0;
            return v ? fmtRubShort(v) + '/мес' : '—';
        },
        variableOf(p) {
            const v = parseFloat((p.smart_contract_data || {}).variableTotal) || 0;
            return v ? fmtRubShort(v) : 'без премии';
        },
        leadershipTotalOf(p) {
            const lt = (p.smart_contract_data || {}).leadershipTotals || {};
            return lt.grand ? fmtRubShort(lt.grand) : '—';
        },

        statusLabel(p) { return CONTRACT_STATUS_LABELS[p.status] || p.status || 'Черновик'; },
        statusClass(p) {
            if (p.status === 'approved') return 'st-completed';
            if (p.status === 'rejected') return 'st-risk';
            if (p.status === 'pending_approval') return 'st-pending';
            if (p.status === 'rework_needed') return 'st-rework';
            return 'st-draft';
        },
        formatDate(iso) {
            if (!iso) return '—';
            return new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
        },
        openProject(p) {
            window.location.href = '/smart-contract?id=' + p.id;
        },
    };
}
