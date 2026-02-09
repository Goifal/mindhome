// MindHome Frontend v0.5.1-blockA2 (2026-02-08T20:10) - app.jsx - DIES IST DIE FRONTEND DATEI
// ================================================================
// MindHome - React Frontend Application v0.5.0
// ================================================================

const { useState, useEffect, useCallback, createContext, useContext, useRef, useMemo, useReducer } = React;

// ================================================================
// #32 API Response Cache
// ================================================================
const _apiCache = {};
const CACHE_TTL = 30000; // 30s

// ================================================================
// API Helper
// ================================================================

const getBasePath = () => {
    const path = window.location.pathname;
    const ingressMatch = path.match(/\/api\/hassio_ingress\/[^/]+/);
    if (ingressMatch) return ingressMatch[0];
    return '';
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

const API_BASE = getBasePath();

const api = {
    async get(endpoint) {
        try {
            // #32 Cache check
            const cached = _apiCache[endpoint];
            if (cached && Date.now() - cached.time < CACHE_TTL) return cached.data;
            const res = await fetch(`${API_BASE}/api/${endpoint}`);
            if (!res.ok) throw new Error(`API Error: ${res.status}`);
            const data = await res.json();
            _apiCache[endpoint] = { data, time: Date.now() };
            return data;
        } catch (e) {
            console.error(`GET ${endpoint} failed:`, e);
            return null;
        }
    },
    invalidate(endpoint) { delete _apiCache[endpoint]; },
    async post(endpoint, data = {}) {
        api.invalidate(endpoint); // bust cache on mutations
        try {
            const res = await fetch(`${API_BASE}/api/${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const json = await res.json();
            if (!res.ok) return { _error: true, status: res.status, ...(json || {}) };
            return json;
        } catch (e) {
            console.error(`POST ${endpoint} failed:`, e);
            return { _error: true, message: e.message };
        }
    },
    async put(endpoint, data = {}) {
        try {
            const res = await fetch(`${API_BASE}/api/${endpoint}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            const json = await res.json();
            if (!res.ok) return { _error: true, status: res.status, ...(json || {}) };
            return json;
        } catch (e) {
            console.error(`PUT ${endpoint} failed:`, e);
            return { _error: true, message: e.message };
        }
    },
    async delete(endpoint, data = null) {
        try {
            const opts = { method: 'DELETE' };
            if (data) { opts.headers = { 'Content-Type': 'application/json' }; opts.body = JSON.stringify(data); }
            const res = await fetch(`${API_BASE}/api/${endpoint}`, opts);
            const json = await res.json();
            if (!res.ok) return { _error: true, status: res.status, ...(json || {}) };
            return json;
        } catch (e) {
            console.error(`DELETE ${endpoint} failed:`, e);
            return { _error: true, message: e.message };
        }
    }
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Translations Context
// ================================================================

const translations = { de: null, en: null };

const loadTranslations = async (lang) => {
    if (translations[lang]) return translations[lang];
    try {
        const res = await fetch(`${API_BASE}/api/system/translations/${lang}`);
        if (res.ok) {
            translations[lang] = await res.json();
            return translations[lang];
        }
    } catch (e) {}
    // Fallback inline translations
    return null;
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

const t = (translations, path) => {
    if (!translations) return path;
    const keys = path.split('.');
    let val = translations;
    for (const key of keys) {
        val = val?.[key];
        if (val === undefined) return path;
    }
    return val;
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// App Context
// ================================================================

const AppContext = createContext();

const useApp = () => useContext(AppContext);

// ================================================================
// #4 Error Boundary
// ================================================================
class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }
    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }
    componentDidCatch(error, info) {
        console.error('MindHome Error:', error, info);
        // #38 Frontend error reporting
        try { api.post('system/frontend-error', { error: error.toString(), stack: info.componentStack?.slice(0, 500) }); } catch(e) {}
    }
    render() {
        if (this.state.hasError) {
            return React.createElement('div', {
                style: { padding: 40, textAlign: 'center', color: 'var(--text-primary)' }
            },
                React.createElement('span', { className: 'mdi mdi-alert-circle', style: { fontSize: 48, color: 'var(--danger)', display: 'block', marginBottom: 16 } }),
                React.createElement('h2', null, 'Etwas ist schiefgelaufen'),
                React.createElement('p', { style: { color: 'var(--text-muted)', marginBottom: 16 } }, this.state.error?.toString()),
                React.createElement('button', {
                    className: 'btn btn-primary',
                    onClick: () => { this.setState({ hasError: false }); window.location.reload(); }
                }, 'Seite neu laden')
            );
        }
        return this.props.children;
    }
}

// ================================================================
// #17 Skeleton Loading
// ================================================================
const Skeleton = ({ width, height, borderRadius, style }) => (
    React.createElement('div', {
        className: 'skeleton-pulse',
        style: {
            width: width || '100%',
            height: height || 16,
            borderRadius: borderRadius || 4,
            background: 'var(--bg-tertiary)',
            animation: 'pulse 1.5s ease-in-out infinite',
            ...style
        }
    })
);

const SkeletonCard = () => (
    React.createElement('div', { className: 'card', style: { padding: 16, marginBottom: 12 } },
        React.createElement(Skeleton, { height: 20, width: '60%', style: { marginBottom: 12 } }),
        React.createElement(Skeleton, { height: 14, width: '80%', style: { marginBottom: 8 } }),
        React.createElement(Skeleton, { height: 14, width: '40%' })
    )
);

// ================================================================
// #8 Toast Stacking
// ================================================================

const Toast = ({ message, type, onClose }) => {
    useEffect(() => {
        const timer = setTimeout(onClose, 4000);
        return () => clearTimeout(timer);
    }, []);

    const icons = {
        success: 'mdi-check-circle',
        error: 'mdi-alert-circle',
        info: 'mdi-information',
        warning: 'mdi-alert'
    };

    return (
        <div style={{
            position: 'fixed', bottom: 24, right: 24, zIndex: 3000,
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '12px 20px',
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)',
            animation: 'slideUp 0.3s ease',
            borderLeft: `3px solid var(--${type === 'error' ? 'danger' : type})`
        }}>
            <span className={`mdi ${icons[type] || icons.info}`}
                  style={{ color: `var(--${type === 'error' ? 'danger' : type})`, fontSize: 20 }} />
            <span style={{ fontSize: 14 }}>{message}</span>
            <button onClick={onClose} className="btn-ghost btn-icon btn"
                    style={{ marginLeft: 8, padding: 0, minWidth: 24 }}>
                <span className="mdi mdi-close" style={{ fontSize: 16 }} />
            </button>
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Modal Component
// ================================================================

const Modal = ({ title, children, onClose, actions, wide }) => (
    <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
        <div className="modal" onClick={e => e.stopPropagation()} style={wide ? { maxWidth: 700, width: '90%' } : {}}>
            <div className="modal-title">{title}</div>
            {children}
            {actions && <div className="modal-actions">{actions}</div>}
        </div>
    </div>
);

const CollapsibleCard = ({ title, icon, children, defaultOpen = true }) => {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div className="card">
            <div onClick={() => setOpen(!open)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', userSelect: 'none' }}>
                <div className="card-title" style={{ marginBottom: 0 }}>
                    {icon && <span className={`mdi ${icon}`} style={{ marginRight: 8, color: 'var(--accent-primary)' }} />}
                    {title}
                </div>
                <span className={`mdi ${open ? 'mdi-chevron-up' : 'mdi-chevron-down'}`} style={{ fontSize: 18, color: 'var(--text-muted)' }} />
            </div>
            {open && <div style={{ marginTop: 12 }}>{children}</div>}
        </div>
    );
};

// ================================================================
// Fix 11: Splash Screen
// ================================================================

const SplashScreen = () => (
    <div style={{
        position: 'fixed', inset: 0, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 20,
        background: 'linear-gradient(135deg, #0D1117 0%, #161B22 50%, #1A1F2B 100%)', zIndex: 9999
    }}>
        <img src={`${API_BASE}/icon.png`} alt="MindHome" style={{
            width: 80, height: 80, borderRadius: 18,
            boxShadow: '0 0 40px rgba(245,166,35,0.3)', animation: 'pulse 2s ease-in-out infinite'
        }} />
        <div style={{ fontSize: 26, fontWeight: 700, color: '#F0F6FC', letterSpacing: 1 }}>MindHome</div>
        <div style={{ fontSize: 13, color: '#8B949E' }}>Dein Zuhause denkt mit</div>
        <div className="loading-spinner" style={{ marginTop: 8 }} />
    </div>
);

// ================================================================
// Fix 23: Confirm Dialog
// ================================================================

const ConfirmDialog = ({ title, message, onConfirm, onCancel, danger }) => (
    <div className="modal-overlay" onClick={onCancel}>
        <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 400 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <span className={`mdi ${danger ? 'mdi-alert-circle' : 'mdi-help-circle'}`}
                      style={{ fontSize: 28, color: danger ? 'var(--danger)' : 'var(--accent-primary)' }} />
                <div className="modal-title" style={{ marginBottom: 0 }}>{title}</div>
            </div>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 20 }}>{message}</p>
            <div className="modal-actions">
                <button className="btn btn-secondary" onClick={onCancel}>Abbrechen</button>
                <button className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm}>
                    {danger ? 'LÃ¶schen' : 'BestÃ¤tigen'}
                </button>
            </div>
        </div>
    </div>
);

// ================================================================
// Fix 8: Custom Dropdown Component
// ================================================================

