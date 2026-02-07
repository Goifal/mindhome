// ================================================================
// MindHome - React Frontend Application
// ================================================================

const { useState, useEffect, useCallback, createContext, useContext, useRef } = React;

// ================================================================
// API Helper
// ================================================================

const getBasePath = () => {
    const path = window.location.pathname;
    const ingressMatch = path.match(/\/api\/hassio_ingress\/[^/]+/);
    if (ingressMatch) return ingressMatch[0];
    return '';
};

const API_BASE = getBasePath();

const api = {
    async get(endpoint) {
        try {
            const res = await fetch(`${API_BASE}/api/${endpoint}`);
            if (!res.ok) throw new Error(`API Error: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error(`GET ${endpoint} failed:`, e);
            return null;
        }
    },
    async post(endpoint, data = {}) {
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
// App Context
// ================================================================

const AppContext = createContext();

const useApp = () => useContext(AppContext);

// ================================================================
// Toast Notifications
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
// Modal Component
// ================================================================

const Modal = ({ title, children, onClose, actions, wide }) => (
    <div className="modal-overlay" onClick={onClose}>
        <div className="modal" onClick={e => e.stopPropagation()} style={wide ? { maxWidth: 700, width: '90%' } : {}}>
            <div className="modal-title">{title}</div>
            {children}
            {actions && <div className="modal-actions">{actions}</div>}
        </div>
    </div>
);

// ================================================================
// Fix 11: Splash Screen
// ================================================================

const SplashScreen = () => (
    <div style={{
        position: 'fixed', inset: 0, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 20,
        background: 'linear-gradient(135deg, #0D1117 0%, #161B22 50%, #1A1F2B 100%)', zIndex: 9999
    }}>
        <div style={{
            width: 72, height: 72, borderRadius: 18,
            background: 'linear-gradient(135deg, #F5A623, #E8912D)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 40px rgba(245,166,35,0.3)', animation: 'pulse 2s ease-in-out infinite'
        }}>
            <span className="mdi mdi-lightbulb-on" style={{ fontSize: 36, color: '#fff' }} />
        </div>
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
                    {danger ? 'Löschen' : 'Bestätigen'}
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
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', userSelect: 'none'
            }}>
                <span style={{ color: selected ? 'var(--text-primary)' : 'var(--text-muted)' }}>{selected?.label || placeholder || '— Auswählen —'}</span>
                <span className={`mdi mdi-chevron-${open ? 'up' : 'down'}`} style={{ fontSize: 18, color: 'var(--text-muted)' }} />
            </div>
            {open && (
                <div style={{
                    position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4,
                    background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)',
                    zIndex: 1000, maxHeight: 240, overflow: 'auto'
                }}>
                    {options.map(opt => (
                        <div key={opt.value} onClick={() => { onChange(opt.value); setOpen(false); }}
                             style={{ padding: '10px 14px', cursor: 'pointer', fontSize: 14,
                                 background: String(opt.value) === String(value) ? 'var(--accent-primary-dim)' : 'transparent',
                                 borderLeft: String(opt.value) === String(value) ? '3px solid var(--accent-primary)' : '3px solid transparent'
                             }}>
                            {opt.label}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

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

// Fix 13: Relative time helper
const relativeTime = (isoStr, lang) => {
    if (!isoStr) return lang === 'de' ? 'Keine Aktivität' : 'No activity';
    const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 60) return lang === 'de' ? 'Gerade eben' : 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)} Min`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} Std`;
    return `${Math.floor(diff / 86400)} ${lang === 'de' ? 'Tage' : 'days'}`;
};

const stateDisplay = (state) => {
    if (!state || state === 'unknown') return { label: '?', color: 'var(--text-muted)' };
    if (state === 'on') return { label: 'on', color: 'var(--success)' };
    if (state === 'off') return { label: 'off', color: 'var(--text-muted)' };
    if (state === 'unavailable') return { label: '✕', color: 'var(--danger)' };
    return { label: state, color: 'var(--info)' };
};

const formatBytes = (bytes) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

// ================================================================
// Dashboard Page
// ================================================================

const DashboardPage = () => {
    const { status, domains, devices, rooms, lang, tr, showToast } = useApp();
    const [learningStats, setLearningStats] = useState(null);
    const [predictions, setPredictions] = useState([]);
    const [anomalies, setAnomalies] = useState([]);
    const [unreadCount, setUnreadCount] = useState(0);
    const activeDomains = domains.filter(d => d.is_enabled).length;
    const trackedDevices = devices.length;

    useEffect(() => {
        api.get('stats/learning').then(setLearningStats).catch(() => {});
        api.get('predictions?status=pending&limit=5').then(setPredictions).catch(() => {});
        api.get('automation/anomalies').then(setAnomalies).catch(() => {});
        api.get('notifications/unread-count').then(d => setUnreadCount(d.unread_count || 0)).catch(() => {});
    }, []);

    const modeLabels = {
        normal: { de: 'Normal', en: 'Normal', color: 'success' },
        away: { de: 'Abwesend', en: 'Away', color: 'info' },
        guest: { de: 'Gäste-Modus', en: 'Guest Mode', color: 'info' },
        vacation: { de: 'Urlaubsmodus', en: 'Vacation', color: 'warning' },
        emergency_stop: { de: 'NOT-AUS', en: 'EMERGENCY STOP', color: 'danger' }
    };

    const mode = modeLabels[status?.system_mode] || modeLabels.normal;

    return (
        <div>
            {/* Status Bar */}
            <div className="stat-grid">
                <div className="stat-card animate-in">
                    <div className="stat-icon" style={{ background: 'var(--success-dim)', color: 'var(--success)' }}>
                        <span className="mdi mdi-home-assistant" />
                    </div>
                    <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span className={`connection-dot ${status?.ha_connected ? 'connected' : 'disconnected'}`} />
                            <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                                {status?.ha_connected
                                    ? (lang === 'de' ? 'Verbunden' : 'Connected')
                                    : (lang === 'de' ? 'Getrennt' : 'Disconnected')}
                            </span>
                        </div>
                        <div className="stat-label">Home Assistant</div>
                    </div>
                </div>

                <div className="stat-card animate-in animate-in-delay-1">
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

                <div className="stat-card animate-in animate-in-delay-2">
                    <div className="stat-icon" style={{ background: 'var(--accent-primary-dim)', color: 'var(--accent-primary)' }}>
                        <span className="mdi mdi-puzzle" />
                    </div>
                    <div>
                        <div className="stat-value">{activeDomains}</div>
                        <div className="stat-label">{lang === 'de' ? 'Aktive Domains' : 'Active Domains'}</div>
                    </div>
                </div>

                <div className="stat-card animate-in animate-in-delay-3">
                    <div className="stat-icon" style={{ background: 'var(--accent-secondary-dim)', color: 'var(--accent-secondary)' }}>
                        <span className="mdi mdi-devices" />
                    </div>
                    <div>
                        <div className="stat-value">{trackedDevices}</div>
                        <div className="stat-label">{lang === 'de' ? 'Geräte' : 'Devices'}</div>
                    </div>
                </div>
            </div>

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
                                {learningStats.avg_confidence ? `${Math.round(learningStats.avg_confidence * 100)}%` : '—'}
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                {lang === 'de' ? 'Ø Vertrauen' : 'Avg Confidence'}
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
                                {lang === 'de' ? 'Vorschläge' : 'Suggestions'}
                                <span className="badge badge-warning" style={{ marginLeft: 8 }}>{predictions.length}</span>
                            </div>
                            <div className="card-subtitle">
                                {lang === 'de' ? 'MindHome hat neue Muster erkannt' : 'MindHome found new patterns'}
                            </div>
                        </div>
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
                                }} title={lang === 'de' ? 'Später' : 'Later'}>
                                    <span className="mdi mdi-clock-outline" />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Phase 2b: Anomaly Alerts */}
            {anomalies.length > 0 && (
                <div className="card animate-in" style={{ marginBottom: 24, borderLeft: '3px solid var(--danger)' }}>
                    <div className="card-header">
                        <div className="card-title">
                            <span className="mdi mdi-alert-circle" style={{ marginRight: 8, color: 'var(--danger)' }} />
                            {lang === 'de' ? 'Ungewöhnliche Aktivität' : 'Unusual Activity'}
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

            {/* Rooms Overview */}
            <div className="card animate-in animate-in-delay-3">
                <div className="card-header">
                    <div>
                        <div className="card-title">{lang === 'de' ? 'Räume' : 'Rooms'}</div>
                        <div className="card-subtitle">
                            {rooms.length} {lang === 'de' ? 'konfiguriert' : 'configured'}
                        </div>
                    </div>
                </div>
                {rooms.length === 0 ? (
                    <div className="empty-state">
                        <span className="mdi mdi-door-open" />
                        <h3>{lang === 'de' ? 'Keine Räume' : 'No Rooms'}</h3>
                        <p>{lang === 'de'
                            ? 'Starte den Einrichtungsassistenten um Räume hinzuzufügen.'
                            : 'Start the setup wizard to add rooms.'}</p>
                    </div>
                ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
                        {rooms.map(room => (
                            <div key={room.id} className="card" style={{ padding: 14 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                                    <span className={`mdi ${room.icon || 'mdi-door'}`}
                                          style={{ fontSize: 22, color: 'var(--accent-primary)' }} />
                                    <div>
                                        <div style={{ fontWeight: 600, fontSize: 14 }}>{room.name}</div>
                                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                            {room.device_count} {lang === 'de' ? 'Geräte' : 'devices'}
                                        </div>
                                    </div>
                                </div>
                                {/* Fix 13: Last activity */}
                                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
                                    <span className="mdi mdi-clock-outline" style={{ marginRight: 4 }} />
                                    {relativeTime(room.last_activity, lang)}
                                </div>
                                {room.domain_states?.length > 0 && (
                                    <div className="phase-bar">
                                        {room.domain_states.map((ds, i) => (
                                            <div key={i} className={`phase-segment ${
                                                ds.learning_phase === 'autonomous' ? 'completed' :
                                                ds.learning_phase === 'suggesting' ? 'active' : ''
                                            }`} />
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};

// ================================================================
// Quick Actions Component
// ================================================================

const QuickActionsGrid = () => {
    const { quickActions, executeQuickAction, lang } = useApp();

    return (
        <div className="quick-actions-grid">
            {quickActions.map(action => (
                <button
                    key={action.id}
                    className={`quick-action-btn ${action.action_data?.type === 'emergency_stop' ? 'danger' : ''}`}
                    onClick={() => executeQuickAction(action.id)}
                >
                    <span className={`mdi ${action.icon}`} />
                    {action.name}
                </button>
            ))}
        </div>
    );
};

// ================================================================
// Domains Page
// ================================================================

const DomainsPage = () => {
    const { domains, toggleDomain, lang, showToast, refreshData } = useApp();
    const [showCreate, setShowCreate] = useState(false);
    const [newDomain, setNewDomain] = useState({ name_de: '', name_en: '', icon: 'mdi:puzzle', description: '' });
    const [confirmDel, setConfirmDel] = useState(null);

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
            refreshData();
        }
    };

    const handleDeleteDomain = async () => {
        if (!confirmDel) return;
        const result = await api.delete(`domains/${confirmDel.id}`);
        if (result?.success) {
            showToast(lang === 'de' ? 'Domain gelöscht' : 'Domain deleted', 'success');
            setConfirmDel(null);
            refreshData();
        } else {
            showToast(result?.error || 'Error', 'error');
        }
    };

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
                    {lang === 'de'
                        ? 'Aktiviere die Bereiche die MindHome überwachen und steuern soll.'
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
                        onClick={() => toggleDomain(domain.id)}
                    >
                        <span className={`mdi ${domain.icon}`} />
                        <div className="domain-card-info">
                            <div className="domain-card-name">{domain.display_name}</div>
                            <div className="domain-card-desc">{domain.description}</div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            {domain.is_custom && (
                                <button className="btn btn-ghost btn-icon"
                                    onClick={e => { e.stopPropagation(); setConfirmDel(domain); }}
                                    title={lang === 'de' ? 'Löschen' : 'Delete'}>
                                    <span className="mdi mdi-delete-outline" style={{ fontSize: 16, color: 'var(--danger)' }} />
                                </button>
                            )}
                            <label className="toggle" onClick={e => e.stopPropagation()}>
                                <input type="checkbox" checked={domain.is_enabled}
                                       onChange={() => toggleDomain(domain.id)} />
                                <div className="toggle-slider" />
                            </label>
                        </div>
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
                            placeholder={lang === 'de' ? 'z.B. Bewässerung' : 'e.g. Irrigation'} />
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
                    title={lang === 'de' ? 'Domain löschen' : 'Delete Domain'}
                    message={lang === 'de' ? `"${confirmDel.display_name}" wirklich löschen?` : `Delete "${confirmDel.display_name}"?`}
                    danger onConfirm={handleDeleteDomain} onCancel={() => setConfirmDel(null)} />
            )}
        </div>
    );
};

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
            showToast(lang === 'de' ? 'Keine Geräte ausgewählt' : 'No devices selected', 'error');
            return;
        }
        const result = await api.post('discover/import', {
            domains: discovered.domains,
            selected_entities: selectedIds
        });
        if (result?.success) {
            showToast(lang === 'de' ? `${result.imported} Geräte importiert` : `${result.imported} devices imported`, 'success');
            setDiscovered(null);
            setSelected({});
            refreshData();
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
            showToast(lang === 'de' ? 'Gerät hinzugefügt' : 'Device added', 'success');
            refreshData();
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
            showToast(lang === 'de' ? 'Gerät entfernt' : 'Device removed', 'success');
            setConfirmDel(null);
            refreshData();
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
            showToast(lang === 'de' ? 'Gerät aktualisiert' : 'Device updated', 'success');
            setEditDevice(null);
            refreshData();
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
            refreshData();
        }
    };

    const handleBulkDelete = async () => {
        const ids = Object.keys(bulkSelected).filter(k => bulkSelected[k]).map(Number);
        const result = await api.delete('devices/bulk', { device_ids: ids });
        if (result?.success) {
            showToast(lang === 'de' ? `${result.deleted} gelöscht` : `${result.deleted} deleted`, 'success');
            setConfirmBulkDel(false);
            setBulkSelected({});
            refreshData();
        }
    };

    const selectedCount = Object.values(selected).filter(Boolean).length;
    const importedEntityIds = new Set(devices.map(d => d.ha_entity_id));

    const getDomainName = (domainId) => domains.find(d => d.id === domainId)?.display_name || '—';
    const getRoomName = (roomId) => rooms.find(r => r.id === roomId)?.name || '—';

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
                    {devices.length} {lang === 'de' ? 'Geräte konfiguriert' : 'devices configured'}
                </p>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn btn-secondary" onClick={handleOpenManual}>
                        <span className="mdi mdi-magnify-plus-outline" />
                        {lang === 'de' ? 'Manuell' : 'Manual'}
                    </button>
                    <button className="btn btn-primary" onClick={handleDiscover} disabled={discovering}>
                        <span className="mdi mdi-magnify" />
                        {discovering ? (lang === 'de' ? 'Suche...' : 'Searching...') : (lang === 'de' ? 'Geräte erkennen' : 'Discover')}
                    </button>
                </div>
            </div>

            {/* Bulk Actions Bar */}
            {bulkCount > 0 && (
                <div className="card" style={{ marginBottom: 16, padding: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    borderColor: 'var(--accent-primary)', background: 'var(--accent-primary-dim)' }}>
                    <span style={{ fontWeight: 600, fontSize: 14 }}>
                        {bulkCount} {lang === 'de' ? 'ausgewählt' : 'selected'}
                    </span>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <button className="btn btn-secondary" onClick={() => setBulkSelected({})}>{lang === 'de' ? 'Aufheben' : 'Deselect'}</button>
                        <button className="btn btn-primary" onClick={() => setShowBulkEdit(true)}>
                            <span className="mdi mdi-pencil" /> {lang === 'de' ? 'Bearbeiten' : 'Edit'}
                        </button>
                        <button className="btn btn-danger" onClick={() => setConfirmBulkDel(true)}>
                            <span className="mdi mdi-delete" /> {lang === 'de' ? 'Löschen' : 'Delete'}
                        </button>
                    </div>
                </div>
            )}

            {/* Discovery Results */}
            {discovered && (
                <div className="card" style={{ marginBottom: 20, borderColor: 'var(--accent-primary)', borderWidth: 2 }}>
                    <div className="card-header">
                        <div>
                            <div className="card-title">{lang === 'de' ? 'Verfügbare Geräte' : 'Available Devices'}</div>
                            <div className="card-subtitle">{selectedCount} {lang === 'de' ? 'ausgewählt' : 'selected'}</div>
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
                        <input className="input" placeholder={lang === 'de' ? '🔍 Geräte suchen...' : '🔍 Search devices...'}
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
                                if (attrs.brightness_pct != null) attrParts.push(`☀ ${attrs.brightness_pct}%`);
                                if (attrs.position_pct != null) attrParts.push(`↕ ${attrs.position_pct}%`);
                                if (attrs.current_temp != null) attrParts.push(`🌡 ${attrs.current_temp}${unit || '°C'}`);
                                if (attrs.target_temp != null) attrParts.push(`→ ${attrs.target_temp}${unit || '°C'}`);
                                if (attrs.humidity != null) attrParts.push(`💧 ${attrs.humidity}%`);
                                if (attrs.power != null || attrs.current_power_w != null) attrParts.push(`⚡ ${attrs.power || attrs.current_power_w} W`);
                                if (attrs.voltage != null) attrParts.push(`🔌 ${attrs.voltage} V`);
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
                                            <div style={{ fontSize: isSensorValue ? 12 : 11, color: isSensorValue ? 'var(--info)' : 'var(--text-muted)', marginTop: isSensorValue ? 0 : 2, fontWeight: isSensorValue ? 600 : 400 }}>{attrParts.join(' · ')}</div>
                                        )}
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: 4 }}>
                                            <button className="btn btn-ghost btn-icon" onClick={() => setEditDevice({...device})}>
                                                <span className="mdi mdi-pencil" style={{ fontSize: 16, color: 'var(--accent-primary)' }} />
                                            </button>
                                            <button className="btn btn-ghost btn-icon" onClick={() => setConfirmDel(device)}>
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
                    <h3>{lang === 'de' ? 'Keine Geräte' : 'No Devices'}</h3>
                    <p>{lang === 'de' ? 'Klicke auf "Geräte erkennen" um deine HA-Geräte zu importieren.' : 'Click "Discover" to import your HA devices.'}</p>
                </div>
            )}

            {/* Manual Search Modal */}
            {showManual && (
                <Modal title={lang === 'de' ? 'Manuelle Gerätesuche' : 'Manual Device Search'} onClose={() => setShowManual(false)} wide>
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
                <Modal title={lang === 'de' ? 'Gerät bearbeiten' : 'Edit Device'} onClose={() => setEditDevice(null)}
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
                        <label className="input-label">{lang === 'de' ? 'Raum' : 'Room'}</label>
                        <select className="input" value={editDevice.room_id || ''} onChange={e => setEditDevice({ ...editDevice, room_id: e.target.value ? parseInt(e.target.value) : null })}>
                            <option value="">{lang === 'de' ? '— Kein Raum —' : '— No Room —'}</option>
                            {rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                        </select>
                    </div>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">Domain</label>
                        <select className="input" value={editDevice.domain_id || ''} onChange={e => setEditDevice({ ...editDevice, domain_id: e.target.value ? parseInt(e.target.value) : null })}>
                            <option value="">{lang === 'de' ? '— Keine —' : '— None —'}</option>
                            {domains.map(d => <option key={d.id} value={d.id}>{d.display_name}</option>)}
                        </select>
                    </div>
                    <div style={{ display: 'flex', gap: 24 }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 14 }}>
                            <input type="checkbox" checked={editDevice.is_tracked} onChange={e => setEditDevice({ ...editDevice, is_tracked: e.target.checked })}
                                style={{ width: 18, height: 18, accentColor: 'var(--accent-primary)' }} />
                            {lang === 'de' ? 'Überwacht' : 'Tracked'}
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
                <Modal title={lang === 'de' ? `${bulkCount} Geräte bearbeiten` : `Edit ${bulkCount} Devices`} onClose={() => setShowBulkEdit(false)}
                    actions={<>
                        <button className="btn btn-secondary" onClick={() => setShowBulkEdit(false)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                        <button className="btn btn-primary" onClick={handleBulkEdit}>{lang === 'de' ? 'Anwenden' : 'Apply'}</button>
                    </>}>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">{lang === 'de' ? 'Raum zuweisen' : 'Assign Room'}</label>
                        <select className="input" value={bulkRoom} onChange={e => setBulkRoom(e.target.value)}>
                            <option value="">{lang === 'de' ? '— Nicht ändern —' : '— No change —'}</option>
                            {rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                        </select>
                    </div>
                    <div className="input-group">
                        <label className="input-label">{lang === 'de' ? 'Domain zuweisen' : 'Assign Domain'}</label>
                        <select className="input" value={bulkDomain} onChange={e => setBulkDomain(e.target.value)}>
                            <option value="">{lang === 'de' ? '— Nicht ändern —' : '— No change —'}</option>
                            {domains.map(d => <option key={d.id} value={d.id}>{d.display_name}</option>)}
                        </select>
                    </div>
                </Modal>
            )}

            {/* Confirm Delete */}
            {confirmDel && (
                <ConfirmDialog title={lang === 'de' ? 'Gerät entfernen' : 'Remove Device'}
                    message={lang === 'de' ? `"${confirmDel.name}" wirklich entfernen?` : `Remove "${confirmDel.name}"?`}
                    danger onConfirm={handleDeleteDevice} onCancel={() => setConfirmDel(null)} />
            )}
            {confirmBulkDel && (
                <ConfirmDialog title={lang === 'de' ? `${bulkCount} Geräte löschen` : `Delete ${bulkCount} Devices`}
                    message={lang === 'de' ? 'Dies kann nicht rückgängig gemacht werden.' : 'This cannot be undone.'}
                    danger onConfirm={handleBulkDelete} onCancel={() => setConfirmBulkDel(false)} />
            )}
        </div>
    );
};


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
            refreshData();
        }
    };

    const handleUpdate = async () => {
        if (!editRoom || !editRoom.name.trim()) return;
        const result = await api.put(`rooms/${editRoom.id}`, { name: editRoom.name, icon: editRoom.icon });
        if (result?.id) {
            showToast(lang === 'de' ? 'Raum aktualisiert' : 'Room updated', 'success');
            setEditRoom(null);
            refreshData();
        }
    };

    const handleDelete = async (room) => {
        setConfirm({ id: room.id, name: room.name, count: room.device_count });
    };

    const confirmDelete = async () => {
        const result = await api.delete(`rooms/${confirm.id}`);
        if (result?.success) { showToast(lang === 'de' ? 'Raum gelöscht' : 'Room deleted', 'success'); refreshData(); }
        setConfirm(null);
    };

    // Fix 9: Import rooms from HA
    const handleImportFromHA = async () => {
        setImporting(true);
        const result = await api.post('rooms/import-from-ha');
        if (result?.success) {
            showToast(lang === 'de' ? `${result.imported} importiert, ${result.skipped} übersprungen` : `${result.imported} imported, ${result.skipped} skipped`,
                result.imported > 0 ? 'success' : 'info');
            refreshData();
        } else { showToast(result?.error || 'Import failed', 'error'); }
        setImporting(false);
    };

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20, flexWrap: 'wrap', gap: 8 }}>
                <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
                    {rooms.length} {lang === 'de' ? 'Räume' : 'Rooms'}
                </p>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn btn-secondary" onClick={handleImportFromHA} disabled={importing}>
                        <span className="mdi mdi-home-import-outline" />
                        {importing ? '...' : (lang === 'de' ? 'Aus HA importieren' : 'Import from HA')}
                    </button>
                    <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
                        <span className="mdi mdi-plus" />
                        {lang === 'de' ? 'Raum hinzufügen' : 'Add Room'}
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
                                            {room.device_count} {lang === 'de' ? 'Geräte' : 'devices'}
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
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                                        {room.domain_states.map((ds, i) => {
                                            const phase = phaseLabels[ds.learning_phase] || phaseLabels.observing;
                                            const dom = domains.find(d => d.id === ds.domain_id);
                                            const domName = dom?.display_name || '?';
                                            const domIcon = dom?.icon?.replace('mdi:', 'mdi-') || 'mdi-puzzle';
                                            const nextPhase = ds.learning_phase === 'observing' ? 'suggesting' : ds.learning_phase === 'suggesting' ? 'autonomous' : 'observing';
                                            const nextLabel = phaseLabels[nextPhase]?.[lang] || nextPhase;
                                            return (
                                                <span key={i} className={`badge badge-${phase.color}`}
                                                    style={{ fontSize: 11, cursor: 'pointer' }}
                                                    title={`${domName}: ${phase[lang]} → ${lang === 'de' ? 'Klick' : 'Click'}: ${nextLabel}`}
                                                    onClick={async () => {
                                                        await api.put(`phases/${room.id}/${ds.domain_id}`, { phase: nextPhase });
                                                        showToast(`${domName}: ${nextLabel}`, 'success');
                                                        refreshData();
                                                    }}>
                                                    <span className={`mdi ${domIcon}`} style={{ marginRight: 4, fontSize: 12 }} />
                                                    {domName}: {phase[lang]}
                                                </span>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            ) : (
                <div className="empty-state">
                    <span className="mdi mdi-door-open" />
                    <h3>{lang === 'de' ? 'Keine Räume' : 'No Rooms'}</h3>
                    <p>{lang === 'de'
                        ? 'Füge Räume hinzu um MindHome zu konfigurieren.'
                        : 'Add rooms to configure MindHome.'}</p>
                </div>
            )}

            {/* Add Room Modal */}
            {showAdd && (
                <Modal
                    title={lang === 'de' ? 'Raum hinzufügen' : 'Add Room'}
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
                    title={lang === 'de' ? 'Raum löschen?' : 'Delete room?'}
                    message={lang === 'de'
                        ? `"${confirm.name}" mit ${confirm.count} Geräten wird gelöscht.`
                        : `"${confirm.name}" with ${confirm.count} devices will be deleted.`}
                    danger onConfirm={confirmDelete} onCancel={() => setConfirm(null)} />
            )}
        </div>
    );
};

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
            refreshData();
        }
    };

    const handleDelete = async (id) => {
        const result = await api.delete(`users/${id}`);
        if (result?.success) {
            showToast(lang === 'de' ? 'Person entfernt' : 'Person removed', 'success');
            refreshData();
        }
    };

    const handleAssignPerson = async (userId, haEntity) => {
        const result = await api.put(`users/${userId}`, { ha_person_entity: haEntity || null });
        if (result?.id) {
            showToast(lang === 'de' ? 'HA-Person zugewiesen' : 'HA person assigned', 'success');
            refreshData();
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
                    {lang === 'de' ? 'Person hinzufügen' : 'Add Person'}
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
                                                ? `🔗 ${user.ha_person_entity}`
                                                : (lang === 'de' ? '⚠️ Keine HA-Person' : '⚠️ No HA person')}
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
                    <p>{lang === 'de' ? 'Füge Personen hinzu die MindHome nutzen.' : 'Add people who use MindHome.'}</p>
                </div>
            )}

            {showAdd && (
                <Modal title={lang === 'de' ? 'Person hinzufügen' : 'Add Person'} onClose={() => setShowAdd(false)}
                    actions={<><button className="btn btn-secondary" onClick={() => setShowAdd(false)}>{lang === 'de' ? 'Abbrechen' : 'Cancel'}</button>
                        <button className="btn btn-primary" onClick={handleAdd}>{lang === 'de' ? 'Erstellen' : 'Create'}</button></>}>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">{lang === 'de' ? 'Name' : 'Name'}</label>
                        <input className="input" value={newUser.name} onChange={e => setNewUser({ ...newUser, name: e.target.value })} autoFocus />
                    </div>
                    <div className="input-group" style={{ marginBottom: 16 }}>
                        <label className="input-label">{lang === 'de' ? 'Rolle' : 'Role'}</label>
                        <select className="input" value={newUser.role} onChange={e => setNewUser({ ...newUser, role: e.target.value })}>
                            <option value="user">{lang === 'de' ? 'Benutzer' : 'User'}</option>
                            <option value="admin">Administrator</option>
                        </select>
                    </div>
                    <div className="input-group">
                        <label className="input-label">{lang === 'de' ? 'HA-Person' : 'HA Person'}</label>
                        <select className="input" value={newUser.ha_person_entity} onChange={e => setNewUser({ ...newUser, ha_person_entity: e.target.value })}>
                            <option value="">{lang === 'de' ? '— Keine —' : '— None —'}</option>
                            {haPersons.map(p => <option key={p.entity_id} value={p.entity_id}>{p.name} ({p.entity_id})</option>)}
                        </select>
                    </div>
                </Modal>
            )}

            {editingUser && (
                <Modal title={lang === 'de' ? `HA-Person: ${editingUser.name}` : `HA Person: ${editingUser.name}`} onClose={() => setEditingUser(null)}
                    actions={<button className="btn btn-secondary" onClick={() => setEditingUser(null)}>{lang === 'de' ? 'Schließen' : 'Close'}</button>}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <div style={{ padding: '10px 14px', borderRadius: 8, cursor: 'pointer',
                            border: !editingUser.ha_person_entity ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
                            background: !editingUser.ha_person_entity ? 'var(--accent-primary-dim)' : 'transparent'
                        }} onClick={() => handleAssignPerson(editingUser.id, '')}>
                            {lang === 'de' ? '— Keine Person —' : '— No Person —'}
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
// Settings Page
// ================================================================

const SettingsPage = () => {
    const { lang, setLang, theme, setTheme, viewMode, setViewMode, showToast, refreshData } = useApp();
    const [sysInfo, setSysInfo] = useState(null);
    const [retention, setRetention] = useState(90);
    const [retentionInput, setRetentionInput] = useState('90');
    const [cleaning, setCleaning] = useState(false);
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
            showToast(lang === 'de' ? `${result.deleted || 0} Einträge gelöscht` : `${result.deleted || 0} entries deleted`, 'success');
            const info = await api.get('system/info');
            if (info) setSysInfo(info);
        }
        setCleaning(false);
    };

    const handleExport = async () => {
        const backup = await api.get('backup/export');
        if (backup) {
            const blob = new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `mindhome-backup-${new Date().toISOString().slice(0,10)}.json`;
            a.click();
            URL.revokeObjectURL(url);
            showToast(lang === 'de' ? 'Backup exportiert' : 'Backup exported', 'success');
        }
    };

    const handleImport = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        try {
            const text = await file.text();
            const data = JSON.parse(text);
            const result = await api.post('backup/import', data);
            if (result?.success) {
                showToast(lang === 'de'
                    ? `Backup geladen: ${result.imported.rooms} Räume, ${result.imported.devices} Geräte, ${result.imported.users} Personen`
                    : `Backup loaded: ${result.imported.rooms} rooms, ${result.imported.devices} devices, ${result.imported.users} users`,
                    'success');
                refreshData();
            } else {
                showToast(result?.error || 'Import failed', 'error');
            }
        } catch (err) {
            showToast(lang === 'de' ? 'Ungültige Datei' : 'Invalid file', 'error');
        }
        e.target.value = '';
    };

    const InfoRow = ({ label, value }) => (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14 }}>
            <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{value}</span>
        </div>
    );

    return (
        <div style={{ maxWidth: 600 }}>
            {/* Appearance */}
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>
                    {lang === 'de' ? 'Darstellung' : 'Appearance'}
                </div>

                <div className="input-group" style={{ marginBottom: 16 }}>
                    <label className="input-label">{lang === 'de' ? 'Sprache' : 'Language'}</label>
                    <select className="input" value={lang} onChange={e => setLang(e.target.value)}>
                        <option value="de">Deutsch</option>
                        <option value="en">English</option>
                    </select>
                </div>

                <div className="input-group" style={{ marginBottom: 16 }}>
                    <label className="input-label">Theme</label>
                    <select className="input" value={theme} onChange={e => setTheme(e.target.value)}>
                        <option value="dark">{lang === 'de' ? 'Dunkel' : 'Dark'}</option>
                        <option value="light">{lang === 'de' ? 'Hell' : 'Light'}</option>
                    </select>
                </div>

                <div className="input-group">
                    <label className="input-label">{lang === 'de' ? 'Ansicht' : 'View Mode'}</label>
                    <select className="input" value={viewMode} onChange={e => setViewMode(e.target.value)}>
                        <option value="simple">{lang === 'de' ? 'Einfach' : 'Simple'}</option>
                        <option value="advanced">{lang === 'de' ? 'Ausführlich' : 'Advanced'}</option>
                    </select>
                </div>
            </div>

            {/* System Info */}
            <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>
                    {lang === 'de' ? 'System' : 'System'}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <InfoRow label="Version" value={sysInfo?.version || '0.3.0'} />
                    <InfoRow label="Phase" value={`2b – ${lang === 'de' ? 'Vorschläge & Automationen' : 'Suggestions & Automations'}`} />
                    <InfoRow label="Home Assistant"
                        value={sysInfo?.ha_connected ? (lang === 'de' ? '✅ Verbunden' : '✅ Connected') : (lang === 'de' ? '❌ Getrennt' : '❌ Disconnected')} />
                    <InfoRow label={lang === 'de' ? 'HA Entities' : 'HA Entities'}
                        value={sysInfo?.ha_entity_count || '—'} />
                    <InfoRow label={lang === 'de' ? 'Datenbankgröße' : 'Database Size'}
                        value={sysInfo?.db_size_bytes ? formatBytes(sysInfo.db_size_bytes) : '—'} />
                    <InfoRow label="Uptime"
                        value={sysInfo?.uptime_seconds ? `${Math.floor(sysInfo.uptime_seconds / 3600)} h` : '—'} />
                    <InfoRow label={lang === 'de' ? 'Gesammelte Events' : 'Collected Events'}
                        value={sysInfo?.state_history_count?.toLocaleString() || '0'} />
                    <InfoRow label={lang === 'de' ? 'Erkannte Muster' : 'Detected Patterns'}
                        value={sysInfo?.pattern_count || '0'} />
                </div>
            </div>

            {/* Data Retention - only in advanced mode */}
            {viewMode === 'advanced' && (
                <div className="card" style={{ marginBottom: 16 }}>
                    <div className="card-title" style={{ marginBottom: 16 }}>
                        {lang === 'de' ? 'Daten-Aufbewahrung' : 'Data Retention'}
                    </div>
                    <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
                        {lang === 'de'
                            ? `Daten älter als ${retention} Tage werden automatisch gelöscht (FIFO).`
                            : `Data older than ${retention} days is automatically deleted (FIFO).`}
                    </p>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginBottom: 16 }}>
                        <div className="input-group" style={{ flex: 1 }}>
                            <label className="input-label">{lang === 'de' ? 'Aufbewahren für (Tage)' : 'Keep for (days)'}</label>
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
                            ? (lang === 'de' ? 'Aufräumen...' : 'Cleaning...')
                            : (lang === 'de' ? 'Jetzt aufräumen' : 'Clean Up Now')}
                    </button>
                </div>
            )}

            {/* Backup & Restore */}
            <div className="card">
                <div className="card-title" style={{ marginBottom: 16 }}>
                    {lang === 'de' ? 'Backup & Wiederherstellung' : 'Backup & Restore'}
                </div>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    <button className="btn btn-primary" onClick={handleExport}>
                        <span className="mdi mdi-download" />
                        {lang === 'de' ? 'Backup exportieren' : 'Export Backup'}
                    </button>
                    <button className="btn btn-secondary" onClick={() => fileInputRef.current?.click()}>
                        <span className="mdi mdi-upload" />
                        {lang === 'de' ? 'Backup laden' : 'Import Backup'}
                    </button>
                    <input ref={fileInputRef} type="file" accept=".json" onChange={handleImport}
                           style={{ display: 'none' }} />
                </div>
                <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 12 }}>
                    {lang === 'de'
                        ? 'Enthält: Räume, Geräte, Personen, Domains, Einstellungen, Logs und Datenbank.'
                        : 'Includes: rooms, devices, users, domains, settings, logs and database.'}
                </p>
            </div>
        </div>
    );
};

// ================================================================
// AI Log Page
// ================================================================

const LogPage = () => {
    const { lang } = useApp();
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [period, setPeriod] = useState('all');

    const loadLogs = async (p) => {
        setLoading(true);
        const data = await api.get(`action-log?limit=200&period=${p}`);
        setLogs(data || []);
        setLoading(false);
    };

    useEffect(() => { loadLogs(period); }, [period]);

    const typeIcons = {
        observation: 'mdi-eye',
        quick_action: 'mdi-lightning-bolt',
        automation: 'mdi-robot',
        suggestion: 'mdi-lightbulb-on',
        anomaly: 'mdi-alert',
        first_time: 'mdi-star-circle'
    };

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 8 }}>
                <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
                    {logs.length} {lang === 'de' ? 'Einträge' : 'entries'}
                </p>
                <PeriodFilter value={period} onChange={setPeriod} lang={lang} />
            </div>

            {loading ? (
                <div className="empty-state"><div className="loading-spinner" /></div>
            ) : logs.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {logs.map(log => {
                        const attrs = log.action_data?.new_attributes || {};
                        const attrParts = [];
                        if (attrs.brightness_pct !== undefined) attrParts.push(`💡 ${attrs.brightness_pct}%`);
                        if (attrs.position_pct !== undefined) attrParts.push(`↕ ${attrs.position_pct}%`);
                        if (attrs.target_temp !== undefined) attrParts.push(`🌡 ${attrs.target_temp}°C`);
                        if (attrs.current_temp !== undefined) attrParts.push(`Ist: ${attrs.current_temp}°C`);
                        return (
                        <div key={log.id} className="card" style={{ padding: 14, display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                            <span className={`mdi ${typeIcons[log.action_type] || 'mdi-circle-small'}`}
                                  style={{ fontSize: 22, color: log.action_type === 'automation' ? 'var(--warning)' : 'var(--accent-primary)', marginTop: 2 }} />
                            <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 14, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}>
                                    {log.reason || log.action_type}
                                    {log.action_type === 'automation' && (
                                        <span className="badge badge-warning" style={{ fontSize: 10 }}>
                                            <span className="mdi mdi-robot" style={{ marginRight: 2 }} />MindHome
                                        </span>
                                    )}
                                </div>
                                {log.action_data?.confidence && (
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>
                                        {lang === 'de' ? 'Vertrauen' : 'Confidence'}: {Math.round(log.action_data.confidence * 100)}%
                                        {log.action_data.pattern_id && ` · Pattern #${log.action_data.pattern_id}`}
                                    </div>
                                )}
                                {attrParts.length > 0 && (
                                    <div style={{ fontSize: 12, color: 'var(--accent-secondary)', marginTop: 2 }}>{attrParts.join(' · ')}</div>
                                )}
                                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                                    {new Date(log.created_at).toLocaleString(lang === 'de' ? 'de-DE' : 'en-US')}
                                </div>
                            </div>
                            {log.was_undone && (
                                <span className="badge badge-warning">{lang === 'de' ? 'Rückgängig' : 'Undone'}</span>
                            )}
                        </div>
                        );
                    })}
                </div>
            ) : (
                <div className="empty-state">
                    <span className="mdi mdi-text-box-outline" />
                    <h3>{lang === 'de' ? 'Noch keine Einträge' : 'No Entries Yet'}</h3>
                    <p>{lang === 'de'
                        ? 'Hier werden alle Aktionen von MindHome protokolliert.'
                        : 'All MindHome actions will be logged here.'}</p>
                </div>
            )}
        </div>
    );
};

// ================================================================
// Data Privacy Page + Backup
// ================================================================

const DataPage = () => {
    const { lang, showToast, refreshData, devices, domains } = useApp();
    const [dataCollections, setDataCollections] = useState([]);
    const [loading, setLoading] = useState(true);
    const [period, setPeriod] = useState('all');

    const loadData = async (p) => {
        setLoading(true);
        const data = await api.get(`data-collections?limit=200&period=${p}`);
        setDataCollections(data || []);
        setLoading(false);
    };

    useEffect(() => { loadData(period); }, [period]);

    const getDeviceName = (deviceId) => {
        const d = devices.find(d => d.id === deviceId);
        return d?.name || `#${deviceId}`;
    };

    return (
        <div>
            <div className="card" style={{ marginBottom: 16, borderColor: 'var(--success)', borderWidth: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span className="mdi mdi-shield-check" style={{ fontSize: 28, color: 'var(--success)' }} />
                    <div>
                        <div style={{ fontWeight: 600, fontSize: 15 }}>
                            {lang === 'de' ? '100% Lokal' : '100% Local'}
                        </div>
                        <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                            {lang === 'de'
                                ? 'Alle Daten werden ausschließlich auf deinem Gerät gespeichert. Backup & Wiederherstellung findest du unter Einstellungen.'
                                : 'All data is stored exclusively on your device. Backup & restore can be found in Settings.'}
                        </div>
                    </div>
                </div>
            </div>

            {/* Collected Data */}
            <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
                    <div className="card-title" style={{ marginBottom: 0 }}>
                        {lang === 'de' ? 'Gesammelte Daten' : 'Collected Data'}
                        <span style={{ fontWeight: 400, fontSize: 13, color: 'var(--text-muted)', marginLeft: 8 }}>
                            ({dataCollections.length})
                        </span>
                    </div>
                    <PeriodFilter value={period} onChange={setPeriod} lang={lang} />
                </div>
                {loading ? (
                    <div className="empty-state"><div className="loading-spinner" /></div>
                ) : dataCollections.length > 0 ? (
                    <div style={{ maxHeight: 400, overflow: 'auto' }}>
                        <table>
                            <thead>
                                <tr>
                                    <th>{lang === 'de' ? 'Zeit' : 'Time'}</th>
                                    <th>{lang === 'de' ? 'Gerät' : 'Device'}</th>
                                    <th>{lang === 'de' ? 'Typ' : 'Type'}</th>
                                    <th>{lang === 'de' ? 'Wert' : 'Value'}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {dataCollections.slice(0, 50).map((dc, i) => (
                                    <tr key={i}>
                                        <td style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                                            {new Date(dc.collected_at).toLocaleString(lang === 'de' ? 'de-DE' : 'en-US')}
                                        </td>
                                        <td style={{ fontSize: 12 }}>{getDeviceName(dc.device_id)}</td>
                                        <td><span className="badge badge-info" style={{ fontSize: 10 }}>{dc.data_type}</span></td>
                                        <td style={{ fontSize: 11, fontFamily: 'var(--font-mono)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                            {(() => {
                                                const dv = dc.data_value || {};
                                                let text = `${dv.old_state || '?'} → ${dv.new_state || '?'}`;
                                                const attrs = dv.new_attributes || {};
                                                const parts = [];
                                                if (attrs.brightness_pct !== undefined) parts.push(`${attrs.brightness_pct}%`);
                                                if (attrs.position_pct !== undefined) parts.push(`Pos ${attrs.position_pct}%`);
                                                if (attrs.target_temp !== undefined) parts.push(`${attrs.target_temp}°C`);
                                                if (parts.length) text += ` (${parts.join(', ')})`;
                                                return text;
                                            })()}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="empty-state" style={{ padding: 32 }}>
                        <span className="mdi mdi-database-outline" />
                        <h3>{lang === 'de' ? 'Noch keine Daten' : 'No Data Yet'}</h3>
                        <p>{lang === 'de'
                            ? 'Daten werden gesammelt sobald überwachte Geräte ihren Status ändern.'
                            : 'Data will be collected when tracked devices change state.'}</p>
                    </div>
                )}
            </div>
        </div>
    );
};

// ================================================================
// Phase 2a: Patterns Page (Muster-Explorer)
// ================================================================

const PatternsPage = () => {
    const { lang, viewMode, showToast } = useApp();
    const [patterns, setPatterns] = useState([]);
    const [stats, setStats] = useState(null);
    const [stateHistory, setStateHistory] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all'); // all, time_based, event_chain, correlation
    const [statusFilter, setStatusFilter] = useState(''); // observed, suggested, active, disabled
    const [showHistory, setShowHistory] = useState(false);
    const [historyEntity, setHistoryEntity] = useState('');
    const [analyzing, setAnalyzing] = useState(false);
    const [confirmDel, setConfirmDel] = useState(null);
    const [expandedId, setExpandedId] = useState(null);

    const load = async () => {
        try {
            const [pats, st] = await Promise.all([
                api.get('patterns'),
                api.get('stats/learning'),
            ]);
            setPatterns(pats);
            setStats(st);
        } catch (e) {
            console.error(e);
        }
        setLoading(false);
    };

    useEffect(() => { load(); }, []);

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
            load();
        } catch (e) { showToast('Error', 'error'); }
    };

    const deletePattern = async (id) => {
        try {
            await api.delete(`patterns/${id}`);
            showToast(lang === 'de' ? 'Muster gelöscht' : 'Pattern deleted', 'success');
            setConfirmDel(null);
            load();
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
    };

    if (loading) return <div style={{ padding: 40, textAlign: 'center' }}><span className="mdi mdi-loading mdi-spin" style={{ fontSize: 32 }} /></div>;

    return (
        <div>
            {/* Learning Stats Overview */}
            {stats && (
                <div className="stat-grid" style={{ marginBottom: 24 }}>
                    <div className="stat-card animate-in">
                        <div className="stat-icon" style={{ background: 'var(--accent-primary-dim)', color: 'var(--accent-primary)' }}>
                            <span className="mdi mdi-database-outline" />
                        </div>
                        <div>
                            <div className="stat-value">{stats.total_events?.toLocaleString() || 0}</div>
                            <div className="stat-label">{lang === 'de' ? 'Events gesammelt' : 'Events collected'}</div>
                        </div>
                    </div>
                    <div className="stat-card animate-in animate-in-delay-1">
                        <div className="stat-icon" style={{ background: 'var(--success-dim)', color: 'var(--success)' }}>
                            <span className="mdi mdi-lightbulb-on" />
                        </div>
                        <div>
                            <div className="stat-value">{stats.total_patterns || 0}</div>
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
                            <div className="stat-value">{stats.avg_confidence ? `${Math.round(stats.avg_confidence * 100)}%` : '—'}</div>
                            <div className="stat-label">{lang === 'de' ? 'Ø Vertrauen' : 'Avg Confidence'}</div>
                        </div>
                    </div>
                </div>
            )}

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
                                    <th>{lang === 'de' ? 'Alt → Neu' : 'Old → New'}</th>
                                    <th>{lang === 'de' ? 'Kontext' : 'Context'}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {stateHistory.map(ev => (
                                    <tr key={ev.id}>
                                        <td style={{ whiteSpace: 'nowrap' }}>{ev.created_at ? new Date(ev.created_at).toLocaleTimeString() : '—'}</td>
                                        <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{ev.entity_id}</td>
                                        <td>
                                            <span style={{ color: 'var(--text-muted)' }}>{ev.old_state || '?'}</span>
                                            <span style={{ margin: '0 4px' }}>→</span>
                                            <span style={{ fontWeight: 600, color: ev.new_state === 'on' ? 'var(--success)' : ev.new_state === 'off' ? 'var(--text-muted)' : 'var(--text-primary)' }}>
                                                {ev.new_state}
                                            </span>
                                        </td>
                                        <td style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                            {ev.context?.time_slot} {ev.context?.persons_home?.length > 0 ? `👤${ev.context.persons_home.length}` : ''}
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
            <div className="card animate-in">
                <div className="card-header">
                    <div>
                        <div className="card-title">
                            {lang === 'de' ? 'Erkannte Muster' : 'Detected Patterns'}
                            <span className="badge badge-info" style={{ marginLeft: 8 }}>{filtered.length}</span>
                        </div>
                    </div>
                </div>
                {filtered.length === 0 ? (
                    <div className="empty-state">
                        <span className="mdi mdi-lightbulb-on" />
                        <h3>{lang === 'de' ? 'Noch keine Muster' : 'No patterns yet'}</h3>
                        <p>{lang === 'de'
                            ? 'MindHome sammelt Daten und analysiert regelmäßig. Muster erscheinen nach einigen Tagen.'
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
                                            {p.match_count}× {lang === 'de' ? 'erkannt' : 'matched'}
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
                                            title={lang === 'de' ? 'Löschen' : 'Delete'}>
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
                                        <div><span style={{ color: 'var(--text-muted)' }}>Entity:</span> <code style={{ fontSize: 12 }}>{p.pattern_data?.entity_id || p.pattern_data?.action_entity || '–'}</code></div>
                                        <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Zielzustand' : 'Target'}:</span> <strong>{p.pattern_data?.target_state || p.action_definition?.target_state || '–'}</strong></div>
                                        {p.pattern_data?.avg_hour !== undefined && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Uhrzeit' : 'Time'}:</span> <strong>{String(p.pattern_data.avg_hour).padStart(2,'0')}:{String(p.pattern_data.avg_minute||0).padStart(2,'0')}</strong> ±{p.pattern_data.time_window_min || 15}min</div>
                                        )}
                                        {p.pattern_data?.weekday_filter && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Tage' : 'Days'}:</span> {p.pattern_data.weekday_filter === 'weekdays' ? (lang === 'de' ? 'Mo–Fr' : 'Mon–Fri') : p.pattern_data.weekday_filter === 'weekends' ? (lang === 'de' ? 'Sa–So' : 'Sat–Sun') : (lang === 'de' ? 'Alle' : 'All')}</div>
                                        )}
                                        {p.pattern_data?.sun_relative_elevation != null && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Sonnenstand' : 'Sun elevation'}:</span> {p.pattern_data.sun_relative_elevation}°</div>
                                        )}
                                        {p.pattern_data?.trigger_entity && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>Trigger:</span> <code style={{ fontSize: 12 }}>{p.pattern_data.trigger_entity}</code> → {p.pattern_data.trigger_state}</div>
                                        )}
                                        {p.pattern_data?.avg_delay_sec && (
                                            <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Verzögerung' : 'Delay'}:</span> {p.pattern_data.avg_delay_sec < 60 ? `${Math.round(p.pattern_data.avg_delay_sec)}s` : `${Math.round(p.pattern_data.avg_delay_sec/60)} min`}</div>
                                        )}
                                        <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Beobachtet' : 'Observed'}:</span> {p.pattern_data?.days_observed || 0} {lang === 'de' ? 'Tage' : 'days'}, {p.pattern_data?.occurrence_count || p.match_count || 0}× {lang === 'de' ? 'Treffer' : 'matches'}</div>
                                        <div><span style={{ color: 'var(--text-muted)' }}>{lang === 'de' ? 'Erstellt' : 'Created'}:</span> {p.created_at ? new Date(p.created_at).toLocaleDateString() : '–'}</div>
                                    </div>
                                    {p.trigger_conditions && (
                                        <details style={{ marginTop: 4 }}>
                                            <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: 12 }}>
                                                {lang === 'de' ? 'Technische Details (JSON)' : 'Technical details (JSON)'}
                                            </summary>
                                            <pre style={{ fontSize: 11, marginTop: 4, padding: 8, background: 'var(--bg-primary)', borderRadius: 4, overflow: 'auto', maxHeight: 120 }}>{JSON.stringify({ trigger: p.trigger_conditions, action: p.action_definition }, null, 2)}</pre>
                                        </details>
                                    )}
                                </div>
                            )}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Confirm delete */}
            {confirmDel && (
                <ConfirmDialog
                    title={lang === 'de' ? 'Muster löschen?' : 'Delete pattern?'}
                    message={lang === 'de' ? 'Das Muster wird unwiderruflich gelöscht.' : 'The pattern will be permanently deleted.'}
                    onConfirm={() => deletePattern(confirmDel)}
                    onCancel={() => setConfirmDel(null)}
                />
            )}
        </div>
    );
};