const Dropdown = ({ value, onChange, options, placeholder, label }) => {
    const [open, setOpen] = useState(false);
    const [hovered, setHovered] = useState(null);
    const ref = useRef(null);
    useEffect(() => {
        const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);
    const selected = options.find(o => String(o.value) === String(value));
    return (
        <div ref={ref} style={{ position: 'relative' }}>
            {label && <label className="input-label">{label}</label>}
            <div className="input" onClick={() => setOpen(!open)} style={{
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', userSelect: 'none',
                borderColor: open ? 'var(--accent-primary)' : undefined,
                boxShadow: open ? '0 0 0 2px rgba(245,166,35,0.15)' : undefined,
                transition: 'border-color 0.2s, box-shadow 0.2s'
            }}>
                <span style={{ color: selected ? 'var(--text-primary)' : 'var(--text-muted)' }}>{selected?.label || placeholder || 'â€” AuswÃ¤hlen â€”'}</span>
                <span className={`mdi mdi-chevron-${open ? 'up' : 'down'}`} style={{ fontSize: 18, color: 'var(--text-muted)', transition: 'transform 0.2s' }} />
            </div>
            {open && (
                <div style={{
                    position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4,
                    background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)',
                    zIndex: 1000, maxHeight: 240, overflow: 'auto',
                    animation: 'fadeIn 0.15s ease-out'
                }}>
                    {options.map(opt => {
                        const isSelected = String(opt.value) === String(value);
                        const isHover = hovered === opt.value;
                        return (
                        <div key={opt.value}
                             onClick={() => { onChange(opt.value); setOpen(false); }}
                             onMouseEnter={() => setHovered(opt.value)}
                             onMouseLeave={() => setHovered(null)}
                             style={{
                                 padding: '10px 14px', cursor: 'pointer', fontSize: 14,
                                 display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                 background: isSelected ? 'var(--accent-primary-dim)' : isHover ? 'var(--bg-tertiary)' : 'transparent',
                                 borderLeft: isSelected ? '3px solid var(--accent-primary)' : '3px solid transparent',
                                 transition: 'background 0.15s',
                             }}>
                            <span>{opt.label}</span>
                            {isSelected && <span className="mdi mdi-check" style={{ color: 'var(--accent-primary)', fontSize: 16 }} />}
                        </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Searchable Entity Dropdown (matches system design)
// ================================================================
const EntitySearchDropdown = ({ value, onChange, entities, label, placeholder }) => {
    const [open, setOpen] = useState(false);
    const [search, setSearch] = useState('');
    const ref = useRef(null);
    const inputRef = useRef(null);

    useEffect(() => {
        const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    useEffect(() => {
        if (open && inputRef.current) inputRef.current.focus();
    }, [open]);

    const filtered = (entities || []).filter(e => {
        if (!search) return true;
        const s = search.toLowerCase();
        return (e.ha_entity_id || '').toLowerCase().includes(s) || (e.name || '').toLowerCase().includes(s);
    }).slice(0, 50);

    const selectedEntity = entities?.find(e => e.ha_entity_id === value);
    const displayValue = selectedEntity ? `${selectedEntity.name} (${selectedEntity.ha_entity_id})` : value || '';

    return (
        <div ref={ref} style={{ position: 'relative' }}>
            {label && <label className="input-label">{label}</label>}
            <div className="input" onClick={() => setOpen(!open)} style={{
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', userSelect: 'none',
                borderColor: open ? 'var(--accent-primary)' : undefined,
                boxShadow: open ? '0 0 0 2px rgba(245,166,35,0.15)' : undefined,
            }}>
                <span style={{ color: displayValue ? 'var(--text-primary)' : 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, fontSize: 13 }}>
                    {displayValue || placeholder || 'â€” Entity wÃ¤hlen â€”'}
                </span>
                <span className={`mdi mdi-chevron-${open ? 'up' : 'down'}`} style={{ fontSize: 18, color: 'var(--text-muted)' }} />
            </div>
            {open && (
                <div style={{
                    position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4,
                    background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)',
                    zIndex: 1001, animation: 'fadeIn 0.15s ease-out',
                }}>
                    <div style={{ padding: '8px 8px 4px' }}>
                        <input ref={inputRef} className="input" value={search} onChange={e => setSearch(e.target.value)}
                            placeholder="ðŸ” Suchen..." style={{ fontSize: 12, padding: '6px 10px' }} />
                    </div>
                    <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                        {filtered.length === 0 ? (
                            <div style={{ padding: '12px 14px', fontSize: 12, color: 'var(--text-muted)' }}>Keine Ergebnisse</div>
                        ) : filtered.map(e => {
                            const isSelected = e.ha_entity_id === value;
                            return (
                                <div key={e.id || e.ha_entity_id}
                                    onClick={() => { onChange(e.ha_entity_id); setOpen(false); setSearch(''); }}
                                    style={{
                                        padding: '8px 14px', cursor: 'pointer', fontSize: 13,
                                        background: isSelected ? 'var(--accent-primary-dim)' : 'transparent',
                                        borderLeft: isSelected ? '3px solid var(--accent-primary)' : '3px solid transparent',
                                        transition: 'background 0.15s',
                                    }}
                                    onMouseEnter={ev => ev.currentTarget.style.background = isSelected ? 'var(--accent-primary-dim)' : 'var(--bg-tertiary)'}
                                    onMouseLeave={ev => ev.currentTarget.style.background = isSelected ? 'var(--accent-primary-dim)' : 'transparent'}>
                                    <div style={{ fontWeight: isSelected ? 600 : 400 }}>{e.name || e.ha_entity_id}</div>
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>{e.ha_entity_id}</div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Fix 2: Time Period Filter
// ================================================================

const PeriodFilter = ({ value, onChange, lang }) => {
    const periods = [
        { id: 'today', de: 'Heute', en: 'Today' },
        { id: 'week', de: 'Woche', en: 'Week' },
        { id: 'month', de: 'Monat', en: 'Month' },
        { id: 'all', de: 'Alles', en: 'All' },
    ];
    return (
        <div style={{ display: 'flex', gap: 4 }}>
            {periods.map(p => (
                <button key={p.id} className={`btn ${value === p.id ? 'btn-primary' : 'btn-secondary'}`}
                    style={{ padding: '6px 14px', fontSize: 13 }} onClick={() => onChange(p.id)}>
                    {p[lang]}
                </button>
            ))}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// Fix 13: Relative time helper
const relativeTime = (isoStr, lang) => {
    if (!isoStr) return lang === 'de' ? 'Keine AktivitÃ¤t' : 'No activity';
    const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 60) return lang === 'de' ? 'Gerade eben' : 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)} Min`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} Std`;
    return `${Math.floor(diff / 86400)} ${lang === 'de' ? 'Tage' : 'days'}`;
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

const stateDisplay = (state) => {
    if (!state || state === 'unknown') return { label: '?', color: 'var(--text-muted)' };
    if (state === 'on') return { label: 'on', color: 'var(--success)' };
    if (state === 'off') return { label: 'off', color: 'var(--text-muted)' };
    if (state === 'unavailable') return { label: 'âœ•', color: 'var(--danger)' };
    return { label: state, color: 'var(--info)' };
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

const formatBytes = (bytes) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Dashboard Page
// ================================================================

const DashboardPage = () => {
    const { status, domains, devices, rooms, lang, tr, showToast } = useApp();
    const [learningStats, setLearningStats] = useState(null);
    const [predictions, setPredictions] = useState([]);
    const [anomalies, setAnomalies] = useState([]);
    const [unreadCount, setUnreadCount] = useState(0);
    const [sysHealth, setSysHealth] = useState(null);
    const [weeklyReport, setWeeklyReport] = useState(null);
    const [configIssues, setConfigIssues] = useState(null);
    const [deviceHealth, setDeviceHealth] = useState(null);      // #24
    const [showChangelog, setShowChangelog] = useState(false);     // #21
    const activeDomains = domains.filter(d => d.is_enabled).length;
    const trackedDevices = devices.length;

    // #43 Onboarding checklist
    const checklist = useMemo(() => {
        const items = [
            { key: 'rooms', label: lang === 'de' ? 'RÃ¤ume erstellt' : 'Rooms created', done: rooms.length > 0 },
            { key: 'devices', label: lang === 'de' ? 'GerÃ¤te zugeordnet' : 'Devices assigned', done: devices.some(d => d.room_id) },
            { key: 'domains', label: lang === 'de' ? 'Domains aktiv' : 'Domains active', done: domains.some(d => d.is_enabled) },
            { key: 'patterns', label: lang === 'de' ? 'Erste Muster' : 'First patterns', done: learningStats?.total_patterns > 0 },
        ];
        return items;
    }, [rooms, devices, domains, learningStats, lang]);
    const checklistProgress = checklist.filter(c => c.done).length;

    useEffect(() => {
        api.get('stats/learning').then(setLearningStats).catch(() => {});
        api.get('predictions?status=pending&limit=5').then(setPredictions).catch(() => {});
        api.get('automation/anomalies').then(setAnomalies).catch(() => {});
        api.get('notifications/unread-count').then(d => setUnreadCount(d.unread_count || 0)).catch(() => {});
        api.get('device-health').then(setDeviceHealth).catch(() => {});  // #24
        api.get('health').then(setSysHealth).catch(() => {});
        api.get('report/weekly').then(setWeeklyReport).catch(() => {});
        api.get('validate-config').then(setConfigIssues).catch(() => {});
    }, []);

    const modeLabels = {
        normal: { de: 'Normal', en: 'Normal', color: 'success' },
        away: { de: 'Abwesend', en: 'Away', color: 'info' },
        guest: { de: 'GÃ¤ste-Modus', en: 'Guest Mode', color: 'info' },
        vacation: { de: 'Urlaubsmodus', en: 'Vacation', color: 'warning' },
        emergency_stop: { de: 'NOT-AUS', en: 'EMERGENCY STOP', color: 'danger' }
    };

    const mode = modeLabels[status?.system_mode] || modeLabels.normal;

    return (
        <div>
            {/* System Status Panel */}
            <div className="card animate-in" style={{ marginBottom: 24, padding: 0, overflow: 'hidden' }}>
                <div style={{ padding: '16px 20px 12px', borderBottom: '1px solid var(--border-color)' }}>
                    <div className="card-title" style={{ marginBottom: 0 }}>
                        <span className="mdi mdi-server-network" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                        {lang === 'de' ? 'Systemstatus' : 'System Status'}
                    </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 0 }}>
                    {/* HA WebSocket */}
                    {(() => {
                        const wsOk = sysHealth?.checks?.ha_websocket?.status === 'ok';
                        return (
                        <div style={{ padding: '14px 20px', borderRight: '1px solid var(--border-color)', borderBottom: '1px solid var(--border-color)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                <span style={{ width: 8, height: 8, borderRadius: '50%', background: wsOk ? 'var(--success)' : 'var(--danger)', boxShadow: wsOk ? '0 0 6px var(--success)' : '0 0 6px var(--danger)', flexShrink: 0 }} />
                                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>HA WebSocket</span>
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', paddingLeft: 16 }}>
                                {wsOk ? (lang === 'de' ? 'Verbunden' : 'Connected') : (lang === 'de' ? 'Getrennt' : 'Disconnected')}
                                {sysHealth?.checks?.ha_websocket?.reconnect_attempts > 0 && (
                                    <span style={{ color: 'var(--warning)' }}> Â· {sysHealth.checks.ha_websocket.reconnect_attempts} Reconnects</span>
                                )}
                            </div>
                        </div>
                        );
                    })()}

                    {/* HA REST API */}
                    {(() => {
                        const restOk = sysHealth?.checks?.ha_rest_api?.status === 'ok';
                        return (
                        <div style={{ padding: '14px 20px', borderRight: '1px solid var(--border-color)', borderBottom: '1px solid var(--border-color)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                <span style={{ width: 8, height: 8, borderRadius: '50%', background: restOk ? 'var(--success)' : 'var(--danger)', boxShadow: restOk ? '0 0 6px var(--success)' : '0 0 6px var(--danger)', flexShrink: 0 }} />
                                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>HA REST API</span>
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', paddingLeft: 16 }}>
                                {restOk ? (lang === 'de' ? 'Erreichbar' : 'Reachable') : (lang === 'de' ? 'Offline' : 'Offline')}
                            </div>
                        </div>
                        );
                    })()}

                    {/* Database */}
                    {(() => {
                        const dbOk = sysHealth?.checks?.database?.status === 'ok';
                        return (
                        <div style={{ padding: '14px 20px', borderRight: '1px solid var(--border-color)', borderBottom: '1px solid var(--border-color)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                <span style={{ width: 8, height: 8, borderRadius: '50%', background: dbOk ? 'var(--success)' : 'var(--danger)', boxShadow: dbOk ? '0 0 6px var(--success)' : '0 0 6px var(--danger)', flexShrink: 0 }} />
                                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{lang === 'de' ? 'Datenbank' : 'Database'}</span>
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', paddingLeft: 16 }}>
                                {dbOk ? 'SQLite OK' : (sysHealth?.checks?.database?.message || 'Error')}
                            </div>
                        </div>
                        );
                    })()}

                    {/* MindHome Engine */}
                    {(() => {
                        const ok = status?.status === 'running';
                        const uptime = sysHealth?.uptime_seconds || 0;
                        const hours = Math.floor(uptime / 3600);
                        const days = Math.floor(hours / 24);
                        const uptimeStr = days > 0 ? `${days}d ${hours % 24}h` : hours > 0 ? `${hours}h ${Math.floor((uptime % 3600) / 60)}m` : `${Math.floor(uptime / 60)}m`;
                        return (
                        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-color)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                                <span style={{ width: 8, height: 8, borderRadius: '50%', background: ok ? 'var(--success)' : 'var(--danger)', boxShadow: ok ? '0 0 6px var(--success)' : '0 0 6px var(--danger)', flexShrink: 0 }} />
                                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>MindHome Engine</span>
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', paddingLeft: 16 }}>
                                v{sysHealth?.version || '0.5.0'} Â· Uptime {uptimeStr}
                            </div>
                        </div>
                        );
                    })()}
                </div>
            </div>

            {/* Stats Overview */}
            <div className="stat-grid">
                <div className="stat-card animate-in">
                    <div className="stat-icon" style={{ background: `var(--${mode.color}-dim)`, color: `var(--${mode.color})` }}>
                        <span className="mdi mdi-shield-check" />
                    </div>
                    <div>
                        <div className={`badge badge-${mode.color}`}>
                            <span className="badge-dot" />{mode[lang]}
                        </div>
                        <div className="stat-label">{lang === 'de' ? 'Systemmodus' : 'System Mode'}</div>
                    </div>
                </div>

                <div className="stat-card animate-in animate-in-delay-1">
                    <div className="stat-icon" style={{ background: 'var(--accent-primary-dim)', color: 'var(--accent-primary)' }}>
                        <span className="mdi mdi-puzzle" />
                    </div>
                    <div>
                        <div className="stat-value">{activeDomains}</div>
                        <div className="stat-label">{lang === 'de' ? 'Aktive Domains' : 'Active Domains'}</div>
                    </div>
                </div>

                <div className="stat-card animate-in animate-in-delay-2">
                    <div className="stat-icon" style={{ background: 'var(--accent-secondary-dim)', color: 'var(--accent-secondary)' }}>
                        <span className="mdi mdi-devices" />
                    </div>
                    <div>
                        <div className="stat-value">{trackedDevices}</div>
                        <div className="stat-label">{lang === 'de' ? 'GerÃ¤te' : 'Devices'}</div>
                    </div>
                </div>

                <div className="stat-card animate-in animate-in-delay-3">
                    <div className="stat-icon" style={{ background: 'var(--info-dim)', color: 'var(--info)' }}>
                        <span className="mdi mdi-door-open" />
                    </div>
                    <div>
                        <div className="stat-value">{rooms.length}</div>
                        <div className="stat-label">{lang === 'de' ? 'RÃ¤ume' : 'Rooms'}</div>
                    </div>
                </div>
            </div>

            {/* #43 Onboarding Checklist */}
            {checklistProgress < checklist.length && (
                <div className="card animate-in" style={{ marginBottom: 16, padding: 16, borderLeft: '3px solid var(--accent-primary)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                        <div className="card-title" style={{ fontSize: 14 }}>
                            <span className="mdi mdi-checkbox-marked-circle-outline" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                            {lang === 'de' ? 'Einrichtung' : 'Setup'} ({checklistProgress}/{checklist.length})
                        </div>
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {checklist.map(c => (
                            <span key={c.key} style={{
                                fontSize: 12, padding: '4px 10px', borderRadius: 12,
                                background: c.done ? 'var(--success-dim)' : 'var(--bg-tertiary)',
                                color: c.done ? 'var(--success)' : 'var(--text-muted)',
                                textDecoration: c.done ? 'line-through' : 'none',
                            }}>
                                <span className={`mdi ${c.done ? 'mdi-check' : 'mdi-circle-outline'}`} style={{ marginRight: 4 }} />
                                {c.label}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {/* #24 Device Health Warnings */}
            {/* Quick Actions */}
            <div className="card animate-in animate-in-delay-2" style={{ marginBottom: 24 }}>
                <div className="card-header">
                    <div>
                        <div className="card-title">Quick Actions</div>
                        <div className="card-subtitle">
                            {lang === 'de' ? 'Schnellzugriff' : 'Quick access'}
                        </div>
                    </div>
                </div>
                <QuickActionsGrid />
            </div>

            {/* Phase 2a: Learning Progress */}
            {learningStats && (learningStats.total_events > 0 || learningStats.total_patterns > 0) && (
                <div className="card animate-in animate-in-delay-2" style={{ marginBottom: 24 }}>
                    <div className="card-header">
                        <div>
                            <div className="card-title">
                                <span className="mdi mdi-lightbulb-on" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                                {lang === 'de' ? 'Lernfortschritt' : 'Learning Progress'}
                            </div>
                            <div className="card-subtitle">
                                {lang === 'de'
                                    ? `${learningStats.days_collecting} Tage Daten, ${learningStats.total_events} Events`
                                    : `${learningStats.days_collecting} days of data, ${learningStats.total_events} events`}
                            </div>
                        </div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, padding: '0 16px 16px' }}>
                        <div style={{ padding: 12, background: 'var(--bg-tertiary)', borderRadius: 8, textAlign: 'center' }}>
                            <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--accent-primary)' }}>
                                {learningStats.total_patterns}
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                {lang === 'de' ? 'Muster erkannt' : 'Patterns found'}
                            </div>
                        </div>
                        <div style={{ padding: 12, background: 'var(--bg-tertiary)', borderRadius: 8, textAlign: 'center' }}>
                            <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--success)' }}>
                                {learningStats.avg_confidence ? `${Math.round(learningStats.avg_confidence * 100)}%` : 'â€”'}
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                {lang === 'de' ? 'Ã˜ Vertrauen' : 'Avg Confidence'}
                            </div>
                        </div>
                        <div style={{ padding: 12, background: 'var(--bg-tertiary)', borderRadius: 8, textAlign: 'center' }}>
                            <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--warning)' }}>
                                {learningStats.events_today}
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                {lang === 'de' ? 'Events heute' : 'Events today'}
                            </div>
                        </div>
                    </div>
                    {/* Top patterns preview */}
                    {learningStats.top_patterns?.length > 0 && (
                        <div style={{ padding: '0 16px 16px' }}>
                            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8 }}>
                                {lang === 'de' ? 'Top Muster:' : 'Top patterns:'}
                            </div>
                            {learningStats.top_patterns.slice(0, 3).map(p => (
                                <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', fontSize: 13 }}>
                                    <span className={`mdi ${p.pattern_type === 'time_based' ? 'mdi-clock-outline' : p.pattern_type === 'event_chain' ? 'mdi-link-variant' : 'mdi-chart-scatter-plot'}`}
                                          style={{ color: 'var(--accent-primary)', fontSize: 16 }} />
                                    <span style={{ flex: 1 }}>{p.description}</span>
                                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{Math.round(p.confidence * 100)}%</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Phase 2b: Pending Suggestions */}
            {predictions.length > 0 && (
                <div className="card animate-in" style={{ marginBottom: 24, borderLeft: '3px solid var(--warning)' }}>
                    <div className="card-header">
                        <div>
                            <div className="card-title">
                                <span className="mdi mdi-lightbulb-on" style={{ marginRight: 8, color: 'var(--warning)' }} />
                                {lang === 'de' ? 'VorschlÃ¤ge' : 'Suggestions'}
                                <span className="badge badge-warning" style={{ marginLeft: 8 }}>{predictions.length}</span>
                            </div>
                            <div className="card-subtitle">
                                {lang === 'de' ? 'MindHome hat neue Muster erkannt' : 'MindHome found new patterns'}
                            </div>
                        </div>
                        {predictions.length > 1 && (
                            <div style={{ display: 'flex', gap: 6 }}>
                                <button className="btn btn-sm btn-success" onClick={async () => {
                                    for (const p of predictions) await api.post(`predictions/${p.id}/confirm`);
                                    setPredictions([]);
                                    showToast(lang === 'de' ? `${predictions.length} aktiviert` : `${predictions.length} activated`, 'success');
                                }}>
                                    <span className="mdi mdi-check-all" style={{ marginRight: 4 }} />
                                    {lang === 'de' ? 'Alle' : 'All'}
                                </button>
                                <button className="btn btn-sm btn-ghost" onClick={async () => {
                                    for (const p of predictions) await api.post(`predictions/${p.id}/reject`);
                                    setPredictions([]);
                                    showToast(lang === 'de' ? 'Alle abgelehnt' : 'All rejected', 'info');
                                }}>
                                    <span className="mdi mdi-close-circle-outline" style={{ marginRight: 4 }} />
                                    {lang === 'de' ? 'Alle' : 'All'}
                                </button>
                            </div>
                        )}
                    </div>
                    {predictions.map(pred => (
                        <div key={pred.id} style={{
                            padding: '12px 16px', borderBottom: '1px solid var(--border-color)',
                            display: 'flex', alignItems: 'center', gap: 12
                        }}>
                            <span className="mdi mdi-robot" style={{ fontSize: 20, color: 'var(--accent-primary)' }} />
                            <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 14 }}>{pred.description || 'New pattern'}</div>
                                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                    {lang === 'de' ? 'Vertrauen' : 'Confidence'}: {Math.round(pred.confidence * 100)}%
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: 6 }}>
                                <button className="btn btn-sm btn-success" onClick={async () => {
                                    await api.post(`predictions/${pred.id}/confirm`);
                                    setPredictions(p => p.filter(x => x.id !== pred.id));
                                    showToast(lang === 'de' ? 'Aktiviert!' : 'Activated!', 'success');
                                }}>
                                    <span className="mdi mdi-check" />
                                </button>
                                <button className="btn btn-sm btn-ghost" onClick={async () => {
                                    await api.post(`predictions/${pred.id}/reject`);
                                    setPredictions(p => p.filter(x => x.id !== pred.id));
                                    showToast(lang === 'de' ? 'Abgelehnt' : 'Rejected', 'info');
                                }}>
                                    <span className="mdi mdi-close" />
                                </button>
                                <button className="btn btn-sm btn-ghost" onClick={async () => {
                                    await api.post(`predictions/${pred.id}/ignore`);
                                    setPredictions(p => p.filter(x => x.id !== pred.id));
                                }} title={lang === 'de' ? 'SpÃ¤ter' : 'Later'}>
                                    <span className="mdi mdi-clock-outline" />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Phase 2b: Anomaly Alerts */}
            {/* Weekly Report - improved (#11) */}
            {weeklyReport && (
                <div className="card animate-in animate-in-delay-2" style={{ marginBottom: 16 }}>
                    <div className="card-title" style={{ marginBottom: 14, display: 'flex', alignItems: 'center' }}>
                        <span className="mdi mdi-chart-timeline-variant" style={{ marginRight: 8, color: 'var(--accent-primary)', fontSize: 20 }} />
                        {lang === 'de' ? 'Wochenbericht' : 'Weekly Report'}
                        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
                            {lang === 'de' ? 'Letzte 7 Tage' : 'Last 7 days'}
                        </span>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
                        <div style={{ textAlign: 'center', padding: '14px 10px', background: 'var(--bg-main)', borderRadius: 10, border: '1px solid rgba(99,102,241,0.15)' }}>
                            <span className="mdi mdi-pulse" style={{ fontSize: 20, color: 'var(--accent-primary)', display: 'block', marginBottom: 4 }} />
                            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--accent-primary)' }}>{weeklyReport.events_collected?.toLocaleString()}</div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{lang === 'de' ? 'Events' : 'Events'}</div>
                        </div>
                        <div style={{ textAlign: 'center', padding: '14px 10px', background: 'var(--bg-main)', borderRadius: 10, border: '1px solid rgba(52,211,153,0.15)' }}>
                            <span className="mdi mdi-lightbulb-on" style={{ fontSize: 20, color: 'var(--success)', display: 'block', marginBottom: 4 }} />
                            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--success)' }}>{weeklyReport.new_patterns}</div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{lang === 'de' ? 'Neue Muster' : 'New Patterns'}</div>
                        </div>
                        <div style={{ textAlign: 'center', padding: '14px 10px', background: 'var(--bg-main)', borderRadius: 10, border: '1px solid rgba(251,191,36,0.15)' }}>
                            <span className="mdi mdi-robot" style={{ fontSize: 20, color: 'var(--warning)', display: 'block', marginBottom: 4 }} />
                            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--warning)' }}>{weeklyReport.automations_executed}</div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{lang === 'de' ? 'Automationen' : 'Automations'}</div>
                        </div>
                        <div style={{ textAlign: 'center', padding: '14px 10px', background: 'var(--bg-main)', borderRadius: 10, border: '1px solid rgba(96,165,250,0.15)' }}>
                            <span className="mdi mdi-check-decagram" style={{ fontSize: 20, color: 'var(--info)', display: 'block', marginBottom: 4 }} />
                            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--info)' }}>{weeklyReport.success_rate}%</div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{lang === 'de' ? 'Erfolgsrate' : 'Success Rate'}</div>
                        </div>
                        {weeklyReport.energy_saved_kwh > 0 && (
                            <div style={{ textAlign: 'center', padding: '14px 10px', background: 'var(--bg-main)', borderRadius: 10, border: '1px solid rgba(52,211,153,0.15)' }}>
                                <span className="mdi mdi-lightning-bolt" style={{ fontSize: 20, color: 'var(--success)', display: 'block', marginBottom: 4 }} />
                                <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--success)' }}>~{weeklyReport.energy_saved_kwh}</div>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>kWh {lang === 'de' ? 'gespart' : 'saved'}</div>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Config Issues - removed per user request (#10) */}

            {/* Anomaly card - moved below weekly report */}
            {anomalies.length > 0 && (
                <div className="card animate-in" style={{ marginBottom: 24, borderLeft: '3px solid var(--danger)' }}>
                    <div className="card-header">
                        <div className="card-title">
                            <span className="mdi mdi-alert-circle" style={{ marginRight: 8, color: 'var(--danger)' }} />
                            {lang === 'de' ? 'UngewÃ¶hnliche AktivitÃ¤t' : 'Unusual Activity'}
                        </div>
                    </div>
                    {anomalies.slice(0, 3).map((a, i) => (
                        <div key={i} style={{ padding: '10px 16px', fontSize: 13, borderBottom: '1px solid var(--border-color)' }}>
                            <span className="mdi mdi-alert" style={{ marginRight: 6, color: 'var(--warning)' }} />
                            {lang === 'de' ? a.reason_de : a.reason_en}
                        </div>
                    ))}
                </div>
            )}

            {/* Rooms Overview - removed per user request (#12), use RÃ¤ume page instead */}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Quick Actions Component
// ================================================================

const QuickActionsGrid = () => {
    const { quickActions, executeQuickAction, lang, showToast, refreshData, isAdmin } = useApp();
    const [showAdd, setShowAdd] = useState(false);
    const [editAction, setEditAction] = useState(null);
    const [newAction, setNewAction] = useState({ name: '', icon: 'mdi:flash', action_data: { type: 'custom', entities: [] } });

    const iconOptions = [
        { value: 'mdi:flash', label: 'âš¡ Flash' }, { value: 'mdi:lightbulb', label: 'ðŸ’¡ Licht' },
        { value: 'mdi:home', label: 'ðŸ  Home' }, { value: 'mdi:exit-run', label: 'ðŸšª Gehen' },
        { value: 'mdi:weather-night', label: 'ðŸŒ™ Nacht' }, { value: 'mdi:shield', label: 'ðŸ›¡ï¸ Schutz' },
        { value: 'mdi:movie-open', label: 'ðŸŽ¬ Kino' }, { value: 'mdi:broom', label: 'ðŸ§¹ AufrÃ¤umen' },
        { value: 'mdi:party-popper', label: 'ðŸŽ‰ Party' }, { value: 'mdi:coffee', label: 'â˜• Kaffee' },
    ];

    const handleCreate = async () => {
        if (!newAction.name.trim()) return;
        await api.post('quick-actions', newAction);
        setShowAdd(false);
        setNewAction({ name: '', icon: 'mdi:flash', action_data: { type: 'custom', entities: [] } });
        await refreshData();
        showToast(lang === 'de' ? 'Quick Action erstellt' : 'Quick Action created', 'success');
    };

    const handleDelete = async (id) => {
        await api.delete(`quick-actions/${id}`);
        await refreshData();
        showToast(lang === 'de' ? 'Quick Action gelÃ¶scht' : 'Quick Action deleted', 'success');
    };

    return (
        <div>
            <div className="quick-actions-grid">
                {quickActions.map(action => {
                    // #9: Smart icon fallback based on action name/type
                    const getSmartIcon = (a) => {
                        const normalizeIcon = (icon) => icon ? icon.replace('mdi:', 'mdi-') : '';
                        const icon = normalizeIcon(a.icon);
                        if (icon && icon !== 'mdi-flash' && icon !== '') return `mdi ${icon}`;
                        const name = (a.name || '').toLowerCase();
                        const type = (a.action_data?.type || '').toLowerCase();
                        if (type === 'emergency_stop' || name.includes('not')) return 'mdi mdi-alert-octagon';
                        if (type === 'all_off' || name.includes('alles aus')) return 'mdi mdi-power-off';
                        if (name.includes('gehe') || name.includes('leaving') || name.includes('weg')) return 'mdi mdi-exit-run';
                        if (name.includes('zurÃ¼ck') || name.includes('back') || name.includes('home')) return 'mdi mdi-home-account';
                        if (name.includes('gÃ¤ste') || name.includes('guest') || name.includes('party')) return 'mdi mdi-account-group';
                        if (name.includes('nacht') || name.includes('night') || name.includes('schlaf')) return 'mdi mdi-weather-night';
                        if (name.includes('morgen') || name.includes('morning')) return 'mdi mdi-weather-sunset-up';
                        if (name.includes('kino') || name.includes('movie') || name.includes('film')) return 'mdi mdi-movie-open';
                        if (name.includes('essen') || name.includes('dinner')) return 'mdi mdi-silverware-fork-knife';
                        return `mdi ${icon || 'mdi-lightning-bolt'}`;
                    };
                    return (
                    <div key={action.id} style={{ position: 'relative' }}>
                        <button
                            className={`quick-action-btn ${action.action_data?.type === 'emergency_stop' ? 'danger' : ''}`}
                            onClick={() => executeQuickAction(action.id)}
                        >
                            <span className={getSmartIcon(action)} />
                            {action.name}
                        </button>
                        {isAdmin && !action.is_system && (
                            <button onClick={() => handleDelete(action.id)}
                                style={{ position: 'absolute', top: -6, right: -6, width: 20, height: 20, borderRadius: '50%',
                                    background: 'var(--danger)', border: 'none', color: '#fff', fontSize: 12,
                                    cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    opacity: 0.8, transition: 'opacity 0.2s' }}
                                onMouseEnter={e => e.target.style.opacity = 1}
                                onMouseLeave={e => e.target.style.opacity = 0.8}>
                                <span className="mdi mdi-close" />
                            </button>
                        )}
                    </div>
                    );
                })}
                {isAdmin && (
                    <button className="quick-action-btn" onClick={() => setShowAdd(true)}
                        style={{ borderStyle: 'dashed', opacity: 0.6 }}>
                        <span className="mdi mdi-plus" />
                        {lang === 'de' ? 'Neu' : 'New'}
                    </button>
                )}
            </div>

            {showAdd && (
                <Modal title={lang === 'de' ? 'Quick Action erstellen' : 'Create Quick Action'}
                    onClose={() => setShowAdd(false)}
                    actions={<>
                        <button className="btn btn-secondary" onClick={() => setShowAdd(false)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                        <button className="btn btn-primary" onClick={handleCreate} disabled={!newAction.name.trim()}>{lang === 'de' ? 'Erstellen' : 'Create'}</button>
                    </>}>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">{lang === 'de' ? 'Name' : 'Name'}</label>
                        <input className="input" value={newAction.name}
                            onChange={e => setNewAction({ ...newAction, name: e.target.value })}
                            placeholder={lang === 'de' ? 'z.B. Gute Nacht' : 'e.g. Good Night'} autoFocus />
                    </div>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <Dropdown label="Icon" value={newAction.icon}
                            onChange={v => setNewAction({ ...newAction, icon: v })}
                            options={iconOptions} />
                    </div>
                </Modal>
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Domains Page
// ================================================================

const DomainsPage = () => {
    const { domains, toggleDomain, lang, showToast, refreshData } = useApp();
    const [showCreate, setShowCreate] = useState(false);
    const [newDomain, setNewDomain] = useState({ name_de: '', name_en: '', icon: 'mdi:puzzle', description: '' });
    const [confirmDel, setConfirmDel] = useState(null);
    const [editDomain, setEditDomain] = useState(null);
    const [capabilities, setCapabilities] = useState({});
    const [expandedDomain, setExpandedDomain] = useState(null);

    useEffect(() => {
        api.get('domains/capabilities').then(c => c && setCapabilities(c));
    }, []);

    const handleCreate = async () => {
        if (!newDomain.name_de.trim()) return;
        const result = await api.post('domains', {
            name: newDomain.name_de.toLowerCase().replace(/\s+/g, '_'),
            display_name_de: newDomain.name_de,
            display_name_en: newDomain.name_en || newDomain.name_de,
            icon: newDomain.icon || 'mdi:puzzle',
            description_de: newDomain.description,
            description_en: newDomain.description
        });
        if (result?.id) {
            showToast(lang === 'de' ? 'Domain erstellt' : 'Domain created', 'success');
            setShowCreate(false);
            setNewDomain({ name_de: '', name_en: '', icon: 'mdi:puzzle', description: '' });
            await refreshData();
        }
    };

    const handleDeleteDomain = async () => {
        if (!confirmDel) return;
        const result = await api.delete(`domains/${confirmDel.id}`);
        if (result?.success) {
            showToast(lang === 'de' ? 'Domain gelÃ¶scht' : 'Domain deleted', 'success');
            setConfirmDel(null);
            await refreshData();
        } else {
            showToast(result?.error || 'Error', 'error');
        }
    };

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
                    {lang === 'de'
                        ? 'Aktiviere die Bereiche die MindHome Ã¼berwachen und steuern soll.'
                        : 'Activate the areas MindHome should monitor and control.'}
                </p>
                <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
                    <span className="mdi mdi-plus" />
                    {lang === 'de' ? 'Custom Domain' : 'Custom Domain'}
                </button>
            </div>
            <div className="domain-grid">
                {domains.map(domain => (
                    <div
                        key={domain.id}
                        className={`domain-card ${domain.is_enabled ? 'enabled' : ''}`}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flex: 1, cursor: 'pointer' }}
                            onClick={() => setExpandedDomain(expandedDomain === domain.id ? null : domain.id)}>
                            <span className={`mdi ${domain.icon}`} />
                            <div className="domain-card-info">
                                <div className="domain-card-name">{domain.display_name}</div>
                                <div className="domain-card-desc">{domain.description}</div>
                            </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, marginLeft: 8 }}>
                            {domain.is_custom && (
                                <button className="btn btn-ghost btn-icon"
                                    onClick={e => { e.stopPropagation(); setEditDomain({ ...domain }); }}
                                    title={lang === 'de' ? 'Bearbeiten' : 'Edit'}>
                                    <span className="mdi mdi-pencil-outline" style={{ fontSize: 16, color: 'var(--accent-primary)' }} />
                                </button>
                            )}
                            {domain.is_custom && (
                                <button className="btn btn-ghost btn-icon"
                                    onClick={e => { e.stopPropagation(); setConfirmDel(domain); }}
                                    title={lang === 'de' ? 'LÃ¶schen' : 'Delete'}>
                                    <span className="mdi mdi-delete-outline" style={{ fontSize: 16, color: 'var(--danger)' }} />
                                </button>
                            )}
                            <label className="toggle" onClick={e => e.stopPropagation()}>
                                <input type="checkbox" checked={domain.is_enabled}
                                       onChange={() => toggleDomain(domain.id)} />
                                <div className="toggle-slider" />
                            </label>
                        </div>
                        {expandedDomain === domain.id && (() => {
                            const cap = capabilities[domain.name] || {};
                            const controlLabels = {
                                toggle: lang === 'de' ? 'Ein/Aus' : 'Toggle',
                                brightness: lang === 'de' ? 'Helligkeit' : 'Brightness',
                                color_temp: lang === 'de' ? 'Farbtemperatur' : 'Color Temp',
                                set_temperature: lang === 'de' ? 'Temperatur' : 'Temperature',
                                set_hvac_mode: lang === 'de' ? 'Modus' : 'HVAC Mode',
                                open: lang === 'de' ? 'Ã–ffnen' : 'Open', close: lang === 'de' ? 'SchlieÃŸen' : 'Close',
                                set_position: lang === 'de' ? 'Position' : 'Position',
                                volume: lang === 'de' ? 'LautstÃ¤rke' : 'Volume', source: 'Quelle',
                                lock: lang === 'de' ? 'Sperren' : 'Lock', unlock: lang === 'de' ? 'Entsperren' : 'Unlock',
                                start: 'Start', stop: 'Stop', return_to_base: lang === 'de' ? 'ZurÃ¼ck' : 'Return',
                                set_percentage: '%',
                            };
                            const featureLabels = {
                                time_of_day: lang === 'de' ? 'Tageszeit' : 'Time of Day',
                                brightness_level: lang === 'de' ? 'Helligkeitsstufe' : 'Brightness Level',
                                duration: lang === 'de' ? 'Dauer' : 'Duration',
                                target_temp: lang === 'de' ? 'Zieltemperatur' : 'Target Temp',
                                schedule: lang === 'de' ? 'Zeitplan' : 'Schedule',
                                comfort_profile: lang === 'de' ? 'Komfortprofil' : 'Comfort Profile',
                                position: 'Position', sun_based: lang === 'de' ? 'Sonnenstand' : 'Sun Position',
                                threshold: lang === 'de' ? 'Schwellwert' : 'Threshold',
                                trend: 'Trend', trigger: 'Trigger', frequency: lang === 'de' ? 'HÃ¤ufigkeit' : 'Frequency',
                                source_preference: lang === 'de' ? 'Quellen-PrÃ¤ferenz' : 'Source Pref.',
                                presence: lang === 'de' ? 'Anwesenheit' : 'Presence',
                                temperature_based: lang === 'de' ? 'Temperaturbasiert' : 'Temp Based',
                            };
                            return cap.controls || cap.pattern_features ? (
                                <div style={{ width: '100%', padding: '12px 0 4px', borderTop: '1px solid var(--border)', marginTop: 8 }}
                                    onClick={e => e.stopPropagation()}>
                                    {cap.controls?.length > 0 && (
                                        <div style={{ marginBottom: 8 }}>
                                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                                                {lang === 'de' ? 'Steuerung:' : 'Controls:'}
                                            </div>
                                            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                                {cap.controls.map(c => (
                                                    <span key={c} className="badge badge-info" style={{ fontSize: 10 }}>
                                                        {controlLabels[c] || c}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                    {cap.pattern_features?.length > 0 && (
                                        <div>
                                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                                                {lang === 'de' ? 'Muster-Erkennung:' : 'Pattern Detection:'}
                                            </div>
                                            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                                {cap.pattern_features.map(f => (
                                                    <span key={f} className="badge badge-success" style={{ fontSize: 10 }}>
                                                        {featureLabels[f] || f}
                                                    </span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            ) : null;
                        })()}
                    </div>
                ))}
            </div>

            {showCreate && (
                <Modal title={lang === 'de' ? 'Custom Domain erstellen' : 'Create Custom Domain'}
                    onClose={() => setShowCreate(false)}
                    actions={
                        <>
                            <button className="btn btn-secondary" onClick={() => setShowCreate(false)}>
                                {lang === 'de' ? 'Abbrechen' : 'Cancel'}
                            </button>
                            <button className="btn btn-primary" onClick={handleCreate} disabled={!newDomain.name_de.trim()}>
                                {lang === 'de' ? 'Erstellen' : 'Create'}
                            </button>
                        </>
                    }>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">{lang === 'de' ? 'Name (Deutsch)' : 'Name (German)'}</label>
                        <input className="input" value={newDomain.name_de}
                            onChange={e => setNewDomain({ ...newDomain, name_de: e.target.value })}
                            placeholder={lang === 'de' ? 'z.B. BewÃ¤sserung' : 'e.g. Irrigation'} />
                    </div>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">{lang === 'de' ? 'Name (Englisch)' : 'Name (English)'}</label>
                        <input className="input" value={newDomain.name_en}
                            onChange={e => setNewDomain({ ...newDomain, name_en: e.target.value })}
                            placeholder={lang === 'de' ? 'z.B. Irrigation' : 'e.g. Irrigation'} />
                    </div>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">Icon (MDI)</label>
                        <input className="input" value={newDomain.icon}
                            onChange={e => setNewDomain({ ...newDomain, icon: e.target.value })}
                            placeholder="mdi:puzzle" />
                    </div>
                    <div className="input-group">
                        <label className="input-label">{lang === 'de' ? 'Beschreibung' : 'Description'}</label>
                        <input className="input" value={newDomain.description}
                            onChange={e => setNewDomain({ ...newDomain, description: e.target.value })} />
                    </div>
                </Modal>
            )}

            {confirmDel && (
                <ConfirmDialog
                    title={lang === 'de' ? 'Domain lÃ¶schen' : 'Delete Domain'}
                    message={lang === 'de' ? `"${confirmDel.display_name}" wirklich lÃ¶schen?` : `Delete "${confirmDel.display_name}"?`}
                    danger onConfirm={handleDeleteDomain} onCancel={() => setConfirmDel(null)} />
            )}

            {editDomain && (
                <Modal title={lang === 'de' ? 'Domain bearbeiten' : 'Edit Domain'} onClose={() => setEditDomain(null)}
                    actions={<><button className="btn btn-secondary" onClick={() => setEditDomain(null)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                        <button className="btn btn-primary" onClick={async () => {
                            await api.put(`domains/${editDomain.id}`, {
                                name_de: editDomain.display_name,
                                description: editDomain.description,
                                icon: editDomain.icon,
                                keywords: editDomain.keywords
                            });
                            setEditDomain(null);
                            await refreshData();
                            showToast(lang === 'de' ? 'Domain aktualisiert' : 'Domain updated', 'success');
                        }}>{lang === 'de' ? 'Speichern' : 'Save'}</button></>}>
                    <div className="input-group" style={{ marginBottom: 12 }}>
                        <label className="input-label">{lang === 'de' ? 'Name' : 'Name'}</label>
                        <input className="input" value={editDomain.display_name || ''} onChange={e => setEditDomain({ ...editDomain, display_name: e.target.value })} />
                    </div>
                    <div className="input-group" style={{ marginBottom: 12 }}>
                        <label className="input-label">{lang === 'de' ? 'Beschreibung' : 'Description'}</label>
                        <input className="input" value={editDomain.description || ''} onChange={e => setEditDomain({ ...editDomain, description: e.target.value })} />
                    </div>
                    <div className="input-group" style={{ marginBottom: 12 }}>
                        <label className="input-label">Icon (mdi:icon-name)</label>
                        <input className="input" value={editDomain.icon || ''} onChange={e => setEditDomain({ ...editDomain, icon: e.target.value })} />
                    </div>
                    <div className="input-group">
                        <label className="input-label">Keywords</label>
                        <input className="input" value={editDomain.keywords || ''} onChange={e => setEditDomain({ ...editDomain, keywords: e.target.value })}
                            placeholder={lang === 'de' ? 'Komma-getrennt' : 'Comma-separated'} />
                    </div>
                </Modal>
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================

// ================================================================
// Devices Page - with manual search, bulk actions, live state, confirm dialog
// ================================================================

const DevicesPage = () => {
    const { devices, rooms, domains, lang, showToast, refreshData } = useApp();
    const [discovering, setDiscovering] = useState(false);
    const [discovered, setDiscovered] = useState(null);
    const [selected, setSelected] = useState({});
    const [editDevice, setEditDevice] = useState(null);
    const [search, setSearch] = useState('');
    const [showManual, setShowManual] = useState(false);
    const [manualEntities, setManualEntities] = useState([]);
    const [manualSearch, setManualSearch] = useState('');
    const [manualLoading, setManualLoading] = useState(false);
    const [bulkSelected, setBulkSelected] = useState({});
    const [showBulkEdit, setShowBulkEdit] = useState(false);
    const [bulkRoom, setBulkRoom] = useState('');
    const [bulkDomain, setBulkDomain] = useState('');
    const [confirmDel, setConfirmDel] = useState(null);
    const [confirmBulkDel, setConfirmBulkDel] = useState(false);

    const handleDiscover = async () => {
        setDiscovering(true);
        const result = await api.get('discover');
        setDiscovered(result);
        setSelected({});
        setDiscovering(false);
    };

    const toggleEntity = (entityId) => {
        setSelected(prev => ({ ...prev, [entityId]: !prev[entityId] }));
    };

    const toggleDiscoverDomain = (domainName) => {
        const entities = discovered?.domains?.[domainName]?.entities || [];
        const allSelected = entities.every(e => selected[e.entity_id]);
        const newSel = { ...selected };
        entities.forEach(e => { newSel[e.entity_id] = !allSelected; });
        setSelected(newSel);
    };

    const handleImport = async () => {
        if (!discovered) return;
        const selectedIds = Object.keys(selected).filter(k => selected[k]);
        if (selectedIds.length === 0) {
            showToast(lang === 'de' ? 'Keine GerÃ¤te ausgewÃ¤hlt' : 'No devices selected', 'error');
            return;
        }
        const result = await api.post('discover/import', {
            domains: discovered.domains,
            selected_entities: selectedIds
        });
        if (result?.success) {
            showToast(lang === 'de' ? `${result.imported} GerÃ¤te importiert` : `${result.imported} devices imported`, 'success');
            setDiscovered(null);
            setSelected({});
            await refreshData();
        }
    };

    // Manual search
    const handleOpenManual = async () => {
        setManualLoading(true);
        setShowManual(true);
        const result = await api.get('discover/all-entities');
        setManualEntities(result?.entities || []);
        setManualLoading(false);
    };

    const handleManualAdd = async (entityId) => {
        const result = await api.post('devices/manual-add', { entity_id: entityId });
        if (result?.success || result?.id) {
            showToast(lang === 'de' ? 'GerÃ¤t hinzugefÃ¼gt' : 'Device added', 'success');
            await refreshData();
            const updated = await api.get('discover/all-entities');
            setManualEntities(updated?.entities || []);
        } else {
            showToast(result?.error || 'Error', 'error');
        }
    };

    // Single delete with confirm
    const handleDeleteDevice = async () => {
        if (!confirmDel) return;
        const result = await api.delete(`devices/${confirmDel.id}`);
        if (result?.success) {
            showToast(lang === 'de' ? 'GerÃ¤t entfernt' : 'Device removed', 'success');
            setConfirmDel(null);
            await refreshData();
        }
    };

    const handleUpdateDevice = async () => {
        if (!editDevice) return;
        const result = await api.put(`devices/${editDevice.id}`, {
            room_id: editDevice.room_id || null,
            domain_id: editDevice.domain_id || null,
            name: editDevice.name,
            is_tracked: editDevice.is_tracked,
            is_controllable: editDevice.is_controllable
        });
        if (result?.id) {
            showToast(lang === 'de' ? 'GerÃ¤t aktualisiert' : 'Device updated', 'success');
            setEditDevice(null);
            await refreshData();
        }
    };

    // Bulk actions
    const bulkCount = Object.values(bulkSelected).filter(Boolean).length;
    const toggleBulk = (id) => setBulkSelected(prev => ({ ...prev, [id]: !prev[id] }));
    const toggleBulkAll = () => {
        const filtered = getFilteredDevices();
        const allChecked = filtered.every(d => bulkSelected[d.id]);
        const newSel = { ...bulkSelected };
        filtered.forEach(d => { newSel[d.id] = !allChecked; });
        setBulkSelected(newSel);
    };

    const handleBulkEdit = async () => {
        const ids = Object.keys(bulkSelected).filter(k => bulkSelected[k]).map(Number);
        const data = {};
        if (bulkRoom) data.room_id = parseInt(bulkRoom);
        if (bulkDomain) data.domain_id = parseInt(bulkDomain);
        const result = await api.put('devices/bulk', { device_ids: ids, ...data });
        if (result?.success) {
            showToast(lang === 'de' ? `${result.updated} aktualisiert` : `${result.updated} updated`, 'success');
            setShowBulkEdit(false);
            setBulkSelected({});
            await refreshData();
        }
    };

    const handleBulkDelete = async () => {
        const ids = Object.keys(bulkSelected).filter(k => bulkSelected[k]).map(Number);
        const result = await api.delete('devices/bulk', { device_ids: ids });
        if (result?.success) {
            showToast(lang === 'de' ? `${result.deleted} gelÃ¶scht` : `${result.deleted} deleted`, 'success');
            setConfirmBulkDel(false);
            setBulkSelected({});
            await refreshData();
        }
    };

    const selectedCount = Object.values(selected).filter(Boolean).length;
    const importedEntityIds = new Set(devices.map(d => d.ha_entity_id));

    const getDomainName = (domainId) => domains.find(d => d.id === domainId)?.display_name || 'â€”';
    const getRoomName = (roomId) => rooms.find(r => r.id === roomId)?.name || 'â€”';

    const getFilteredDevices = () => {
        if (!search) return devices;
        const s = search.toLowerCase();
        return devices.filter(d =>
            d.ha_entity_id?.toLowerCase().includes(s) || d.name?.toLowerCase().includes(s)
            || getDomainName(d.domain_id)?.toLowerCase().includes(s)
            || getRoomName(d.room_id)?.toLowerCase().includes(s)
        );
    };

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 8 }}>
                <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
                    {devices.length} {lang === 'de' ? 'GerÃ¤te konfiguriert' : 'devices configured'}
                </p>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn btn-secondary" onClick={handleOpenManual}>
                        <span className="mdi mdi-magnify-plus-outline" />
                        {lang === 'de' ? 'Manuell' : 'Manual'}
                    </button>
                    <button className="btn btn-primary" onClick={handleDiscover} disabled={discovering}>
                        <span className="mdi mdi-magnify" />
                        {discovering ? (lang === 'de' ? 'Suche...' : 'Searching...') : (lang === 'de' ? 'GerÃ¤te erkennen' : 'Discover')}
                    </button>
                </div>
            </div>

            {/* Bulk Actions Bar */}
            {bulkCount > 0 && (
                <div className="card" style={{ marginBottom: 16, padding: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    borderColor: 'var(--accent-primary)', background: 'var(--accent-primary-dim)' }}>
                    <span style={{ fontWeight: 600, fontSize: 14 }}>
                        {bulkCount} {lang === 'de' ? 'ausgewÃ¤hlt' : 'selected'}
                    </span>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <button className="btn btn-secondary" onClick={() => setBulkSelected({})}>{lang === 'de' ? 'Aufheben' : 'Deselect'}</button>
                        <button className="btn btn-primary" onClick={() => setShowBulkEdit(true)}>
                            <span className="mdi mdi-pencil" /> {lang === 'de' ? 'Bearbeiten' : 'Edit'}
                        </button>
                        <button className="btn btn-danger" onClick={() => setConfirmBulkDel(true)}>
                            <span className="mdi mdi-delete" /> {lang === 'de' ? 'LÃ¶schen' : 'Delete'}
                        </button>
                    </div>
                </div>
            )}

            {/* Discovery Results */}
            {discovered && (
                <div className="card" style={{ marginBottom: 20, borderColor: 'var(--accent-primary)', borderWidth: 2 }}>
                    <div className="card-header">
                        <div>
                            <div className="card-title">{lang === 'de' ? 'VerfÃ¼gbare GerÃ¤te' : 'Available Devices'}</div>
                            <div className="card-subtitle">{selectedCount} {lang === 'de' ? 'ausgewÃ¤hlt' : 'selected'}</div>
                        </div>
                        <div style={{ display: 'flex', gap: 8 }}>
                            <button className="btn btn-secondary" onClick={() => { setDiscovered(null); setSelected({}); }}>
                                {lang === 'de' ? 'Abbrechen' : 'Cancel'}
                            </button>
                            <button className="btn btn-primary" onClick={handleImport} disabled={selectedCount === 0}>
                                <span className="mdi mdi-import" /> {lang === 'de' ? `${selectedCount} importieren` : `Import ${selectedCount}`}
                            </button>
                        </div>
                    </div>
                    <div style={{ maxHeight: 400, overflow: 'auto' }}>
                    {Object.entries(discovered.domains || {}).map(([domainName, data]) => {
                        const entities = (data.entities || []).filter(e => !importedEntityIds.has(e.entity_id));
                        if (entities.length === 0) return null;
                        const allSel = entities.every(e => selected[e.entity_id]);
                        return (
                            <div key={domainName} style={{ marginBottom: 12 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0',
                                    borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                                    onClick={() => toggleDiscoverDomain(domainName)}>
                                    <input type="checkbox" checked={allSel} readOnly style={{ width: 18, height: 18, accentColor: 'var(--accent-primary)' }} />
                                    <strong>{domainName}</strong>
                                    <span className="badge badge-info">{entities.length}</span>
                                </div>
                                <div style={{ paddingLeft: 26 }}>
                                    {entities.map(entity => (
                                        <div key={entity.entity_id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 13, cursor: 'pointer' }}
                                            onClick={() => toggleEntity(entity.entity_id)}>
                                            <input type="checkbox" checked={!!selected[entity.entity_id]} readOnly style={{ width: 16, height: 16, accentColor: 'var(--accent-primary)' }} />
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', minWidth: 200 }}>{entity.entity_id}</span>
                                            <span style={{ flex: 1 }}>{entity.friendly_name}</span>
                                            <span className="badge badge-info" style={{ fontSize: 10 }}>{entity.state}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        );
                    })}
                    </div>
                </div>
            )}

            {/* Device Table */}
            {devices.length > 0 ? (
                <div>
                    <div style={{ marginBottom: 12 }}>
                        <input className="input" placeholder={lang === 'de' ? 'ðŸ” GerÃ¤te suchen...' : 'ðŸ” Search devices...'}
                            value={search} onChange={e => setSearch(e.target.value)} style={{ maxWidth: 400 }} />
                    </div>
                    <div className="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th style={{ width: 40 }}>
                                    <input type="checkbox"
                                        checked={getFilteredDevices().length > 0 && getFilteredDevices().every(d => bulkSelected[d.id])}
                                        onChange={toggleBulkAll} style={{ width: 16, height: 16, accentColor: 'var(--accent-primary)' }} />
                                </th>
                                <th>Entity ID</th>
                                <th>{lang === 'de' ? 'Name' : 'Name'}</th>
                                <th>Domain</th>
                                <th>{lang === 'de' ? 'Raum' : 'Room'}</th>
                                <th>Status</th>
                                <th style={{ width: 90 }}>{lang === 'de' ? 'Aktionen' : 'Actions'}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {getFilteredDevices().map(device => {
                                const st = stateDisplay(device.live_state);
                                const attrs = device.live_attributes || {};
                                const unit = attrs.unit || '';
                                const attrParts = [];
                                if (attrs.brightness_pct != null) attrParts.push(`â˜€ ${attrs.brightness_pct}%`);
                                if (attrs.position_pct != null) attrParts.push(`â†• ${attrs.position_pct}%`);
                                if (attrs.current_temp != null) attrParts.push(`ðŸŒ¡ ${attrs.current_temp}${unit || 'Â°C'}`);
                                if (attrs.target_temp != null) attrParts.push(`â†’ ${attrs.target_temp}${unit || 'Â°C'}`);
                                if (attrs.humidity != null) attrParts.push(`ðŸ’§ ${attrs.humidity}%`);
                                if (attrs.power != null || attrs.current_power_w != null) attrParts.push(`âš¡ ${attrs.power || attrs.current_power_w} W`);
                                if (attrs.voltage != null) attrParts.push(`ðŸ”Œ ${attrs.voltage} V`);
                                // For sensors: show state + unit directly (replaces generic state label)
                                const isSensorValue = (attrParts.length === 0 && device.live_state && device.live_state !== 'on' && device.live_state !== 'off' && device.live_state !== 'unavailable' && device.live_state !== 'unknown');
                                if (isSensorValue) {
                                    attrParts.push(`${device.live_state}${unit ? ' ' + unit : ''}`);
                                }
                                return (
                                <tr key={device.id}>
                                    <td>
                                        <input type="checkbox" checked={!!bulkSelected[device.id]}
                                            onChange={() => toggleBulk(device.id)}
                                            style={{ width: 16, height: 16, accentColor: 'var(--accent-primary)' }} />
                                    </td>
                                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{device.ha_entity_id}</td>
                                    <td>{device.name}</td>
                                    <td>{getDomainName(device.domain_id)}</td>
                                    <td>{getRoomName(device.room_id)}</td>
                                    <td>
                                        {!isSensorValue && (
                                            <span style={{ color: st.color, fontWeight: 600, fontSize: 12 }}>{st.label}</span>
                                        )}
                                        {attrParts.length > 0 && (
                                            <div style={{ fontSize: isSensorValue ? 12 : 11, color: isSensorValue ? 'var(--info)' : 'var(--text-muted)', marginTop: isSensorValue ? 0 : 2, fontWeight: isSensorValue ? 600 : 400 }}>{attrParts.join(' Â· ')}</div>
                                        )}
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: 4 }}>
                                            <button className="btn btn-ghost btn-icon" onClick={() => setEditDevice({...device})}
                                                title={lang === 'de' ? 'Bearbeiten' : 'Edit'}>
                                                <span className="mdi mdi-pencil" style={{ fontSize: 16, color: 'var(--accent-primary)' }} />
                                            </button>
                                            <button className="btn btn-ghost btn-icon"
                                                title={lang === 'de' ? 'Benachrichtigungen stumm' : 'Mute notifications'}
                                                onClick={async () => {
                                                    await api.post('notification-settings/mute-device', { device_id: device.id });
                                                    showToast(lang === 'de' ? 'GerÃ¤t stummgeschaltet' : 'Device muted', 'success');
                                                }}>
                                                <span className="mdi mdi-bell-off-outline" style={{ fontSize: 16, color: 'var(--text-muted)' }} />
                                            </button>
                                            <button className="btn btn-ghost btn-icon" onClick={() => setConfirmDel(device)}
                                                title={lang === 'de' ? 'LÃ¶schen' : 'Delete'}>
                                                <span className="mdi mdi-delete-outline" style={{ fontSize: 16, color: 'var(--danger)' }} />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                                );
                            })}
                        </tbody>
                    </table>
                    </div>
                </div>
            ) : !discovered && (
                <div className="empty-state">
                    <span className="mdi mdi-devices" />
                    <h3>{lang === 'de' ? 'Keine GerÃ¤te' : 'No Devices'}</h3>
                    <p>{lang === 'de' ? 'Klicke auf "GerÃ¤te erkennen" um deine HA-GerÃ¤te zu importieren.' : 'Click "Discover" to import your HA devices.'}</p>
                </div>
            )}

            {/* Manual Search Modal */}
            {showManual && (
                <Modal title={lang === 'de' ? 'Manuelle GerÃ¤tesuche' : 'Manual Device Search'} onClose={() => setShowManual(false)} wide>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <input className="input" value={manualSearch} onChange={e => setManualSearch(e.target.value)}
                            placeholder={lang === 'de' ? 'Entity-ID oder Name suchen...' : 'Search entity ID or name...'} />
                    </div>
                    {manualLoading ? (
                        <div style={{ textAlign: 'center', padding: 24 }}><div className="loading-spinner" style={{ margin: '0 auto' }} /></div>
                    ) : (
                        <div style={{ maxHeight: 400, overflow: 'auto' }}>
                            {manualEntities
                                .filter(e => !manualSearch || e.entity_id?.toLowerCase().includes(manualSearch.toLowerCase()) || e.friendly_name?.toLowerCase().includes(manualSearch.toLowerCase()))
                                .slice(0, 100)
                                .map(entity => {
                                    const isImported = importedEntityIds.has(entity.entity_id);
                                    return (
                                        <div key={entity.entity_id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
                                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', minWidth: 220 }}>{entity.entity_id}</span>
                                            <span style={{ flex: 1 }}>{entity.friendly_name}</span>
                                            <span className="badge badge-info" style={{ fontSize: 10 }}>{entity.state}</span>
                                            {isImported ? (
                                                <span className="badge badge-success" style={{ fontSize: 10 }}>{lang === 'de' ? 'Importiert' : 'Imported'}</span>
                                            ) : (
                                                <button className="btn btn-primary" style={{ padding: '4px 10px', fontSize: 11 }} onClick={() => handleManualAdd(entity.entity_id)}>
                                                    <span className="mdi mdi-plus" style={{ fontSize: 14 }} />
                                                </button>
                                            )}
                                        </div>
                                    );
                                })}
                        </div>
                    )}
                </Modal>
            )}

            {/* Edit Device Modal */}
            {editDevice && (
                <Modal title={lang === 'de' ? 'GerÃ¤t bearbeiten' : 'Edit Device'} onClose={() => setEditDevice(null)}
                    actions={<>
                        <button className="btn btn-secondary" onClick={() => setEditDevice(null)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                        <button className="btn btn-primary" onClick={handleUpdateDevice}>{lang === 'de' ? 'Speichern' : 'Save'}</button>
                    </>}>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: 16 }}>{editDevice.ha_entity_id}</div>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">Name</label>
                        <input className="input" value={editDevice.name} onChange={e => setEditDevice({ ...editDevice, name: e.target.value })} />
                    </div>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <Dropdown
                            label={lang === 'de' ? 'Raum' : 'Room'}
                            value={editDevice.room_id || ''}
                            onChange={v => setEditDevice({ ...editDevice, room_id: v ? parseInt(v) : null })}
                            options={[
                                { value: '', label: lang === 'de' ? 'â€” Kein Raum â€”' : 'â€” No Room â€”' },
                                ...rooms.map(r => ({ value: r.id, label: r.name }))
                            ]}
                        />
                    </div>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <Dropdown
                            label="Domain"
                            value={editDevice.domain_id || ''}
                            onChange={v => setEditDevice({ ...editDevice, domain_id: v ? parseInt(v) : null })}
                            options={[
                                { value: '', label: lang === 'de' ? 'â€” Keine â€”' : 'â€” None â€”' },
                                ...domains.map(d => ({ value: d.id, label: d.display_name }))
                            ]}
                        />
                    </div>
                    <div style={{ display: 'flex', gap: 24 }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 14 }}>
                            <input type="checkbox" checked={editDevice.is_tracked} onChange={e => setEditDevice({ ...editDevice, is_tracked: e.target.checked })}
                                style={{ width: 18, height: 18, accentColor: 'var(--accent-primary)' }} />
                            {lang === 'de' ? 'Ãœberwacht' : 'Tracked'}
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 14 }}>
                            <input type="checkbox" checked={editDevice.is_controllable} onChange={e => setEditDevice({ ...editDevice, is_controllable: e.target.checked })}
                                style={{ width: 18, height: 18, accentColor: 'var(--accent-primary)' }} />
                            {lang === 'de' ? 'Steuerbar' : 'Controllable'}
                        </label>
                    </div>
                </Modal>
            )}

            {/* Bulk Edit Modal */}
            {showBulkEdit && (
                <Modal title={lang === 'de' ? `${bulkCount} GerÃ¤te bearbeiten` : `Edit ${bulkCount} Devices`} onClose={() => setShowBulkEdit(false)}
                    actions={<>
                        <button className="btn btn-secondary" onClick={() => setShowBulkEdit(false)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                        <button className="btn btn-primary" onClick={handleBulkEdit}>{lang === 'de' ? 'Anwenden' : 'Apply'}</button>
                    </>}>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <Dropdown
                            label={lang === 'de' ? 'Raum zuweisen' : 'Assign Room'}
                            value={bulkRoom}
                            onChange={v => setBulkRoom(v)}
                            options={[
                                { value: '', label: lang === 'de' ? 'â€” Nicht Ã¤ndern â€”' : 'â€” No change â€”' },
                                ...rooms.map(r => ({ value: String(r.id), label: r.name }))
                            ]}
                        />
                    </div>
                    <div className="input-group">
                        <Dropdown
                            label={lang === 'de' ? 'Domain zuweisen' : 'Assign Domain'}
                            value={bulkDomain}
                            onChange={v => setBulkDomain(v)}
                            options={[
                                { value: '', label: lang === 'de' ? 'â€” Nicht Ã¤ndern â€”' : 'â€” No change â€”' },
                                ...domains.map(d => ({ value: String(d.id), label: d.display_name }))
                            ]}
                        />
                    </div>
                </Modal>
            )}

            {/* Confirm Delete */}
            {confirmDel && (
                <ConfirmDialog title={lang === 'de' ? 'GerÃ¤t entfernen' : 'Remove Device'}
                    message={lang === 'de' ? `"${confirmDel.name}" wirklich entfernen?` : `Remove "${confirmDel.name}"?`}
                    danger onConfirm={handleDeleteDevice} onCancel={() => setConfirmDel(null)} />
            )}
            {confirmBulkDel && (
                <ConfirmDialog title={lang === 'de' ? `${bulkCount} GerÃ¤te lÃ¶schen` : `Delete ${bulkCount} Devices`}
                    message={lang === 'de' ? 'Dies kann nicht rÃ¼ckgÃ¤ngig gemacht werden.' : 'This cannot be undone.'}
                    danger onConfirm={handleBulkDelete} onCancel={() => setConfirmBulkDel(false)} />
            )}

            {/* Device Groups Section (#44) */}
            <DeviceGroupsSection />
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

const DeviceGroupsSection = () => {
    const { lang, showToast, devices } = useApp();
    const [groups, setGroups] = useState([]);
    const [suggestions, setSuggestions] = useState([]);
    const [showCreate, setShowCreate] = useState(false);
    const [newGroup, setNewGroup] = useState({ name: '', device_ids: [] });

    const load = async () => {
        const data = await api.get('device-groups');
        if (data) { setGroups(data.groups || []); setSuggestions(data.suggestions || []); }
    };
    useEffect(() => { load(); }, []);

    const createGroup = async (name, deviceIds, roomId) => {
        await api.post('device-groups', { name, device_ids: deviceIds, room_id: roomId });
        showToast(lang === 'de' ? 'Gruppe erstellt' : 'Group created', 'success');
        setShowCreate(false); setNewGroup({ name: '', device_ids: [] }); await load();
    };

    const deleteGroup = async (id) => {
        await api.delete(`device-groups/${id}`);
        showToast(lang === 'de' ? 'Gruppe gelÃ¶scht' : 'Group deleted', 'success'); await load();
    };

    const executeGroup = async (id, service) => {
        const result = await api.post(`device-groups/${id}/execute`, { service });
        showToast(result?.success ? (lang === 'de' ? 'Aktion ausgefÃ¼hrt' : 'Action executed') : 'Error', result?.success ? 'success' : 'error');
    };

    return (
        <div style={{ marginTop: 32 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <h3 style={{ fontSize: 16, fontWeight: 600 }}>
                    <span className="mdi mdi-group" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                    {lang === 'de' ? 'GerÃ¤tegruppen' : 'Device Groups'}
                </h3>
                <button className="btn btn-secondary" onClick={() => setShowCreate(true)} style={{ fontSize: 12 }}>
                    <span className="mdi mdi-plus" /> {lang === 'de' ? 'Neue Gruppe' : 'New Group'}
                </button>
            </div>

            {groups.map(g => (
                <div key={g.id} className="card" style={{ marginBottom: 8, padding: '12px 16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                            <strong>{g.name}</strong>
                            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>
                                {g.device_ids?.length || 0} {lang === 'de' ? 'GerÃ¤te' : 'devices'}
                                {g.room_name && ` Â· ${g.room_name}`}
                            </span>
                        </div>
                        <div style={{ display: 'flex', gap: 4 }}>
                            <button className="btn btn-sm btn-ghost" onClick={() => executeGroup(g.id, 'turn_on')} title="On">
                                <span className="mdi mdi-power" style={{ color: 'var(--success)' }} />
                            </button>
                            <button className="btn btn-sm btn-ghost" onClick={() => executeGroup(g.id, 'turn_off')} title="Off">
                                <span className="mdi mdi-power-off" style={{ color: 'var(--danger)' }} />
                            </button>
                            <button className="btn btn-sm btn-ghost" onClick={() => deleteGroup(g.id)}>
                                <span className="mdi mdi-delete" style={{ color: 'var(--danger)' }} />
                            </button>
                        </div>
                    </div>
                </div>
            ))}

            {suggestions.length > 0 && (
                <div style={{ marginTop: 16 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                        {lang === 'de' ? 'Vorgeschlagene Gruppen' : 'Suggested Groups'}
                    </div>
                    {suggestions.map((s, i) => (
                        <div key={i} className="card" style={{ marginBottom: 6, padding: '10px 16px', borderStyle: 'dashed' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div>
                                    <span style={{ fontSize: 13 }}>{s.suggested_name}</span>
                                    <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>
                                        {s.devices.length} {lang === 'de' ? 'GerÃ¤te' : 'devices'}
                                    </span>
                                </div>
                                <button className="btn btn-sm btn-ghost" onClick={() => createGroup(s.suggested_name, s.devices.map(d => d.id), s.room_id)}>
                                    <span className="mdi mdi-plus-circle" style={{ color: 'var(--success)' }} /> {lang === 'de' ? 'Ãœbernehmen' : 'Accept'}
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {showCreate && (
                <Modal title={lang === 'de' ? 'Neue GerÃ¤tegruppe' : 'New Device Group'} onClose={() => setShowCreate(false)}
                    actions={<><button className="btn btn-secondary" onClick={() => setShowCreate(false)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                        <button className="btn btn-primary" onClick={() => createGroup(newGroup.name, newGroup.device_ids)}
                            disabled={!newGroup.name || newGroup.device_ids.length < 2}>{lang === 'de' ? 'Erstellen' : 'Create'}</button></>}>
                    <div className="input-group" style={{ marginBottom: 12 }}>
                        <label className="input-label">{lang === 'de' ? 'Name' : 'Name'}</label>
                        <input className="input" value={newGroup.name} onChange={e => setNewGroup({ ...newGroup, name: e.target.value })} autoFocus />
                    </div>
                    <div className="input-group">
                        <label className="input-label">{lang === 'de' ? 'GerÃ¤te auswÃ¤hlen' : 'Select Devices'}</label>
                        <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8, padding: 8 }}>
                            {devices.filter(d => d.ha_entity_id).map(d => (
                                <label key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', cursor: 'pointer', fontSize: 13 }}>
                                    <input type="checkbox" checked={newGroup.device_ids.includes(d.id)}
                                        onChange={() => setNewGroup(prev => ({
                                            ...prev, device_ids: prev.device_ids.includes(d.id)
                                                ? prev.device_ids.filter(id => id !== d.id)
                                                : [...prev.device_ids, d.id]
                                        }))} />
                                    {d.name} <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>({d.ha_entity_id})</span>
                                </label>
                            ))}
                        </div>
                    </div>
                </Modal>
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)


// ================================================================
// Rooms Page - with edit name
// ================================================================

const RoomsPage = () => {
    const { rooms, domains, lang, showToast, refreshData } = useApp();
    const [showAdd, setShowAdd] = useState(false);
    const [newRoom, setNewRoom] = useState({ name: '', icon: 'mdi:door' });
    const [editRoom, setEditRoom] = useState(null);
    const [confirm, setConfirm] = useState(null);
    const [importing, setImporting] = useState(false);

    const phaseLabels = {
        observing: { de: 'Beobachten', en: 'Observing', color: 'info' },
        suggesting: { de: 'Vorschlagen', en: 'Suggesting', color: 'warning' },
        autonomous: { de: 'Autonom', en: 'Autonomous', color: 'success' }
    };

    const handleAdd = async () => {
        if (!newRoom.name.trim()) return;
        const result = await api.post('rooms', newRoom);
        if (result?.id) {
            showToast(lang === 'de' ? 'Raum erstellt' : 'Room created', 'success');
            setShowAdd(false);
            setNewRoom({ name: '', icon: 'mdi:door' });
            await refreshData();
        }
    };

    const handleUpdate = async () => {
        if (!editRoom || !editRoom.name.trim()) return;
        const result = await api.put(`rooms/${editRoom.id}`, { name: editRoom.name, icon: editRoom.icon });
        if (result?.id) {
            showToast(lang === 'de' ? 'Raum aktualisiert' : 'Room updated', 'success');
            setEditRoom(null);
            await refreshData();
        }
    };

    const handleDelete = async (room) => {
        setConfirm({ id: room.id, name: room.name, count: room.device_count });
    };

    const confirmDelete = async () => {
        const result = await api.delete(`rooms/${confirm.id}`);
        if (result?.success) { showToast(lang === 'de' ? 'Raum gelÃ¶scht' : 'Room deleted', 'success'); await refreshData(); }
        setConfirm(null);
    };

    // Fix 9: Import rooms from HA
    const handleImportFromHA = async () => {
        setImporting(true);
        const result = await api.post('rooms/import-from-ha');
        if (result?.success) {
            showToast(lang === 'de' ? `${result.imported} importiert, ${result.skipped} Ã¼bersprungen` : `${result.imported} imported, ${result.skipped} skipped`,
                result.imported > 0 ? 'success' : 'info');
            await refreshData();
        } else { showToast(result?.error || 'Import failed', 'error'); }
        setImporting(false);
    };

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20, flexWrap: 'wrap', gap: 8 }}>
                <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
                    {rooms.length} {lang === 'de' ? 'RÃ¤ume' : 'Rooms'}
                </p>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn btn-secondary" onClick={handleImportFromHA} disabled={importing}>
                        <span className="mdi mdi-home-import-outline" />
                        {importing ? '...' : (lang === 'de' ? 'Aus HA importieren' : 'Import from HA')}
                    </button>
                    <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
                        <span className="mdi mdi-plus" />
                        {lang === 'de' ? 'Raum hinzufÃ¼gen' : 'Add Room'}
                    </button>
                </div>
            </div>

            {rooms.length > 0 ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
                    {rooms.map(room => (
                        <div key={room.id} className="card">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                    <div className="card-icon" style={{ background: 'var(--accent-primary-dim)', color: 'var(--accent-primary)' }}>
                                        <span className={`mdi ${room.icon?.replace('mdi:', 'mdi-') || 'mdi-door'}`} />
                                    </div>
                                    <div>
                                        <div className="card-title">{room.name}</div>
                                        <div className="card-subtitle">
                                            {room.device_count} {lang === 'de' ? 'GerÃ¤te' : 'devices'}
                                            {room.last_activity && (
                                                <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                                                    Â· <span className="mdi mdi-clock-outline" style={{ fontSize: 11, marginRight: 2 }} />
                                                    {relativeTime(room.last_activity, lang)}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                                <div style={{ display: 'flex', gap: 4 }}>
                                    <button className="btn btn-ghost btn-icon" onClick={() => setEditRoom({...room})}
                                        title={lang === 'de' ? 'Bearbeiten' : 'Edit'}>
                                        <span className="mdi mdi-pencil" style={{ fontSize: 16, color: 'var(--accent-primary)' }} />
                                    </button>
                                    <button className="btn btn-ghost btn-icon" onClick={() => handleDelete(room)}>
                                        <span className="mdi mdi-delete-outline" style={{ fontSize: 16, color: 'var(--text-muted)' }} />
                                    </button>
                                </div>
                            </div>

                            {room.domain_states?.length > 0 && (
                                <div style={{ marginTop: 16 }}>
                                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                                        {lang === 'de' ? 'Lernphasen' : 'Learning Phases'}
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                        {room.domain_states.map((ds, i) => {
                                            const phase = phaseLabels[ds.learning_phase] || phaseLabels.observing;
                                            const dom = domains.find(d => d.id === ds.domain_id);
                                            const domName = dom?.display_name || '?';
                                            const domIcon = dom?.icon?.replace('mdi:', 'mdi-') || 'mdi-puzzle';
                                            const nextPhase = ds.learning_phase === 'observing' ? 'suggesting' : ds.learning_phase === 'suggesting' ? 'autonomous' : 'observing';
                                            const nextLabel = phaseLabels[nextPhase]?.[lang] || nextPhase;
                                            const progress = ds.learning_phase === 'autonomous' ? 100 : ds.learning_phase === 'suggesting' ? 66 : ds.confidence_score ? Math.min(33, Math.round(ds.confidence_score * 33)) : 10;
                                            return (
                                                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                    <span className={`mdi ${domIcon}`} style={{ fontSize: 14, color: 'var(--text-muted)', width: 18 }} />
                                                    <div style={{ flex: 1, minWidth: 0 }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 2 }}>
                                                            <span>{domName}</span>
                                                            <span className={`badge badge-${phase.color}`} style={{ fontSize: 9, padding: '1px 6px', cursor: 'pointer' }}
                                                                title={`â†’ ${nextLabel}`}
                                                                onClick={async () => {
                                                                    await api.put(`phases/${room.id}/${ds.domain_id}`, { phase: nextPhase });
                                                                    showToast(`${domName}: ${nextLabel}`, 'success');
                                                                    await refreshData();
                                                                }}>
                                                                {phase[lang]}
                                                            </span>
                                                        </div>
                                                        <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-main)', overflow: 'hidden' }}>
                                                            <div style={{ height: '100%', borderRadius: 2, width: `${progress}%`,
                                                                background: ds.learning_phase === 'autonomous' ? 'var(--success)' : ds.learning_phase === 'suggesting' ? 'var(--warning)' : 'var(--accent-primary)',
                                                                transition: 'width 0.3s' }} />
                                                        </div>
                                                    </div>
                                                    {isAdmin && (
                                                        <button className="btn btn-ghost" style={{ padding: 2, fontSize: 12 }}
                                                            title={lang === 'de' ? 'Lernphase zurÃ¼cksetzen' : 'Reset learning phase'}
                                                            onClick={async (e) => {
                                                                e.stopPropagation();
                                                                if (confirm(lang === 'de' ? `${domName} zurÃ¼cksetzen? Alle Muster werden gelÃ¶scht.` : `Reset ${domName}? All patterns will be deleted.`)) {
                                                                    await api.post(`phases/${room.id}/${ds.domain_id}/reset`);
                                                                    showToast(lang === 'de' ? 'ZurÃ¼ckgesetzt' : 'Reset', 'success');
                                                                    await refreshData();
                                                                }
                                                            }}>
                                                            <span className="mdi mdi-restart" style={{ color: 'var(--text-muted)' }} />
                                                        </button>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {/* Privacy Mode */}
                            <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        <span className="mdi mdi-shield-lock" style={{ fontSize: 14, color: room.privacy_mode?.enabled ? 'var(--warning)' : 'var(--text-muted)' }} />
                                        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                            {lang === 'de' ? 'PrivatsphÃ¤re-Modus' : 'Privacy Mode'}
                                        </span>
                                    </div>
                                    <label className="toggle" style={{ transform: 'scale(0.8)' }}>
                                        <input type="checkbox" checked={!!room.privacy_mode?.enabled}
                                            onChange={async () => {
                                                const newMode = { ...room.privacy_mode, enabled: !room.privacy_mode?.enabled };
                                                await api.put(`rooms/${room.id}`, { privacy_mode: newMode });
                                                await refreshData();
                                            }} />
                                        <div className="toggle-slider" />
                                    </label>
                                </div>
                                {room.privacy_mode?.enabled && (
                                    <div style={{ marginTop: 6, padding: '6px 8px', background: 'var(--bg-main)', borderRadius: 6, fontSize: 11, color: 'var(--warning)' }}>
                                        <span className="mdi mdi-information" style={{ marginRight: 4 }} />
                                        {lang === 'de'
                                            ? 'Keine Datenerfassung, keine Muster, keine Automationen in diesem Raum.'
                                            : 'No data collection, no patterns, no automations in this room.'}
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="empty-state">
                    <span className="mdi mdi-door-open" />
                    <h3>{lang === 'de' ? 'Keine RÃ¤ume' : 'No Rooms'}</h3>
                    <p>{lang === 'de'
                        ? 'FÃ¼ge RÃ¤ume hinzu um MindHome zu konfigurieren.'
                        : 'Add rooms to configure MindHome.'}</p>
                </div>
            )}

            {/* Add Room Modal */}
            {showAdd && (
                <Modal
                    title={lang === 'de' ? 'Raum hinzufÃ¼gen' : 'Add Room'}
                    onClose={() => setShowAdd(false)}
                    actions={
                        <>
                            <button className="btn btn-secondary" onClick={() => setShowAdd(false)}>
                                {lang === 'de' ? 'Abbrechen' : 'Cancel'}
                            </button>
                            <button className="btn btn-primary" onClick={handleAdd}>
                                {lang === 'de' ? 'Erstellen' : 'Create'}
                            </button>
                        </>
                    }
                >
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">{lang === 'de' ? 'Name' : 'Name'}</label>
                        <input className="input" value={newRoom.name}
                               onChange={e => setNewRoom({ ...newRoom, name: e.target.value })}
                               placeholder={lang === 'de' ? 'z.B. Wohnzimmer' : 'e.g. Living Room'}
                               autoFocus />
                    </div>
                </Modal>
            )}

            {/* Edit Room Modal */}
            {editRoom && (
                <Modal
                    title={lang === 'de' ? 'Raum bearbeiten' : 'Edit Room'}
                    onClose={() => setEditRoom(null)}
                    actions={
                        <>
                            <button className="btn btn-secondary" onClick={() => setEditRoom(null)}>
                                {lang === 'de' ? 'Abbrechen' : 'Cancel'}
                            </button>
                            <button className="btn btn-primary" onClick={handleUpdate}>
                                {lang === 'de' ? 'Speichern' : 'Save'}
                            </button>
                        </>
                    }
                >
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">{lang === 'de' ? 'Name' : 'Name'}</label>
                        <input className="input" value={editRoom.name}
                               onChange={e => setEditRoom({ ...editRoom, name: e.target.value })}
                               autoFocus />
                    </div>
                    <div className="input-group">
                        <label className="input-label">Icon</label>
                        <input className="input" value={editRoom.icon || ''}
                               onChange={e => setEditRoom({ ...editRoom, icon: e.target.value })}
                               placeholder="mdi:door" />
                    </div>
                </Modal>
            )}
            {confirm && (
                <ConfirmDialog
                    title={lang === 'de' ? 'Raum lÃ¶schen?' : 'Delete room?'}
                    message={lang === 'de'
                        ? `"${confirm.name}" mit ${confirm.count} GerÃ¤ten wird gelÃ¶scht.`
                        : `"${confirm.name}" with ${confirm.count} devices will be deleted.`}
                    danger onConfirm={confirmDelete} onCancel={() => setConfirm(null)} />
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Users Page - with HA person assignment
// ================================================================

const UsersPage = () => {
    const { users, lang, showToast, refreshData } = useApp();
    const [showAdd, setShowAdd] = useState(false);
    const [newUser, setNewUser] = useState({ name: '', role: 'user', ha_person_entity: '' });
    const [haPersons, setHaPersons] = useState([]);
    const [editingUser, setEditingUser] = useState(null);

    useEffect(() => {
        api.get('ha/persons').then(r => setHaPersons(r?.persons || []));
    }, []);

    const handleAdd = async () => {
        if (!newUser.name.trim()) return;
        const result = await api.post('users', newUser);
        if (result?.id) {
            showToast(lang === 'de' ? 'Person erstellt' : 'Person created', 'success');
            setShowAdd(false);
            setNewUser({ name: '', role: 'user', ha_person_entity: '' });
            await refreshData();
        }
    };

    const handleDelete = async (id) => {
        const result = await api.delete(`users/${id}`);
        if (result?.success) {
            showToast(lang === 'de' ? 'Person entfernt' : 'Person removed', 'success');
            await refreshData();
        }
    };

    const handleAssignPerson = async (userId, haEntity) => {
        const result = await api.put(`users/${userId}`, { ha_person_entity: haEntity || null });
        if (result?.id) {
            showToast(lang === 'de' ? 'HA-Person zugewiesen' : 'HA person assigned', 'success');
            await refreshData();
            setEditingUser(null);
        }
    };

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
                <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
                    {users.length} {lang === 'de' ? 'Personen' : 'People'}
                </p>
                <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
                    <span className="mdi mdi-account-plus" />
                    {lang === 'de' ? 'Person hinzufÃ¼gen' : 'Add Person'}
                </button>
            </div>

            {users.length > 0 ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
                    {users.map(user => (
                        <div key={user.id} className="card">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                    <div className="card-icon" style={{
                                        background: user.role === 'admin' ? 'var(--accent-primary-dim)' : 'var(--accent-secondary-dim)',
                                        color: user.role === 'admin' ? 'var(--accent-primary)' : 'var(--accent-secondary)'
                                    }}>
                                        <span className={`mdi ${user.role === 'admin' ? 'mdi-shield-crown' : 'mdi-account'}`} />
                                    </div>
                                    <div>
                                        <div className="card-title">{user.name}</div>
                                        <div className="card-subtitle">
                                            {user.role === 'admin' ? 'Administrator' : (lang === 'de' ? 'Benutzer' : 'User')}
                                        </div>
                                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                                            {user.ha_person_entity
                                                ? `ðŸ”— ${user.ha_person_entity}`
                                                : (lang === 'de' ? 'âš ï¸ Keine HA-Person' : 'âš ï¸ No HA person')}
                                        </div>
                                    </div>
                                </div>
                                <div style={{ display: 'flex', gap: 4 }}>
                                    <button className="btn btn-ghost btn-icon" onClick={() => setEditingUser(user)}
                                        title={lang === 'de' ? 'HA-Person zuweisen' : 'Assign HA person'}>
                                        <span className="mdi mdi-link-variant" style={{ fontSize: 18, color: 'var(--accent-primary)' }} />
                                    </button>
                                    <button className="btn btn-ghost btn-icon" onClick={() => handleDelete(user.id)}>
                                        <span className="mdi mdi-delete-outline" style={{ fontSize: 18, color: 'var(--text-muted)' }} />
                                    </button>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="empty-state">
                    <span className="mdi mdi-account-group" />
                    <h3>{lang === 'de' ? 'Keine Personen' : 'No People'}</h3>
                    <p>{lang === 'de' ? 'FÃ¼ge Personen hinzu die MindHome nutzen.' : 'Add people who use MindHome.'}</p>
                </div>
            )}

            {showAdd && (
                <Modal title={lang === 'de' ? 'Person hinzufÃ¼gen' : 'Add Person'} onClose={() => setShowAdd(false)}
                    actions={<><button className="btn btn-secondary" onClick={() => setShowAdd(false)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                        <button className="btn btn-primary" onClick={handleAdd}>{lang === 'de' ? 'Erstellen' : 'Create'}</button></>}>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">{lang === 'de' ? 'Name' : 'Name'}</label>
                        <input className="input" value={newUser.name} onChange={e => setNewUser({ ...newUser, name: e.target.value })} autoFocus />
                    </div>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <Dropdown
                            label={lang === 'de' ? 'Rolle' : 'Role'}
                            value={newUser.role}
                            onChange={v => setNewUser({ ...newUser, role: v })}
                            options={[
                                { value: 'user', label: lang === 'de' ? 'Benutzer' : 'User' },
                                { value: 'admin', label: 'Administrator' },
                            ]}
                        />
                    </div>
                    <div className="input-group">
                        <Dropdown
                            label={lang === 'de' ? 'HA-Person' : 'HA Person'}
                            value={newUser.ha_person_entity}
                            onChange={v => setNewUser({ ...newUser, ha_person_entity: v })}
                            options={[
                                { value: '', label: lang === 'de' ? 'â€” Keine â€”' : 'â€” None â€”' },
                                ...haPersons.map(p => ({ value: p.entity_id, label: `${p.name} (${p.entity_id})` }))
                            ]}
                        />
                    </div>
                </Modal>
            )}

            {editingUser && (
                <Modal title={lang === 'de' ? `HA-Person: ${editingUser.name}` : `HA Person: ${editingUser.name}`} onClose={() => setEditingUser(null)}
                    actions={<button className="btn btn-secondary" onClick={() => setEditingUser(null)}>{lang === 'de' ? 'SchlieÃŸen' : 'Close'}</button>}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <div style={{ padding: '10px 14px', borderRadius: 8, cursor: 'pointer',
                            border: !editingUser.ha_person_entity ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
                            background: !editingUser.ha_person_entity ? 'var(--accent-primary-dim)' : 'transparent'
                        }} onClick={() => handleAssignPerson(editingUser.id, '')}>
                            {lang === 'de' ? 'â€” Keine Person â€”' : 'â€” No Person â€”'}
                        </div>
                        {haPersons.map(p => (
                            <div key={p.entity_id} style={{ padding: '10px 14px', borderRadius: 8, cursor: 'pointer',
                                border: editingUser.ha_person_entity === p.entity_id ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
                                background: editingUser.ha_person_entity === p.entity_id ? 'var(--accent-primary-dim)' : 'transparent',
                                display: 'flex', justifyContent: 'space-between', alignItems: 'center'
                            }} onClick={() => handleAssignPerson(editingUser.id, p.entity_id)}>
                                <div><strong>{p.name}</strong><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{p.entity_id}</div></div>
                                <span className={`badge badge-${p.state === 'home' ? 'success' : 'warning'}`}>
                                    <span className="badge-dot" />{p.state === 'home' ? (lang === 'de' ? 'Zuhause' : 'Home') : (lang === 'de' ? 'Weg' : 'Away')}
                                </span>
                            </div>
                        ))}
                    </div>
                </Modal>
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)
// ================================================================
// Settings Page
// ================================================================

const SettingsPage = () => {
    const { lang, setLang, theme, setTheme, viewMode, setViewMode, showToast, refreshData } = useApp();
    const [sysInfo, setSysInfo] = useState(null);
    const [retention, setRetention] = useState(90);
    const [retentionInput, setRetentionInput] = useState('90');
    const [cleaning, setCleaning] = useState(false);
    const [anomalySensitivity, setAnomalySensitivity] = useState('medium');
    const fileInputRef = useRef(null);

    useEffect(() => {
        (async () => {
            const info = await api.get('system/info');
            if (info) setSysInfo(info);
            const ret = await api.get('system/retention');
            if (ret) {
                setRetention(ret.retention_days || 90);
                setRetentionInput(String(ret.retention_days || 90));
            }
            const anomSettings = await api.get('anomaly-settings');
            if (anomSettings?.length > 0) {
                const global = anomSettings.find(s => !s.room_id && !s.domain_id && !s.device_id);
                if (global) setAnomalySensitivity(global.sensitivity || 'medium');
            }
        })();
    }, []);

    const saveRetention = async () => {
        const days = parseInt(retentionInput);
        if (isNaN(days) || days < 1) return;
        const result = await api.put('system/retention', { days });
        if (result?.success) {
            setRetention(days);
            showToast(lang === 'de' ? `Aufbewahrung auf ${days} Tage gesetzt` : `Retention set to ${days} days`, 'success');
        }
    };

    const handleCleanup = async () => {
        setCleaning(true);
        const result = await api.post('system/cleanup');
        if (result?.success) {
            showToast(lang === 'de' ? `${result.deleted || 0} EintrÃ¤ge gelÃ¶scht` : `${result.deleted || 0} entries deleted`, 'success');
            const info = await api.get('system/info');
            if (info) setSysInfo(info);
        }
        setCleaning(false);
    };

    const [exportHistory, setExportHistory] = useState(false);

    const handleExport = async (mode = 'standard') => {
        showToast(lang === 'de' ? 'Backup wird erstellt...' : 'Creating backup...', 'info');
        const histParam = mode === 'full' ? `&include_history=${exportHistory}` : '';
        const backup = await api.get(`backup/export?mode=${mode}${histParam}`);
        if (backup) {
            const blob = new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `mindhome-${mode}-backup-${new Date().toISOString().slice(0,10)}.json`;
            a.click();
            URL.revokeObjectURL(url);
            const s = backup._summary || {};
            showToast(lang === 'de'
                ? `Backup: ${s.rooms || 0} Räume, ${s.devices || 0} Geräte, ${s.patterns || 0} Muster`
                : `Backup: ${s.rooms || 0} rooms, ${s.devices || 0} devices, ${s.patterns || 0} patterns`, 'success');
        }
    };

    const [importPreview, setImportPreview] = useState(null);

    const handleImport = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        try {
            const text = await file.text();
            const data = JSON.parse(text);

            // Strip heavy history tables from large backups to prevent memory issues
            const historyKeys = ['state_history', 'notification_log', 'audit_trail',
                'pattern_match_log', 'data_collection', 'offline_queue'];
            const strippedCount = {};
            for (const key of historyKeys) {
                if (data[key] && Array.isArray(data[key]) && data[key].length > 0) {
                    strippedCount[key] = data[key].length;
                    data[key] = [];
                }
            }
            // Limit action_log to 500 most recent
            if (data.action_log && data.action_log.length > 500) {
                strippedCount['action_log'] = data.action_log.length;
                data.action_log = data.action_log.slice(0, 500);
            }

            // Show preview first
            if (data._summary) {
                setImportPreview({ data, summary: data._summary, filename: file.name, strippedCount });
            } else {
                // Build summary from data
                const summary = {
                    rooms: (data.rooms || []).length,
                    devices: (data.devices || []).length,
                    users: (data.users || []).length,
                    patterns: (data.patterns || []).length,
                    settings: (data.settings || []).length,
                    action_log: (data.action_log || []).length,
                };
                setImportPreview({ data, summary, filename: file.name, strippedCount });
            }
        } catch (err) {
            showToast(lang === 'de' ? 'Ungültige Datei' : 'Invalid file', 'error');
        }
        e.target.value = '';
    };

    const confirmImport = async () => {
        if (!importPreview) return;
        try {
            const result = await api.post('backup/import', importPreview.data);
            if (result?.success) {
                showToast(lang === 'de'
                    ? `Backup geladen: ${result.imported.rooms} RÃ¤ume, ${result.imported.devices} GerÃ¤te`
                    : `Backup loaded: ${result.imported.rooms} rooms, ${result.imported.devices} devices`, 'success');
                await refreshData();
            } else {
                showToast(result?.error || 'Import failed', 'error');
            }
        } catch (err) {
            showToast('Import error', 'error');
        }
        setImportPreview(null);
    };

    const InfoRow = ({ label, value }) => (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14 }}>
            <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{value}</span>
        </div>
    );

    return (
        <>
            {/* Import Preview Modal - outside grid to not affect layout */}
            {importPreview && (
                <Modal title={lang === 'de' ? 'Backup-Vorschau' : 'Backup Preview'} onClose={() => setImportPreview(null)} actions={<>
                    <button className="btn btn-secondary" onClick={() => setImportPreview(null)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                    <button className="btn btn-primary" onClick={confirmImport}>{lang === 'de' ? 'Importieren' : 'Import'}</button>
                </>}>
                    <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>{importPreview.filename}</p>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
                        {Object.entries(importPreview.summary).map(([key, val]) => (
                            <div key={key} style={{ padding: '8px 10px', background: 'var(--bg-main)', borderRadius: 8 }}>
                                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent-primary)' }}>{val}</div>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{key.replace(/_/g, ' ')}</div>
                            </div>
                        ))}
                    </div>
                    {importPreview.data.export_mode && (
                        <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
                            Modus: {importPreview.data.export_mode} Â· {importPreview.data.exported_at?.slice(0, 10)}
                        </p>
                    )}
                </Modal>
            )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, alignItems: 'start' }}>
            {/* LEFT COLUMN */}
            <div>
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>
                    {lang === 'de' ? 'Darstellung' : 'Appearance'}
                </div>

                <div className="input-group" style={{ marginBottom: 16 }}>
                    <Dropdown
                        label={lang === 'de' ? 'Sprache' : 'Language'}
                        value={lang}
                        onChange={v => setLang(v)}
                        options={[
                            { value: 'de', label: 'ðŸ‡©ðŸ‡ª Deutsch' },
                            { value: 'en', label: 'ðŸ‡¬ðŸ‡§ English' },
                        ]}
                    />
                </div>

                <div className="input-group" style={{ marginBottom: 16 }}>
                    <Dropdown
                        label="Theme"
                        value={theme}
                        onChange={v => setTheme(v)}
                        options={[
                            { value: 'dark', label: lang === 'de' ? 'ðŸŒ™ Dunkel' : 'ðŸŒ™ Dark' },
                            { value: 'light', label: lang === 'de' ? 'â˜€ï¸ Hell' : 'â˜€ï¸ Light' },
                        ]}
                    />
                </div>

                <div className="input-group">
                    <Dropdown
                        label={lang === 'de' ? 'Ansicht' : 'View Mode'}
                        value={viewMode}
                        onChange={v => setViewMode(v)}
                        options={[
                            { value: 'simple', label: lang === 'de' ? 'ðŸ“‹ Einfach' : 'ðŸ“‹ Simple' },
                            { value: 'advanced', label: lang === 'de' ? 'ðŸ“Š AusfÃ¼hrlich' : 'ðŸ“Š Advanced' },
                        ]}
                    />
                </div>
            </div>

            {/* Privacy & Storage */}
            <div className="card" style={{ marginBottom: 16, borderColor: 'var(--success)', borderWidth: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                    <span className="mdi mdi-shield-check" style={{ fontSize: 24, color: 'var(--success)' }} />
                    <div className="card-title" style={{ marginBottom: 0 }}>
                        {lang === 'de' ? 'Datenschutz & Speicher' : 'Privacy & Storage'}
                    </div>
                </div>
                <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
                    {lang === 'de'
                        ? '100% lokal â€“ alle Daten bleiben auf deinem GerÃ¤t. Keine Cloud, keine Tracking.'
                        : '100% local â€“ all data stays on your device. No cloud, no tracking.'}
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <InfoRow label={lang === 'de' ? 'DatenbankgrÃ¶ÃŸe' : 'Database Size'}
                        value={sysInfo?.db_size_bytes ? formatBytes(sysInfo.db_size_bytes) : 'â€”'} />
                    <InfoRow label={lang === 'de' ? 'Gesammelte Events' : 'Collected Events'}
                        value={sysInfo?.state_history_count?.toLocaleString() || '0'} />
                    <InfoRow label={lang === 'de' ? 'Aufbewahrung' : 'Retention'}
                        value={`${retention} ${lang === 'de' ? 'Tage' : 'days'}`} />
                </div>
            </div>

            {/* System Info */}
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>
                    {lang === 'de' ? 'System' : 'System'}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <InfoRow label="Version" value={sysInfo?.version || '0.5.0'} />
                    <InfoRow label="Phase" value={`2 â€“ ${lang === 'de' ? 'VollstÃ¤ndig' : 'Complete'}`} />
                    <InfoRow label="Home Assistant"
                        value={sysInfo?.ha_connected ? (lang === 'de' ? 'âœ… Verbunden' : 'âœ… Connected') : (lang === 'de' ? 'âŒ Getrennt' : 'âŒ Disconnected')} />
                    <InfoRow label={lang === 'de' ? 'Zeitzone' : 'Timezone'}
                        value={sysInfo?.timezone || 'â€”'} />
                    <InfoRow label={lang === 'de' ? 'HA Entities' : 'HA Entities'}
                        value={sysInfo?.ha_entity_count || 'â€”'} />
                    <InfoRow label={lang === 'de' ? 'DatenbankgrÃ¶ÃŸe' : 'Database Size'}
                        value={sysInfo?.db_size_bytes ? formatBytes(sysInfo.db_size_bytes) : 'â€”'} />
                    <InfoRow label="Uptime"
                        value={sysInfo?.uptime_seconds ? `${Math.floor(sysInfo.uptime_seconds / 3600)} h` : 'â€”'} />
                    <InfoRow label={lang === 'de' ? 'Gesammelte Events' : 'Collected Events'}
                        value={sysInfo?.state_history_count?.toLocaleString() || '0'} />
                    <InfoRow label={lang === 'de' ? 'Erkannte Muster' : 'Detected Patterns'}
                        value={sysInfo?.pattern_count || '0'} />
                </div>
            </div>

            {/* System Status (#40 Watchdog + #10 Self-Test + #64 Diagnose + #62 Update) */}
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>
                    <span className="mdi mdi-monitor-dashboard" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                    {lang === 'de' ? 'Systemstatus' : 'System Status'}
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <button className="btn btn-sm btn-secondary" onClick={async () => {
                        const r = await api.get('system/watchdog');
                        if (r) showToast(r.healthy ? (lang === 'de' ? 'âœ… System gesund' : 'âœ… System healthy') : `âš ï¸ ${r.issues?.join(', ')}`, r.healthy ? 'success' : 'warning');
                    }}>
                        <span className="mdi mdi-heart-pulse" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Health-Check' : 'Health Check'}
                    </button>
                    <button className="btn btn-sm btn-secondary" onClick={async () => {
                        const r = await api.get('system/self-test');
                        if (r) showToast(r.passed ? (lang === 'de' ? 'âœ… Selbsttest bestanden' : 'âœ… Self-test passed') : `âš ï¸ ${r.tests?.filter(t => t.status !== 'ok').map(t => t.test).join(', ')}`, r.passed ? 'success' : 'warning');
                    }}>
                        <span className="mdi mdi-flask-outline" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Selbsttest' : 'Self-Test'}
                    </button>
                    <button className="btn btn-sm btn-secondary" onClick={async () => {
                        showToast(lang === 'de' ? 'Diagnose wird erstellt...' : 'Creating diagnostics...', 'info');
                        try {
                            const resp = await fetch(`${API_BASE}/api/system/diagnose`, { credentials: 'include' });
                            if (resp.ok) {
                                const blob = await resp.blob();
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement('a'); a.href = url;
                                a.download = `mindhome-diagnose-${new Date().toISOString().slice(0,10)}.zip`;
                                a.click(); URL.revokeObjectURL(url);
                            } else { showToast('Download failed', 'error'); }
                        } catch(e) { showToast('Error: ' + e.message, 'error'); }
                    }}>
                        <span className="mdi mdi-bug-outline" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Diagnose-Paket' : 'Diagnostic Package'}
                    </button>
                    <button className="btn btn-sm btn-secondary" onClick={async () => {
                        const r = await api.get('system/check-update');
                        if (r) showToast(r.update_available ? `Update: ${r.latest_version}` : (lang === 'de' ? `v${r.current_version} â€“ Aktuell` : `v${r.current_version} â€“ Up to date`), r.update_available ? 'info' : 'success');
                    }}>
                        <span className="mdi mdi-update" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Update prÃ¼fen' : 'Check Update'}
                    </button>
                </div>
            </div>

            </div>
            {/* RIGHT COLUMN */}
            <div>

            {/* Data Retention - only in advanced mode */}
            {viewMode === 'advanced' && (
                <div className="card" style={{ marginBottom: 16 }}>
                    <div className="card-title" style={{ marginBottom: 16 }}>
                        {lang === 'de' ? 'Daten-Aufbewahrung' : 'Data Retention'}
                    </div>
                    <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                        {lang === 'de'
                            ? `Daten Ã¤lter als ${retention} Tage werden automatisch gelÃ¶scht (FIFO).`
                            : `Data older than ${retention} days is automatically deleted (FIFO).`}
                    </p>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginBottom: 16 }}>
                        <div className="input-group" style={{ flex: 1 }}>
                            <label className="input-label">{lang === 'de' ? 'Aufbewahren fÃ¼r (Tage)' : 'Keep for (days)'}</label>
                            <input className="input" type="number" min="1" max="3650"
                                value={retentionInput} onChange={e => setRetentionInput(e.target.value)} />
                        </div>
                        <button className="btn btn-primary" onClick={saveRetention}
                            disabled={parseInt(retentionInput) === retention}>
                            {lang === 'de' ? 'Speichern' : 'Save'}
                        </button>
                    </div>
                    <button className="btn btn-secondary" onClick={handleCleanup} disabled={cleaning}>
                        <span className="mdi mdi-broom" />
                        {cleaning
                            ? (lang === 'de' ? 'AufrÃ¤umen...' : 'Cleaning...')
                            : (lang === 'de' ? 'Jetzt aufrÃ¤umen' : 'Clean Up Now')}
                    </button>
                </div>
            )}

            {/* Backup & Restore + Auto Backup (merged) */}
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>
                    {lang === 'de' ? 'Backup & Wiederherstellung' : 'Backup & Restore'}
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                    <button className="btn btn-primary" onClick={() => handleExport('standard')}>
                        <span className="mdi mdi-download" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Standard' : 'Standard'}
                    </button>
                    <button className="btn btn-secondary" onClick={() => handleExport('full')}>
                        <span className="mdi mdi-download-multiple" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Vollständig' : 'Full'}
                    </button>
                    <button className="btn btn-secondary" onClick={() => fileInputRef.current?.click()}>
                        <span className="mdi mdi-upload" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Backup laden' : 'Import'}
                    </button>
                    <input ref={fileInputRef} type="file" accept=".json" onChange={handleImport}
                           style={{ display: 'none' }} />
                </div>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer', marginBottom: 8 }}>
                    <input type="checkbox" checked={exportHistory} onChange={e => setExportHistory(e.target.checked)} />
                    {lang === 'de' ? 'Historische Daten einschließen (State History, Logs)' : 'Include historical data (state history, logs)'}
                </label>
                <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 0 }}>
                    {lang === 'de'
                        ? 'Standard: Konfiguration. Vollständig: inkl. Patterns & Regeln. History-Checkbox: State History, Action Logs (90 Tage).'
                        : 'Standard: config only. Full: incl. patterns & rules. History checkbox: state history, action logs (90 days).'}
                </p>
            </div>

            {/* Anomaly Detection Settings */}
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>
                    <span className="mdi mdi-alert-circle" style={{ marginRight: 8, color: 'var(--warning)' }} />
                    {lang === 'de' ? 'Anomalie-Erkennung' : 'Anomaly Detection'}
                </div>
                <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                    {lang === 'de'
                        ? 'Steuere wie empfindlich MindHome auf ungewÃ¶hnliche GerÃ¤tezustÃ¤nde reagiert.'
                        : 'Control how sensitively MindHome reacts to unusual device states.'}
                </p>
                <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                    {[{ id: 'low', label: lang === 'de' ? 'Niedrig' : 'Low', desc: lang === 'de' ? 'Nur extreme Anomalien' : 'Only extreme anomalies' },
                      { id: 'medium', label: 'Medium', desc: lang === 'de' ? 'Ausgewogen' : 'Balanced' },
                      { id: 'high', label: lang === 'de' ? 'Hoch' : 'High', desc: lang === 'de' ? 'Auch kleine Abweichungen' : 'Small deviations too' }].map(s => (
                        <button key={s.id} className={`btn ${anomalySensitivity === s.id ? 'btn-primary' : 'btn-secondary'}`} style={{ flex: 1, textAlign: 'center', padding: '10px 8px' }}
                            onClick={async () => {
                                setAnomalySensitivity(s.id);
                                await api.post('anomaly-settings', { sensitivity: s.id });
                                showToast(`${s.label}`, 'success');
                            }}>
                            <div style={{ fontWeight: 600, fontSize: 14 }}>{s.label}</div>
                            <div style={{ fontSize: 11, color: anomalySensitivity === s.id ? 'rgba(255,255,255,0.7)' : 'var(--text-muted)', marginTop: 2 }}>{s.desc}</div>
                        </button>
                    ))}
                </div>

                {/* Advanced Anomaly Settings - only in advanced mode */}
                {viewMode === 'advanced' && <AnomalyAdvancedPanel lang={lang} showToast={showToast} />}
            </div>

            {/* #23 Vacation Mode + #42 Debug Mode + #49 Auto Theme + #63 Export + #68 Accessibility */}
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>
                    <span className="mdi mdi-cog-outline" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                    {lang === 'de' ? 'Erweitert' : 'Advanced'}
                </div>

            </div>
                {/* #23 Vacation Mode */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ fontSize: 13 }}><span className="mdi mdi-airplane" style={{ marginRight: 6, color: 'var(--accent-primary)' }} />{lang === 'de' ? 'Urlaubsmodus' : 'Vacation Mode'}</span>
                    <label className="toggle" style={{ transform: 'scale(0.85)' }}>
                        <input type="checkbox" onChange={async () => {
                            const r = await api.put('system/vacation-mode', { enabled: true });
                            showToast(r?.enabled ? (lang === 'de' ? 'Urlaub aktiv' : 'Vacation ON') : (lang === 'de' ? 'Urlaub beendet' : 'Vacation OFF'), 'info');
                        }} />
                        <span className="toggle-slider" />
                    </label>
                </div>

                {/* #42 Debug Mode */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ fontSize: 13 }}><span className="mdi mdi-bug" style={{ marginRight: 6 }} />{lang === 'de' ? 'Debug-Modus' : 'Debug Mode'}</span>
                    <label className="toggle" style={{ transform: 'scale(0.85)' }}>
                        <input type="checkbox" onChange={async () => { const r = await api.put('system/debug'); showToast(r?.debug_mode ? 'Debug ON' : 'Debug OFF', 'info'); }} />
                        <span className="toggle-slider" />
                    </label>
                </div>

                {/* #49 Auto Theme */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ fontSize: 13 }}><span className="mdi mdi-theme-light-dark" style={{ marginRight: 6 }} />{lang === 'de' ? 'Auto-Theme' : 'Auto Theme'}</span>
                    <label className="toggle" style={{ transform: 'scale(0.85)' }}>
                        <input type="checkbox" defaultChecked={false} onChange={(e) => {
                            localStorage.setItem('mindhome_auto_theme', e.target.checked ? 'true' : 'false');
                            showToast(e.target.checked ? 'Auto' : 'Manual', 'info');
                        }} />
                        <span className="toggle-slider" />
                    </label>
                </div>

                {/* #68 Font Size */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ fontSize: 13 }}><span className="mdi mdi-format-size" style={{ marginRight: 6 }} />{lang === 'de' ? 'SchriftgrÃ¶ÃŸe' : 'Font Size'}</span>
                    <div style={{ display: 'flex', gap: 4 }}>
                        {[{ s: '13px', l: 'S' }, { s: '15px', l: 'M' }, { s: '17px', l: 'L' }].map(f => (
                            <button key={f.l} className="btn btn-sm btn-ghost" onClick={() => { document.documentElement.style.fontSize = f.s; }}
                                style={{ width: 28, fontSize: 11 }}>{f.l}</button>
                        ))}
                    </div>
                </div>

                {/* #63 Data Export */}
                <div style={{ padding: '10px 0 4px' }}>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>{lang === 'de' ? 'Daten exportieren' : 'Export Data'}</div>
                    <div style={{ display: 'flex', gap: 6 }}>
                        {['patterns', 'history', 'automations'].map(dt => (
                            <button key={dt} className="btn btn-sm btn-secondary"
                                onClick={() => window.open(`${API_BASE}/api/export/${dt}?format=csv`, '_blank')}
                                style={{ fontSize: 11, textTransform: 'capitalize' }}>{dt}</button>
                        ))}
                    </div>
                </div>
            </div>

            {/* Calendar Trigger Configuration */}
            <CalendarTriggersConfig lang={lang} showToast={showToast} />

        </div>
        </>
    );
};

const CalendarTriggersConfig = ({ lang, showToast }) => {
    const [triggers, setTriggers] = useState([]);
    const [calendars, setCalendars] = useState([]);
    const [showAdd, setShowAdd] = useState(false);
    const [newTrigger, setNewTrigger] = useState({ calendar: '', keyword: '', action: 'vacation_on', lead_minutes: 0 });

    useEffect(() => {
        (async () => {
            const t = await api.get('calendar-triggers');
            if (t) setTriggers(t);
            const c = await api.get('ha/entities?domain=calendar');
            if (c?.entities) setCalendars(c.entities);
        })();
    }, []);

    const save = async (updated) => {
        setTriggers(updated);
        await api.put('calendar-triggers', { triggers: updated });
    };

    const addTrigger = () => {
        if (!newTrigger.calendar || !newTrigger.keyword) return;
        save([...triggers, { ...newTrigger, id: Date.now() }]);
        setNewTrigger({ calendar: '', keyword: '', action: 'vacation_on', lead_minutes: 0 });
        setShowAdd(false);
        showToast(lang === 'de' ? 'Trigger erstellt' : 'Trigger created', 'success');
    };

    const removeTrigger = (id) => save(triggers.filter(t => t.id !== id));

    const actionLabels = {
        vacation_on: lang === 'de' ? 'Urlaubsmodus AN' : 'Vacation ON',
        vacation_off: lang === 'de' ? 'Urlaubsmodus AUS' : 'Vacation OFF',
        all_off: lang === 'de' ? 'Alles aus' : 'All off',
        notify: lang === 'de' ? 'Benachrichtigung' : 'Notification',
    };

    return (
        <div className="card" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div className="card-title" style={{ marginBottom: 0 }}>
                    <span className="mdi mdi-calendar-clock" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                    {lang === 'de' ? 'Kalender-Trigger' : 'Calendar Triggers'}
                </div>
                <button className="btn btn-sm btn-primary" onClick={() => setShowAdd(!showAdd)}>
                    <span className="mdi mdi-plus" />
                </button>
            </div>

            {showAdd && (
                <div style={{ padding: 12, background: 'var(--bg-main)', borderRadius: 8, marginBottom: 12 }}>
                    <div className="input-group" style={{ marginBottom: 8 }}>
                        <label className="input-label">{lang === 'de' ? 'Kalender' : 'Calendar'}</label>
                        <select className="input" value={newTrigger.calendar} onChange={e => setNewTrigger({ ...newTrigger, calendar: e.target.value })}>
                            <option value="">-- {lang === 'de' ? 'AuswÃ¤hlen' : 'Select'} --</option>
                            {calendars.map(c => <option key={c.entity_id} value={c.entity_id}>{c.name || c.entity_id}</option>)}
                        </select>
                    </div>
                    <div className="input-group" style={{ marginBottom: 8 }}>
                        <label className="input-label">{lang === 'de' ? 'Stichwort im Event' : 'Keyword in event'}</label>
                        <input className="input" value={newTrigger.keyword} onChange={e => setNewTrigger({ ...newTrigger, keyword: e.target.value })}
                            placeholder={lang === 'de' ? 'z.B. Urlaub, Meeting' : 'e.g. Vacation, Meeting'} />
                    </div>
                    <div className="input-group" style={{ marginBottom: 8 }}>
                        <label className="input-label">{lang === 'de' ? 'Aktion' : 'Action'}</label>
                        <select className="input" value={newTrigger.action} onChange={e => setNewTrigger({ ...newTrigger, action: e.target.value })}>
                            {Object.entries(actionLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                    </div>
                    <div className="input-group" style={{ marginBottom: 8 }}>
                        <label className="input-label">{lang === 'de' ? 'Vorlaufzeit (Min)' : 'Lead time (min)'}</label>
                        <input className="input" type="number" value={newTrigger.lead_minutes}
                            onChange={e => setNewTrigger({ ...newTrigger, lead_minutes: parseInt(e.target.value) || 0 })} />
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <button className="btn btn-sm btn-primary" onClick={addTrigger}>{lang === 'de' ? 'Erstellen' : 'Create'}</button>
                        <button className="btn btn-sm btn-secondary" onClick={() => setShowAdd(false)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                    </div>
                </div>
            )}

            {triggers.length === 0 && !showAdd ? (
                <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {lang === 'de' ? 'Keine Kalender-Trigger konfiguriert.' : 'No calendar triggers configured.'}
                </p>
            ) : triggers.map(t => (
                <div key={t.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '8px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                    <div>
                        <div style={{ fontWeight: 500 }}>{t.keyword} â†’ {actionLabels[t.action] || t.action}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                            {t.calendar}{t.lead_minutes ? ` Â· ${t.lead_minutes} min ${lang === 'de' ? 'vorher' : 'before'}` : ''}
                        </div>
                    </div>
                    <button className="btn btn-ghost btn-icon" onClick={() => removeTrigger(t.id)}>
                        <span className="mdi mdi-delete-outline" style={{ fontSize: 16, color: 'var(--danger)' }} />
                    </button>
                </div>
            ))}
        </div>
    );
};

const DeviceAnomalyConfig = ({ lang }) => {
    const { devices, rooms } = useApp();
    const [search, setSearch] = useState('');
    const [selected, setSelected] = useState(null);
    const [deviceConfig, setDeviceConfig] = useState(null);
    const [allConfigs, setAllConfigs] = useState({});

    useEffect(() => {
        (async () => { const c = await api.get('anomaly-settings/devices'); if (c) setAllConfigs(c); })();
    }, []);

    const loadDevice = async (deviceId) => {
        setSelected(deviceId);
        const c = await api.get(`anomaly-settings/device/${deviceId}`);
        if (c) setDeviceConfig(c);
    };

    const updateDevice = async (key, value) => {
        const updated = { ...deviceConfig, [key]: value };
        setDeviceConfig(updated);
        await api.put(`anomaly-settings/device/${selected}`, { [key]: value });
        setAllConfigs(prev => ({ ...prev, [selected]: updated }));
    };

    const filtered = (devices || []).filter(d =>
        !search || d.name?.toLowerCase().includes(search.toLowerCase()) ||
        d.entity_id?.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div>
            <input className="input" placeholder={lang === 'de' ? 'GerÃ¤t suchen...' : 'Search device...'}
                value={search} onChange={e => setSearch(e.target.value)}
                style={{ width: '100%', marginBottom: 8, padding: '6px 10px', fontSize: 12 }} />
            <div style={{ maxHeight: 200, overflowY: 'auto', marginBottom: selected ? 12 : 0 }}>
                {filtered.slice(0, 30).map(d => {
                    const hasConfig = allConfigs[d.id];
                    const isWhitelisted = hasConfig?.whitelisted;
                    const room = rooms?.find(r => r.id === d.room_id);
                    return (
                        <div key={d.id} onClick={() => loadDevice(d.id)}
                            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                padding: '5px 6px', cursor: 'pointer', fontSize: 12, borderRadius: 4,
                                background: selected === d.id ? 'var(--accent-primary-alpha)' : 'transparent',
                                borderBottom: '1px solid var(--border)' }}>
                            <div>
                                <span style={{ fontWeight: selected === d.id ? 600 : 400 }}>{d.name}</span>
                                {room && <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 6 }}>{room.name}</span>}
                            </div>
                            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                                {isWhitelisted && <span className="mdi mdi-shield-off" style={{ fontSize: 12, color: 'var(--text-muted)' }} title="Whitelisted" />}
                                {hasConfig && !isWhitelisted && <span className="mdi mdi-cog" style={{ fontSize: 12, color: 'var(--accent-primary)' }} title="Custom config" />}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Selected device config */}
            {selected && deviceConfig && (
                <div style={{ padding: 10, background: 'var(--bg-main)', borderRadius: 8, marginTop: 8 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
                        {devices?.find(d => d.id === selected)?.name}
                    </div>

                    {/* Enabled / Whitelisted */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                        <span style={{ fontSize: 11 }}>{lang === 'de' ? 'Ausgeschlossen (Whitelist)' : 'Excluded (Whitelist)'}</span>
                        <label className="toggle" style={{ transform: 'scale(0.7)' }}><input type="checkbox" checked={deviceConfig.whitelisted || false}
                            onChange={() => updateDevice('whitelisted', !deviceConfig.whitelisted)} /><div className="toggle-slider" /></label>
                    </div>

                    {!deviceConfig.whitelisted && (<>
                        {/* Sensitivity */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}>
                            <span style={{ fontSize: 11 }}>{lang === 'de' ? 'Empfindlichkeit' : 'Sensitivity'}</span>
                            <div style={{ display: 'flex', gap: 3 }}>
                                {[{id:'inherit',l:lang==='de'?'Vererbt':'Inherit'},{id:'low',l:lang==='de'?'Niedrig':'Low'},{id:'medium',l:'Medium'},{id:'high',l:lang==='de'?'Hoch':'High'},{id:'off',l:'Aus'}].map(s => (
                                    <button key={s.id} className={`btn btn-sm ${(deviceConfig.sensitivity || 'inherit') === s.id ? 'btn-primary' : 'btn-ghost'}`}
                                        onClick={() => updateDevice('sensitivity', s.id)} style={{ fontSize: 9, padding: '2px 5px' }}>{s.l}</button>
                                ))}
                            </div>
                        </div>

                        {/* Detection Types */}
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6, marginBottom: 2 }}>{lang === 'de' ? 'Erkennungs-Typen' : 'Detection Types'}</div>
                        {['offline', 'stuck', 'value', 'frequency'].map(t => (
                            <div key={t} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '2px 0' }}>
                                <span style={{ fontSize: 11 }}>{t.charAt(0).toUpperCase() + t.slice(1)}</span>
                                <label className="toggle" style={{ transform: 'scale(0.65)' }}><input type="checkbox"
                                    checked={deviceConfig.detection_types?.[t] !== false}
                                    onChange={() => updateDevice('detection_types', { ...(deviceConfig.detection_types || {}), [t]: !deviceConfig.detection_types?.[t] })} /><div className="toggle-slider" /></label>
                            </div>
                        ))}

                        {/* Reaction */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0', marginTop: 4 }}>
                            <span style={{ fontSize: 11 }}>{lang === 'de' ? 'Reaktion' : 'Reaction'}</span>
                            <div style={{ display: 'flex', gap: 3 }}>
                                {[{id:'inherit',l:lang==='de'?'Vererbt':'Inherit'},{id:'log',l:'Log'},{id:'push',l:'Push'},{id:'push_tts',l:'TTS'}].map(r => (
                                    <button key={r.id} className={`btn btn-sm ${(deviceConfig.reaction || 'inherit') === r.id ? 'btn-primary' : 'btn-ghost'}`}
                                        onClick={() => updateDevice('reaction', r.id)} style={{ fontSize: 9, padding: '2px 5px' }}>{r.l}</button>
                                ))}
                            </div>
                        </div>

                        {/* Thresholds */}
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6, marginBottom: 2 }}>{lang === 'de' ? 'Schwellwerte' : 'Thresholds'}</div>
                        {[{key:'temp_min',l:lang==='de'?'Temp. min Â°C':'Temp min Â°C',ph:'5'},
                          {key:'temp_max',l:lang==='de'?'Temp. max Â°C':'Temp max Â°C',ph:'30'},
                          {key:'power_max',l:lang==='de'?'Strom max W':'Power max W',ph:'3000'},
                          {key:'battery_min',l:lang==='de'?'Batterie min %':'Battery min %',ph:'20'}].map(t => (
                            <div key={t.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '2px 0' }}>
                                <span style={{ fontSize: 11 }}>{t.l}</span>
                                <input className="input" type="number" placeholder={t.ph}
                                    value={deviceConfig.thresholds?.[t.key] || ''} style={{ width: 60, padding: '2px 6px', fontSize: 11, textAlign: 'right' }}
                                    onChange={e => updateDevice('thresholds', { ...(deviceConfig.thresholds || {}), [t.key]: e.target.value ? Number(e.target.value) : null })} />
                            </div>
                        ))}
                    </>)}
                </div>
            )}
        </div>
    );
};

const AnomalyAdvancedPanel = ({ lang, showToast }) => {
    const [config, setConfig] = useState(null);
    const [stats, setStats] = useState(null);
    const { domains, devices } = useApp();

    useEffect(() => {
        (async () => {
            const [c, s] = await Promise.all([api.get('anomaly-settings/extended'), api.get('anomaly-settings/stats')]);
            if (c) setConfig(c);
            if (s) setStats(s);
        })();
    }, []);

    if (!config) return null;
    const update = async (key, value) => {
        setConfig(prev => ({ ...prev, [key]: value }));
        await api.put('anomaly-settings/extended', { [key]: value });
    };

    return (
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>
                <span className="mdi mdi-tune" style={{ marginRight: 6, color: 'var(--accent-primary)' }} />
                {lang === 'de' ? 'Erweiterte Anomalie-Einstellungen' : 'Advanced Anomaly Settings'}
            </div>

            {/* Detection Types */}
            <CollapsibleCard title={lang === 'de' ? 'Erkennungs-Typen' : 'Detection Types'} icon="mdi-radar" defaultOpen={false}>
                {[{key:'frequency',de:'HÃ¤ufigkeit',en:'Frequency'},{key:'time',de:'Zeitabweichung',en:'Time'},{key:'value',de:'Wertabweichung',en:'Value'},
                  {key:'offline',de:'Offline',en:'Offline'},{key:'stuck',de:'Stuck',en:'Stuck'},{key:'pattern_deviation',de:'Muster-Abweichung',en:'Pattern'}].map(t => (
                    <div key={t.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0' }}>
                        <span style={{ fontSize: 12 }}>{lang === 'de' ? t.de : t.en}</span>
                        <label className="toggle" style={{ transform: 'scale(0.75)' }}><input type="checkbox" checked={config.detection_types?.[t.key] !== false}
                            onChange={() => update('detection_types', { ...config.detection_types, [t.key]: !config.detection_types?.[t.key] })} /><div className="toggle-slider" /></label>
                    </div>
                ))}
            </CollapsibleCard>

            {/* Thresholds */}
            <CollapsibleCard title={lang === 'de' ? 'Schwellwerte' : 'Thresholds'} icon="mdi-speedometer" defaultOpen={false}>
                {[{key:'offline_timeout_min',de:'Offline nach (Min)',en:'Offline after (min)',vals:[15,30,60,120],unit:''},
                  {key:'stuck_timeout_hours',de:'Stuck nach (Std)',en:'Stuck after (hrs)',vals:[4,8,12,24],unit:''},
                  {key:'value_deviation_pct',de:'Wert-Abweichung',en:'Value deviation',vals:[10,20,30,50],unit:'%'},
                  {key:'battery_threshold',de:'Batterie-Warnung',en:'Battery warning',vals:[10,20,30],unit:'%'}].map(t => (
                    <div key={t.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0' }}>
                        <span style={{ fontSize: 12 }}>{lang === 'de' ? t.de : t.en}</span>
                        <div style={{ display: 'flex', gap: 3 }}>
                            {t.vals.map(v => (
                                <button key={v} className={`btn btn-sm ${config[t.key] === v ? 'btn-primary' : 'btn-ghost'}`}
                                    onClick={() => update(t.key, v)} style={{ fontSize: 10, padding: '2px 6px' }}>{v}{t.unit}</button>
                            ))}
                        </div>
                    </div>
                ))}
            </CollapsibleCard>

            {/* Reactions per severity */}
            <CollapsibleCard title={lang === 'de' ? 'Reaktionen' : 'Reactions'} icon="mdi-bell-cog" defaultOpen={false}>
                {['low','medium','high','critical'].map(sev => {
                    const labels = {low: lang==='de'?'Niedrig':'Low', medium:'Medium', high: lang==='de'?'Hoch':'High', critical: lang==='de'?'Kritisch':'Critical'};
                    return (
                        <div key={sev} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0' }}>
                            <span style={{ fontSize: 12 }}>{labels[sev]}</span>
                            <div style={{ display: 'flex', gap: 3 }}>
                                {[{id:'log',l:'Log'},{id:'push',l:'Push'},{id:'push_tts',l:'Push+TTS'},{id:'push_tts_action',l:'Auto'}].map(o => (
                                    <button key={o.id} className={`btn btn-sm ${config.reactions?.[sev] === o.id ? 'btn-primary' : 'btn-ghost'}`}
                                        onClick={() => update('reactions', { ...config.reactions, [sev]: o.id })}
                                        style={{ fontSize: 9, padding: '2px 5px' }}>{o.l}</button>
                                ))}
                            </div>
                        </div>
                    );
                })}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', marginTop: 4 }}>
                    <span style={{ fontSize: 12 }}>{lang === 'de' ? 'VerzÃ¶gerung (Min)' : 'Delay (min)'}</span>
                    <div style={{ display: 'flex', gap: 3 }}>
                        {[0,1,5,10].map(m => (
                            <button key={m} className={`btn btn-sm ${config.reaction_delay_min === m ? 'btn-primary' : 'btn-ghost'}`}
                                onClick={() => update('reaction_delay_min', m)} style={{ fontSize: 10, padding: '2px 6px' }}>{m}</button>
                        ))}
                    </div>
                </div>
            </CollapsibleCard>

            {/* Exceptions & Learning */}
            <CollapsibleCard title={lang === 'de' ? 'Ausnahmen & Lernen' : 'Exceptions & Learning'} icon="mdi-shield-off" defaultOpen={false}>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                    <button className="btn btn-sm btn-secondary" onClick={async () => {
                        await api.post('anomaly-settings/pause', { hours: 1 });
                        showToast(lang === 'de' ? 'Pausiert fÃ¼r 1h' : 'Paused 1h', 'info'); }}>
                        <span className="mdi mdi-pause" style={{ marginRight: 4 }} />1h
                    </button>
                    <button className="btn btn-sm btn-secondary" onClick={async () => {
                        await api.post('anomaly-settings/pause', { hours: 4 });
                        showToast(lang === 'de' ? 'Pausiert fÃ¼r 4h' : 'Paused 4h', 'info'); }}>
                        <span className="mdi mdi-pause" style={{ marginRight: 4 }} />4h
                    </button>
                    <button className="btn btn-sm btn-secondary" onClick={async () => {
                        await api.post('anomaly-settings/pause', { hours: 24 });
                        showToast(lang === 'de' ? 'Pausiert fÃ¼r 24h' : 'Paused 24h', 'info'); }}>
                        <span className="mdi mdi-pause" style={{ marginRight: 4 }} />24h
                    </button>
                    <button className="btn btn-sm btn-warning" onClick={async () => {
                        await api.post('anomaly-settings/reset-baseline');
                        showToast(lang === 'de' ? 'Baseline wird neu gelernt (7 Tage)' : 'Baseline reset (7 days)', 'info'); }}>
                        <span className="mdi mdi-restart" style={{ marginRight: 4 }} />{lang === 'de' ? 'Baseline reset' : 'Reset baseline'}
                    </button>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0' }}>
                    <span style={{ fontSize: 12 }}>{lang === 'de' ? 'Saisonale Anpassung' : 'Seasonal adjustment'}</span>
                    <label className="toggle" style={{ transform: 'scale(0.75)' }}><input type="checkbox" checked={config.seasonal_adjustment?.enabled !== false}
                        onChange={() => update('seasonal_adjustment', { enabled: !config.seasonal_adjustment?.enabled })} /><div className="toggle-slider" /></label>
                </div>
                {config.paused_until && new Date(config.paused_until) > new Date() && (
                    <div style={{ fontSize: 11, color: 'var(--warning)', marginTop: 4 }}>
                        <span className="mdi mdi-pause-circle" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Pausiert bis' : 'Paused until'} {new Date(config.paused_until).toLocaleTimeString()}
                    </div>
                )}
            </CollapsibleCard>

            {/* Per-Device Configuration */}
            <CollapsibleCard title={lang === 'de' ? 'GerÃ¤te-Konfiguration' : 'Device Configuration'} icon="mdi-devices" defaultOpen={false}>
                <DeviceAnomalyConfig lang={lang} />
            </CollapsibleCard>

            {/* Statistics */}
            {stats && stats.total_30d > 0 && (
                <CollapsibleCard title={`${lang === 'de' ? 'Statistik' : 'Statistics'} Â· ${stats.total_30d}`} icon="mdi-chart-bar" defaultOpen={false}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6, marginBottom: 8 }}>
                        {Object.entries(stats.by_type || {}).map(([type, count]) => (
                            <div key={type} style={{ padding: '6px 8px', background: 'var(--bg-main)', borderRadius: 6, fontSize: 11 }}>
                                <div style={{ fontWeight: 600 }}>{count}Ã—</div>
                                <div style={{ color: 'var(--text-muted)' }}>{type}</div>
                            </div>
                        ))}
                    </div>
                    {stats.top_devices?.length > 0 && (
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                            {lang === 'de' ? 'Top-GerÃ¤te' : 'Top devices'}: {stats.top_devices.slice(0, 3).map(d => `${d.name} (${d.count}Ã—)`).join(', ')}
                        </div>
                    )}
                </CollapsibleCard>
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)
// ================================================================

const ActivitiesPage = () => {
    const { lang, devices, rooms, domains } = useApp();
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [period, setPeriod] = useState('7d');
    const [tab, setTab] = useState('all');
    const [search, setSearch] = useState('');
    const [roomFilter, setRoomFilter] = useState('');
    const [deviceFilter, setDeviceFilter] = useState('');
    const [liveMode, setLiveMode] = useState(false);
    const [auditTab, setAuditTab] = useState(false);
    const [auditLogs, setAuditLogs] = useState([]);

    const loadLogs = async (p) => {
        setLoading(true);
        const data = await api.get(`action-log?limit=500&period=${p}`);
        setLogs(data || []);
        setLoading(false);
    };

    useEffect(() => { loadLogs(period); }, [period]);

    const loadAudit = async () => { const data = await api.get('audit-trail?limit=200'); setAuditLogs(data || []); };
    useEffect(() => { if (auditTab) loadAudit(); }, [auditTab]);

    // Live mode: poll every 10s
    useEffect(() => {
        if (!liveMode) return;
        const iv = setInterval(() => loadLogs(period), 10000);
        return () => clearInterval(iv);
    }, [liveMode, period]);

    const typeIcons = {
        observation: 'mdi-eye', quick_action: 'mdi-lightning-bolt', automation: 'mdi-robot',
        suggestion: 'mdi-lightbulb-on', anomaly: 'mdi-alert', system: 'mdi-cog', first_time: 'mdi-star-circle'
    };
    const typeColors = {
        observation: 'var(--text-muted)', quick_action: 'var(--info)', automation: 'var(--warning)',
        suggestion: 'var(--accent-primary)', anomaly: 'var(--danger)', system: 'var(--text-secondary)'
    };

    const tabTypes = {
        all: null,
        devices: ['observation'],
        automations: ['automation', 'suggestion', 'quick_action'],
        system: ['anomaly', 'system', 'first_time']
    };

    const getDeviceName = (id) => devices.find(d => d.id === id)?.name || '';
    const getRoomName = (id) => rooms.find(r => r.id === id)?.name || '';

    const filtered = logs.filter(log => {
        if (tab !== 'all' && tabTypes[tab] && !tabTypes[tab].includes(log.action_type)) return false;
        if (roomFilter && log.room_id !== parseInt(roomFilter)) return false;
        if (deviceFilter && log.device_id !== parseInt(deviceFilter)) return false;
        if (search) {
            const s = search.toLowerCase();
            const reason = (log.reason || '').toLowerCase();
            const entity = (log.action_data?.entity_id || '').toLowerCase();
            const devName = getDeviceName(log.device_id).toLowerCase();
            const roomName = getRoomName(log.room_id).toLowerCase();
            if (!reason.includes(s) && !entity.includes(s) && !devName.includes(s) && !roomName.includes(s)) return false;
        }
        return true;
    });

    const exportCSV = () => {
        const headers = ['Datum', 'Typ', 'Beschreibung', 'GerÃ¤t', 'Raum'];
        const rows = filtered.map(l => [
            new Date(l.created_at).toLocaleString('de-DE'),
            l.action_type,
            (l.reason || '').replace(/,/g, ';'),
            getDeviceName(l.device_id),
            getRoomName(l.room_id)
        ]);
        const csv = [headers, ...rows].map(r => r.join(',')).join('\n');
        const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
        a.download = `mindhome-activities-${new Date().toISOString().slice(0, 10)}.csv`;
        a.click();
    };

    const tabs = [
        { id: 'all', label: lang === 'de' ? 'Alle' : 'All', icon: 'mdi-format-list-bulleted' },
        { id: 'devices', label: lang === 'de' ? 'GerÃ¤te' : 'Devices', icon: 'mdi-devices' },
        { id: 'automations', label: lang === 'de' ? 'Automationen' : 'Automations', icon: 'mdi-robot' },
        { id: 'system', label: 'System', icon: 'mdi-alert-circle' },
    ];

    return (
        <div>
            {/* Tabs */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 16, overflowX: 'auto', paddingBottom: 4 }}>
                {tabs.map(t => (
                    <button key={t.id} className={`btn ${tab === t.id ? 'btn-primary' : 'btn-ghost'}`}
                        style={{ fontSize: 13, whiteSpace: 'nowrap', padding: '6px 14px' }}
                        onClick={() => setTab(t.id)}>
                        <span className={`mdi ${t.icon}`} style={{ marginRight: 6 }} />
                        {t.label}
                        {t.id !== 'all' && (() => {
                            const count = logs.filter(l => tabTypes[t.id]?.includes(l.action_type)).length;
                            return count > 0 ? <span style={{ marginLeft: 6, opacity: 0.7 }}>({count})</span> : null;
                        })()}
                    </button>
                ))}
            </div>

            {/* Search & Filters */}
            <div className="card" style={{ marginBottom: 16, padding: 14 }}>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                    <div style={{ flex: '1 1 200px' }}>
                        <div style={{ position: 'relative' }}>
                            <span className="mdi mdi-magnify" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: 18 }} />
                            <input className="input" placeholder={lang === 'de' ? 'Suchen...' : 'Search...'}
                                value={search} onChange={e => setSearch(e.target.value)}
                                style={{ paddingLeft: 34 }} />
                        </div>
                    </div>
                    <div style={{ flex: '0 1 160px' }}>
                        <Dropdown value={roomFilter} onChange={v => setRoomFilter(v)}
                            placeholder={lang === 'de' ? 'Alle RÃ¤ume' : 'All Rooms'}
                            options={[{ value: '', label: lang === 'de' ? 'Alle RÃ¤ume' : 'All Rooms' }, ...rooms.map(r => ({ value: String(r.id), label: r.name }))]} />
                    </div>
                    <div style={{ flex: '0 1 160px' }}>
                        <Dropdown value={deviceFilter} onChange={v => setDeviceFilter(v)}
                            placeholder={lang === 'de' ? 'Alle GerÃ¤te' : 'All Devices'}
                            options={[{ value: '', label: lang === 'de' ? 'Alle GerÃ¤te' : 'All Devices' }, ...devices.map(d => ({ value: String(d.id), label: d.name }))]} />
                    </div>
                    <PeriodFilter value={period} onChange={setPeriod} lang={lang} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10 }}>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                        {filtered.length} {lang === 'de' ? 'EintrÃ¤ge' : 'entries'}
                        {search && ` (${lang === 'de' ? 'gefiltert' : 'filtered'})`}
                    </span>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <button className={`btn ${auditTab ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setAuditTab(!auditTab)}
                            style={{ fontSize: 12, padding: '4px 10px' }}>
                            <span className="mdi mdi-shield-check" style={{ marginRight: 4 }} />
                            {lang === 'de' ? 'Audit-Log' : 'Audit Log'}
                        </button>
                        <button className={`btn btn-ghost`} onClick={() => setLiveMode(!liveMode)}
                            style={{ fontSize: 12, padding: '4px 10px', color: liveMode ? 'var(--success)' : undefined }}>
                            <span className={`mdi ${liveMode ? 'mdi-access-point' : 'mdi-access-point-off'}`} style={{ marginRight: 4 }} />
                            Live
                        </button>
                        <button className="btn btn-ghost" onClick={exportCSV} style={{ fontSize: 12, padding: '4px 10px' }}>
                            <span className="mdi mdi-download" style={{ marginRight: 4 }} />CSV
                        </button>
                    </div>
                </div>
            </div>

            {/* Log Entries */}
            {loading ? (
                <div className="empty-state"><div className="loading-spinner" /></div>
            ) : filtered.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {filtered.map(log => {
                        const attrs = log.action_data?.new_attributes || {};
                        const attrParts = [];
                        if (attrs.brightness_pct !== undefined) attrParts.push(`ðŸ’¡ ${attrs.brightness_pct}%`);
                        if (attrs.position_pct !== undefined) attrParts.push(`â†• ${attrs.position_pct}%`);
                        if (attrs.target_temp !== undefined) attrParts.push(`ðŸŒ¡ ${attrs.target_temp}Â°C`);
                        if (attrs.current_temp !== undefined) attrParts.push(`Ist: ${attrs.current_temp}Â°C`);
                        const roomName = getRoomName(log.room_id);
                        return (
                        <div key={log.id} className="card" style={{ padding: '12px 14px', display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                            <span className={`mdi ${typeIcons[log.action_type] || 'mdi-circle-small'}`}
                                  style={{ fontSize: 20, color: typeColors[log.action_type] || 'var(--accent-primary)', marginTop: 2, flexShrink: 0 }} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 14, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{log.reason || log.action_type}</span>
                                    {log.action_type === 'automation' && (
                                        <span className="badge badge-warning" style={{ fontSize: 10 }}>
                                            <span className="mdi mdi-robot" style={{ marginRight: 2 }} />MindHome
                                        </span>
                                    )}
                                </div>
                                {log.action_data?.confidence && (
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>
                                        {lang === 'de' ? 'Vertrauen' : 'Confidence'}: {Math.round(log.action_data.confidence * 100)}%
                                    </div>
                                )}
                                {attrParts.length > 0 && (
                                    <div style={{ fontSize: 12, color: 'var(--accent-secondary)', marginTop: 2 }}>{attrParts.join(' Â· ')}</div>
                                )}
                                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3, display: 'flex', gap: 8 }}>
                                    <span>{new Date(log.created_at).toLocaleString(lang === 'de' ? 'de-DE' : 'en-US')}</span>
                                    {roomName && <span>Â· {roomName}</span>}
                                </div>
                            </div>
                            {log.was_undone && (
                                <span className="badge badge-warning" style={{ flexShrink: 0 }}>{lang === 'de' ? 'RÃ¼ckgÃ¤ngig' : 'Undone'}</span>
                            )}
                        </div>
                        );
                    })}
                </div>
            ) : (
                <div className="empty-state">
                    <span className="mdi mdi-text-box-search-outline" />
                    <h3>{lang === 'de' ? 'Keine EintrÃ¤ge gefunden' : 'No Entries Found'}</h3>
                    <p>{search || roomFilter || deviceFilter
                        ? (lang === 'de' ? 'Versuche andere Filter.' : 'Try different filters.')
                        : (lang === 'de' ? 'Hier werden alle AktivitÃ¤ten protokolliert.' : 'All activities will be logged here.')}</p>
                </div>
            )}

            {/* Audit Trail (#60) */}
            {auditTab && (
                <div className="card" style={{ marginTop: 16 }}>
                    <div className="card-title" style={{ marginBottom: 12 }}>
                        <span className="mdi mdi-shield-check" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                        {lang === 'de' ? 'Audit-Log (Wer hat was geÃ¤ndert)' : 'Audit Log (Who changed what)'}
                    </div>
                    {auditLogs.length === 0 ? (
                        <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>{lang === 'de' ? 'Noch keine Audit-EintrÃ¤ge.' : 'No audit entries yet.'}</p>
                    ) : (
                        <div style={{ maxHeight: 400, overflowY: 'auto' }}>
                            {auditLogs.map(a => (
                                <div key={a.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--border-color)', fontSize: 13 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                        <strong>{a.action}</strong>
                                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{a.created_at ? relativeTime(a.created_at, lang) : 'â€“'}</span>
                                    </div>
                                    {a.target && <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{a.target}</div>}
                                    {a.details && <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 2 }}>{typeof a.details === 'string' ? a.details : JSON.stringify(a.details)}</div>}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)
// ================================================================

const PatternsPage = () => {
    const { lang, viewMode, showToast, devices, rooms, domains } = useApp();
    const [patterns, setPatterns] = useState([]);
    const [stats, setStats] = useState(null);
    const [stateHistory, setStateHistory] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all');
    const [statusFilter, setStatusFilter] = useState('');
    const [showHistory, setShowHistory] = useState(false);
    const [historyEntity, setHistoryEntity] = useState('');
    const [analyzing, setAnalyzing] = useState(false);
    const [confirmDel, setConfirmDel] = useState(null);
    const [expandedId, setExpandedId] = useState(null);
    const [ptab, setPtab] = useState('patterns');
    const [rejected, setRejected] = useState([]);
    const [exclusions, setExclusions] = useState([]);
    const [manualRules, setManualRules] = useState([]);
    const [showAddExcl, setShowAddExcl] = useState(false);
    const [showAddRule, setShowAddRule] = useState(false);
    const [newExcl, setNewExcl] = useState({ type: 'device_pair', entity_a: '', entity_b: '', reason: '' });
    const [newRule, setNewRule] = useState({ name: '', trigger_entity: '', trigger_state: '', action_entity: '', action_service: 'turn_on' });
    const [rejectReason, setRejectReason] = useState(null);
    const [conflicts, setConflicts] = useState([]);    // #26
    const [scenes, setScenes] = useState([]);           // #29
    const [bulkSelected, setBulkSelected] = useState({});  // #16 Bulk actions
    const [bulkMode, setBulkMode] = useState(false);       // #16

    const load = async () => {
        try {
            const [pats, st, rej, excl, rules, conf, sc] = await Promise.all([
                api.get('patterns'),
                api.get('stats/learning'),
                api.get('patterns/rejected'),
                api.get('pattern-exclusions'),
                api.get('manual-rules'),
                api.get('patterns/conflicts'),   // #26
                api.get('patterns/scenes'),       // #29
            ]);
            setPatterns(pats);
            setStats(st);
            setRejected(rej || []);
            setExclusions(excl || []);
            setManualRules(rules || []);
            setConflicts(conf?.conflicts || []);
            setScenes(sc?.scenes || []);
        } catch (e) {
            console.error(e);
        }
        setLoading(false);
    };

    useEffect(() => {
        // Auto-reclassify existing sensorâ†’sensor patterns as insights
        api.post('patterns/reclassify-insights').then(() => load());
    }, []);

    const loadHistory = async (entity) => {
        try {
            const h = await api.get(`state-history?hours=48&limit=100${entity ? `&entity_id=${entity}` : ''}`);
            setStateHistory(h);
        } catch (e) { console.error(e); }
    };

    const triggerAnalysis = async () => {
        setAnalyzing(true);
        try {
            await api.post('patterns/analyze');
            showToast(lang === 'de' ? 'Analyse gestartet...' : 'Analysis started...', 'success');
            // Reload after a delay
            setTimeout(() => { load(); setAnalyzing(false); }, 8000);
        } catch (e) {
            showToast('Error', 'error');
            setAnalyzing(false);
        }
    };

    const togglePattern = async (id, newStatus) => {
        try {
            await api.put(`patterns/${id}`, { status: newStatus });
            showToast(lang === 'de' ? 'Muster aktualisiert' : 'Pattern updated', 'success');
            await load();
        } catch (e) { showToast('Error', 'error'); }
    };

    const deletePattern = async (id) => {
        try {
            await api.delete(`patterns/${id}`);
            showToast(lang === 'de' ? 'Muster gelÃ¶scht' : 'Pattern deleted', 'success');
            setConfirmDel(null);
            await load();
        } catch (e) { showToast('Error', 'error'); }
    };

    const filtered = patterns.filter(p => {
        if (filter !== 'all' && p.pattern_type !== filter) return false;
        if (statusFilter && p.status !== statusFilter) return false;
        return true;
    });

    const typeIcons = {
        time_based: 'mdi-clock-outline',
        event_chain: 'mdi-link-variant',
        correlation: 'mdi-chart-scatter-plot',
    };

    const typeLabels = {
        time_based: lang === 'de' ? 'Zeitbasiert' : 'Time-based',
        event_chain: lang === 'de' ? 'Sequenz' : 'Sequence',
        correlation: lang === 'de' ? 'Korrelation' : 'Correlation',
    };

    const statusColors = {
        observed: 'info',
        suggested: 'warning',
        active: 'success',
        disabled: 'danger',
    };

    const statusLabels = {
        observed: lang === 'de' ? 'Beobachtet' : 'Observed',
        suggested: lang === 'de' ? 'Vorgeschlagen' : 'Suggested',
        active: lang === 'de' ? 'Aktiv' : 'Active',
        disabled: lang === 'de' ? 'Deaktiviert' : 'Disabled',
        insight: lang === 'de' ? 'Insights' : 'Insights',
    };

    const rejectPattern = async (id, reason) => {
        // Optimistic UI update - immediately move from patterns to rejected
        const pattern = patterns.find(p => p.id === id);
        setPatterns(prev => prev.filter(p => p.id !== id));
        if (pattern) setRejected(prev => [{ ...pattern, status: 'rejected', rejected_at: new Date().toISOString() }, ...prev]);
        await api.put(`patterns/reject/${id}`, { reason });
        showToast(lang === 'de' ? 'Muster abgelehnt' : 'Pattern rejected', 'success');
        setRejectReason(null);
        await load();
    };

    const reactivatePattern = async (id) => {
        // Optimistic UI update
        const pattern = rejected.find(p => p.id === id);
        setRejected(prev => prev.filter(p => p.id !== id));
        if (pattern) setPatterns(prev => [{ ...pattern, status: 'observed' }, ...prev]);
        await api.put(`patterns/reactivate/${id}`, {});
        showToast(lang === 'de' ? 'Muster reaktiviert' : 'Pattern reactivated', 'success');
        await load();
    };

    const createExclusion = async () => {
        if (!newExcl.entity_a || !newExcl.entity_b) return;
        await api.post('pattern-exclusions', newExcl);
        setShowAddExcl(false);
        setNewExcl({ type: 'device_pair', entity_a: '', entity_b: '', reason: '' });
        await load();
        showToast(lang === 'de' ? 'Ausschluss erstellt' : 'Exclusion created', 'success');
    };

    const createRule = async () => {
        if (!newRule.name || !newRule.trigger_entity || !newRule.action_entity) return;
        await api.post('manual-rules', newRule);
        setShowAddRule(false);
        setNewRule({ name: '', trigger_entity: '', trigger_state: '', action_entity: '', action_service: 'turn_on' });
        await load();
        showToast(lang === 'de' ? 'Regel erstellt' : 'Rule created', 'success');
    };

    if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><span className="mdi mdi-loading mdi-spin" style={{ fontSize: 32 }} /></div>;

    const ptabs = [
        { id: 'patterns', label: lang === 'de' ? 'Muster' : 'Patterns', icon: 'mdi-lightbulb-on', count: patterns.length },
        { id: 'rejected', label: lang === 'de' ? 'Abgelehnt' : 'Rejected', icon: 'mdi-close-circle', count: rejected.length },
        { id: 'exclusions', label: lang === 'de' ? 'AusschlÃ¼sse' : 'Exclusions', icon: 'mdi-link-off', count: exclusions.length },
        { id: 'rules', label: lang === 'de' ? 'Eigene Regeln' : 'Manual Rules', icon: 'mdi-pencil-ruler', count: manualRules.length },
    ];

    return (
        <div>
            {/* #26 Pattern Conflicts Warning */}
            {conflicts.length > 0 && (
                <div className="card" style={{ marginBottom: 16, padding: '12px 16px', borderLeft: '3px solid var(--danger)' }}>
                    <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                        <span className="mdi mdi-alert" style={{ color: 'var(--danger)', marginRight: 6 }} />
                        {lang === 'de' ? `${conflicts.length} Muster-Konflikte` : `${conflicts.length} Pattern Conflicts`}
                    </div>
                    {conflicts.slice(0, 3).map((c, i) => (
                        <div key={i} style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 2 }}>
                            {lang === 'de' ? c.message_de : c.message_en}
                        </div>
                    ))}
                </div>
            )}

            {/* #29 Scene Suggestions */}
            {scenes.length > 0 && (
                <div className="card" style={{ marginBottom: 16, padding: '12px 16px', borderLeft: '3px solid var(--accent-primary)' }}>
                    <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>
                        <span className="mdi mdi-group" style={{ color: 'var(--accent-primary)', marginRight: 6 }} />
                        {lang === 'de' ? 'Szenen-VorschlÃ¤ge' : 'Scene Suggestions'}
                    </div>
                    {scenes.slice(0, 3).map((s, i) => (
                        <div key={i} style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 2 }}>
                            {lang === 'de' ? s.message_de : s.message_en}
                            <span style={{ opacity: 0.6, marginLeft: 4 }}>({s.entities.length} {lang === 'de' ? 'GerÃ¤te' : 'devices'})</span>
                        </div>
                    ))}
                </div>
            )}
            {/* Tabs */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 16, overflowX: 'auto', paddingBottom: 4 }}>
                {ptabs.map(t => (
                    <button key={t.id} className={`btn ${ptab === t.id ? 'btn-primary' : 'btn-ghost'}`}
                        style={{ fontSize: 13, whiteSpace: 'nowrap', padding: '6px 14px' }} onClick={() => setPtab(t.id)}>
                        <span className={`mdi ${t.icon}`} style={{ marginRight: 6 }} />
                        {t.label}{t.count > 0 ? ` (${t.count})` : ''}
                    </button>
                ))}
            </div>

            {ptab === 'rejected' ? (
                <div>
                    {rejected.length > 0 ? rejected.map(p => (
                        <div key={p.id} className="card" style={{ marginBottom: 8, padding: 14 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <div>
                                    <div style={{ fontSize: 14, fontWeight: 500 }}>{p.description || `Pattern #${p.id}`}</div>
                                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                                        {p.rejection_reason && <span className="badge badge-danger" style={{ fontSize: 10, marginRight: 6 }}>{p.rejection_reason}</span>}
                                        {p.rejected_at && new Date(p.rejected_at).toLocaleDateString()}
                                    </div>
                                </div>
                                <button className="btn btn-secondary" style={{ fontSize: 12 }}
                                    onClick={() => reactivatePattern(p.id)}>
                                    <span className="mdi mdi-refresh" style={{ marginRight: 4 }} />
                                    {lang === 'de' ? 'Reaktivieren' : 'Reactivate'}
                                </button>
                            </div>
                        </div>
                    )) : <div className="empty-state"><span className="mdi mdi-check-circle" />
                        <h3>{lang === 'de' ? 'Keine abgelehnten Muster' : 'No Rejected Patterns'}</h3></div>}
                </div>

            ) : ptab === 'exclusions' ? (
                <div>
                    <button className="btn btn-primary" style={{ marginBottom: 16 }} onClick={() => setShowAddExcl(true)}>
                        <span className="mdi mdi-plus" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Ausschluss hinzufÃ¼gen' : 'Add Exclusion'}
                    </button>
                    {exclusions.length > 0 ? exclusions.map(e => (
                        <div key={e.id} className="card" style={{ marginBottom: 8, padding: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                                <div style={{ fontSize: 13 }}>
                                    <span style={{ fontWeight: 500 }}>{e.entity_a}</span>
                                    <span className="mdi mdi-link-off" style={{ margin: '0 8px', color: 'var(--danger)' }} />
                                    <span style={{ fontWeight: 500 }}>{e.entity_b}</span>
                                </div>
                                {e.reason && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{e.reason}</div>}
                            </div>
                            <button className="btn btn-ghost" onClick={async () => { await api.delete(`pattern-exclusions/${e.id}`); await load(); }}>
                                <span className="mdi mdi-delete" style={{ color: 'var(--danger)' }} />
                            </button>
                        </div>
                    )) : <div className="empty-state"><span className="mdi mdi-link-variant" />
                        <h3>{lang === 'de' ? 'Keine AusschlÃ¼sse' : 'No Exclusions'}</h3>
                        <p>{lang === 'de' ? 'Bestimme welche GerÃ¤te/RÃ¤ume nie verknÃ¼pft werden sollen.' : 'Define which devices/rooms should never be linked.'}</p></div>}

                    {showAddExcl && (
                        <Modal title={lang === 'de' ? 'Ausschluss erstellen' : 'Create Exclusion'} onClose={() => setShowAddExcl(false)}
                            actions={<><button className="btn btn-secondary" onClick={() => setShowAddExcl(false)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                                <button className="btn btn-primary" onClick={createExclusion}>{lang === 'de' ? 'Erstellen' : 'Create'}</button></>}>
                            <div className="input-group" style={{ marginBottom: 12 }}>
                                <Dropdown label={lang === 'de' ? 'Typ' : 'Type'} value={newExcl.type} onChange={v => setNewExcl({ ...newExcl, type: v, entity_a: '', entity_b: '' })}
                                    options={[{ value: 'device_pair', label: lang === 'de' ? 'GerÃ¤te-Paar' : 'Device Pair' }, { value: 'room_pair', label: lang === 'de' ? 'Raum-Paar' : 'Room Pair' }, { value: 'domain_pair', label: lang === 'de' ? 'Domain-Paar' : 'Domain Pair' }]} />
                            </div>
                            {newExcl.type === 'device_pair' ? (<>
                                <div className="input-group" style={{ marginBottom: 12 }}>
                                    <EntitySearchDropdown label={lang === 'de' ? 'GerÃ¤t A' : 'Device A'} value={newExcl.entity_a}
                                        onChange={v => setNewExcl({ ...newExcl, entity_a: v })}
                                        entities={devices.filter(d => d.ha_entity_id)} placeholder="light.living_room" />
                                </div>
                                <div className="input-group" style={{ marginBottom: 12 }}>
                                    <EntitySearchDropdown label={lang === 'de' ? 'GerÃ¤t B' : 'Device B'} value={newExcl.entity_b}
                                        onChange={v => setNewExcl({ ...newExcl, entity_b: v })}
                                        entities={devices.filter(d => d.ha_entity_id && d.ha_entity_id !== newExcl.entity_a)} />
                                </div>
                            </>) : newExcl.type === 'room_pair' ? (<>
                                <div className="input-group" style={{ marginBottom: 12 }}>
                                    <Dropdown label={lang === 'de' ? 'Raum A' : 'Room A'} value={newExcl.entity_a}
                                        onChange={v => setNewExcl({ ...newExcl, entity_a: v })}
                                        options={rooms.map(r => ({ value: String(r.id), label: r.name }))} />
                                </div>
                                <div className="input-group" style={{ marginBottom: 12 }}>
                                    <Dropdown label={lang === 'de' ? 'Raum B' : 'Room B'} value={newExcl.entity_b}
                                        onChange={v => setNewExcl({ ...newExcl, entity_b: v })}
                                        options={rooms.filter(r => String(r.id) !== newExcl.entity_a).map(r => ({ value: String(r.id), label: r.name }))} />
                                </div>
                            </>) : (<>
                                <div className="input-group" style={{ marginBottom: 12 }}>
                                    <Dropdown label="Domain A" value={newExcl.entity_a}
                                        onChange={v => setNewExcl({ ...newExcl, entity_a: v })}
                                        options={domains.map(d => ({ value: String(d.id), label: d.name }))} />
                                </div>
                                <div className="input-group" style={{ marginBottom: 12 }}>
                                    <Dropdown label="Domain B" value={newExcl.entity_b}
                                        onChange={v => setNewExcl({ ...newExcl, entity_b: v })}
                                        options={domains.filter(d => String(d.id) !== newExcl.entity_a).map(d => ({ value: String(d.id), label: d.name }))} />
                                </div>
                            </>)}
                            <div className="input-group">
                                <label className="input-label">{lang === 'de' ? 'Grund (optional)' : 'Reason (optional)'}</label>
                                <input className="input" value={newExcl.reason} onChange={e => setNewExcl({ ...newExcl, reason: e.target.value })} />
                            </div>
                        </Modal>
                    )}
                </div>

            ) : ptab === 'rules' ? (
                <div>
                    <button className="btn btn-primary" style={{ marginBottom: 16 }} onClick={() => setShowAddRule(true)}>
                        <span className="mdi mdi-plus" style={{ marginRight: 4 }} />
                        {lang === 'de' ? 'Regel erstellen' : 'Create Rule'}
                    </button>
                    {manualRules.length > 0 ? manualRules.map(r => (
                        <div key={r.id} className="card" style={{ marginBottom: 8, padding: 14 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <div>
                                    <div style={{ fontSize: 14, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}>
                                        {r.name}
                                        <span className={`badge badge-${r.is_active ? 'success' : 'secondary'}`} style={{ fontSize: 10 }}>
                                            {r.is_active ? (lang === 'de' ? 'Aktiv' : 'Active') : (lang === 'de' ? 'Pausiert' : 'Paused')}
                                        </span>
                                    </div>
                                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                                        {lang === 'de' ? 'Wenn' : 'If'} <strong>{r.trigger_entity}</strong> = {r.trigger_state}
                                        â†’ <strong>{r.action_entity}</strong> {r.action_service}
                                        {r.delay_seconds > 0 && ` (${r.delay_seconds}s ${lang === 'de' ? 'VerzÃ¶gerung' : 'delay'})`}
                                    </div>
                                    {r.execution_count > 0 && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                                        {r.execution_count}x {lang === 'de' ? 'ausgefÃ¼hrt' : 'executed'}
                                    </div>}
                                </div>
                                <div style={{ display: 'flex', gap: 4 }}>
                                    <button className="btn btn-ghost" onClick={async () => {
                                        await api.put(`manual-rules/${r.id}`, { is_active: !r.is_active }); await load();
                                    }}><span className={`mdi ${r.is_active ? 'mdi-pause' : 'mdi-play'}`} style={{ fontSize: 16 }} /></button>
                                    <button className="btn btn-ghost" onClick={async () => {
                                        await api.delete(`manual-rules/${r.id}`); await load();
                                    }}><span className="mdi mdi-delete" style={{ fontSize: 16, color: 'var(--danger)' }} /></button>
                                </div>
                            </div>
                        </div>
                    )) : <div className="empty-state"><span className="mdi mdi-pencil-ruler" />
                        <h3>{lang === 'de' ? 'Keine eigenen Regeln' : 'No Manual Rules'}</h3>
                        <p>{lang === 'de' ? 'Erstelle eigene Wenn-Dann Regeln.' : 'Create your own If-Then rules.'}</p></div>}

                    {showAddRule && (
                        <Modal title={lang === 'de' ? 'Regel erstellen' : 'Create Rule'} onClose={() => setShowAddRule(false)}
                            actions={<><button className="btn btn-secondary" onClick={() => setShowAddRule(false)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                                <button className="btn btn-primary" onClick={createRule}>{lang === 'de' ? 'Erstellen' : 'Create'}</button></>}>
                            <div className="input-group" style={{ marginBottom: 12 }}>
                                <label className="input-label">{lang === 'de' ? 'Name' : 'Name'}</label>
                                <input className="input" value={newRule.name} onChange={e => setNewRule({ ...newRule, name: e.target.value })}
                                    placeholder={lang === 'de' ? 'z.B. Flurlicht bei HaustÃ¼r' : 'e.g. Hall light on door open'} autoFocus />
                            </div>
                            <div className="input-group" style={{ marginBottom: 12 }}>
                                <EntitySearchDropdown
                                    label={lang === 'de' ? 'Wenn (Entity)' : 'When (Entity)'}
                                    value={newRule.trigger_entity}
                                    onChange={v => setNewRule({ ...newRule, trigger_entity: v })}
                                    entities={devices.filter(d => d.ha_entity_id)}
                                    placeholder="binary_sensor.front_door" />
                            </div>
                            <div className="input-group" style={{ marginBottom: 12 }}>
                                <label className="input-label">{lang === 'de' ? 'Status wird' : 'State becomes'}</label>
                                <input className="input" value={newRule.trigger_state} onChange={e => setNewRule({ ...newRule, trigger_state: e.target.value })}
                                    placeholder="on" />
                            </div>
                            <div className="input-group" style={{ marginBottom: 12 }}>
                                <EntitySearchDropdown
                                    label={lang === 'de' ? 'Dann (Entity)' : 'Then (Entity)'}
                                    value={newRule.action_entity}
                                    onChange={v => setNewRule({ ...newRule, action_entity: v })}
                                    entities={devices.filter(d => d.ha_entity_id)}
                                    placeholder="light.hallway" />
                            </div>
                            <div className="input-group">
                                <Dropdown label={lang === 'de' ? 'Aktion' : 'Action'} value={newRule.action_service}
                                    onChange={v => setNewRule({ ...newRule, action_service: v })}
                                    options={[{ value: 'turn_on', label: lang === 'de' ? 'Einschalten' : 'Turn On' },
                                        { value: 'turn_off', label: lang === 'de' ? 'Ausschalten' : 'Turn Off' },
                                        { value: 'toggle', label: 'Toggle' }]} />
                            </div>
                        </Modal>
                    )}
                </div>
            ) : (<div>
            {/* Learning Stats Overview */}
            {(() => {
                const s = stats || {};
                return (
                <div className="stat-grid" style={{ marginBottom: 24 }}>
                    <div className="stat-card animate-in">
                        <div className="stat-icon" style={{ background: 'var(--accent-primary-dim)', color: 'var(--accent-primary)' }}>
                            <span className="mdi mdi-database-outline" />
                        </div>
                        <div>
                            <div className="stat-value">{s.total_events?.toLocaleString() || 0}</div>
                            <div className="stat-label">{lang === 'de' ? 'Events gesammelt' : 'Events collected'}</div>
                        </div>
                    </div>
                    <div className="stat-card animate-in animate-in-delay-1">
                        <div className="stat-icon" style={{ background: 'var(--success-dim)', color: 'var(--success)' }}>
                            <span className="mdi mdi-lightbulb-on" />
                        </div>
                        <div>
                            <div className="stat-value">{s.total_patterns || 0}</div>
                            <div className="stat-label">{lang === 'de' ? 'Muster erkannt' : 'Patterns found'}</div>
                        </div>
                    </div>
                    <div className="stat-card animate-in animate-in-delay-2">
                        <div className="stat-icon" style={{ background: 'var(--warning-dim)', color: 'var(--warning)' }}>
                            <span className="mdi mdi-calendar-range" />
                        </div>
                        <div>
                            <div className="stat-value">{stats.days_collecting || 0}</div>
                            <div className="stat-label">{lang === 'de' ? 'Tage Daten' : 'Days of data'}</div>
                        </div>
                    </div>
                    <div className="stat-card animate-in animate-in-delay-3">
                        <div className="stat-icon" style={{ background: 'var(--info-dim)', color: 'var(--info)' }}>
                            <span className="mdi mdi-speedometer" />
                        </div>
                        <div>
                            <div className="stat-value">{s.avg_confidence ? `${Math.round(s.avg_confidence * 100)}%` : 'â€”'}</div>
                            <div className="stat-label">{lang === 'de' ? 'Ã˜ Vertrauen' : 'Avg Confidence'}</div>
                        </div>
                    </div>
                </div>
                );
            })()}

            {/* Learning Speed Control */}
            <div className="card animate-in" style={{ marginBottom: 16, padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                <div>
                    <span className="mdi mdi-speedometer" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                    <span style={{ fontSize: 14, fontWeight: 500 }}>{lang === 'de' ? 'Lerngeschwindigkeit' : 'Learning Speed'}</span>
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                    {[{ id: 'conservative', label: lang === 'de' ? 'Vorsichtig' : 'Conservative', icon: 'ðŸ¢' },
                      { id: 'normal', label: 'Normal', icon: 'âš–ï¸' },
                      { id: 'aggressive', label: lang === 'de' ? 'Aggressiv' : 'Aggressive', icon: 'ðŸš€' }].map(s => (
                        <button key={s.id} className={`btn btn-sm ${(stats?.learning_speed || 'normal') === s.id ? 'btn-primary' : 'btn-ghost'}`}
                            onClick={async () => {
                                try {
                                    await api.put('phases/speed', { speed: s.id });
                                    showToast(`${s.icon} ${s.label}`, 'success');
                                    // Force immediate UI update
                                    setStats(prev => prev ? { ...prev, learning_speed: s.id } : prev);
                                    await load();
                                } catch(e) { showToast('Fehler', 'error'); }
                            }} style={{ fontSize: 12 }}>
                            {s.icon} {s.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Pattern Type Distribution */}
            {stats && stats.patterns_by_type && (
                <div className="card animate-in" style={{ marginBottom: 24, padding: 16 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                        <div className="card-title">{lang === 'de' ? 'Muster-Verteilung' : 'Pattern Distribution'}</div>
                        <button className="btn btn-sm btn-primary" onClick={triggerAnalysis} disabled={analyzing}>
                            <span className={`mdi ${analyzing ? 'mdi-loading mdi-spin' : 'mdi-magnify'}`} style={{ marginRight: 6 }} />
                            {analyzing ? (lang === 'de' ? 'Analysiere...' : 'Analyzing...') : (lang === 'de' ? 'Jetzt analysieren' : 'Analyze now')}
                        </button>
                    </div>
                    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                        {Object.entries(stats.patterns_by_type).map(([type, count]) => (
                            <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px', background: 'var(--bg-tertiary)', borderRadius: 8 }}>
                                <span className={`mdi ${typeIcons[type]}`} style={{ fontSize: 18, color: 'var(--accent-primary)' }} />
                                <span style={{ fontWeight: 600 }}>{count}</span>
                                <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{typeLabels[type]}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Filter Bar */}
            <div className="card" style={{ padding: 12, marginBottom: 16 }}>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                    <span style={{ fontSize: 13, color: 'var(--text-secondary)', marginRight: 4 }}>
                        {lang === 'de' ? 'Typ:' : 'Type:'}
                    </span>
                    {['all', 'time_based', 'event_chain', 'correlation'].map(f => (
                        <button key={f} className={`btn btn-sm ${filter === f ? 'btn-primary' : 'btn-ghost'}`}
                                onClick={() => setFilter(f)}>
                            {f === 'all' ? (lang === 'de' ? 'Alle' : 'All') : typeLabels[f]}
                        </button>
                    ))}
                    <span style={{ borderLeft: '1px solid var(--border-color)', height: 20, margin: '0 8px' }} />
                    <span style={{ fontSize: 13, color: 'var(--text-secondary)', marginRight: 4 }}>Status:</span>
                    {['', 'observed', 'suggested', 'active', 'disabled'].map(s => (
                        <button key={s} className={`btn btn-sm ${statusFilter === s ? 'btn-primary' : 'btn-ghost'}`}
                                onClick={() => setStatusFilter(s)}>
                            {s === '' ? (lang === 'de' ? 'Alle' : 'All') : statusLabels[s]}
                        </button>
                    ))}

                    {viewMode === 'advanced' && (
                        <>
                            <span style={{ borderLeft: '1px solid var(--border-color)', height: 20, margin: '0 8px' }} />
                            <button className={`btn btn-sm ${showHistory ? 'btn-primary' : 'btn-ghost'}`}
                                    onClick={() => { setShowHistory(!showHistory); if (!showHistory) loadHistory(historyEntity); }}>
                                <span className="mdi mdi-history" style={{ marginRight: 4 }} />
                                {lang === 'de' ? 'Event-Verlauf' : 'Event History'}
                            </button>
                        </>
                    )}
                </div>
            </div>

            {/* State History Viewer (Advanced only) */}
            {showHistory && viewMode === 'advanced' && (
                <div className="card animate-in" style={{ marginBottom: 16 }}>
                    <div className="card-header">
                        <div className="card-title">
                            <span className="mdi mdi-history" style={{ marginRight: 8 }} />
                            {lang === 'de' ? 'Event-Verlauf (48h)' : 'Event History (48h)'}
                        </div>
                        <input type="text" placeholder={lang === 'de' ? 'Entity filtern...' : 'Filter entity...'}
                               value={historyEntity}
                               onChange={e => { setHistoryEntity(e.target.value); loadHistory(e.target.value); }}
                               style={{ width: 220, padding: '6px 10px', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', borderRadius: 6, color: 'var(--text-primary)', fontSize: 13 }} />
                    </div>
                    <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                        <table className="data-table" style={{ fontSize: 12 }}>
                            <thead>
                                <tr>
                                    <th>{lang === 'de' ? 'Zeit' : 'Time'}</th>
                                    <th>Entity</th>
                                    <th>{lang === 'de' ? 'Alt â†’ Neu' : 'Old â†’ New'}</th>
                                    <th>{lang === 'de' ? 'Kontext' : 'Context'}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {stateHistory.map(ev => (
                                    <tr key={ev.id}>
                                        <td style={{ whiteSpace: 'nowrap' }}>{ev.created_at ? new Date(ev.created_at).toLocaleTimeString() : 'â€”'}</td>
                                        <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{ev.entity_id}</td>
                                        <td>
                                            <span style={{ color: 'var(--text-muted)' }}>{ev.old_state || '?'}</span>
                                            <span style={{ margin: '0 4px' }}>â†’</span>
                                            <span style={{ fontWeight: 600, color: ev.new_state === 'on' ? 'var(--success)' : ev.new_state === 'off' ? 'var(--text-muted)' : 'var(--text-primary)' }}>
                                                {ev.new_state}
                                            </span>
                                        </td>
                                        <td style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                            {ev.context?.time_slot} {ev.context?.persons_home?.length > 0 ? `ðŸ‘¤${ev.context.persons_home.length}` : ''}
                                        </td>
                                    </tr>
                                ))}
                                {stateHistory.length === 0 && (
                                    <tr><td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 20 }}>
                                        {lang === 'de' ? 'Noch keine Events gesammelt' : 'No events collected yet'}
                                    </td></tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Pattern List */}
            {/* #26 Pattern Conflict Warning */}
            {conflicts.length > 0 && (
                <div className="card animate-in" style={{ marginBottom: 16, borderLeft: '3px solid var(--warning)', padding: '12px 16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                        <span className="mdi mdi-alert" style={{ color: 'var(--warning)', fontSize: 18 }} />
                        <strong style={{ fontSize: 14 }}>{lang === 'de' ? `${conflicts.length} Muster-Konflikte` : `${conflicts.length} Pattern Conflicts`}</strong>
                    </div>
                    {conflicts.slice(0, 3).map((c, i) => (
                        <div key={i} style={{ fontSize: 12, color: 'var(--text-secondary)', padding: '4px 0' }}>
                            {c.message_de || c.message_en || c.description || `${c.pattern_a?.desc || c.pattern_a?.id || '?'} â†” ${c.pattern_b?.desc || c.pattern_b?.id || '?'}`}
                        </div>
                    ))}
                </div>
            )}

            <div className="card animate-in">
                <div className="card-header">
                    <div>
                        <div className="card-title">
                            {lang === 'de' ? 'Erkannte Muster' : 'Detected Patterns'}
                            <span className="badge badge-info" style={{ marginLeft: 8 }}>{filtered.length}</span>
                        </div>
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                        <button className={`btn btn-sm ${bulkMode ? 'btn-primary' : 'btn-ghost'}`}
                            onClick={() => { setBulkMode(!bulkMode); setBulkSelected({}); }}>
                            <span className="mdi mdi-checkbox-multiple-marked-outline" style={{ marginRight: 4 }} />
                            {lang === 'de' ? 'Mehrfachauswahl' : 'Multi-select'}
                        </button>
                    </div>
                </div>

                {/* Bulk Action Bar */}
                {bulkMode && Object.values(bulkSelected).some(v => v) && (() => {
                    const selectedIds = Object.entries(bulkSelected).filter(([_, v]) => v).map(([k]) => parseInt(k));
                    const count = selectedIds.length;
                    return (
                        <div style={{ padding: '10px 16px', background: 'var(--accent-primary-dim)', borderBottom: '1px solid var(--border)',
                            display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                            <span style={{ fontSize: 13, fontWeight: 500, marginRight: 8 }}>
                                {count} {lang === 'de' ? 'ausgewÃ¤hlt' : 'selected'}
                            </span>
                            <button className="btn btn-sm btn-ghost" onClick={async () => {
                                setPatterns(prev => prev.filter(p => !selectedIds.includes(p.id)));
                                for (const id of selectedIds) { await api.put(`patterns/reject/${id}`, { reason: 'bulk' }); }
                                setBulkSelected({}); setBulkMode(false); await load();
                                showToast(`${count} ${lang === 'de' ? 'Muster abgelehnt' : 'patterns rejected'}`, 'success');
                            }}>
                                <span className="mdi mdi-close-circle" style={{ marginRight: 4, color: 'var(--warning)' }} />
                                {lang === 'de' ? 'Alle ablehnen' : 'Reject all'}
                            </button>
                            <button className="btn btn-sm btn-ghost" onClick={async () => {
                                setPatterns(prev => prev.filter(p => !selectedIds.includes(p.id)));
                                for (const id of selectedIds) { await api.delete(`patterns/${id}`); }
                                setBulkSelected({}); setBulkMode(false); await load();
                                showToast(`${count} ${lang === 'de' ? 'Muster gelÃ¶scht' : 'patterns deleted'}`, 'success');
                            }}>
                                <span className="mdi mdi-delete" style={{ marginRight: 4, color: 'var(--danger)' }} />
                                {lang === 'de' ? 'Alle lÃ¶schen' : 'Delete all'}
                            </button>
                            <button className="btn btn-sm btn-ghost" onClick={() => {
                                const all = {};
                                filtered.forEach(p => all[p.id] = true);
                                setBulkSelected(all);
                            }}>
                                {lang === 'de' ? 'Alle auswÃ¤hlen' : 'Select all'}
                            </button>
                            <button className="btn btn-sm btn-ghost" onClick={() => setBulkSelected({})}>
                                {lang === 'de' ? 'Auswahl aufheben' : 'Deselect'}
                            </button>
                        </div>
                    );
                })()}

                {filtered.length === 0 ? (
                    <div className="empty-state">
                        <span className="mdi mdi-lightbulb-on" />
                        <h3>{lang === 'de' ? 'Noch keine Muster' : 'No patterns yet'}</h3>
                        <p>{lang === 'de'
                            ? 'MindHome sammelt Daten und analysiert regelmÃ¤ÃŸig. Muster erscheinen nach einigen Tagen.'
                            : 'MindHome collects data and analyzes regularly. Patterns will appear after a few days.'}</p>
                        <button className="btn btn-primary" onClick={triggerAnalysis} disabled={analyzing}>
                            <span className="mdi mdi-magnify" style={{ marginRight: 6 }} />
                            {lang === 'de' ? 'Jetzt analysieren' : 'Analyze now'}
                        </button>
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        {filtered.map(p => (
                            <div key={p.id}>
                            <div style={{
                                padding: '14px 16px',
                                borderBottom: expandedId === p.id ? 'none' : '1px solid var(--border-color)',
                                display: 'flex', alignItems: 'center', gap: 12,
                                opacity: p.status === 'disabled' ? 0.5 : 1,
                                cursor: 'pointer', transition: 'background 0.15s',
                            }} onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
                               onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-tertiary)'}
                               onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                                {/* #16 Bulk checkbox */}
                                {bulkMode && (
                                    <input type="checkbox" checked={!!bulkSelected[p.id]}
                                        onClick={e => e.stopPropagation()}
                                        onChange={e => setBulkSelected(prev => ({ ...prev, [p.id]: e.target.checked }))}
                                        style={{ width: 16, height: 16, accentColor: 'var(--accent-primary)', flexShrink: 0 }} />
                                )}
                                {/* Type icon */}
                                <span className={`mdi ${typeIcons[p.pattern_type]}`}
                                      style={{ fontSize: 22, color: 'var(--accent-primary)', flexShrink: 0 }} />

                                {/* Description */}
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontWeight: 500, fontSize: 14, marginBottom: 4 }}>
                                        {p.description || p.pattern_type}
                                    </div>
                                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 12 }}>
                                        <span className={`badge badge-${statusColors[p.status]}`} style={{ fontSize: 11 }}>
                                            {statusLabels[p.status]}
                                        </span>
                                        <span style={{ color: 'var(--text-muted)' }}>
                                            {typeLabels[p.pattern_type]}
                                        </span>
                                        <span style={{ color: 'var(--text-muted)' }}>
                                            {p.match_count}Ã— {lang === 'de' ? 'erkannt' : 'matched'}
                                        </span>
                                    </div>
                                </div>

                                {/* Vertrauen/Confidence bar */}
                                <div style={{ width: 80, flexShrink: 0 }}>
                                    <div style={{ fontSize: 12, textAlign: 'center', marginBottom: 4, fontWeight: 600 }}>
                                        {Math.round(p.confidence * 100)}%
                                    </div>
                                    <div style={{ height: 4, background: 'var(--bg-tertiary)', borderRadius: 2, overflow: 'hidden' }}>
                                        <div style={{
                                            height: '100%', borderRadius: 2, width: `${Math.round(p.confidence * 100)}%`,
                                            background: p.confidence > 0.7 ? 'var(--success)' : p.confidence > 0.4 ? 'var(--warning)' : 'var(--danger)',
                                        }} />
                                    </div>
                                </div>

                                {/* Actions */}
                                <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                                    {p.status === 'disabled' ? (
                                        <button className="btn btn-sm btn-ghost" onClick={() => togglePattern(p.id, 'observed')}
                                                title={lang === 'de' ? 'Reaktivieren' : 'Reactivate'}>
                                            <span className="mdi mdi-refresh" />
                                        </button>
                                    ) : (
                                        <button className="btn btn-sm btn-ghost" onClick={() => togglePattern(p.id, 'disabled')}
                                                title={lang === 'de' ? 'Deaktivieren' : 'Disable'}>
                                            <span className="mdi mdi-pause" />
                                        </button>
                                    )}
                                    <button className="btn btn-sm btn-ghost" style={{ color: 'var(--danger)' }}
                                            onClick={() => setConfirmDel(p.id)}
                                            title={lang === 'de' ? 'LÃ¶schen' : 'Delete'}>
                                        <span className="mdi mdi-delete" />
                                    </button>
                                </div>
                            </div>

                            {/* Detail panel (expanded) */}
                            {expandedId === p.id && (
                                <div style={{
                                    padding: '12px 16px 16px 50px', borderBottom: '1px solid var(--border-color)',
                                    background: 'var(--bg-tertiary)', fontSize: 13,
                                }}>
                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 24px', marginBottom: 12 }}>
                                        <div><span style={{ color: 'var(--text-muted)' }}>Entity:</span> <code style={{ fontSize: 12 }}>{p.pattern_data?.entity_id || p.pattern_data?.action_entity || 'â€“'}</code></div>
                                        <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Zielzustand' : 'Target'}:</span> <strong>{p.pattern_data?.target_state || p.action_definition?.target_state || 'â€“'}</strong></div>
                                        {p.pattern_data?.avg_hour !== undefined && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Uhrzeit' : 'Time'}:</span> <strong>{String(p.pattern_data.avg_hour).padStart(2,'0')}:{String(p.pattern_data.avg_minute||0).padStart(2,'0')}</strong> Â±{p.pattern_data.time_window_min || 15}min</div>
                                        )}
                                        {p.pattern_data?.weekday_filter && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Tage' : 'Days'}:</span> {p.pattern_data.weekday_filter === 'weekdays' ? (lang === 'de' ? 'Moâ€“Fr' : 'Monâ€“Fri') : p.pattern_data.weekday_filter === 'weekends' ? (lang === 'de' ? 'Saâ€“So' : 'Satâ€“Sun') : (lang === 'de' ? 'Alle' : 'All')}</div>
                                        )}
                                        {p.pattern_data?.sun_relative_elevation != null && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Sonnenstand' : 'Sun elevation'}:</span> {p.pattern_data.sun_relative_elevation}Â°</div>
                                        )}
                                        {p.pattern_data?.trigger_entity && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>Trigger:</span> <code style={{ fontSize: 12 }}>{p.pattern_data.trigger_entity}</code> â†’ {p.pattern_data.trigger_state}</div>
                                        )}
                                        {p.pattern_data?.avg_delay_sec && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'VerzÃ¶gerung' : 'Delay'}:</span> {p.pattern_data.avg_delay_sec < 60 ? `${Math.round(p.pattern_data.avg_delay_sec)}s` : `${Math.round(p.pattern_data.avg_delay_sec/60)} min`}</div>
                                        )}
                                        <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Beobachtet' : 'Observed'}:</span> {p.pattern_data?.days_observed || 0} {lang === 'de' ? 'Tage' : 'days'}, {p.pattern_data?.occurrence_count || p.match_count || 0}Ã— {lang === 'de' ? 'Treffer' : 'matches'}</div>
                                        <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Erstellt' : 'Created'}:</span> {p.created_at ? new Date(p.created_at).toLocaleDateString() : 'â€“'}</div>
                                        {/* #51 Confidence Explanation */}
                                        <div style={{ marginTop: 6, padding: '6px 10px', background: 'var(--bg-primary)', borderRadius: 6, fontSize: 11 }}>
                                            <span className="mdi mdi-information" style={{ marginRight: 4, color: 'var(--info)' }} />
                                            {p.confidence >= 0.8 ? (lang === 'de' ? 'Hohe Konfidenz: Muster wurde hÃ¤ufig und konsistent beobachtet.' : 'High confidence: Pattern observed frequently and consistently.')
                                            : p.confidence >= 0.5 ? (lang === 'de' ? 'Mittlere Konfidenz: Muster zeigt sich regelmÃ¤ÃŸig, aber mit Abweichungen.' : 'Medium confidence: Pattern appears regularly but with variations.')
                                            : (lang === 'de' ? 'Niedrige Konfidenz: Noch zu wenige Daten fÃ¼r eine sichere Aussage.' : 'Low confidence: Not enough data for reliable prediction.')}
                                            {p.match_count > 0 && ` (${p.match_count} ${lang === 'de' ? 'Treffer' : 'matches'})`}
                                        </div>
                                    </div>
                                    {p.trigger_conditions && (
                                        <details style={{ marginTop: 4 }}>
                                            <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: 12 }}>
                                                {lang === 'de' ? 'Technische Details (JSON)' : 'Technical details (JSON)'}
                                            </summary>
                                            <pre style={{ fontSize: 11, marginTop: 4, padding: 8, background: 'var(--bg-primary)', borderRadius: 4, overflow: 'auto', maxHeight: 120 }}>{JSON.stringify({ trigger: p.trigger_conditions, action: p.action_definition }, null, 2)}</pre>
                                        </details>
                                    )}
                                    {/* Test mode + Reject */}
                                    <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                                        <button className={`btn btn-sm ${p.test_mode ? 'btn-warning' : 'btn-ghost'}`}
                                            onClick={async (e) => { e.stopPropagation();
                                                await api.put(`patterns/test-mode/${p.id}`, { enabled: !p.test_mode });
                                                showToast(p.test_mode ? (lang === 'de' ? 'Testmodus deaktiviert' : 'Test mode off') : (lang === 'de' ? 'Testmodus aktiviert' : 'Test mode on'), 'success');
                                                await load(); }} style={{ fontSize: 11 }}>
                                            <span className="mdi mdi-flask" style={{ marginRight: 4 }} />
                                            {p.test_mode ? (lang === 'de' ? 'Test lÃ¤uft' : 'Testing') : (lang === 'de' ? 'Testlauf' : 'Test Run')}
                                        </button>
                                        {p.status !== 'rejected' && (
                                            <button className="btn btn-sm btn-ghost" onClick={(e) => { e.stopPropagation(); setRejectReason(p.id); }}
                                                style={{ fontSize: 11, color: 'var(--danger)' }}>
                                                <span className="mdi mdi-close-circle" style={{ marginRight: 4 }} />
                                                {lang === 'de' ? 'Ablehnen' : 'Reject'}
                                            </button>
                                        )}
                                        {p.season && <span className="badge badge-info" style={{ fontSize: 10 }}>ðŸŒ¿ {p.season}</span>}
                                        {p.category && <span className="badge badge-secondary" style={{ fontSize: 10 }}>{p.category}</span>}
                                    </div>
                                </div>
                            )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
            </div>)}

            {/* Confirm delete */}
            {confirmDel && (
                <ConfirmDialog
                    title={lang === 'de' ? 'Muster lÃ¶schen?' : 'Delete pattern?'}
                    message={lang === 'de' ? 'Das Muster wird unwiderruflich gelÃ¶scht.' : 'The pattern will be permanently deleted.'}
                    onConfirm={() => deletePattern(confirmDel)}
                    onCancel={() => setConfirmDel(null)}
                />
            )}

            {/* Reject reason modal */}
            {rejectReason && (
                <Modal title={lang === 'de' ? 'Ablehnungsgrund' : 'Rejection Reason'} onClose={() => setRejectReason(null)}
                    actions={<button className="btn btn-secondary" onClick={() => setRejectReason(null)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>}>
                    {[{ id: 'coincidence', label: lang === 'de' ? 'Zufall' : 'Coincidence' },
                      { id: 'unwanted', label: lang === 'de' ? 'Will ich nicht' : 'Unwanted' },
                      { id: 'wrong', label: lang === 'de' ? 'Falsch erkannt' : 'Wrong detection' }].map(r => (
                        <button key={r.id} className="btn btn-secondary" style={{ display: 'block', width: '100%', marginBottom: 8, textAlign: 'left' }}
                            onClick={() => rejectPattern(rejectReason, r.id)}>
                            {r.label}
                        </button>
                    ))}
                </Modal>
            )}
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Phase 2b: Notifications Page
// ================================================================

const NotificationsPage = () => {
    const { lang, showToast, devices, users } = useApp();
    const [notifications, setNotifications] = useState([]);
    const [loading, setLoading] = useState(true);
    const [predictions, setPredictions] = useState([]);
    const [predFilter, setPredFilter] = useState('all');
    const [tab, setTab] = useState('inbox');
    const [notifSettings, setNotifSettings] = useState(null);
    const [stats, setStats] = useState(null);
    const [extSettings, setExtSettings] = useState(null);
    const [ttsDevices, setTtsDevices] = useState([]);

    const load = async () => {
        try {
            const [notifs, preds, ns, st, ext, tts] = await Promise.all([
                api.get('notifications?limit=100'),
                api.get('predictions?limit=50'),
                api.get('notification-settings'),
                api.get('notification-stats'),
                api.get('notification-settings/extended'),
                api.get('tts/devices'),
            ]);
            setNotifications(notifs);
            setPredictions(preds);
            setNotifSettings(ns);
            setStats(st);
            if (ext) setExtSettings(ext);
            if (tts) setTtsDevices(tts);
        } catch (e) { console.error(e); }
        setLoading(false);
    };

    useEffect(() => { load(); }, []);

    const markRead = async (id) => {
        await api.post(`notifications/${id}/read`);
        setNotifications(n => n.map(x => x.id === id ? { ...x, was_read: true } : x));
    };

    const markAllRead = async () => {
        await api.post('notifications/mark-all-read');
        setNotifications(n => n.map(x => ({ ...x, was_read: true })));
        showToast(lang === 'de' ? 'Alle gelesen' : 'All read', 'success');
    };

    const confirmPred = async (id) => {
        await api.post(`predictions/${id}/confirm`);
        showToast(lang === 'de' ? 'Aktiviert!' : 'Activated!', 'success');
        await load();
    };

    const rejectPred = async (id) => {
        await api.post(`predictions/${id}/reject`);
        showToast(lang === 'de' ? 'Abgelehnt' : 'Rejected', 'info');
        await load();
    };

    const undoPred = async (id) => {
        const result = await api.post(`predictions/${id}/undo`);
        if (result.error) {
            showToast(result.error, 'error');
        } else {
            showToast(lang === 'de' ? 'RÃ¼ckgÃ¤ngig gemacht' : 'Undone', 'success');
            await load();
        }
    };

    const filteredPreds = predictions.filter(p => {
        if (predFilter === 'all') return true;
        return p.status === predFilter;
    });

    const typeIcons = {
        suggestion: 'mdi-lightbulb-on',
        anomaly: 'mdi-alert-circle',
        critical: 'mdi-alert-octagon',
        info: 'mdi-information',
    };

    const statusColors = {
        pending: 'warning', confirmed: 'success', rejected: 'danger',
        executed: 'info', undone: 'warning', ignored: 'secondary',
    };

    if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><span className="mdi mdi-loading mdi-spin" style={{ fontSize: 32 }} /></div>;

    const toggleDND = async () => {
        const newVal = !notifSettings?.dnd_enabled;
        await api.put('notification-settings/dnd', { enabled: newVal });
        setNotifSettings(s => ({ ...s, dnd_enabled: newVal }));
        showToast(newVal ? (lang === 'de' ? 'Nicht stÃ¶ren aktiviert' : 'DND enabled') : (lang === 'de' ? 'Nicht stÃ¶ren deaktiviert' : 'DND disabled'), 'success');
    };

    const updateNS = async (type, field, value) => {
        await api.put('notification-settings', { type, [field]: value });
        await load();
    };

    const discoverChannels = async () => {
        const result = await api.post('notification-settings/discover-channels');
        showToast(result?.found > 0 ? `${result.found} ${lang === 'de' ? 'KanÃ¤le gefunden' : 'channels found'}` : (lang === 'de' ? 'Keine neuen KanÃ¤le' : 'No new channels'), result?.found > 0 ? 'success' : 'info');
        await load();
    };

    return (
        <div>
            {/* Tab bar + DND */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
                <div style={{ display: 'flex', gap: 4 }}>
                    {[{ id: 'inbox', label: lang === 'de' ? 'Posteingang' : 'Inbox', icon: 'mdi-bell' },
                      { id: 'settings', label: lang === 'de' ? 'Einstellungen' : 'Settings', icon: 'mdi-cog' }].map(t => (
                        <button key={t.id} className={`btn ${tab === t.id ? 'btn-primary' : 'btn-ghost'}`}
                            style={{ fontSize: 13, padding: '6px 14px' }} onClick={() => setTab(t.id)}>
                            <span className={`mdi ${t.icon}`} style={{ marginRight: 6 }} />{t.label}
                        </button>
                    ))}
                </div>
                <button className={`btn ${notifSettings?.dnd_enabled ? 'btn-warning' : 'btn-ghost'}`}
                    onClick={toggleDND} style={{ fontSize: 12, padding: '6px 12px' }}>
                    <span className="mdi mdi-bell-off" style={{ marginRight: 4 }} />DND
                </button>
            </div>

            {stats && <div style={{ display: 'flex', gap: 12, marginBottom: 16, fontSize: 12, color: 'var(--text-muted)' }}>
                <span>30d:</span><span>{stats.total} {lang === 'de' ? 'gesamt' : 'total'}</span>
                <span>Â· {stats.read} {lang === 'de' ? 'gelesen' : 'read'}</span>
                <span>Â· {stats.sent} push</span>
            </div>}

            {tab === 'settings' ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
                    {/* LEFT COLUMN */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                        {/* Types with channel + sound */}
                        <div className="card">
                            <div className="card-title" style={{ marginBottom: 12 }}>{lang === 'de' ? 'Typen' : 'Types'}</div>
                            {['anomaly', 'suggestion', 'critical', 'info'].map(type => {
                                const s = notifSettings?.settings?.find(x => x.type === type);
                                const labels = { anomaly: lang === 'de' ? 'Anomalien' : 'Anomalies', suggestion: lang === 'de' ? 'VorschlÃ¤ge' : 'Suggestions', critical: lang === 'de' ? 'Kritisch' : 'Critical', info: 'Info' };
                                const typeSound = extSettings?.type_sounds?.[type];
                                return (<div key={type} style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                        <span style={{ fontSize: 13 }}>{labels[type]}</span>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                            <button className={`btn btn-sm ${typeSound !== false ? 'btn-ghost' : 'btn-ghost'}`}
                                                onClick={async () => {
                                                    const sounds = { ...(extSettings?.type_sounds || {}), [type]: !typeSound };
                                                    setExtSettings(prev => ({ ...prev, type_sounds: sounds }));
                                                    await api.put('notification-settings/extended', { type_sounds: sounds });
                                                }} title={lang === 'de' ? 'Ton' : 'Sound'} style={{ padding: '2px 4px' }}>
                                                <span className={`mdi ${typeSound !== false ? 'mdi-volume-high' : 'mdi-volume-off'}`} style={{ color: typeSound !== false ? 'var(--accent-primary)' : 'var(--text-muted)', fontSize: 14 }} />
                                            </button>
                                            <label className="toggle"><input type="checkbox" checked={s?.enabled !== false}
                                                onChange={async () => { await api.put(`notification-settings/${type}`, { enabled: !s?.enabled }); await load(); }} /><div className="toggle-slider" /></label>
                                        </div>
                                    </div>
                                </div>);
                            })}
                        </div>

                        {/* Quiet Hours Extended */}
                        <div className="card">
                            <div className="card-title" style={{ marginBottom: 12 }}>
                                <span className="mdi mdi-moon-waning-crescent" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                                {lang === 'de' ? 'Ruhezeiten' : 'Quiet Hours'}
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>{lang === 'de' ? 'Kein Push in diesem Zeitraum (auÃŸer Kritisch)' : 'No push during this period (except Critical)'}</div>
                            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                                <div style={{ fontSize: 12 }}>{lang === 'de' ? 'Werktag' : 'Weekday'}:</div>
                                <input type="time" className="input" value={extSettings?.quiet_hours?.start || '22:00'} style={{ width: 90, padding: '4px 8px', fontSize: 12 }}
                                    onChange={async (e) => { const qh = { ...extSettings?.quiet_hours, start: e.target.value }; setExtSettings(prev => ({ ...prev, quiet_hours: qh })); await api.put('notification-settings/extended', { quiet_hours: qh }); }} />
                                <span>â€“</span>
                                <input type="time" className="input" value={extSettings?.quiet_hours?.end || '07:00'} style={{ width: 90, padding: '4px 8px', fontSize: 12 }}
                                    onChange={async (e) => { const qh = { ...extSettings?.quiet_hours, end: e.target.value }; setExtSettings(prev => ({ ...prev, quiet_hours: qh })); await api.put('notification-settings/extended', { quiet_hours: qh }); }} />
                            </div>
                            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                                <div style={{ fontSize: 12 }}>{lang === 'de' ? 'Wochenende' : 'Weekend'}:</div>
                                <input type="time" className="input" value={extSettings?.quiet_hours?.weekend_start || '23:00'} style={{ width: 90, padding: '4px 8px', fontSize: 12 }}
                                    onChange={async (e) => { const qh = { ...extSettings?.quiet_hours, weekend_start: e.target.value }; setExtSettings(prev => ({ ...prev, quiet_hours: qh })); await api.put('notification-settings/extended', { quiet_hours: qh }); }} />
                                <span>â€“</span>
                                <input type="time" className="input" value={extSettings?.quiet_hours?.weekend_end || '09:00'} style={{ width: 90, padding: '4px 8px', fontSize: 12 }}
                                    onChange={async (e) => { const qh = { ...extSettings?.quiet_hours, weekend_end: e.target.value }; setExtSettings(prev => ({ ...prev, quiet_hours: qh })); await api.put('notification-settings/extended', { quiet_hours: qh }); }} />
                            </div>
                        </div>

                        {/* Extended Settings */}
                        <div className="card">
                            <div className="card-title" style={{ marginBottom: 12 }}>
                                <span className="mdi mdi-tune" style={{ marginRight: 8, color: 'var(--accent-primary)' }} />
                                {lang === 'de' ? 'Erweiterte Einstellungen' : 'Extended Settings'}
                            </div>
                            {[
                                { key: 'escalation', icon: 'mdi-arrow-up-bold', de: 'Eskalation (Push â†’ TTS)', en: 'Escalation (Push â†’ TTS)' },
                                { key: 'repeat_rules', icon: 'mdi-repeat', de: 'Wiederholung bei Nichtlesen', en: 'Repeat if unread' },
                                { key: 'confirmation_required', icon: 'mdi-check-decagram', de: 'BestÃ¤tigungspflicht (Kritisch)', en: 'Confirmation required (Critical)' },
                                { key: 'critical_override', icon: 'mdi-alert-octagon', de: 'Kritisch durchbricht alles', en: 'Critical overrides everything' },
                                { key: 'fallback_channels', icon: 'mdi-swap-horizontal', de: 'Kanal-Fallback bei Fehler', en: 'Channel fallback on error' },
                                { key: 'vacation_coupling', icon: 'mdi-palm-tree', de: 'Urlaub: nur Kritisch', en: 'Vacation: critical only' },
                                { key: 'test_mode', icon: 'mdi-flask', de: 'Testmodus (nur loggen)', en: 'Test mode (log only)' },
                            ].map(item => (
                                <div key={item.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
                                    <span style={{ fontSize: 13 }}><span className={`mdi ${item.icon}`} style={{ marginRight: 6, fontSize: 14 }} />{lang === 'de' ? item.de : item.en}</span>
                                    <label className="toggle"><input type="checkbox" checked={extSettings?.[item.key]?.enabled || false}
                                        onChange={async () => {
                                            const val = { ...(extSettings?.[item.key] || {}), enabled: !extSettings?.[item.key]?.enabled };
                                            setExtSettings(prev => ({ ...prev, [item.key]: val }));
                                            await api.put('notification-settings/extended', { [item.key]: val });
                                        }} /><div className="toggle-slider" /></label>
                                </div>
                            ))}

                            {/* Grouping window */}
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
                                <span style={{ fontSize: 13 }}><span className="mdi mdi-group" style={{ marginRight: 6, fontSize: 14 }} />{lang === 'de' ? 'Gruppierung' : 'Grouping'}</span>
                                <div style={{ display: 'flex', gap: 4 }}>
                                    {[1, 5, 15, 30].map(m => (
                                        <button key={m} className={`btn btn-sm ${(extSettings?.grouping?.window_min || 5) === m ? 'btn-primary' : 'btn-ghost'}`}
                                            onClick={async () => { const g = { enabled: true, window_min: m }; setExtSettings(prev => ({ ...prev, grouping: g })); await api.put('notification-settings/extended', { grouping: g }); }}
                                            style={{ fontSize: 10, padding: '2px 6px' }}>{m}m</button>
                                    ))}
                                </div>
                            </div>

                            {/* Rate limits */}
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
                                <span style={{ fontSize: 13 }}><span className="mdi mdi-speedometer" style={{ marginRight: 6, fontSize: 14 }} />{lang === 'de' ? 'Max pro Stunde' : 'Rate limit /h'}</span>
                                <div style={{ display: 'flex', gap: 4 }}>
                                    {[5, 10, 20, 0].map(r => (
                                        <button key={r} className={`btn btn-sm ${(extSettings?.rate_limits?.anomaly || 10) === r ? 'btn-primary' : 'btn-ghost'}`}
                                            onClick={async () => { const rl = { anomaly: r, suggestion: r, critical: 0, info: r }; setExtSettings(prev => ({ ...prev, rate_limits: rl })); await api.put('notification-settings/extended', { rate_limits: rl }); }}
                                            style={{ fontSize: 10, padding: '2px 6px' }}>{r === 0 ? 'âˆž' : r}</button>
                                    ))}
                                </div>
                            </div>

                            {/* Digest */}
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
                                <span style={{ fontSize: 13 }}><span className="mdi mdi-email-newsletter" style={{ marginRight: 6, fontSize: 14 }} />{lang === 'de' ? 'Zusammenfassung' : 'Digest'}</span>
                                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                                    <label className="toggle"><input type="checkbox" checked={extSettings?.digest?.enabled || false}
                                        onChange={async () => { const d = { ...(extSettings?.digest || {}), enabled: !extSettings?.digest?.enabled }; setExtSettings(prev => ({ ...prev, digest: d })); await api.put('notification-settings/extended', { digest: d }); }} /><div className="toggle-slider" /></label>
                                    {extSettings?.digest?.enabled && <input type="time" className="input" value={extSettings?.digest?.time || '08:00'} style={{ width: 80, padding: '2px 6px', fontSize: 11 }}
                                        onChange={async (e) => { const d = { ...extSettings.digest, time: e.target.value }; setExtSettings(prev => ({ ...prev, digest: d })); await api.put('notification-settings/extended', { digest: d }); }} />}
                                </div>
                            </div>

                            {/* Battery threshold */}
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '7px 0' }}>
                                <span style={{ fontSize: 13 }}><span className="mdi mdi-battery-alert" style={{ marginRight: 6, fontSize: 14 }} />{lang === 'de' ? 'Batterie-Warnung unter' : 'Battery warning below'}</span>
                                <div style={{ display: 'flex', gap: 4 }}>
                                    {[10, 20, 30].map(p => (
                                        <button key={p} className={`btn btn-sm ${(extSettings?.battery_threshold || 20) === p ? 'btn-primary' : 'btn-ghost'}`}
                                            onClick={async () => { setExtSettings(prev => ({ ...prev, battery_threshold: p })); await api.put('notification-settings/extended', { battery_threshold: p }); }}
                                            style={{ fontSize: 10, padding: '2px 6px' }}>{p}%</button>
                                    ))}
                                </div>
                            </div>
                        </div>

                        {/* Stats */}
                        {stats && (
                            <div className="card">
                                <div className="card-title" style={{ marginBottom: 12 }}>{lang === 'de' ? 'Statistiken (30 Tage)' : 'Statistics (30 days)'}</div>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                                    <div style={{ textAlign: 'center', padding: 10, background: 'var(--bg-main)', borderRadius: 8 }}>
                                        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--accent-primary)' }}>{stats.total || 0}</div>
                                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{lang === 'de' ? 'Gesamt' : 'Total'}</div>
                                    </div>
                                    <div style={{ textAlign: 'center', padding: 10, background: 'var(--bg-main)', borderRadius: 8 }}>
                                        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--success)' }}>{stats.read || 0}</div>
                                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{lang === 'de' ? 'Gelesen' : 'Read'}</div>
                                    </div>
                                    <div style={{ textAlign: 'center', padding: 10, background: 'var(--bg-main)', borderRadius: 8 }}>
                                        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--info)' }}>{stats.pushed || 0}</div>
                                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Push</div>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* RIGHT COLUMN */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                        {/* Push Channels - Collapsible */}
                        <CollapsibleCard title={`${lang === 'de' ? 'Push-KanÃ¤le' : 'Push Channels'} Â· ${notifSettings?.channels?.length || 0}`} icon="mdi-send" defaultOpen={false}>
                            <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
                                <button className="btn btn-sm btn-secondary" onClick={async () => { await api.post('notification-settings/scan-channels'); await load(); }}>
                                    <span className="mdi mdi-refresh" style={{ marginRight: 4 }} />{lang === 'de' ? 'Suchen' : 'Scan'}
                                </button>
                            </div>
                            <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                                {(notifSettings?.channels || []).map(ch => (
                                    <div key={ch.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                                        <div>
                                            <div style={{ fontSize: 13, fontWeight: 500 }}>{ch.name}</div>
                                            <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{ch.ha_service}</div>
                                        </div>
                                        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                                            <button className="btn btn-sm btn-ghost" onClick={async () => { await api.post(`notification-settings/test-channel/${ch.id}`); showToast('Test sent', 'success'); }} style={{ fontSize: 10 }}>Test</button>
                                            <label className="toggle" style={{ transform: 'scale(0.8)' }}><input type="checkbox" checked={ch.is_active}
                                                onChange={async () => { await api.put(`notification-settings/channel/${ch.id}`, { is_active: !ch.is_active }); await load(); }} /><div className="toggle-slider" /></label>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </CollapsibleCard>

                        {/* Person Channel Assignment - Collapsible */}
                        <CollapsibleCard title={lang === 'de' ? 'Personen-Zuordnung' : 'Person Assignment'} icon="mdi-account-group" defaultOpen={false}>
                            {(users || []).map(u => (
                                <div key={u.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                                    <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>{u.name}</div>
                                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                                        {(notifSettings?.channels || []).filter(c => c.is_active).map(ch => {
                                            const assigned = extSettings?.person_channels?.[u.id]?.includes(ch.id);
                                            return <button key={ch.id} className={`btn btn-sm ${assigned ? 'btn-primary' : 'btn-ghost'}`}
                                                onClick={async () => {
                                                    const pc = { ...(extSettings?.person_channels || {}) };
                                                    const current = pc[u.id] || [];
                                                    pc[u.id] = assigned ? current.filter(id => id !== ch.id) : [...current, ch.id];
                                                    setExtSettings(prev => ({ ...prev, person_channels: pc }));
                                                    await api.put('notification-settings/extended', { person_channels: pc });
                                                }} style={{ fontSize: 10, padding: '2px 6px' }}>{ch.name}</button>;
                                        })}
                                    </div>
                                </div>
                            ))}
                        </CollapsibleCard>

                        {/* TTS - Collapsible */}
                        {ttsDevices.length > 0 && (
                            <CollapsibleCard title={`${lang === 'de' ? 'Sprachausgabe (TTS)' : 'Text-to-Speech'} Â· ${ttsDevices.length}`} icon="mdi-bullhorn" defaultOpen={false}>
                                {ttsDevices.map(d => (
                                    <div key={d.entity_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                                        <span style={{ fontSize: 13 }}>{d.name}</span>
                                        <button className="btn btn-sm btn-secondary" onClick={async () => {
                                            await api.post('tts/announce', { message: lang === 'de' ? 'Dies ist ein Test von MindHome.' : 'This is a test from MindHome.', entity_id: d.entity_id });
                                            showToast(lang === 'de' ? 'TTS gesendet' : 'TTS sent', 'success');
                                        }} style={{ fontSize: 11 }}><span className="mdi mdi-play" style={{ marginRight: 2 }} />Test</button>
                                    </div>
                                ))}
                            </CollapsibleCard>
                        )}

                        {/* Muted Devices - Collapsible */}
                        <CollapsibleCard title={`${lang === 'de' ? 'Stummgeschaltete GerÃ¤te' : 'Muted Devices'} Â· ${notifSettings?.muted_devices?.length || 0}`} icon="mdi-volume-off" defaultOpen={false}>
                            {notifSettings?.muted_devices?.length > 0 ? notifSettings.muted_devices.map(m => (
                                <div key={m.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0' }}>
                                    <span style={{ fontSize: 13 }}>{devices.find(d => d.id === m.device_id)?.name || `#${m.device_id}`}</span>
                                    <button className="btn btn-ghost" style={{ fontSize: 11, color: 'var(--danger)' }}
                                        onClick={async () => { await api.delete(`notification-settings/unmute-device/${m.id}`); await load(); }}>
                                        <span className="mdi mdi-volume-high" style={{ marginRight: 2 }} />{lang === 'de' ? 'Entstummen' : 'Unmute'}
                                    </button>
                                </div>
                            )) : <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>{lang === 'de' ? 'Keine stummgeschalteten GerÃ¤te.' : 'No muted devices.'}</p>}
                        </CollapsibleCard>

                        {/* DND Button */}
                        <button className={`btn ${notifSettings?.dnd_enabled ? 'btn-warning' : 'btn-secondary'}`}
                            onClick={async () => { const newVal = !notifSettings?.dnd_enabled; setNotifSettings(s => ({ ...s, dnd_enabled: newVal })); await api.put('notification-settings/dnd', { enabled: newVal }); }}
                            style={{ fontSize: 13, padding: '10px 16px' }}>
                            <span className={`mdi ${notifSettings?.dnd_enabled ? 'mdi-bell-off' : 'mdi-bell-ring'}`} style={{ marginRight: 8 }} />
                            {notifSettings?.dnd_enabled ? (lang === 'de' ? 'DND aktiv â€“ Benachrichtigungen stumm' : 'DND active') : (lang === 'de' ? 'Nicht stÃ¶ren aktivieren' : 'Enable Do Not Disturb')}
                        </button>
                    </div>
                </div>
            ) : (<div>
            {/* Suggestions / Predictions */}
            <div className="card animate-in" style={{ marginBottom: 24 }}>
                <div className="card-header">
                    <div>
                        <div className="card-title">
                            <span className="mdi mdi-lightbulb-on" style={{ marginRight: 8, color: 'var(--warning)' }} />
                            {lang === 'de' ? 'VorschlÃ¤ge & Automationen' : 'Suggestions & Automations'}
                        </div>
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                        {['all', 'pending', 'executed', 'confirmed', 'rejected', 'undone'].map(f => (
                            <button key={f} className={`btn btn-sm ${predFilter === f ? 'btn-primary' : 'btn-ghost'}`}
                                    onClick={() => setPredFilter(f)} style={{ fontSize: 12 }}>
                                {f === 'all' ? (lang === 'de' ? 'Alle' : 'All') :
                                 f === 'pending' ? (lang === 'de' ? 'Offen' : 'Pending') :
                                 f === 'executed' ? (lang === 'de' ? 'AusgefÃ¼hrt' : 'Executed') :
                                 f === 'confirmed' ? (lang === 'de' ? 'BestÃ¤tigt' : 'Confirmed') :
                                 f === 'rejected' ? (lang === 'de' ? 'Abgelehnt' : 'Rejected') :
                                 f === 'undone' ? (lang === 'de' ? 'RÃ¼ckgÃ¤ngig' : 'Undone') : f}
                            </button>
                        ))}
                    </div>
                </div>
                {filteredPreds.length === 0 ? (
                    <div className="empty-state">
                        <span className="mdi mdi-lightbulb-outline" />
                        <h3>{lang === 'de' ? 'Keine VorschlÃ¤ge' : 'No suggestions'}</h3>
                        <p>{lang === 'de' ? 'VorschlÃ¤ge erscheinen sobald Muster erkannt werden.' : 'Suggestions will appear once patterns are detected.'}</p>
                    </div>
                ) : (
                    (() => {
                        // Group by day for timeline
                        const grouped = {};
                        filteredPreds.forEach(pred => {
                            const day = pred.created_at ? new Date(pred.created_at).toLocaleDateString(lang === 'de' ? 'de-DE' : 'en-US', { weekday: 'long', day: 'numeric', month: 'long' }) : (lang === 'de' ? 'Unbekannt' : 'Unknown');
                            if (!grouped[day]) grouped[day] = [];
                            grouped[day].push(pred);
                        });
                        return Object.entries(grouped).map(([day, preds]) => (
                            <div key={day}>
                                <div style={{ padding: '8px 16px', fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', background: 'var(--bg-tertiary)', borderBottom: '1px solid var(--border-color)' }}>
                                    {day}
                                </div>
                                {preds.map(pred => (
                        <div key={pred.id} style={{
                            padding: '12px 16px', borderBottom: '1px solid var(--border-color)',
                            display: 'flex', alignItems: 'center', gap: 12,
                            opacity: ['rejected', 'undone'].includes(pred.status) ? 0.6 : 1,
                        }}>
                            <span className="mdi mdi-robot" style={{ fontSize: 20, color: 'var(--accent-primary)', flexShrink: 0 }} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 14 }}>{pred.description || 'Pattern'}</div>
                                <div style={{ display: 'flex', gap: 8, fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                                    <span className={`badge badge-${statusColors[pred.status] || 'info'}`} style={{ fontSize: 11 }}>
                                        {pred.status}
                                    </span>
                                    <span>{Math.round(pred.confidence * 100)}%</span>
                                    {pred.executed_at && <span>{new Date(pred.executed_at).toLocaleString()}</span>}
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                                {pred.status === 'pending' && (
                                    <>
                                        <button className="btn btn-sm btn-success" onClick={() => confirmPred(pred.id)} title={lang === 'de' ? 'Aktivieren' : 'Activate'}>
                                            <span className="mdi mdi-check" />
                                        </button>
                                        <button className="btn btn-sm btn-ghost" onClick={() => rejectPred(pred.id)} title={lang === 'de' ? 'Ablehnen' : 'Reject'}>
                                            <span className="mdi mdi-close" />
                                        </button>
                                    </>
                                )}
                                {pred.status === 'executed' && (
                                    <button className="btn btn-sm btn-warning" onClick={() => undoPred(pred.id)} title={lang === 'de' ? 'RÃ¼ckgÃ¤ngig' : 'Undo'}>
                                        <span className="mdi mdi-undo" />
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}
                        </div>
                    ))
                    })()
                )}
            </div>

            {/* Notification Log */}
            <div className="card animate-in">
                <div className="card-header">
                    <div>
                        <div className="card-title">
                            <span className="mdi mdi-bell" style={{ marginRight: 8 }} />
                            {lang === 'de' ? 'Benachrichtigungen' : 'Notifications'}
                            {notifications.filter(n => !n.was_read).length > 0 && (
                                <span className="badge badge-danger" style={{ marginLeft: 8 }}>
                                    {notifications.filter(n => !n.was_read).length}
                                </span>
                            )}
                        </div>
                    </div>
                    {notifications.some(n => !n.was_read) && (
                        <button className="btn btn-sm btn-ghost" onClick={markAllRead}>
                            <span className="mdi mdi-check-all" style={{ marginRight: 4 }} />
                            {lang === 'de' ? 'Alle gelesen' : 'Mark all read'}
                        </button>
                    )}
                </div>
                {notifications.length === 0 ? (
                    <div className="empty-state">
                        <span className="mdi mdi-bell-outline" />
                        <h3>{lang === 'de' ? 'Keine Benachrichtigungen' : 'No notifications'}</h3>
                    </div>
                ) : (
                    notifications.map(n => (
                        <div key={n.id} style={{
                            padding: '10px 16px', borderBottom: '1px solid var(--border-color)',
                            display: 'flex', alignItems: 'center', gap: 12,
                            background: n.was_read ? 'transparent' : 'var(--bg-tertiary)',
                            cursor: 'pointer',
                        }} onClick={() => !n.was_read && markRead(n.id)}>
                            <span className={`mdi ${typeIcons[n.type] || 'mdi-bell'}`}
                                  style={{ fontSize: 18, color: n.type === 'anomaly' ? 'var(--danger)' : 'var(--accent-primary)', flexShrink: 0 }} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontWeight: n.was_read ? 400 : 600, fontSize: 13 }}>{n.title}</div>
                                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{n.message}</div>
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', flexShrink: 0, whiteSpace: 'nowrap' }}>
                                {n.created_at ? new Date(n.created_at).toLocaleString() : ''}
                            </div>
                            {!n.was_read && <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent-primary)', flexShrink: 0 }} />}
                        </div>
                    ))
                )}
            </div>
        </div>)}
    </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Onboarding Wizard
// ================================================================

const OnboardingWizard = ({ onComplete }) => {
    const [step, setStep] = useState(0);
    const [lang, setLangLocal] = useState('de');
    const [adminName, setAdminName] = useState('');
    const [discovered, setDiscovered] = useState(null);
    const [discovering, setDiscovering] = useState(false);
    const [restoring, setRestoring] = useState(false);
    const [backupData, setBackupData] = useState(null);
    const [backupError, setBackupError] = useState('');
    const restoreInputRef = useRef(null);

    const handleFileSelect = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        setBackupError('');
        try {
            const text = await file.text();
            const data = JSON.parse(text);
            if (!data.version) {
                setBackupError(lang === 'de' ? 'UngÃ¼ltige Backup-Datei' : 'Invalid backup file');
                return;
            }
            setBackupData(data);
        } catch (err) {
            setBackupError(lang === 'de' ? 'Datei konnte nicht gelesen werden' : 'Could not read file');
        }
        e.target.value = '';
    };

    const handleConfirmRestore = async () => {
        if (!backupData) return;
        setRestoring(true);
        setBackupError('');
        try {
            const result = await api.post('backup/import', backupData);
            if (result?.success) {
                onComplete();
                return;
            } else {
                setBackupError(result?.error || (lang === 'de' ? 'Import fehlgeschlagen' : 'Import failed'));
            }
        } catch (err) {
            setBackupError(lang === 'de' ? 'Import fehlgeschlagen' : 'Import failed');
        }
        setRestoring(false);
    };

    const steps = [
        { id: 'welcome', icon: 'mdi-lightbulb-on' },
        { id: 'language', icon: 'mdi-translate' },
        { id: 'admin', icon: 'mdi-shield-crown' },
        { id: 'discover', icon: 'mdi-magnify' },
        { id: 'privacy', icon: 'mdi-shield-lock' },
        { id: 'done', icon: 'mdi-check-circle' },
    ];

    const handleDiscover = async () => {
        setDiscovering(true);
        const result = await api.get('discover');
        setDiscovered(result);
        setDiscovering(false);
    };

    const handleComplete = async () => {
        // Create admin user
        if (adminName.trim()) {
            await api.post('users', { name: adminName, role: 'admin' });
        }

        // Devices are imported manually from the Devices page

        // Set language
        await api.put('system/settings/language', { value: lang });

        // Mark onboarding complete
        await api.post('onboarding/complete');

        onComplete();
    };

    const labels = {
        de: {
            welcome_title: 'Willkommen bei MindHome!',
            welcome_sub: 'Dein Zuhause wird intelligent. Lass uns gemeinsam alles einrichten.',
            lang_title: 'Sprache wÃ¤hlen',
            lang_sub: 'In welcher Sprache soll MindHome kommunizieren?',
            admin_title: 'Dein Profil',
            admin_sub: 'Erstelle das Admin-Konto fÃ¼r MindHome.',
            admin_name: 'Dein Name',
            discover_title: 'GerÃ¤te erkennen',
            discover_sub: 'MindHome sucht jetzt nach allen GerÃ¤ten in deinem Home Assistant.',
            discover_btn: 'GerÃ¤te suchen',
            discover_searching: 'Suche lÃ¤uft...',
            discover_found: 'GerÃ¤te gefunden in',
            discover_domains: 'Bereichen',
            privacy_title: 'Datenschutz',
            privacy_sub: 'Alle deine Daten bleiben lokal auf deinem GerÃ¤t. Nichts wird an externe Server gesendet. Du hast volle Kontrolle.',
            privacy_note: 'Du kannst spÃ¤ter pro Raum einstellen welche Daten erfasst werden.',
            done_title: 'Alles bereit!',
            done_sub: 'MindHome beginnt jetzt mit der Lernphase. Die ersten Tage beobachtet MindHome nur und sammelt Daten.',
            start: 'Los geht\'s',
            next: 'Weiter',
            back: 'ZurÃ¼ck',
            finish: 'MindHome starten'
        },
        en: {
            welcome_title: 'Welcome to MindHome!',
            welcome_sub: 'Your home is getting smart. Let\'s set everything up together.',
            lang_title: 'Choose Language',
            lang_sub: 'Which language should MindHome use?',
            admin_title: 'Your Profile',
            admin_sub: 'Create the admin account for MindHome.',
            admin_name: 'Your Name',
            discover_title: 'Discover Devices',
            discover_sub: 'MindHome will now search for all devices in your Home Assistant.',
            discover_btn: 'Search Devices',
            discover_searching: 'Searching...',
            discover_found: 'devices found in',
            discover_domains: 'domains',
            privacy_title: 'Privacy',
            privacy_sub: 'All your data stays local on your device. Nothing is sent to external servers. You have full control.',
            privacy_note: 'You can later configure per room which data is collected.',
            done_title: 'All set!',
            done_sub: 'MindHome now begins the learning phase. For the first days, MindHome will only observe and collect data.',
            start: 'Let\'s go',
            next: 'Next',
            back: 'Back',
            finish: 'Start MindHome'
        }
    };

    const l = labels[lang];

    return (
        <div className="onboarding-overlay">
            <div className="onboarding-container">
                {/* Progress */}
                <div className="onboarding-progress">
                    {steps.map((s, i) => (
                        <div key={s.id} className={`onboarding-progress-step ${
                            i < step ? 'completed' : i === step ? 'active' : ''
                        }`} />
                    ))}
                </div>

                {/* Step Content */}
                <div className="onboarding-content" key={step}>
                    {step === 0 && (
                        <div style={{ textAlign: 'center' }}>
                            <img src={`${API_BASE}/icon.png`} alt="MindHome" style={{ width: 72, height: 72, borderRadius: 18, margin: '0 auto 24px', display: 'block', boxShadow: 'var(--shadow-glow)' }} />
                            <div className="onboarding-title">{l.welcome_title}</div>
                            <div className="onboarding-subtitle">{l.welcome_sub}</div>

                            {/* Backup Restore Section */}
                            {!backupData ? (
                                <div style={{ marginTop: 24, padding: 16, border: '1px dashed var(--border)', borderRadius: 12 }}>
                                    <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
                                        {lang === 'de'
                                            ? 'Du hast bereits ein Backup? Stelle es hier wieder her:'
                                            : 'Already have a backup? Restore it here:'}
                                    </p>
                                    <button className="btn btn-secondary" onClick={() => restoreInputRef.current?.click()}>
                                        <span className="mdi mdi-upload" />
                                        {lang === 'de' ? 'Backup-Datei wÃ¤hlen' : 'Choose Backup File'}
                                    </button>
                                    <input ref={restoreInputRef} type="file" accept=".json" onChange={handleFileSelect} style={{ display: 'none' }} />
                                    {backupError && (
                                        <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 8 }}>{backupError}</p>
                                    )}
                                </div>
                            ) : (
                                <div style={{ marginTop: 24, padding: 20, border: '2px solid var(--success)', borderRadius: 12, background: 'var(--bg-secondary)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'center', marginBottom: 16 }}>
                                        <span className="mdi mdi-check-circle" style={{ fontSize: 28, color: 'var(--success)' }} />
                                        <strong style={{ fontSize: 16 }}>
                                            {lang === 'de' ? 'Backup erkannt!' : 'Backup Found!'}
                                        </strong>
                                    </div>
                                    <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16, lineHeight: 1.6 }}>
                                        <div>{lang === 'de' ? 'Erstellt am' : 'Created'}: {new Date(backupData.exported_at).toLocaleString(lang === 'de' ? 'de-DE' : 'en-US')}</div>
                                        <div>{backupData.rooms?.length || 0} {lang === 'de' ? 'RÃ¤ume' : 'Rooms'} Â· {backupData.devices?.length || 0} {lang === 'de' ? 'GerÃ¤te' : 'Devices'} Â· {backupData.users?.length || 0} {lang === 'de' ? 'Personen' : 'Users'}</div>
                                    </div>
                                    <p style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>
                                        {lang === 'de'
                                            ? 'MÃ¶chtest du dieses Backup in MindHome laden?'
                                            : 'Do you want to load this backup into MindHome?'}
                                    </p>
                                    <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
                                        <button className="btn btn-secondary" onClick={() => { setBackupData(null); setBackupError(''); }}>
                                            {lang === 'de' ? 'Abbrechen' : 'Cancel'}
                                        </button>
                                        <button className="btn btn-primary" onClick={handleConfirmRestore} disabled={restoring}>
                                            <span className="mdi mdi-restore" />
                                            {restoring
                                                ? (lang === 'de' ? 'Wird geladen...' : 'Loading...')
                                                : (lang === 'de' ? 'Backup wiederherstellen' : 'Restore Backup')}
                                        </button>
                                    </div>
                                    {backupError && (
                                        <p style={{ color: 'var(--danger)', fontSize: 13, marginTop: 12 }}>{backupError}</p>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {step === 1 && (
                        <div>
                            <div className="onboarding-title">{l.lang_title}</div>
                            <div className="onboarding-subtitle">{l.lang_sub}</div>
                            <div style={{ display: 'flex', gap: 12 }}>
                                {[{ code: 'de', label: 'Deutsch', flag: 'ðŸ‡©ðŸ‡ª' }, { code: 'en', label: 'English', flag: 'ðŸ‡¬ðŸ‡§' }].map(opt => (
                                    <button key={opt.code}
                                        className={`card ${lang === opt.code ? '' : ''}`}
                                        onClick={() => setLangLocal(opt.code)}
                                        style={{
                                            flex: 1, cursor: 'pointer', textAlign: 'center', padding: 20,
                                            border: lang === opt.code ? '2px solid var(--accent-primary)' : '1px solid var(--border)',
                                            background: lang === opt.code ? 'var(--accent-primary-dim)' : 'var(--bg-card)'
                                        }}>
                                        <div style={{ fontSize: 32 }}>{opt.flag}</div>
                                        <div style={{ fontWeight: 600, marginTop: 8 }}>{opt.label}</div>
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    {step === 2 && (
                        <div>
                            <div className="onboarding-title">{l.admin_title}</div>
                            <div className="onboarding-subtitle">{l.admin_sub}</div>
                            <div className="input-group">
                                <label className="input-label">{l.admin_name}</label>
                                <input className="input" style={{ fontSize: 16, padding: 14 }}
                                       value={adminName}
                                       onChange={e => setAdminName(e.target.value)}
                                       autoFocus />
                            </div>
                        </div>
                    )}

                    {step === 3 && (
                        <div>
                            <div className="onboarding-title">{l.discover_title}</div>
                            <div className="onboarding-subtitle">{l.discover_sub}</div>
                            {!discovered ? (
                                <div style={{ textAlign: 'center', padding: 24 }}>
                                    <button className="btn btn-primary btn-lg" onClick={handleDiscover} disabled={discovering}>
                                        {discovering ? (
                                            <><div className="loading-spinner" style={{ width: 20, height: 20, borderWidth: 2 }} /> {l.discover_searching}</>
                                        ) : (
                                            <><span className="mdi mdi-magnify" /> {l.discover_btn}</>
                                        )}
                                    </button>
                                </div>
                            ) : (
                                <div className="card" style={{ borderColor: 'var(--success)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                                        <span className="mdi mdi-check-circle" style={{ fontSize: 28, color: 'var(--success)' }} />
                                        <div>
                                            <div style={{ fontWeight: 600 }}>
                                                {discovered.total_entities} {l.discover_found} {Object.keys(discovered.domains || {}).length} {l.discover_domains}
                                            </div>
                                        </div>
                                    </div>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                        {Object.entries(discovered.domains || {}).map(([domain, data]) => (
                                            <span key={domain} className="badge badge-info">{domain}: {data.count}</span>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {step === 4 && (
                        <div>
                            <div className="onboarding-title">{l.privacy_title}</div>
                            <div className="onboarding-subtitle">{l.privacy_sub}</div>
                            <div className="card" style={{ borderColor: 'var(--success)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                    <span className="mdi mdi-shield-check" style={{ fontSize: 32, color: 'var(--success)' }} />
                                    <div style={{ fontSize: 14, lineHeight: 1.6 }}>
                                        {l.privacy_note}
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {step === 5 && (
                        <div style={{ textAlign: 'center' }}>
                            <span className="mdi mdi-check-circle" style={{ fontSize: 64, color: 'var(--success)', display: 'block', marginBottom: 16 }} />
                            <div className="onboarding-title">{l.done_title}</div>
                            <div className="onboarding-subtitle">{l.done_sub}</div>
                        </div>
                    )}
                </div>

                {/* Navigation */}
                <div className="onboarding-actions">
                    {step > 0 ? (
                        <button className="btn btn-secondary" onClick={() => setStep(s => s - 1)}>
                            <span className="mdi mdi-arrow-left" /> {l.back}
                        </button>
                    ) : <div />}

                    {step < steps.length - 1 ? (
                        <button className="btn btn-primary" onClick={() => setStep(s => s + 1)}>
                            {step === 0 ? l.start : l.next} <span className="mdi mdi-arrow-right" />
                        </button>
                    ) : (
                        <button className="btn btn-primary btn-lg" onClick={handleComplete}>
                            <span className="mdi mdi-rocket-launch" /> {l.finish}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

// ================================================================
// Main App
// ================================================================

// ================================================================
// Phase 3: Energy Dashboard Page
// ================================================================
const EnergyPage = () => {
    const { lang, showToast } = useApp();
    const [config, setConfig] = useState(null);
    const [readings, setReadings] = useState([]);
    const [standbyConfigs, setSConfigs] = useState([]);
    const [summary, setSummary] = useState(null);
    const [hours, setHours] = useState(24);

    const load = () => {
        api.get('energy/config').then(setConfig).catch(() => {});
        api.get(`energy/readings?hours=${hours}`).then(setReadings).catch(() => {});
        api.get('energy/standby-config').then(setSConfigs).catch(() => {});
        api.get('energy/summary').then(setSummary).catch(() => {});
    };
    useEffect(load, [hours]);

    const saveConfig = () => {
        api.put('energy/config', config).then(() => showToast(lang === 'de' ? 'Gespeichert' : 'Saved', 'success'));
    };

    return (
        <div>
            <h2 style={{ marginBottom: 16 }}>{lang === 'de' ? 'Energie-Dashboard' : 'Energy Dashboard'}</h2>
            {config && (
                <div className="card animate-in" style={{ marginBottom: 16 }}>
                    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', fontWeight: 600 }}>
                        {lang === 'de' ? 'Konfiguration' : 'Configuration'}
                    </div>
                    <div style={{ padding: 16, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                        <div>
                            <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>{lang === 'de' ? 'Preis/kWh' : 'Price/kWh'}</label>
                            <input type="number" step="0.01" className="form-input" style={{ width: 100 }} value={config.price_per_kwh || 0.25}
                                onChange={e => setConfig({ ...config, price_per_kwh: parseFloat(e.target.value) })} />
                        </div>
                        <div>
                            <label style={{ fontSize: 12, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>{lang === 'de' ? 'Währung' : 'Currency'}</label>
                            <input type="text" className="form-input" style={{ width: 80 }} value={config.currency || 'EUR'}
                                onChange={e => setConfig({ ...config, currency: e.target.value })} />
                        </div>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                            <input type="checkbox" checked={config.solar_enabled || false}
                                onChange={e => setConfig({ ...config, solar_enabled: e.target.checked })} />
                            Solar
                        </label>
                        <button className="btn btn-primary" onClick={saveConfig}>{lang === 'de' ? 'Speichern' : 'Save'}</button>
                    </div>
                </div>
            )}
            {summary && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
                    <div className="card animate-in" style={{ padding: 16, textAlign: 'center' }}>
                        <div style={{ fontSize: 24, fontWeight: 700 }}>{(summary.total_kwh || 0).toFixed(1)} kWh</div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{lang === 'de' ? 'Gesamt heute' : 'Total today'}</div>
                    </div>
                    <div className="card animate-in" style={{ padding: 16, textAlign: 'center' }}>
                        <div style={{ fontSize: 24, fontWeight: 700 }}>{(summary.total_cost || 0).toFixed(2)} {config?.currency || 'EUR'}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{lang === 'de' ? 'Kosten heute' : 'Cost today'}</div>
                    </div>
                    <div className="card animate-in" style={{ padding: 16, textAlign: 'center' }}>
                        <div style={{ fontSize: 24, fontWeight: 700 }}>{(summary.current_power_w || 0).toFixed(0)} W</div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{lang === 'de' ? 'Aktuelle Leistung' : 'Current power'}</div>
                    </div>
                    <div className="card animate-in" style={{ padding: 16, textAlign: 'center' }}>
                        <div style={{ fontSize: 24, fontWeight: 700 }}>{standbyConfigs.length}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{lang === 'de' ? 'Standby-Geräte' : 'Standby devices'}</div>
                    </div>
                </div>
            )}
            <div style={{ marginBottom: 12, display: 'flex', gap: 6 }}>
                {[6, 12, 24, 48, 168].map(hr => (
                    <button key={hr} className={`btn btn-sm ${hours === hr ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setHours(hr)}>{hr}h</button>
                ))}
            </div>
            <div className="card" style={{ overflow: 'hidden' }}>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontWeight: 600 }}>{lang === 'de' ? 'Messwerte' : 'Readings'}</span>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{readings.length} {lang === 'de' ? 'Einträge' : 'entries'}</span>
                </div>
                <div style={{ maxHeight: 400, overflowY: 'auto' }}>
                    <table className="data-table" style={{ width: '100%' }}>
                        <thead><tr><th>Entity</th><th>W</th><th>kWh</th><th>{lang === 'de' ? 'Zeit' : 'Time'}</th></tr></thead>
                        <tbody>
                            {readings.slice(0, 100).map(r => (
                                <tr key={r.id}><td>{r.entity_id}</td><td>{r.power_w?.toFixed(1)}</td><td>{r.energy_kwh?.toFixed(3)}</td>
                                <td>{r.created_at ? new Date(r.created_at).toLocaleTimeString() : '-'}</td></tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};

// ================================================================
// Phase 3: Scenes Page
// ================================================================
const ScenesPage = () => {
    const { lang, showToast } = useApp();
    const [scenes, setScenes] = useState([]);

    const load = () => api.get('scenes').then(setScenes).catch(() => {});
    useEffect(load, []);

    const activate = (id) => api.post(`scenes/${id}/activate`).then(() => { showToast(lang === 'de' ? 'Szene aktiviert' : 'Scene activated', 'success'); load(); });
    const remove = (id) => { if (confirm(lang === 'de' ? 'Szene löschen?' : 'Delete scene?')) api.delete(`scenes/${id}`).then(load); };
    const accept = (id) => api.put(`scenes/${id}`, { status: 'accepted' }).then(() => { showToast(lang === 'de' ? 'Akzeptiert' : 'Accepted', 'success'); load(); });

    const detected = scenes.filter(s => s.status === 'detected');
    const accepted = scenes.filter(s => s.status === 'accepted' || s.source === 'manual');

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <h2>{lang === 'de' ? 'Szenen' : 'Scenes'}</h2>
            </div>
            {detected.length > 0 && (
                <div className="card animate-in" style={{ marginBottom: 16 }}>
                    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', fontWeight: 600, color: 'var(--warning)' }}>
                        {lang === 'de' ? 'Erkannte Szenen' : 'Detected Scenes'} ({detected.length})
                    </div>
                    {detected.map(s => (
                        <div key={s.id} style={{ padding: '10px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                                <strong>{lang === 'de' ? s.name_de : s.name_en}</strong>
                                <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--text-muted)' }}>{s.frequency}x</span>
                            </div>
                            <div style={{ display: 'flex', gap: 6 }}>
                                <button className="btn btn-sm btn-primary" onClick={() => accept(s.id)}>{lang === 'de' ? 'Akzeptieren' : 'Accept'}</button>
                                <button className="btn btn-sm btn-ghost" onClick={() => remove(s.id)}>✕</button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
            <div className="card animate-in">
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', fontWeight: 600 }}>
                    {lang === 'de' ? 'Aktive Szenen' : 'Active Scenes'} ({accepted.length})
                </div>
                {accepted.length === 0 ? (
                    <div style={{ padding: 16, color: 'var(--text-muted)' }}>{lang === 'de' ? 'Noch keine Szenen' : 'No scenes yet'}</div>
                ) : accepted.map(s => (
                    <div key={s.id} style={{ padding: '10px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                            <span className={'mdi ' + (s.icon || 'mdi-palette')} style={{ marginRight: 8 }} />
                            <strong>{lang === 'de' ? s.name_de : s.name_en}</strong>
                            <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--text-muted)' }}>{s.states?.length || 0} {lang === 'de' ? 'Geräte' : 'devices'}</span>
                        </div>
                        <div style={{ display: 'flex', gap: 6 }}>
                            <button className="btn btn-sm btn-primary" onClick={() => activate(s.id)}>{lang === 'de' ? 'Aktivieren' : 'Activate'}</button>
                            <button className="btn btn-sm btn-ghost" onClick={() => remove(s.id)}>✕</button>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

// ================================================================
// Phase 3: Presence Page
// ================================================================
const PresencePage = () => {
    const { lang, showToast } = useApp();
    const [modes, setModes] = useState([]);
    const [current, setCurrent] = useState(null);
    const [persons, setPersons] = useState([]);
    const [logs, setLogs] = useState([]);
    const [guests, setGuests] = useState([]);

    const load = () => {
        api.get('presence-modes').then(setModes).catch(() => {});
        api.get('presence-modes/current').then(setCurrent).catch(() => {});
        api.get('persons').then(setPersons).catch(() => {});
        api.get('presence-log').then(setLogs).catch(() => {});
        api.get('guest-devices').then(setGuests).catch(() => {});
    };
    useEffect(load, []);

    const activate = (id) => api.post(`presence-modes/${id}/activate`).then(() => { showToast(lang === 'de' ? 'Modus aktiviert' : 'Mode activated', 'success'); load(); });

    return (
        <div>
            <h2 style={{ marginBottom: 16 }}>{lang === 'de' ? 'Anwesenheit' : 'Presence'}</h2>
            {current && (
                <div className="card animate-in" style={{ marginBottom: 16, padding: 24, textAlign: 'center' }}>
                    <span className={'mdi ' + (current.icon || 'mdi-home')} style={{ fontSize: 40, color: current.color || 'var(--accent-primary)' }} />
                    <div style={{ fontSize: 20, fontWeight: 700, marginTop: 8 }}>{lang === 'de' ? current.name_de : current.name_en}</div>
                    {current.since && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>seit {new Date(current.since).toLocaleTimeString()}</div>}
                </div>
            )}
            <div className="card animate-in" style={{ marginBottom: 16 }}>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', fontWeight: 600 }}>{lang === 'de' ? 'Personen' : 'Persons'}</div>
                {persons.map(p => (
                    <div key={p.entity_id} style={{ padding: '10px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between' }}>
                        <span>{p.name}</span>
                        <span style={{ padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 600,
                            background: p.state === 'home' ? 'rgba(76,175,80,0.15)' : 'rgba(158,158,158,0.15)',
                            color: p.state === 'home' ? 'var(--success)' : 'var(--text-muted)' }}>{p.state}</span>
                    </div>
                ))}
            </div>
            <div className="card animate-in" style={{ marginBottom: 16 }}>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', fontWeight: 600 }}>{lang === 'de' ? 'Modi' : 'Modes'}</div>
                {modes.map(m => (
                    <div key={m.id} style={{ padding: '10px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                            <span className={'mdi ' + (m.icon || 'mdi-home')} style={{ marginRight: 8, color: m.color || 'var(--text-primary)' }} />
                            <strong>{lang === 'de' ? m.name_de : m.name_en}</strong>
                            <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--text-muted)' }}>{m.trigger_type}</span>
                        </div>
                        <button className="btn btn-sm btn-ghost" onClick={() => activate(m.id)}>{lang === 'de' ? 'Aktivieren' : 'Activate'}</button>
                    </div>
                ))}
            </div>
            {guests.length > 0 && (
                <div className="card animate-in" style={{ marginBottom: 16 }}>
                    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', fontWeight: 600 }}>{lang === 'de' ? 'Gäste' : 'Guests'} ({guests.length})</div>
                    {guests.map(g => (
                        <div key={g.id} style={{ padding: '10px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between' }}>
                            <span>{g.name || g.mac_address || g.entity_id}</span>
                            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{g.visit_count}x</span>
                        </div>
                    ))}
                </div>
            )}
            <div className="card animate-in">
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', fontWeight: 600 }}>{lang === 'de' ? 'Verlauf' : 'History'}</div>
                <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                    {logs.slice(0, 20).map(l => (
                        <div key={l.id} style={{ padding: '8px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                            <span>{l.mode_name}</span>
                            <span style={{ color: 'var(--text-muted)' }}>{l.created_at ? new Date(l.created_at).toLocaleString() : '-'}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
};

const App = () => {
    const [page, setPage] = useState('dashboard');
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const [lang, setLang] = useState('de');
    const [theme, setTheme] = useState('dark');
    const [viewMode, setViewMode] = useState('simple');
    const [toasts, setToasts] = useState([]);

    const [status, setStatus] = useState(null);
    const [domains, setDomains] = useState([]);
    const [devices, setDevices] = useState([]);
    const [rooms, setRooms] = useState([]);
    const [users, setUsers] = useState([]);
    const [quickActions, setQuickActions] = useState([]);
    const [onboardingDone, setOnboardingDone] = useState(null);
    const [loading, setLoading] = useState(true);
    const [settingsLoaded, setSettingsLoaded] = useState(false);
    const [unreadNotifs, setUnreadNotifs] = useState(0);

    // #8 Toast stacking
    const showToast = useCallback((message, type = 'info') => {
        const id = Date.now();
        setToasts(prev => [...prev.slice(-4), { id, message, type }]);
        setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
    }, []);

    // Backwards compat
    const toast = toasts.length > 0 ? toasts[toasts.length - 1] : null;

    // #16 Keyboard Shortcuts
    useEffect(() => {
        const handler = (e) => {
            // Ignore if typing in input/textarea
            if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
            if (e.key === 'Escape') {
                setSidebarOpen(false);
                // Close any open modals by dispatching custom event
                document.dispatchEvent(new CustomEvent('mindhome-escape'));
            }
            if (e.key === 'n' && !e.ctrlKey && !e.metaKey) {
                setPage('notifications');
            }
            if (e.key === 'd' && !e.ctrlKey && !e.metaKey) {
                setPage('dashboard');
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, []);

    // #49 Auto Theme (follow system preference)
    useEffect(() => {
        const autoTheme = localStorage.getItem('mindhome_auto_theme');
        if (autoTheme === 'true') {
            const mq = window.matchMedia('(prefers-color-scheme: dark)');
            const handler = (e) => setTheme(e.matches ? 'dark' : 'light');
            handler(mq);
            mq.addEventListener('change', handler);
            return () => mq.removeEventListener('change', handler);
        }
    }, []);

    // Phase 2b: Poll notification count
    useEffect(() => {
        const fetchUnread = () => api.get('notifications/unread-count')
            .then(d => setUnreadNotifs(d?.unread_count || 0)).catch(() => {});
        fetchUnread();
        const interval = setInterval(fetchUnread, 60000);
        return () => clearInterval(interval);
    }, []);

    const refreshData = useCallback(async () => {
        const [s, d, dev, r, u, qa] = await Promise.all([
            api.get('system/status'),
            api.get('domains'),
            api.get('devices'),
            api.get('rooms'),
            api.get('users'),
            api.get('quick-actions')
        ]);
        if (s) setStatus(s);
        if (d) setDomains(d);
        if (dev) setDevices(dev);
        if (r) setRooms(r);
        if (u) setUsers(u);
        if (qa) setQuickActions(qa);
    }, []);

    useEffect(() => {
        const init = async () => {
            const s = await api.get('system/status');
            if (s) {
                setStatus(s);
                setLang(s.language || 'de');
                setTheme(s.theme || 'dark');
                setViewMode(s.view_mode || 'simple');
                setOnboardingDone(s.onboarding_completed);
            } else {
                setOnboardingDone(false);
            }
            await refreshData();
            setLoading(false);
            // Mark settings as loaded so useEffects don't overwrite on first render
            setTimeout(() => setSettingsLoaded(true), 500);
        };
        init();

        // Refresh data: full load only on page change, lightweight poll every 60s
        const interval = setInterval(() => {
            api.get('system/status').then(s => { if (s) setStatus(s); });
        }, 60000);
        return () => clearInterval(interval);
    }, []);

    // Apply theme
    useEffect(() => {
        document.documentElement.setAttribute('data-theme', theme);
        if (settingsLoaded) api.put('system/settings/theme', { value: theme });
    }, [theme, settingsLoaded]);

    // Save viewMode
    useEffect(() => {
        if (settingsLoaded) api.put('system/settings/view_mode', { value: viewMode });
    }, [viewMode, settingsLoaded]);

    // Save language
    useEffect(() => {
        if (settingsLoaded) api.put('system/settings/language', { value: lang });
    }, [lang, settingsLoaded]);

    const toggleDomain = async (domainId) => {
        const result = await api.post(`domains/${domainId}/toggle`);
        if (result) {
            setDomains(prev => prev.map(d =>
                d.id === domainId ? { ...d, is_enabled: result.is_enabled } : d
            ));
        }
    };

    const executeQuickAction = async (actionId) => {
        const result = await api.post(`quick-actions/execute/${actionId}`);
        if (result?.success) {
            showToast(lang === 'de' ? 'Aktion ausgefÃ¼hrt' : 'Action executed', 'success');
            await refreshData();
        }
    };

    // Role: first user is always admin, or if only 1 user exists â†’ admin
    const isAdmin = users.length <= 1 || (users[0]?.role === 'admin');

    const contextValue = React.useMemo(() => ({
        status, domains, devices, rooms, users, quickActions, isAdmin,
        lang, setLang, theme, setTheme, viewMode, setViewMode,
        showToast, refreshData, toggleDomain, executeQuickAction
    }), [status, domains, devices, rooms, users, quickActions, isAdmin, lang, theme, viewMode]);

    if (loading) {
        return <SplashScreen />;
    }

    if (onboardingDone === false) {
        return (
            <AppContext.Provider value={contextValue}>
                <OnboardingWizard onComplete={async () => {
                    setOnboardingDone(true);
                    await refreshData();
                }} />
            </AppContext.Provider>
        );
    }

    const navItems = [
        { section: lang === 'de' ? 'Ãœbersicht' : 'Overview' },
        { id: 'dashboard', icon: 'mdi-view-dashboard', label: 'Dashboard' },
        { section: lang === 'de' ? 'Konfiguration' : 'Configuration', adminOnly: true },
        { id: 'domains', icon: 'mdi-puzzle', label: 'Domains', adminOnly: true },
        { id: 'rooms', icon: 'mdi-door', label: lang === 'de' ? 'RÃ¤ume' : 'Rooms' },
        { id: 'devices', icon: 'mdi-devices', label: lang === 'de' ? 'GerÃ¤te' : 'Devices' },
        { id: 'users', icon: 'mdi-account-group', label: lang === 'de' ? 'Personen' : 'People', adminOnly: true },
        { section: 'System' },
        { id: 'activities', icon: 'mdi-timeline-clock', label: lang === 'de' ? 'AktivitÃ¤ten' : 'Activities' },
        { id: 'patterns', icon: 'mdi-lightbulb-on', label: lang === 'de' ? 'Muster' : 'Patterns' },
        { id: 'energy', icon: 'mdi-lightning-bolt', label: lang === 'de' ? 'Energie' : 'Energy' },
        { id: 'scenes', icon: 'mdi-palette', label: lang === 'de' ? 'Szenen' : 'Scenes' },
        { id: 'presence', icon: 'mdi-account-multiple', label: lang === 'de' ? 'Anwesenheit' : 'Presence' },
        { id: 'notifications', icon: 'mdi-bell', label: lang === 'de' ? 'Benachrichtigungen' : 'Notifications' },
        { id: 'settings', icon: 'mdi-cog', label: lang === 'de' ? 'Einstellungen' : 'Settings', adminOnly: true },
    ].filter(item => !item.adminOnly || isAdmin);

    const pages = {
        dashboard: DashboardPage,
        domains: DomainsPage,
        devices: DevicesPage,
        rooms: RoomsPage,
        users: UsersPage,
        activities: ActivitiesPage,
        patterns: PatternsPage,
        energy: EnergyPage,
        scenes: ScenesPage,
        presence: PresencePage,
        notifications: NotificationsPage,
        settings: SettingsPage,
    };

    const PageComponent = pages[page] || DashboardPage;
    const currentNav = navItems.find(n => n.id === page);
    const pageTitle = currentNav?.label || 'Dashboard';

    return (
        <AppContext.Provider value={contextValue}>
            <div className="app-layout">
                {/* Sidebar */}
                <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
                    <div className="sidebar-header">
                        <div className="sidebar-brand" onClick={() => { setPage('dashboard'); setSidebarOpen(false); }}>
                            <img src={`${API_BASE}/icon.png`} alt="MindHome" style={{ width: 36, height: 36, borderRadius: 8 }} />
                            <div>
                                <div className="sidebar-title">MindHome</div>
                                <div className="sidebar-tagline">
                                    {lang === 'de' ? 'Dein Zuhause denkt mit' : 'Your home thinks ahead'}
                                </div>
                            </div>
                        </div>
                    </div>

                    <nav className="sidebar-nav" role="navigation" aria-label="Main navigation">
                        {navItems.map((item, i) => {
                            if (item.section) {
                                return <div key={i} className="nav-section-title" role="separator">{item.section}</div>;
                            }
                            return (
                                <div
                                    key={item.id}
                                    role="button"
                                    tabIndex={0}
                                    aria-label={item.label}
                                    aria-current={page === item.id ? 'page' : undefined}
                                    className={`nav-item ${page === item.id ? 'active' : ''}`}
                                    onClick={() => { setPage(item.id); setSidebarOpen(false); }}
                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPage(item.id); setSidebarOpen(false); }}}
                                >
                                    <span className={`mdi ${item.icon}`} aria-hidden="true" />
                                    {item.label}
                                </div>
                            );
                        })}
                    </nav>

                    <div className="sidebar-footer">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-muted)' }}>
                            <span className={`connection-dot ${status?.ha_connected ? 'connected' : 'disconnected'}`} />
                            {status?.ha_connected ? 'HA Connected' : 'HA Disconnected'}
                        </div>
                    </div>
                </aside>

                {/* Mobile overlay */}
                {sidebarOpen && (
                    <div style={{
                        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
                        zIndex: 99
                    }} onClick={() => setSidebarOpen(false)} />
                )}

                {/* Main */}
                <main className="main-content">
                    <header className="main-header">
                        <div className="main-header-left">
                            <button className="menu-toggle" onClick={() => setSidebarOpen(true)}>
                                <span className="mdi mdi-menu" />
                            </button>
                            {page === 'dashboard' && (
                                <img src={`${API_BASE}/icon.png`} alt="MindHome" style={{ width: 28, height: 28, borderRadius: 6, marginRight: 8, flexShrink: 0 }} />
                            )}
                            <h1 className="page-title">{pageTitle}</h1>
                        </div>
                        <div className="main-header-right">
                            <button className="btn btn-ghost btn-icon" style={{ position: 'relative' }}
                                    onClick={() => setPage('notifications')}
                                    title={lang === 'de' ? 'Benachrichtigungen' : 'Notifications'}>
                                <span className="mdi mdi-bell-outline" style={{ fontSize: 20 }} />
                                {unreadNotifs > 0 && (
                                    <span style={{
                                        position: 'absolute', top: 2, right: 2, width: 16, height: 16,
                                        borderRadius: '50%', background: 'var(--danger)', color: '#fff',
                                        fontSize: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        fontWeight: 700
                                    }}>{unreadNotifs > 9 ? '9+' : unreadNotifs}</span>
                                )}
                            </button>
                            <button className="btn btn-ghost btn-icon"
                                    onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
                                    title={theme === 'dark' ? 'Light Mode' : 'Dark Mode'}>
                                <span className={`mdi ${theme === 'dark' ? 'mdi-weather-sunny' : 'mdi-weather-night'}`} style={{ fontSize: 20 }} />
                            </button>
                            <button className="btn btn-ghost btn-icon"
                                    onClick={() => setViewMode(v => v === 'simple' ? 'advanced' : 'simple')}
                                    title={viewMode === 'simple' ? 'Advanced' : 'Simple'}>
                                <span className={`mdi ${viewMode === 'simple' ? 'mdi-tune' : 'mdi-tune-variant'}`} style={{ fontSize: 20 }} />
                            </button>
                        </div>
                    </header>

                    <div className="main-body" role="main" aria-label="Page content">
                        <PageComponent />
                    </div>
                </main>
            </div>

            {/* Toast */}
            {/* #8 Stacked Toasts */}
            <div style={{ position: 'fixed', bottom: 20, right: 20, zIndex: 9999, display: 'flex', flexDirection: 'column-reverse', gap: 8 }}>
                {toasts.map((t, i) => (
                    <Toast key={t.id} message={t.message} type={t.type} onClose={() => setToasts(prev => prev.filter(x => x.id !== t.id))} />
                ))}
            </div>
        </AppContext.Provider>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)

// ================================================================
// Mount App
// ================================================================

// ================================================================
// #9 Mobile Responsive + #50 Animations + #17 Skeleton + #67 High Contrast CSS
// ================================================================
(() => {
    const style = document.createElement('style');
    style.textContent = `
        /* #17 Skeleton pulse */
        @keyframes pulse {
            0%, 100% { opacity: 0.4; }
            50% { opacity: 0.8; }
        }
        .skeleton-pulse { animation: pulse 1.5s ease-in-out infinite; }

        /* #50 Smooth transitions */
        .card { transition: transform 0.15s, box-shadow 0.15s; }
        .card:hover { transform: translateY(-1px); }
        .nav-item { transition: background 0.15s, color 0.15s, transform 0.1s; }
        .btn { transition: background 0.15s, transform 0.1s; }
        .btn:active { transform: scale(0.97); }
        .badge { transition: background 0.2s; }

        /* #9 Mobile Responsive */
        @media (max-width: 768px) {
            .sidebar { position: fixed !important; z-index: 1000; transform: translateX(-100%); transition: transform 0.25s; }
            .sidebar.open { transform: translateX(0); }
            .main-content { margin-left: 0 !important; }
            .stat-grid { grid-template-columns: 1fr 1fr !important; }
            .mobile-header { display: flex !important; }
            .table-container { overflow-x: auto; }
            table { min-width: 500px; }
        }
        @media (max-width: 480px) {
            .stat-grid { grid-template-columns: 1fr !important; }
        }

        /* #67 High Contrast Mode */
        @media (prefers-contrast: high) {
            :root, [data-theme="dark"] {
                --border-color: #888 !important;
                --text-primary: #fff !important;
                --text-secondary: #ddd !important;
            }
            [data-theme="light"] {
                --border-color: #333 !important;
                --text-primary: #000 !important;
                --text-secondary: #222 !important;
            }
            .btn { border: 1px solid currentColor !important; }
            .card { border: 1px solid var(--border-color) !important; }
        }

        /* #66 Focus visible for keyboard nav */
        :focus-visible { outline: 2px solid var(--accent-primary) !important; outline-offset: 2px; }
        .nav-item:focus-visible { background: var(--bg-tertiary); }

        /* Toast position fix for stacking */
        .toast { position: relative !important; bottom: auto !important; right: auto !important; }
    `;
    document.head.appendChild(style);
})();


ReactDOM.createRoot(document.getElementById('root')).render(
    React.createElement(ErrorBoundary, null, React.createElement(App))
);