// ================================================================
// Phase 2b: Notifications Page
// ================================================================

const NotificationsPage = () => {
    const { lang, showToast } = useApp();
    const [notifications, setNotifications] = useState([]);
    const [loading, setLoading] = useState(true);
    const [predictions, setPredictions] = useState([]);
    const [predFilter, setPredFilter] = useState('all');

    const load = async () => {
        try {
            const [notifs, preds] = await Promise.all([
                api.get('notifications?limit=100'),
                api.get('predictions?limit=50'),
            ]);
            setNotifications(notifs);
            setPredictions(preds);
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
        load();
    };

    const rejectPred = async (id) => {
        await api.post(`predictions/${id}/reject`);
        showToast(lang === 'de' ? 'Abgelehnt' : 'Rejected', 'info');
        load();
    };

    const undoPred = async (id) => {
        const result = await api.post(`predictions/${id}/undo`);
        if (result.error) {
            showToast(result.error, 'error');
        } else {
            showToast(lang === 'de' ? 'Rückgängig gemacht' : 'Undone', 'success');
            load();
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

    return (
        <div>
            {/* Suggestions / Predictions */}
            <div className="card animate-in" style={{ marginBottom: 24 }}>
                <div className="card-header">
                    <div>
                        <div className="card-title">
                            <span className="mdi mdi-lightbulb-on" style={{ marginRight: 8, color: 'var(--warning)' }} />
                            {lang === 'de' ? 'Vorschläge & Automationen' : 'Suggestions & Automations'}
                        </div>
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                        {['all', 'pending', 'executed', 'confirmed', 'rejected', 'undone'].map(f => (
                            <button key={f} className={`btn btn-sm ${predFilter === f ? 'btn-primary' : 'btn-ghost'}`}
                                    onClick={() => setPredFilter(f)} style={{ fontSize: 12 }}>
                                {f === 'all' ? (lang === 'de' ? 'Alle' : 'All') :
                                 f === 'pending' ? (lang === 'de' ? 'Offen' : 'Pending') :
                                 f === 'executed' ? (lang === 'de' ? 'Ausgeführt' : 'Executed') :
                                 f === 'confirmed' ? (lang === 'de' ? 'Bestätigt' : 'Confirmed') :
                                 f === 'rejected' ? (lang === 'de' ? 'Abgelehnt' : 'Rejected') :
                                 f === 'undone' ? (lang === 'de' ? 'Rückgängig' : 'Undone') : f}
                            </button>
                        ))}
                    </div>
                </div>
                {filteredPreds.length === 0 ? (
                    <div className="empty-state">
                        <span className="mdi mdi-lightbulb-outline" />
                        <h3>{lang === 'de' ? 'Keine Vorschläge' : 'No suggestions'}</h3>
                        <p>{lang === 'de' ? 'Vorschläge erscheinen sobald Muster erkannt werden.' : 'Suggestions will appear once patterns are detected.'}</p>
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
                                    <button className="btn btn-sm btn-warning" onClick={() => undoPred(pred.id)} title={lang === 'de' ? 'Rückgängig' : 'Undo'}>
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
        </div>
    );
};

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
                setBackupError(lang === 'de' ? 'Ungültige Backup-Datei' : 'Invalid backup file');
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
            lang_title: 'Sprache wählen',
            lang_sub: 'In welcher Sprache soll MindHome kommunizieren?',
            admin_title: 'Dein Profil',
            admin_sub: 'Erstelle das Admin-Konto für MindHome.',
            admin_name: 'Dein Name',
            discover_title: 'Geräte erkennen',
            discover_sub: 'MindHome sucht jetzt nach allen Geräten in deinem Home Assistant.',
            discover_btn: 'Geräte suchen',
            discover_searching: 'Suche läuft...',
            discover_found: 'Geräte gefunden in',
            discover_domains: 'Bereichen',
            privacy_title: 'Datenschutz',
            privacy_sub: 'Alle deine Daten bleiben lokal auf deinem Gerät. Nichts wird an externe Server gesendet. Du hast volle Kontrolle.',
            privacy_note: 'Du kannst später pro Raum einstellen welche Daten erfasst werden.',
            done_title: 'Alles bereit!',
            done_sub: 'MindHome beginnt jetzt mit der Lernphase. Die ersten Tage beobachtet MindHome nur und sammelt Daten.',
            start: 'Los geht\'s',
            next: 'Weiter',
            back: 'Zurück',
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
                            <div className="sidebar-logo" style={{ width: 72, height: 72, fontSize: 36, margin: '0 auto 24px', boxShadow: 'var(--shadow-glow)' }}>
                                <span className="mdi mdi-lightbulb-on" />
                            </div>
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
                                        {lang === 'de' ? 'Backup-Datei wählen' : 'Choose Backup File'}
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
                                        <div>{backupData.rooms?.length || 0} {lang === 'de' ? 'Räume' : 'Rooms'} · {backupData.devices?.length || 0} {lang === 'de' ? 'Geräte' : 'Devices'} · {backupData.users?.length || 0} {lang === 'de' ? 'Personen' : 'Users'}</div>
                                    </div>
                                    <p style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>
                                        {lang === 'de'
                                            ? 'Möchtest du dieses Backup in MindHome laden?'
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
                                {[{ code: 'de', label: 'Deutsch', flag: '🇩🇪' }, { code: 'en', label: 'English', flag: '🇬🇧' }].map(opt => (
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

const App = () => {
    const [page, setPage] = useState('dashboard');
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const [lang, setLang] = useState('de');
    const [theme, setTheme] = useState('dark');
    const [viewMode, setViewMode] = useState('simple');
    const [toast, setToast] = useState(null);

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

    const showToast = (message, type = 'info') => setToast({ message, type });

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
            showToast(lang === 'de' ? 'Aktion ausgeführt' : 'Action executed', 'success');
            refreshData();
        }
    };

    const contextValue = {
        status, domains, devices, rooms, users, quickActions,
        lang, setLang, theme, setTheme, viewMode, setViewMode,
        showToast, refreshData, toggleDomain, executeQuickAction
    };

    if (loading) {
        return <SplashScreen />;
    }

    if (onboardingDone === false) {
        return (
            <AppContext.Provider value={contextValue}>
                <OnboardingWizard onComplete={() => {
                    setOnboardingDone(true);
                    refreshData();
                }} />
            </AppContext.Provider>
        );
    }

    const navItems = [
        { section: lang === 'de' ? 'Übersicht' : 'Overview' },
        { id: 'dashboard', icon: 'mdi-view-dashboard', label: 'Dashboard' },
        { section: lang === 'de' ? 'Konfiguration' : 'Configuration' },
        { id: 'domains', icon: 'mdi-puzzle', label: 'Domains' },
        { id: 'rooms', icon: 'mdi-door', label: lang === 'de' ? 'Räume' : 'Rooms' },
        { id: 'devices', icon: 'mdi-devices', label: lang === 'de' ? 'Geräte' : 'Devices' },
        { id: 'users', icon: 'mdi-account-group', label: lang === 'de' ? 'Personen' : 'People' },
        { section: 'System' },
        { id: 'log', icon: 'mdi-text-box-outline', label: 'KI-Log' },
        { id: 'patterns', icon: 'mdi-lightbulb-on', label: lang === 'de' ? 'Muster' : 'Patterns' },
        { id: 'notifications', icon: 'mdi-bell', label: lang === 'de' ? 'Benachrichtigungen' : 'Notifications' },
        { id: 'data', icon: 'mdi-shield-lock', label: lang === 'de' ? 'Datenschutz' : 'Privacy' },
        { id: 'settings', icon: 'mdi-cog', label: lang === 'de' ? 'Einstellungen' : 'Settings' },
    ];

    const pages = {
        dashboard: DashboardPage,
        domains: DomainsPage,
        devices: DevicesPage,
        rooms: RoomsPage,
        users: UsersPage,
        log: LogPage,
        patterns: PatternsPage,
        notifications: NotificationsPage,
        data: DataPage,
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
                            <div className="sidebar-logo">
                                <span className="mdi mdi-lightbulb-on" />
                            </div>
                            <div>
                                <div className="sidebar-title">MindHome</div>
                                <div className="sidebar-tagline">
                                    {lang === 'de' ? 'Dein Zuhause denkt mit' : 'Your home thinks ahead'}
                                </div>
                            </div>
                        </div>
                    </div>

                    <nav className="sidebar-nav">
                        {navItems.map((item, i) => {
                            if (item.section) {
                                return <div key={i} className="nav-section-title">{item.section}</div>;
                            }
                            return (
                                <div
                                    key={item.id}
                                    className={`nav-item ${page === item.id ? 'active' : ''}`}
                                    onClick={() => { setPage(item.id); setSidebarOpen(false); }}
                                >
                                    <span className={`mdi ${item.icon}`} />
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
                                <div className="sidebar-logo" style={{ width: 28, height: 28, fontSize: 14, marginRight: 8, flexShrink: 0 }}>
                                    <span className="mdi mdi-lightbulb-on" />
                                </div>
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

                    <div className="main-body">
                        <PageComponent />
                    </div>
                </main>
            </div>

            {/* Toast */}
            {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
        </AppContext.Provider>
    );
};

// ================================================================
// Mount App
// ================================================================

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
