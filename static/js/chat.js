const API_BASE = '/api/v1';

let currentModelKey = null;
let isProcessing = false;
let modelsData = {};
let confirmCallback = null;

let conversations = {};
let currentConversationId = null;
let currentSessionId = null;
let lastExtractionResult = null;

const CONVERSATIONS_STORAGE_KEY = 'kingdee_kb_conversations';

document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
    setupEventListeners();
});

async function initializeApp() {
    initElectronTitlebar();
    loadConversationsFromStorage();
    await loadModels();
    await loadStatistics();
    await loadCurrentModel();
    await loadSearchStatus();
    renderConversationsList();
    
    if (Object.keys(conversations).length === 0) {
        createNewConversation();
    }
}

function initElectronTitlebar() {
    const isElectron = typeof window !== 'undefined' && window.electronAPI;
    
    if (isElectron) {
        document.body.classList.add('electron-mode');
        
        document.querySelectorAll('.settings-category.electron-only').forEach(category => {
            category.style.display = 'flex';
        });
    }
}

function loadConversationsFromStorage() {
    try {
        const stored = localStorage.getItem(CONVERSATIONS_STORAGE_KEY);
        if (stored) {
            conversations = JSON.parse(stored);
        }
    } catch (e) {
        console.error('Failed to load conversations from storage:', e);
        conversations = {};
    }
}

function saveConversationsToStorage() {
    try {
        localStorage.setItem(CONVERSATIONS_STORAGE_KEY, JSON.stringify(conversations));
    } catch (e) {
        console.error('Failed to save conversations to storage:', e);
    }
}

function createNewConversation() {
    const id = 'conv_' + Date.now();
    const conversation = {
        id: id,
        title: '新对话',
        messages: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        unread: false
    };
    conversations[id] = conversation;
    currentConversationId = id;
    requirementSessionId = null;
    saveConversationsToStorage();
    renderConversationsList();
    clearChatContainer();
    showWelcomeMessage();
    return id;
}

function switchConversation(conversationId) {
    if (!conversations[conversationId]) return;
    
    if (currentConversationId && conversations[currentConversationId]) {
        conversations[currentConversationId].unread = false;
    }
    
    currentConversationId = conversationId;
    requirementSessionId = conversationId;
    saveConversationsToStorage();
    renderConversationsList();
    renderConversationMessages(conversationId);
}

function deleteConversation(conversationId) {
    if (!conversations[conversationId]) return;
    
    delete conversations[conversationId];
    saveConversationsToStorage();
    
    if (currentConversationId === conversationId) {
        const remainingIds = Object.keys(conversations);
        if (remainingIds.length > 0) {
            switchConversation(remainingIds[0]);
        } else {
            createNewConversation();
        }
    }
    
    renderConversationsList();
}

function renderConversationsList() {
    const container = document.getElementById('conversations-list');
    const sortedConversations = Object.values(conversations).sort((a, b) => 
        new Date(b.updatedAt) - new Date(a.updatedAt)
    );
    
    if (sortedConversations.length === 0) {
        container.innerHTML = `
            <div class="empty-conversations">
                <p>暂无对话</p>
                <button class="btn-primary" onclick="createNewConversation()">开始新对话</button>
            </div>
        `;
        return;
    }
    
    container.innerHTML = sortedConversations.map(conv => `
        <div class="conversation-item ${conv.id === currentConversationId ? 'active' : ''} ${conv.unread ? 'unread' : ''}" 
             data-id="${conv.id}" onclick="switchConversation('${conv.id}')">
            <div class="conversation-title">${escapeHtml(conv.title)}</div>
            <div class="conversation-preview">${conv.messages.length > 0 ? escapeHtml(getLastMessagePreview(conv)) : '空对话'}</div>
            <div class="conversation-time">${formatConversationTime(conv.updatedAt)}</div>
            <div class="conversation-actions">
                <button class="delete-btn" onclick="event.stopPropagation(); deleteConversation('${conv.id}')">🗑️</button>
            </div>
        </div>
    `).join('');
}

function getLastMessagePreview(conversation) {
    if (conversation.messages.length === 0) return '';
    const lastMsg = conversation.messages[conversation.messages.length - 1];
    return lastMsg.content.substring(0, 50) + (lastMsg.content.length > 50 ? '...' : '');
}

function formatConversationTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;
    
    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前';
    if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前';
    if (diff < 604800000) return Math.floor(diff / 86400000) + '天前';
    
    return date.toLocaleDateString();
}

function renderConversationMessages(conversationId) {
    const conversation = conversations[conversationId];
    if (!conversation) return;
    
    clearChatContainer();
    
    if (conversation.messages.length === 0) {
        showWelcomeMessage();
        return;
    }
    
    conversation.messages.forEach(msg => {
        addMessageToDOM(msg.role, msg.content, false, msg.sources);
    });
}

function clearChatContainer() {
    const chatContainer = document.getElementById('chat-container');
    chatContainer.innerHTML = '';
}

function showWelcomeMessage() {
    const chatContainer = document.getElementById('chat-container');
    chatContainer.innerHTML = `
        <div class="welcome-message">
            <h2>👋 欢迎使用金蝶知识库助手</h2>
            <p>我可以帮助您:</p>
            <ul>
                <li>查询金蝶平台实体、表单、报表定义</li>
                <li>获取代码模板和API使用示例</li>
                <li>解答开发过程中的问题</li>
                <li>根据您的反馈优化知识库</li>
            </ul>
            <p class="hint">选择AI模型可获得更智能的回答，未配置模型时将基于知识库检索生成响应。</p>
        </div>
    `;
}

function setupEventListeners() {
    const modelSelect = document.getElementById('ai-model-select');
    const importFileBtn = document.getElementById('import-file-btn');
    const fileInput = document.getElementById('file-input');
    const importDirBtn = document.getElementById('import-dir-btn');
    const viewStatsBtn = document.getElementById('view-stats-btn');
    const clearKbBtn = document.getElementById('clear-kb-btn');
    const sendBtn = document.getElementById('send-btn');
    const userInput = document.getElementById('user-input');
    const manageModelsBtn = document.getElementById('manage-models-btn');
    const settingsBtn = document.getElementById('settings-btn');
    const newConversationBtn = document.getElementById('new-conversation-btn');

    if (modelSelect) modelSelect.addEventListener('change', handleModelChange);
    if (importFileBtn) importFileBtn.addEventListener('click', () => fileInput.click());
    if (fileInput) fileInput.addEventListener('change', handleFileImport);
    if (importDirBtn) importDirBtn.addEventListener('click', showImportPathModal);
    if (viewStatsBtn) viewStatsBtn.addEventListener('click', showStatsModal);
    if (clearKbBtn) clearKbBtn.addEventListener('click', handleClearKnowledgeBase);
    if (sendBtn) sendBtn.addEventListener('click', handleSendMessage);
    if (settingsBtn) settingsBtn.addEventListener('click', showSettingsModal);
    if (newConversationBtn) newConversationBtn.addEventListener('click', createNewConversation);
    
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSendMessage();
        }
    });

    userInput.addEventListener('input', () => {
        userInput.style.height = 'auto';
        userInput.style.height = Math.min(userInput.scrollHeight, 200) + 'px';
    });

    document.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', () => {
            btn.closest('.modal').classList.remove('active');
        });
    });

    document.getElementById('submit-feedback-btn')?.addEventListener('click', handleSubmitFeedback);
    document.getElementById('cancel-feedback-btn')?.addEventListener('click', () => {
        document.getElementById('feedback-modal').classList.remove('active');
    });
    document.getElementById('start-import-btn')?.addEventListener('click', handleDirectoryImport);
    document.getElementById('cancel-import-btn')?.addEventListener('click', () => {
        document.getElementById('import-path-modal').classList.remove('active');
    });

    if (manageModelsBtn) {
        manageModelsBtn.addEventListener('click', showManageModelsModal);
    }

    document.getElementById('reset-hidden-btn')?.addEventListener('click', handleResetHiddenModels);
    document.getElementById('add-new-model-btn')?.addEventListener('click', () => showEditModelModal(null));
    document.getElementById('save-model-btn')?.addEventListener('click', handleSaveModel);
    document.getElementById('cancel-edit-btn')?.addEventListener('click', () => {
        document.getElementById('edit-model-modal').classList.remove('active');
    });

    const toggleEditApiKey = document.getElementById('toggle-edit-api-key');
    if (toggleEditApiKey) {
        toggleEditApiKey.addEventListener('click', () => {
            const apiKeyInput = document.getElementById('edit-model-api-key');
            if (apiKeyInput.type === 'password') {
                apiKeyInput.type = 'text';
                toggleEditApiKey.textContent = '🔒';
            } else {
                apiKeyInput.type = 'password';
                toggleEditApiKey.textContent = '👁️';
            }
        });
    }

    const editModelProvider = document.getElementById('edit-model-provider');
    if (editModelProvider) {
        editModelProvider.addEventListener('change', handleEditProviderChange);
    }

    document.getElementById('confirm-yes-btn')?.addEventListener('click', () => {
        document.getElementById('confirm-modal').classList.remove('active');
        if (confirmCallback) {
            const cb = confirmCallback;
            confirmCallback = null;
            cb();
        }
    });
    
    document.getElementById('confirm-no-btn')?.addEventListener('click', () => {
        document.getElementById('confirm-modal').classList.remove('active');
        confirmCallback = null;
    });

    document.getElementById('close-settings-btn')?.addEventListener('click', hideSettingsPanel);
    document.getElementById('back-to-settings-btn')?.addEventListener('click', backToSettingsList);
    
    document.querySelectorAll('.settings-category').forEach(category => {
        category.addEventListener('click', () => {
            const categoryName = category.dataset.category;
            showSettingsDetail(categoryName);
        });
    });

    document.getElementById('view-sessions-btn')?.addEventListener('click', showSessionsModal);
    document.getElementById('view-corrections-btn')?.addEventListener('click', showCorrectionsModal);
    document.getElementById('extract-knowledge-btn')?.addEventListener('click', handleExtractCurrentChat);
    document.getElementById('extract-this-session-btn')?.addEventListener('click', handleExtractSession);
    document.getElementById('import-extractions-btn')?.addEventListener('click', handleImportExtractions);
    
    document.getElementById('view-token-report-btn')?.addEventListener('click', showTokenReportModal);
    document.getElementById('reset-token-stats-btn')?.addEventListener('click', handleResetTokenStats);
    
    const closeSettingsBtn = document.getElementById('close-settings-btn');
    if (closeSettingsBtn) {
        closeSettingsBtn.addEventListener('click', hideSettingsPanel);
    }
    
    const settingsOverlay = document.getElementById('settings-overlay');
    if (settingsOverlay) {
        settingsOverlay.addEventListener('click', hideSettingsPanel);
    }
    
    document.getElementById('refresh-logs-btn')?.addEventListener('click', loadLogs);
    document.getElementById('export-logs-btn')?.addEventListener('click', exportLogs);
    document.getElementById('clear-logs-btn')?.addEventListener('click', clearLogs);
    document.getElementById('log-level-filter')?.addEventListener('change', loadLogs);
    document.getElementById('log-type-filter')?.addEventListener('change', loadLogs);
}

function showSettingsModal() {
    showSettingsPanel();
}

function showSettingsPanel() {
    const panel = document.getElementById('settings-panel');
    const overlay = document.getElementById('panel-overlay');
    if (panel) panel.classList.add('active');
    if (overlay) overlay.classList.add('active');
}

function hideSettingsPanel() {
    const panel = document.getElementById('settings-panel');
    const detailPanel = document.getElementById('settings-detail-panel');
    const overlay = document.getElementById('panel-overlay');
    if (panel) panel.classList.remove('active');
    if (detailPanel) detailPanel.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
}

function backToSettingsList() {
    const detailPanel = document.getElementById('settings-detail-panel');
    if (detailPanel) detailPanel.classList.remove('active');
}

function showSettingsDetail(category) {
    const detailPanel = document.getElementById('settings-detail-panel');
    const titleEl = document.getElementById('settings-detail-title');
    const contentEl = document.getElementById('settings-detail-content');
    
    if (!detailPanel || !contentEl) return;
    
    const titles = {
        'ai-models': 'AI模型设置',
        'knowledge-base': '知识库管理',
        'session-stats': '会话统计',
        'knowledge-learning': '知识学习',
        'connection': '连接设置',
        'about': '关于'
    };
    
    if (titleEl) titleEl.textContent = titles[category] || '设置';
    
    let content = '';
    
    if (category === 'ai-models') {
        content = `
            <div class="settings-detail-section">
                <h3>选择AI模型</h3>
                <p>选择用于对话的AI模型</p>
                <div class="model-selector">
                    <select id="ai-model-select">
                        <option value="">加载中...</option>
                    </select>
                </div>
                <div class="settings-actions" style="margin-top: 16px;">
                    <button id="manage-models-btn" class="btn-primary">管理模型配置</button>
                </div>
            </div>
            <div class="settings-detail-section">
                <h3>当前模型信息</h3>
                <div class="settings-stats">
                    <div class="settings-stats-row">
                        <span class="settings-stats-label">当前模型</span>
                        <span class="settings-stats-value" id="current-model-display">未选择</span>
                    </div>
                    <div class="settings-stats-row">
                        <span class="settings-stats-label">提供商</span>
                        <span class="settings-stats-value" id="current-provider-display">-</span>
                    </div>
                </div>
            </div>
        `;
    } else if (category === 'session-stats') {
        content = `
            <div class="stats-overview">
                <div class="stats-card">
                    <div class="stats-card-value" id="stats-total-sessions">0</div>
                    <div class="stats-card-label">总会话数</div>
                </div>
                <div class="stats-card">
                    <div class="stats-card-value" id="stats-total-tokens">0</div>
                    <div class="stats-card-label">总Token消耗</div>
                </div>
                <div class="stats-card">
                    <div class="stats-card-value" id="stats-today-tokens">0</div>
                    <div class="stats-card-label">今日Token</div>
                </div>
                <div class="stats-card">
                    <div class="stats-card-value" id="stats-avg-tokens">0</div>
                    <div class="stats-card-label">平均/会话</div>
                </div>
            </div>
            
            <div class="stats-section">
                <h3>Token消耗趋势</h3>
                <div class="stats-tabs">
                    <button class="stats-tab active" data-period="daily">每日</button>
                    <button class="stats-tab" data-period="weekly">每周</button>
                    <button class="stats-tab" data-period="monthly">每月</button>
                </div>
                <div class="chart-container">
                    <canvas id="token-chart"></canvas>
                </div>
            </div>
            
            <div class="stats-section">
                <h3>按模型统计</h3>
                <div id="stats-by-model" class="stats-list"></div>
            </div>
            
            <div class="stats-section">
                <h3>按提供商统计</h3>
                <div id="stats-by-provider" class="stats-list"></div>
            </div>
            
            <div class="stats-section">
                <h3>最近会话记录</h3>
                <div id="recent-sessions" class="sessions-list"></div>
            </div>
            
            <div class="settings-actions" style="margin-top: 20px;">
                <button id="export-stats-btn" class="btn-secondary">导出统计报告</button>
            </div>
        `;
    } else if (category === 'knowledge-base') {
        content = `
            <div class="settings-detail-section">
                <h3>知识库操作</h3>
                <div class="settings-actions">
                    <button id="import-file-btn" class="btn-primary">
                        <svg viewBox="0 0 24 24" width="16" height="16">
                            <path fill="none" stroke="currentColor" stroke-width="1.5" d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
                        </svg>
                        导入文件
                    </button>
                    <input type="file" id="file-input" accept=".xml,.java,.txt,.md,.json,.yaml,.yml" multiple hidden>
                    <button id="import-dir-btn" class="btn-secondary">
                        <svg viewBox="0 0 24 24" width="16" height="16">
                            <path fill="none" stroke="currentColor" stroke-width="1.5" d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                        </svg>
                        导入目录
                    </button>
                    <button id="view-stats-btn" class="btn-secondary">
                        <svg viewBox="0 0 24 24" width="16" height="16">
                            <path fill="none" stroke="currentColor" stroke-width="1.5" d="M18 20V10M12 20V4M6 20v-6"/>
                        </svg>
                        查看统计
                    </button>
                    <button id="clear-kb-btn" class="btn-danger">
                        <svg viewBox="0 0 24 24" width="16" height="16">
                            <path fill="none" stroke="currentColor" stroke-width="1.5" d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                        </svg>
                        清空知识库
                    </button>
                </div>
            </div>
            <div class="settings-detail-section">
                <h3>知识库统计</h3>
                <div class="settings-stats">
                    <div class="settings-stats-row">
                        <span class="settings-stats-label">总条目</span>
                        <span class="settings-stats-value" id="total-count">0</span>
                    </div>
                    <div id="type-stats"></div>
                </div>
            </div>
        `;
    } else if (category === 'knowledge-learning') {
        content = `
            <div class="settings-detail-section">
                <h3>知识学习</h3>
                <p>从对话中提取和验证知识</p>
                <div class="settings-actions">
                    <button id="view-sessions-btn" class="btn-secondary">
                        <svg viewBox="0 0 24 24" width="16" height="16">
                            <path fill="none" stroke="currentColor" stroke-width="1.5" d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                        </svg>
                        对话记录
                    </button>
                    <button id="view-corrections-btn" class="btn-secondary">
                        <svg viewBox="0 0 24 24" width="16" height="16">
                            <path fill="none" stroke="currentColor" stroke-width="1.5" d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                            <path fill="none" stroke="currentColor" stroke-width="1.5" d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                        </svg>
                        待审核纠正
                    </button>
                    <button id="extract-knowledge-btn" class="btn-primary">
                        <svg viewBox="0 0 24 24" width="16" height="16">
                            <path fill="none" stroke="currentColor" stroke-width="1.5" d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/>
                            <rect x="9" y="3" width="6" height="4" rx="1" fill="none" stroke="currentColor" stroke-width="1.5"/>
                            <path fill="none" stroke="currentColor" stroke-width="1.5" d="M9 12h6M9 16h6"/>
                        </svg>
                        提取当前对话知识
                    </button>
                </div>
            </div>
        `;
    } else if (category === 'connection') {
        content = `
            <div class="settings-detail-section">
                <h3>连接设置</h3>
                <p>配置知识库服务连接地址</p>
                <div class="connection-form">
                    <div class="form-row">
                        <div class="form-group">
                            <label for="connection-host">服务器地址</label>
                            <input type="text" id="connection-host" class="form-input" value="127.0.0.1" placeholder="例如: 127.0.0.1">
                        </div>
                        <div class="form-group">
                            <label for="connection-port">端口</label>
                            <input type="number" id="connection-port" class="form-input" value="8001" placeholder="例如: 8001">
                        </div>
                    </div>
                    <div id="connection-status" class="connection-status" style="display: none;"></div>
                    <div class="settings-actions" style="margin-top: 16px;">
                        <button id="test-connection-btn" class="btn-secondary">测试连接</button>
                        <button id="save-connection-btn" class="btn-primary">保存并重连</button>
                    </div>
                </div>
            </div>
        `;
    } else if (category === 'about') {
        content = `
            <div class="settings-detail-section about-section">
                <div class="about-logo">
                    <svg viewBox="0 0 24 24" width="64" height="64">
                        <path fill="none" stroke="currentColor" stroke-width="1.5" d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                    </svg>
                </div>
                <h2>知识库助手</h2>
                <p class="version">版本 1.0.0</p>
                <div class="about-info">
                    <div class="info-row">
                        <span class="info-label">当前连接</span>
                        <span class="info-value" id="about-connection">127.0.0.1:8001</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">服务状态</span>
                        <span class="info-value" id="about-status">检测中...</span>
                    </div>
                </div>
                <div class="about-description">
                    <p>金蝶苍穹星瀚平台 AI 知识库助手</p>
                    <p>帮助开发者快速查询平台实体、表单、报表定义，获取代码模板和API使用示例。</p>
                </div>
            </div>
        `;
    }
    
    contentEl.innerHTML = content;
    detailPanel.classList.add('active');
    
    initializeSettingsDetailEvents(category);
}

function initializeSettingsDetailEvents(category) {
    if (category === 'ai-models') {
        loadModels();
        const modelSelect = document.getElementById('ai-model-select');
        if (modelSelect) {
            modelSelect.addEventListener('change', handleModelChange);
        }
        document.getElementById('manage-models-btn')?.addEventListener('click', showModelManagerModal);
    } else if (category === 'knowledge-base') {
        document.getElementById('import-file-btn')?.addEventListener('click', () => document.getElementById('file-input').click());
        document.getElementById('file-input')?.addEventListener('change', handleFileImport);
        document.getElementById('import-dir-btn')?.addEventListener('click', handleDirectoryImport);
        document.getElementById('view-stats-btn')?.addEventListener('click', showStatsModal);
        document.getElementById('clear-kb-btn')?.addEventListener('click', handleClearKnowledge);
        loadStatistics();
    } else if (category === 'session-stats') {
        loadSessionStats();
        document.getElementById('export-stats-btn')?.addEventListener('click', exportSessionStats);
        document.querySelectorAll('.stats-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.stats-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                loadTokenChart(tab.dataset.period);
            });
        });
    } else if (category === 'knowledge-learning') {
        document.getElementById('view-sessions-btn')?.addEventListener('click', showSessionsModal);
        document.getElementById('view-corrections-btn')?.addEventListener('click', showCorrectionsModal);
        document.getElementById('extract-knowledge-btn')?.addEventListener('click', handleExtractKnowledge);
    } else if (category === 'connection') {
        loadConnectionSettings();
        document.getElementById('test-connection-btn')?.addEventListener('click', handleTestConnection);
        document.getElementById('save-connection-btn')?.addEventListener('click', handleSaveConnection);
    } else if (category === 'about') {
        loadAboutInfo();
    }
}

async function loadConnectionSettings() {
    const hostInput = document.getElementById('connection-host');
    const portInput = document.getElementById('connection-port');
    
    if (!hostInput || !portInput) return;
    
    try {
        const response = await fetch('/api/v1/system/connection');
        const data = await response.json();
        
        if (data.success) {
            hostInput.value = data.connection.host || '127.0.0.1';
            portInput.value = data.connection.port || 8001;
        }
    } catch (error) {
        console.error('加载连接设置失败:', error);
    }
}

async function handleTestConnection() {
    const hostInput = document.getElementById('connection-host');
    const portInput = document.getElementById('connection-port');
    const statusDiv = document.getElementById('connection-status');
    const testBtn = document.getElementById('test-connection-btn');
    
    const host = hostInput.value.trim();
    const port = portInput.value.trim();
    
    if (!host || !port) {
        showConnectionStatus('请填写完整的服务器地址和端口', false);
        return;
    }
    
    testBtn.disabled = true;
    testBtn.textContent = '测试中...';
    
    try {
        const response = await fetch('/api/v1/system/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host, port: parseInt(port) })
        });
        const data = await response.json();
        
        if (data.success && data.connected) {
            showConnectionStatus('✓ 连接成功！', true);
        } else {
            showConnectionStatus('✗ 连接失败，请检查服务器地址和端口', false);
        }
    } catch (error) {
        showConnectionStatus('✗ 连接测试失败', false);
    } finally {
        testBtn.disabled = false;
        testBtn.textContent = '测试连接';
    }
}

async function handleSaveConnection() {
    const hostInput = document.getElementById('connection-host');
    const portInput = document.getElementById('connection-port');
    const saveBtn = document.getElementById('save-connection-btn');
    
    const host = hostInput.value.trim();
    const port = portInput.value.trim();
    
    if (!host || !port) {
        showConnectionStatus('请填写完整的服务器地址和端口', false);
        return;
    }
    
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中...';
    
    try {
        const response = await fetch('/api/v1/system/connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host, port: parseInt(port) })
        });
        const data = await response.json();
        
        if (data.success) {
            showConnectionStatus('✓ 设置已保存，正在重新连接...', true);
            setTimeout(() => {
                if (window.electronAPI) {
                    window.electronAPI.reload();
                } else {
                    window.location.reload();
                }
            }, 1000);
        } else {
            showConnectionStatus('✗ 保存失败: ' + (data.message || '未知错误'), false);
        }
    } catch (error) {
        showConnectionStatus('✗ 保存失败', false);
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存并重连';
    }
}

function showConnectionStatus(message, isSuccess) {
    const statusDiv = document.getElementById('connection-status');
    if (!statusDiv) return;
    
    statusDiv.textContent = message;
    statusDiv.className = 'connection-status ' + (isSuccess ? 'success' : 'error');
    statusDiv.style.display = 'block';
}

async function loadAboutInfo() {
    const connectionEl = document.getElementById('about-connection');
    const statusEl = document.getElementById('about-status');
    
    if (!connectionEl || !statusEl) return;
    
    try {
        const response = await fetch('/api/v1/system/connection');
        const data = await response.json();
        
        if (data.success) {
            connectionEl.textContent = `${data.connection.host}:${data.connection.port}`;
            statusEl.textContent = '● 已连接';
            statusEl.style.color = '#2e7d32';
        } else {
            statusEl.textContent = '● 未连接';
            statusEl.style.color = '#c62828';
        }
    } catch (error) {
        console.error('加载关于信息失败:', error);
        statusEl.textContent = '● 连接异常';
        statusEl.style.color = '#c62828';
    }
}

async function loadSessionStats() {
    try {
        const response = await fetch(`${API_BASE}/ai/token-usage`);
        const data = await response.json();
        
        if (data.success) {
            const usage = data.usage;
            document.getElementById('stats-total-sessions').textContent = usage.total_sessions.toLocaleString();
            document.getElementById('stats-total-tokens').textContent = usage.total_tokens.toLocaleString();
            
            const todayTokens = usage.by_date?.[new Date().toISOString().split('T')[0]] || 0;
            document.getElementById('stats-today-tokens').textContent = todayTokens.toLocaleString();
            
            const avgTokens = usage.total_sessions > 0 
                ? Math.round(usage.total_tokens / usage.total_sessions) 
                : 0;
            document.getElementById('stats-avg-tokens').textContent = avgTokens.toLocaleString();
            
            const byModelDiv = document.getElementById('stats-by-model');
            if (byModelDiv) {
                if (Object.keys(usage.by_model || {}).length > 0) {
                    byModelDiv.innerHTML = Object.entries(usage.by_model)
                        .sort((a, b) => b[1].total_tokens - a[1].total_tokens)
                        .map(([model, stats]) => `
                            <div class="stats-list-item">
                                <span class="stats-list-item-name">${model}</span>
                                <div>
                                    <span class="stats-list-item-value">${stats.total_tokens?.toLocaleString() || 0} tokens</span>
                                    <span class="stats-list-item-count">(${stats.sessions || 0}次)</span>
                                </div>
                            </div>
                        `).join('');
                } else {
                    byModelDiv.innerHTML = '<p style="color: #999; font-size: 14px; text-align: center; padding: 20px;">暂无数据</p>';
                }
            }
            
            const byProviderDiv = document.getElementById('stats-by-provider');
            if (byProviderDiv) {
                if (Object.keys(usage.by_provider || {}).length > 0) {
                    byProviderDiv.innerHTML = Object.entries(usage.by_provider)
                        .sort((a, b) => b[1].total_tokens - a[1].total_tokens)
                        .map(([provider, stats]) => `
                            <div class="stats-list-item">
                                <span class="stats-list-item-name">${provider}</span>
                                <div>
                                    <span class="stats-list-item-value">${stats.total_tokens?.toLocaleString() || 0} tokens</span>
                                    <span class="stats-list-item-count">(${stats.sessions || 0}次)</span>
                                </div>
                            </div>
                        `).join('');
                } else {
                    byProviderDiv.innerHTML = '<p style="color: #999; font-size: 14px; text-align: center; padding: 20px;">暂无数据</p>';
                }
            }
            
            loadRecentSessions();
            loadTokenChart('daily');
        }
    } catch (error) {
        console.error('加载会话统计失败:', error);
    }
}

async function loadRecentSessions() {
    const container = document.getElementById('recent-sessions');
    if (!container) return;
    
    try {
        const response = await fetch(`${API_BASE}/ai/token-report`);
        const data = await response.json();
        
        if (data.success && data.report?.recent_sessions?.length > 0) {
            container.innerHTML = data.report.recent_sessions.slice(0, 10).map(session => `
                <div class="session-item">
                    <div class="session-item-header">
                        <span class="session-item-model">${session.model_name || '未知模型'}</span>
                        <span class="session-item-time">${new Date(session.timestamp).toLocaleString()}</span>
                    </div>
                    <div class="session-item-tokens">
                        <span>输入: <strong>${session.prompt_tokens || 0}</strong></span>
                        <span>输出: <strong>${session.completion_tokens || 0}</strong></span>
                        <span>总计: <strong>${session.total_tokens || 0}</strong></span>
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p style="color: #999; font-size: 14px; text-align: center; padding: 20px;">暂无会话记录</p>';
        }
    } catch (error) {
        console.error('加载最近会话失败:', error);
        container.innerHTML = '<p style="color: #999; font-size: 14px; text-align: center; padding: 20px;">加载失败</p>';
    }
}

function loadTokenChart(period) {
    const canvas = document.getElementById('token-chart');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    const container = canvas.parentElement;
    canvas.width = container.clientWidth - 40;
    canvas.height = container.clientHeight - 40;
    
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    ctx.fillStyle = '#f5f5f5';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    ctx.fillStyle = '#999';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`Token消耗趋势 (${period === 'daily' ? '每日' : period === 'weekly' ? '每周' : '每月'})`, canvas.width / 2, 20);
    
    ctx.fillStyle = '#666';
    ctx.font = '11px sans-serif';
    ctx.fillText('请调用API获取实际数据', canvas.width / 2, canvas.height / 2);
}

async function exportSessionStats() {
    try {
        const response = await fetch(`${API_BASE}/ai/token-report`);
        const data = await response.json();
        
        if (data.success) {
            const blob = new Blob([JSON.stringify(data.report, null, 2)], { type: 'application/json' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `session_stats_${new Date().toISOString().split('T')[0]}.json`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            showToast('统计报告已导出', 'success');
        }
    } catch (error) {
        console.error('导出统计失败:', error);
        showToast('导出失败', 'error');
    }
}

async function loadTokenUsage() {
    try {
        const response = await fetch(`${API_BASE}/ai/token-usage`);
        const data = await response.json();
        
        if (data.success) {
            const usage = data.usage;
            document.getElementById('token-total-sessions').textContent = usage.total_sessions.toLocaleString();
            document.getElementById('token-total-tokens').textContent = usage.total_tokens.toLocaleString();
            document.getElementById('token-prompt-tokens').textContent = usage.total_prompt_tokens.toLocaleString();
            document.getElementById('token-completion-tokens').textContent = usage.total_completion_tokens.toLocaleString();
            
            const byModelDiv = document.getElementById('token-by-model');
            if (Object.keys(usage.by_model).length > 0) {
                byModelDiv.innerHTML = '<h4 style="font-size: 13px; color: #666; margin-bottom: 8px;">按模型统计:</h4>' +
                    Object.entries(usage.by_model).map(([model, stats]) => `
                        <div class="token-model-item">
                            <span>${model}</span>
                            <span>${stats.total_tokens.toLocaleString()} tokens (${stats.sessions}次)</span>
                        </div>
                    `).join('');
            } else {
                byModelDiv.innerHTML = '<p style="color: #999; font-size: 12px;">暂无使用记录</p>';
            }
        }
    } catch (error) {
        console.error('加载token统计失败:', error);
    }
}

async function loadLogs() {
    const container = document.getElementById('logs-container');
    if (!container) return;
    
    const levelFilter = document.getElementById('log-level-filter')?.value || '';
    const typeFilter = document.getElementById('log-type-filter')?.value || '';
    
    container.innerHTML = '<p class="logs-empty">加载中...</p>';
    
    try {
        const params = new URLSearchParams();
        if (levelFilter) params.append('level', levelFilter);
        if (typeFilter) params.append('type', typeFilter);
        params.append('limit', '100');
        
        const response = await fetch(`${API_BASE}/logs?${params.toString()}`);
        const data = await response.json();
        
        if (data.success && data.logs && data.logs.length > 0) {
            container.innerHTML = data.logs.map(log => `
                <div class="log-entry ${log.level.toLowerCase()}">
                    <div class="log-entry-header">
                        <span class="log-entry-level ${log.level.toLowerCase()}">${log.level}</span>
                        <span class="log-entry-time">${new Date(log.timestamp).toLocaleString()}</span>
                    </div>
                    <div class="log-entry-message">${escapeHtml(log.message)}</div>
                </div>
            `).join('');
            
            document.getElementById('logs-total-count').textContent = data.total || data.logs.length;
            document.getElementById('logs-today-count').textContent = data.today_count || 0;
            document.getElementById('logs-error-count').textContent = data.error_count || 0;
            document.getElementById('logs-warning-count').textContent = data.warning_count || 0;
        } else {
            container.innerHTML = '<p class="logs-empty">暂无日志记录</p>';
            document.getElementById('logs-total-count').textContent = '0';
            document.getElementById('logs-today-count').textContent = '0';
            document.getElementById('logs-error-count').textContent = '0';
            document.getElementById('logs-warning-count').textContent = '0';
        }
    } catch (error) {
        console.error('加载日志失败:', error);
        container.innerHTML = '<p class="logs-empty">加载失败，请稍后重试</p>';
    }
}

async function exportLogs() {
    try {
        const response = await fetch(`${API_BASE}/logs/export`);
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `logs_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        showToast('日志导出成功', 'success');
    } catch (error) {
        console.error('导出日志失败:', error);
        showToast('导出日志失败', 'error');
    }
}

async function clearLogs() {
    showConfirmModal('确定要清空所有日志吗？此操作不可恢复。', async () => {
        try {
            const response = await fetch(`${API_BASE}/logs/clear`, { method: 'POST' });
            const data = await response.json();
            
            if (data.success) {
                showToast('日志已清空', 'success');
                loadLogs();
            } else {
                showToast('清空日志失败', 'error');
            }
        } catch (error) {
            console.error('清空日志失败:', error);
            showToast('清空日志失败', 'error');
        }
    }, '清空日志');
}

async function showTokenReportModal() {
    const modal = document.getElementById('token-report-modal');
    const content = document.getElementById('token-report-content');
    content.innerHTML = '<p>加载中...</p>';
    modal.classList.add('active');
    
    try {
        const response = await fetch(`${API_BASE}/ai/token-report`);
        const data = await response.json();
        
        if (data.success) {
            const report = data.report;
            content.innerHTML = `
                <div class="token-report-section">
                    <h3>📊 总览</h3>
                    <div class="token-stats-grid">
                        <div class="token-stat-item">
                            <span class="stat-label">总会话数</span>
                            <span class="stat-value">${report.summary.total_sessions.toLocaleString()}</span>
                        </div>
                        <div class="token-stat-item">
                            <span class="stat-label">总Token数</span>
                            <span class="stat-value">${report.summary.total_tokens.toLocaleString()}</span>
                        </div>
                        <div class="token-stat-item">
                            <span class="stat-label">输入Token</span>
                            <span class="stat-value">${report.summary.total_prompt_tokens.toLocaleString()}</span>
                        </div>
                        <div class="token-stat-item">
                            <span class="stat-label">输出Token</span>
                            <span class="stat-value">${report.summary.total_completion_tokens.toLocaleString()}</span>
                        </div>
                        <div class="token-stat-item">
                            <span class="stat-label">平均Token/会话</span>
                            <span class="stat-value">${report.summary.avg_tokens_per_session.toFixed(0)}</span>
                        </div>
                    </div>
                </div>
                
                ${Object.keys(report.by_provider).length > 0 ? `
                <div class="token-report-section">
                    <h3>🏢 按提供商统计</h3>
                    <div class="token-table">
                        ${Object.entries(report.by_provider).map(([provider, stats]) => `
                            <div class="token-table-row">
                                <span>${provider}</span>
                                <span>${stats.sessions}次</span>
                                <span>${stats.total_tokens.toLocaleString()} tokens</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
                ` : ''}
                
                ${Object.keys(report.by_date).length > 0 ? `
                <div class="token-report-section">
                    <h3>📅 按日期统计 (最近30天)</h3>
                    <div class="token-table">
                        ${Object.entries(report.by_date).slice(0, 10).map(([date, stats]) => `
                            <div class="token-table-row">
                                <span>${date}</span>
                                <span>${stats.sessions}次</span>
                                <span>${stats.total_tokens.toLocaleString()} tokens</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
                ` : ''}
                
                <div class="token-report-section">
                    <h3>💡 优化建议</h3>
                    <ul class="recommendations-list">
                        ${report.recommendations.map(r => `<li>${r}</li>`).join('')}
                    </ul>
                </div>
            `;
        }
    } catch (error) {
        console.error('加载token报告失败:', error);
        content.innerHTML = '<p class="error-message">加载失败</p>';
    }
}

async function handleResetTokenStats() {
    showConfirmModal('确定要重置Token统计吗？此操作不可恢复！', async () => {
        try {
            const response = await fetch(`${API_BASE}/ai/token-usage/reset`, {
                method: 'POST'
            });
            const data = await response.json();
            
            if (data.success) {
                showToast('Token统计已重置', 'success');
                loadTokenUsage();
            } else {
                showToast(data.message || '重置失败', 'error');
            }
        } catch (error) {
            console.error('重置token统计失败:', error);
            showToast('重置失败', 'error');
        }
    }, '重置Token统计');
}

async function loadModels() {
    try {
        const response = await fetch(`${API_BASE}/ai/models`);
        const data = await response.json();
        
        modelsData = data.models;
        const modelSelect = document.getElementById('ai-model-select');
        modelSelect.innerHTML = '<option value="">-- 不使用AI模型 --</option>';
        
        const presetGroup = document.createElement('optgroup');
        presetGroup.label = '预设模型';
        
        const customGroup = document.createElement('optgroup');
        customGroup.label = '自定义模型';
        
        for (const [key, model] of Object.entries(data.models)) {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = model.display_name;
            if (!model.has_api_key) {
                option.textContent += ' (未配置)';
            }
            
            if (model.is_custom) {
                option.classList.add('custom-model-option');
                customGroup.appendChild(option);
            } else {
                presetGroup.appendChild(option);
            }
        }
        
        modelSelect.appendChild(presetGroup);
        if (customGroup.children.length > 0) {
            modelSelect.appendChild(customGroup);
        }
        
        if (data.current_model) {
            modelSelect.value = data.current_model.model_key;
            currentModelKey = data.current_model.model_key;
            updateCurrentModelDisplay(data.current_model);
        } else {
            modelSelect.value = '';
            currentModelKey = null;
            updateCurrentModelDisplay({ display_name: '知识库检索模式' });
        }
    } catch (error) {
        console.error('加载模型列表失败:', error);
        showToast('加载模型列表失败', 'error');
    }
}

async function loadCurrentModel() {
    try {
        const response = await fetch(`${API_BASE}/ai/models/current`);
        if (response.ok) {
            const data = await response.json();
            currentModelKey = data.model_key;
            updateCurrentModelDisplay(data);
        }
    } catch (error) {
        console.error('加载当前模型失败:', error);
    }
}

function updateCurrentModelDisplay(model) {
    const modelNameSpan = document.getElementById('current-model-name');
    modelNameSpan.textContent = model.display_name || model.model_name || '知识库检索模式';
}

async function loadSearchStatus() {
    const indicator = document.getElementById('search-status-indicator');
    const modeText = document.getElementById('search-mode-text');
    
    indicator.className = 'search-status-indicator loading';
    modeText.textContent = '检索模式: 加载中...';
    
    try {
        const response = await fetch(`${API_BASE}/knowledge/search-status`);
        if (response.ok) {
            const data = await response.json();
            
            if (data.success) {
                if (data.search_mode === 'vector') {
                    indicator.className = 'search-status-indicator';
                    modeText.textContent = `向量检索 | ${data.vector_count.toLocaleString()} 条`;
                } else {
                    indicator.className = 'search-status-indicator database';
                    modeText.textContent = '数据库检索';
                }
            } else {
                indicator.className = 'search-status-indicator database';
                modeText.textContent = '检索模式: 未知';
            }
        }
    } catch (error) {
        console.error('加载检索状态失败:', error);
        indicator.className = 'search-status-indicator database';
        modeText.textContent = '检索模式: 离线';
    }
}

async function handleModelChange(e) {
    const modelKey = e.target.value || null;
    
    if (!modelKey) {
        currentModelKey = null;
        updateCurrentModelDisplay({ display_name: '知识库检索模式' });
        showToast('已切换到知识库检索模式', 'success');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/ai/models/switch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_key: modelKey })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentModelKey = modelKey;
            updateCurrentModelDisplay(data.model_info);
            showToast(data.message, 'success');
        } else {
            showToast(data.message || '切换模型失败', 'error');
        }
    } catch (error) {
        console.error('切换模型失败:', error);
        showToast('切换模型失败', 'error');
    }
}

async function handleSendMessage() {
    const userInput = document.getElementById('user-input');
    const message = userInput.value.trim();
    
    if (!message || isProcessing) return;
    
    isProcessing = true;
    const sendBtn = document.getElementById('send-btn');
    sendBtn.disabled = true;
    
    if (!currentConversationId) {
        createNewConversation();
    }
    
    const conversation = conversations[currentConversationId];
    conversation.messages.push({ role: 'user', content: message });
    conversation.updatedAt = new Date().toISOString();
    
    if (conversation.messages.length === 1) {
        conversation.title = message.substring(0, 30) + (message.length > 30 ? '...' : '');
    }
    
    saveConversationsToStorage();
    renderConversationsList();
    
    addMessageToDOM('user', message);
    userInput.value = '';
    userInput.style.height = 'auto';
    
    const typingIndicator = addTypingIndicator();
    
    try {
        let response;
        let data;
        
        if (currentModelKey) {
            const requestBody = {
                message: message,
                history: conversation.messages.slice(-10)
            };
            
            if (requirementSessionId) {
                requestBody.session_id = requirementSessionId;
            }
            
            response = await fetch(`${API_BASE}/ai/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody)
            });
            
            data = await response.json();
            
            if (data.success) {
                removeTypingIndicator(typingIndicator);
                
                if (!requirementSessionId) {
                    requirementSessionId = currentConversationId;
                }
                
                let enhancedContent = data.content;
                const metaInfo = [];
                
                if (data.requirement_phase) {
                    const phaseInfo = formatPhaseDisplay(data.requirement_phase);
                    metaInfo.push(`${phaseInfo.icon} ${phaseInfo.text}`);
                }
                
                if (data.clarity_score !== undefined && data.clarity_score !== null) {
                    metaInfo.push(`清晰度: ${(data.clarity_score * 100).toFixed(0)}%`);
                }
                
                if (data.intent) {
                    metaInfo.push(`意图: ${data.intent}`);
                }
                
                if (metaInfo.length > 0) {
                    enhancedContent = `> ${metaInfo.join(' | ')}\n\n${enhancedContent}`;
                }
                
                if (data.clarification_questions && data.clarification_questions.length > 0) {
                    enhancedContent += '\n\n---\n\n**为了更好地帮助您，请回答以下问题：**\n';
                    data.clarification_questions.forEach((q, idx) => {
                        enhancedContent += `\n${idx + 1}. ${q.question}`;
                        if (q.options && q.options.length > 0) {
                            enhancedContent += `\n   - 选项: ${q.options.join(' / ')}`;
                        }
                    });
                }
                
                conversation.messages.push({ 
                    role: 'assistant', 
                    content: enhancedContent, 
                    sources: [],
                    metadata: {
                        phase: data.requirement_phase,
                        clarity: data.clarity_score,
                        intent: data.intent,
                        keywords: data.keywords
                    }
                });
                conversation.updatedAt = new Date().toISOString();
                saveConversationsToStorage();
                renderConversationsList();
                addMessageToDOM('assistant', enhancedContent);
            } else {
                console.log('AI模型调用失败，回退到知识库检索:', data.error);
                currentModelKey = null;
                response = await fetch(`${API_BASE}/knowledge/query`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        query: message,
                        limit: 5,
                        min_relevance: 0.3
                    })
                });
                
                data = await response.json();
                removeTypingIndicator(typingIndicator);
                
                if (data.success && data.results && data.results.length > 0) {
                    const responseContent = generateResponseFromKnowledge(data.results, message);
                    const sources = data.results.map(r => ({
                        id: r.id,
                        type: r.type,
                        name: r.name,
                        relevance: r.relevance
                    }));
                    
                    conversation.messages.push({ role: 'assistant', content: responseContent, sources: sources });
                    conversation.updatedAt = new Date().toISOString();
                    saveConversationsToStorage();
                    renderConversationsList();
                    addMessageToDOM('assistant', responseContent, false, sources);
                } else {
                    const noResultContent = '抱歉，我在知识库中没有找到与您问题相关的信息。\n\n建议您：\n1. 尝试使用不同的关键词重新搜索\n2. 在设置中导入相关的知识文档\n3. 配置AI模型以获得更智能的回答';
                    conversation.messages.push({ role: 'assistant', content: noResultContent, sources: [] });
                    conversation.updatedAt = new Date().toISOString();
                    saveConversationsToStorage();
                    renderConversationsList();
                    addMessageToDOM('assistant', noResultContent, false, []);
                }
            }
        } else {
            response = await fetch(`${API_BASE}/knowledge/query`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: message,
                    limit: 5,
                    min_relevance: 0.3
                })
            });
            
            data = await response.json();
            
            removeTypingIndicator(typingIndicator);
            
            if (data.success && data.results && data.results.length > 0) {
                const responseContent = generateResponseFromKnowledge(data.results, message);
                const sources = data.results.map(r => ({
                    id: r.id,
                    type: r.type,
                    name: r.name,
                    relevance: r.relevance
                }));
                
                conversation.messages.push({ role: 'assistant', content: responseContent, sources: sources });
                conversation.updatedAt = new Date().toISOString();
                saveConversationsToStorage();
                renderConversationsList();
                addMessageToDOM('assistant', responseContent, false, sources);
            } else {
                const noResultContent = '抱歉，我在知识库中没有找到与您问题相关的信息。\n\n建议您：\n1. 尝试使用不同的关键词重新搜索\n2. 在设置中导入相关的知识文档\n3. 配置AI模型以获得更智能的回答';
                conversation.messages.push({ role: 'assistant', content: noResultContent, sources: [] });
                conversation.updatedAt = new Date().toISOString();
                saveConversationsToStorage();
                renderConversationsList();
                addMessageToDOM('assistant', noResultContent, false, []);
            }
        }
    } catch (error) {
        console.error('发送消息失败:', error);
        removeTypingIndicator(typingIndicator);
        addMessageToDOM('assistant', `请求失败: ${error.message}`, true);
    } finally {
        isProcessing = false;
        sendBtn.disabled = false;
    }
}

function generateResponseFromKnowledge(results, query) {
    let response = `根据知识库检索，为您找到以下相关信息：\n\n`;
    
    results.forEach((result, index) => {
        response += `**${index + 1}. ${result.name}** (${result.type})\n`;
        if (result.description) {
            response += `${result.description}\n`;
        }
        if (result.highlights && result.highlights.length > 0) {
            response += `相关内容：${result.highlights.join('...')}\n`;
        }
        response += `\n`;
    });
    
    response += `\n*以上信息来自知识库检索，相关度: ${(results[0]?.relevance * 100 || 0).toFixed(0)}%*`;
    
    return response;
}

function addMessageToDOM(role, content, isError = false, sources = null) {
    const chatContainer = document.getElementById('chat-container');
    
    const welcomeMessage = chatContainer.querySelector('.welcome-message');
    if (welcomeMessage) {
        welcomeMessage.remove();
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? '👤' : '🤖';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    
    if (isError) {
        contentDiv.style.borderColor = 'var(--danger-color)';
        contentDiv.style.color = 'var(--danger-color)';
    }
    
    contentDiv.innerHTML = formatMessage(content);
    
    if (sources && sources.length > 0) {
        const sourcesDiv = document.createElement('div');
        sourcesDiv.className = 'knowledge-source';
        sourcesDiv.innerHTML = `
            <div class="knowledge-source-title">📚 知识来源</div>
            ${sources.map(s => `
                <div class="knowledge-source-item">
                    <strong>${escapeHtml(s.name)}</strong> (${s.type}) - 相关度: ${(s.relevance * 100).toFixed(0)}%
                </div>
            `).join('')}
        `;
        contentDiv.appendChild(sourcesDiv);
    }
    
    if (role === 'assistant' && !isError) {
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'message-actions';
        actionsDiv.innerHTML = `
            <button class="like-btn" onclick="handleFeedback('like', this)">👍 有帮助</button>
            <button class="dislike-btn" onclick="handleFeedback('dislike', this)">👎 需改进</button>
            <button class="copy-btn" onclick="copyMessage(this)">📋 复制</button>
        `;
        contentDiv.appendChild(actionsDiv);
    }
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentDiv);
    chatContainer.appendChild(messageDiv);
    
    chatContainer.scrollTop = chatContainer.scrollHeight;
    
    return messageDiv;
}

function formatMessage(content) {
    content = content.replace(/```(\w+)?\n([\s\S]*?)```/g, (match, lang, code) => {
        return `<pre><code class="language-${lang || 'text'}">${escapeHtml(code.trim())}</code></pre>`;
    });
    
    content = content.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    content = content.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    content = content.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    
    content = content.replace(/\n/g, '<br>');
    
    return content;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function addTypingIndicator() {
    const chatContainer = document.getElementById('chat-container');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';
    messageDiv.id = 'typing-indicator';
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '🤖';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = `
        <div class="typing-indicator">
            <span></span>
            <span></span>
            <span></span>
        </div>
    `;
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentDiv);
    chatContainer.appendChild(messageDiv);
    
    chatContainer.scrollTop = chatContainer.scrollHeight;
    
    return messageDiv;
}

function removeTypingIndicator(indicator) {
    if (indicator && indicator.parentNode) {
        indicator.remove();
    }
}

function handleFeedback(type, button) {
    const feedbackModal = document.getElementById('feedback-modal');
    feedbackModal.classList.add('active');
    feedbackModal.dataset.type = type;
    feedbackModal.dataset.messageId = button.closest('.message').querySelector('.message-content').textContent;
}

async function handleSubmitFeedback() {
    const feedbackModal = document.getElementById('feedback-modal');
    const feedbackInput = document.getElementById('feedback-input');
    const feedback = feedbackInput.value.trim();
    const type = feedbackModal.dataset.type;
    
    if (!feedback) {
        showToast('请输入反馈内容', 'warning');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/knowledge/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                type: type,
                feedback: feedback,
                message_id: feedbackModal.dataset.messageId
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('感谢您的反馈！我们会持续改进知识库。', 'success');
            feedbackModal.classList.remove('active');
            feedbackInput.value = '';
        } else {
            showToast(data.message || '提交反馈失败', 'error');
        }
    } catch (error) {
        console.error('提交反馈失败:', error);
        showToast('提交反馈失败', 'error');
    }
}

function copyMessage(button) {
    const content = button.closest('.message-content').querySelector('pre')?.textContent || 
                   button.closest('.message-content').textContent;
    
    navigator.clipboard.writeText(content).then(() => {
        showToast('已复制到剪贴板', 'success');
    }).catch(() => {
        showToast('复制失败', 'error');
    });
}

async function handleFileImport(e) {
    const files = e.target.files;
    if (!files.length) return;
    
    showLoading();
    
    try {
        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            
            const response = await fetch(`${API_BASE}/knowledge/import/file`, {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (data.success) {
                showToast(`${file.name}: 导入成功，共 ${data.knowledge_count} 条知识`, 'success');
            } else {
                showToast(`${file.name}: 导入失败 - ${data.message}`, 'error');
            }
        }
        
        await loadStatistics();
    } catch (error) {
        console.error('导入文件失败:', error);
        showToast('导入文件失败', 'error');
    } finally {
        hideLoading();
        e.target.value = '';
    }
}

function showImportPathModal() {
    document.getElementById('import-path-modal').classList.add('active');
}

async function handleDirectoryImport() {
    const pathInput = document.getElementById('import-path-input');
    const path = pathInput.value.trim();
    
    if (!path) {
        showToast('请输入目录路径', 'warning');
        return;
    }
    
    document.getElementById('import-path-modal').classList.remove('active');
    showLoading();
    
    try {
        const response = await fetch(`${API_BASE}/knowledge/import`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_path: path, recursive: true })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`导入成功，共 ${data.knowledge_count} 条知识`, 'success');
        } else {
            showToast(`导入失败: ${data.message}`, 'error');
        }
        
        await loadStatistics();
    } catch (error) {
        console.error('导入目录失败:', error);
        showToast('导入目录失败', 'error');
    } finally {
        hideLoading();
        pathInput.value = '';
    }
}

async function loadStatistics() {
    try {
        const response = await fetch(`${API_BASE}/knowledge/statistics`);
        const data = await response.json();
        
        document.getElementById('total-count').textContent = data.total_count;
        
        const typeStatsDiv = document.getElementById('type-stats');
        typeStatsDiv.innerHTML = '';
        
        for (const [type, count] of Object.entries(data.by_type)) {
            const badge = document.createElement('span');
            badge.className = 'type-badge';
            badge.textContent = `${type}: ${count}`;
            typeStatsDiv.appendChild(badge);
        }
        
        if (data.faiss_chunks !== undefined) {
            const chunkBadge = document.createElement('span');
            chunkBadge.className = 'type-badge chunk-badge';
            chunkBadge.textContent = `向量分块: ${data.faiss_chunks}`;
            typeStatsDiv.appendChild(chunkBadge);
        }
    } catch (error) {
        console.error('加载统计信息失败:', error);
    }
}

async function showStatsModal() {
    try {
        const response = await fetch(`${API_BASE}/knowledge/statistics`);
        const data = await response.json();
        
        const modalBody = document.getElementById('stats-modal-body');
        let chunkTypeHtml = '';
        
        if (data.faiss_by_chunk_type && Object.keys(data.faiss_by_chunk_type).length > 0) {
            chunkTypeHtml = `
                <h3>分块类型分布</h3>
                <ul>
                    ${Object.entries(data.faiss_by_chunk_type).map(([type, count]) => 
                        `<li>${type}: ${count}</li>`
                    ).join('')}
                </ul>
            `;
        }
        
        modalBody.innerHTML = `
            <div class="stats-detail">
                <h3>总览</h3>
                <p>知识库总条目: <strong>${data.total_count}</strong></p>
                ${data.faiss_chunks !== undefined ? `
                    <p>向量分块数: <strong>${data.faiss_chunks}</strong></p>
                    <p>已索引知识: <strong>${data.faiss_knowledge}</strong></p>
                ` : ''}
                
                <h3>按类型分布</h3>
                <ul>
                    ${Object.entries(data.by_type).map(([type, count]) => 
                        `<li>${type}: ${count}</li>`
                    ).join('')}
                </ul>
                
                <h3>按来源分布</h3>
                <ul>
                    ${Object.entries(data.by_source).map(([source, count]) => 
                        `<li>${source}: ${count}</li>`
                    ).join('')}
                </ul>
                
                ${chunkTypeHtml}
                
                <div class="stats-actions" style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #eee;">
                    <button class="btn-primary" onclick="handleRebuildIndex()">🔄 重建向量索引</button>
                </div>
            </div>
        `;
        
        document.getElementById('stats-modal').classList.add('active');
    } catch (error) {
        console.error('加载统计信息失败:', error);
        showToast('加载统计信息失败', 'error');
    }
}

async function handleRebuildIndex() {
    showConfirmModal('确定要重建向量索引吗？这可能需要一些时间。', async () => {
        showLoading();
        try {
            const response = await fetch(`${API_BASE}/knowledge/rebuild-index`, {
                method: 'POST'
            });
            const data = await response.json();
            
            hideLoading();
            
            if (data.success) {
                showToast(data.message, 'success');
                await loadStatistics();
            } else {
                showToast(data.message || '重建索引失败', 'error');
            }
        } catch (error) {
            hideLoading();
            console.error('重建索引失败:', error);
            showToast('重建索引失败', 'error');
        }
    }, '重建向量索引');
}

async function handleClearKnowledgeBase() {
    showConfirmModal('确定要清空知识库吗？此操作不可恢复！', async () => {
        try {
            const response = await fetch(`${API_BASE}/knowledge/clear`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                showToast('知识库已清空', 'success');
                await loadStatistics();
            } else {
                showToast(data.message || '清空失败', 'error');
            }
        } catch (error) {
            console.error('清空知识库失败:', error);
            showToast('清空知识库失败', 'error');
        }
    }, '清空知识库');
}

async function showManageModelsModal() {
    document.getElementById('manage-models-modal').classList.add('active');
    await loadAllModels();
}

async function loadAllModels() {
    try {
        const response = await fetch(`${API_BASE}/ai/models/all`);
        const data = await response.json();
        
        if (data.success) {
            renderModelsList(data.models);
        }
    } catch (error) {
        console.error('加载模型列表失败:', error);
        showToast('加载模型列表失败', 'error');
    }
}

function renderModelsList(models) {
    const container = document.getElementById('models-list');
    container.innerHTML = '';
    
    const providers = {};
    for (const [key, model] of Object.entries(models)) {
        if (!providers[model.provider]) {
            providers[model.provider] = [];
        }
        providers[model.provider].push({ key, ...model });
    }
    
    const providerNames = {
        'openai': 'OpenAI',
        'doubao': '豆包',
        'kimi': 'Kimi',
        'minimax': 'MiniMax',
        'glm': '智谱GLM',
        'local': '本地模型'
    };
    
    for (const [provider, modelList] of Object.entries(providers)) {
        const section = document.createElement('div');
        section.className = 'model-provider-section';
        
        const header = document.createElement('h4');
        const isCustomProvider = !providerNames[provider];
        if (isCustomProvider) {
            const displayName = provider.charAt(0).toUpperCase() + provider.slice(1);
            header.innerHTML = `${displayName} <span class="model-badge custom" style="margin-left: 8px;">自定义提供商</span>`;
        } else {
            header.textContent = providerNames[provider];
        }
        section.appendChild(header);
        
        const list = document.createElement('div');
        list.className = 'model-items';
        
        for (const model of modelList) {
            const item = document.createElement('div');
            item.className = `model-item ${model.hidden ? 'hidden-model' : ''} ${model.is_custom ? 'custom-model' : ''}`;
            
            item.innerHTML = `
                <div class="model-item-info">
                    <span class="model-name">${model.display_name}</span>
                    <span class="model-key">(${model.model_name})</span>
                    ${model.is_custom ? '<span class="model-badge custom">自定义</span>' : ''}
                    ${model.hidden ? '<span class="model-badge hidden">已隐藏</span>' : ''}
                    ${!model.has_api_key ? '<span class="model-badge no-key">未配置Key</span>' : ''}
                </div>
                <div class="model-item-actions">
                    <button class="btn-small btn-edit" onclick="showEditModelModal('${model.key}')">✏️ 编辑</button>
                    ${model.hidden 
                        ? `<button class="btn-small btn-show" onclick="handleShowModel('${model.key}')">👁️ 显示</button>`
                        : `<button class="btn-small btn-hide" onclick="handleHideModel('${model.key}')">🙈 隐藏</button>`
                    }
                    <button class="btn-small btn-delete" onclick="handleDeleteModelFromList('${model.key}')">🗑️</button>
                </div>
            `;
            
            list.appendChild(item);
        }
        
        section.appendChild(list);
        container.appendChild(section);
    }
}

async function showEditModelModal(modelKey) {
    const modal = document.getElementById('edit-model-modal');
    const title = document.getElementById('edit-modal-title');
    const isNew = modelKey === null;
    const customProviderInput = document.getElementById('edit-model-provider-custom');
    
    document.getElementById('edit-is-new').value = isNew ? 'true' : 'false';
    document.getElementById('edit-model-key').value = modelKey || '';
    
    if (isNew) {
        title.textContent = '➕ 添加模型';
        document.getElementById('edit-model-provider').value = 'openai';
        document.getElementById('edit-model-name').value = '';
        document.getElementById('edit-model-display-name').value = '';
        document.getElementById('edit-model-api-base').value = '';
        document.getElementById('edit-model-api-key').value = '';
        document.getElementById('edit-model-max-tokens').value = '4096';
        customProviderInput.value = '';
        customProviderInput.style.display = 'none';
        handleEditProviderChange();
    } else {
        title.textContent = '✏️ 编辑模型';
        try {
            const response = await fetch(`${API_BASE}/ai/models/${modelKey}`);
            const data = await response.json();
            
            if (data.success) {
                const config = data.config;
                const providerSelect = document.getElementById('edit-model-provider');
                const knownProviders = ['openai', 'doubao', 'kimi', 'minimax', 'glm', 'local'];
                
                if (knownProviders.includes(config.provider)) {
                    providerSelect.value = config.provider;
                    customProviderInput.style.display = 'none';
                } else {
                    providerSelect.value = 'custom';
                    customProviderInput.value = config.provider;
                    customProviderInput.style.display = 'block';
                }
                
                document.getElementById('edit-model-name').value = config.model_name;
                document.getElementById('edit-model-display-name').value = config.display_name || '';
                document.getElementById('edit-model-api-base').value = config.api_base || '';
                document.getElementById('edit-model-api-key').value = '';
                document.getElementById('edit-model-api-key').placeholder = config.has_api_key ? '已配置 (留空保持不变)' : '输入API Key';
                document.getElementById('edit-model-max-tokens').value = config.max_tokens;
                
                handleEditProviderChange();
            }
        } catch (error) {
            console.error('加载模型配置失败:', error);
            showToast('加载模型配置失败', 'error');
            return;
        }
    }
    
    modal.classList.add('active');
}

async function handleEditProviderChange() {
    const provider = document.getElementById('edit-model-provider').value;
    const customInput = document.getElementById('edit-model-provider-custom');
    const apiBaseInput = document.getElementById('edit-model-api-base');
    const apiBaseHint = document.getElementById('edit-api-base-hint');
    const suggestionsDiv = document.getElementById('edit-model-name-suggestions');
    
    if (provider === 'custom') {
        customInput.style.display = 'block';
        customInput.required = true;
        apiBaseHint.textContent = '请输入API地址';
        suggestionsDiv.innerHTML = '';
        return;
    } else {
        customInput.style.display = 'none';
        customInput.required = false;
    }
    
    try {
        const response = await fetch(`${API_BASE}/ai/providers`);
        const data = await response.json();
        
        if (data.success && data.providers[provider]) {
            const providerInfo = data.providers[provider];
            
            if (!apiBaseInput.value) {
                apiBaseInput.placeholder = providerInfo.default_api_base;
            }
            apiBaseHint.textContent = `默认: ${providerInfo.default_api_base}`;
            
            if (providerInfo.models && providerInfo.models.length > 0) {
                suggestionsDiv.innerHTML = '<small>常用: ' + 
                    providerInfo.models.map(m => `<span class="model-tag" onclick="selectEditModelName('${m}')">${m}</span>`).join(' ') + 
                    '</small>';
            } else {
                suggestionsDiv.innerHTML = '';
            }
        }
    } catch (error) {
        console.error('获取提供商信息失败:', error);
    }
}

function selectEditModelName(modelName) {
    document.getElementById('edit-model-name').value = modelName;
}

async function handleSaveModel() {
    const isNew = document.getElementById('edit-is-new').value === 'true';
    const modelKey = document.getElementById('edit-model-key').value || null;
    let provider = document.getElementById('edit-model-provider').value;
    const customProvider = document.getElementById('edit-model-provider-custom').value.trim();
    const modelName = document.getElementById('edit-model-name').value.trim();
    const displayName = document.getElementById('edit-model-display-name').value.trim();
    const apiBase = document.getElementById('edit-model-api-base').value.trim();
    const apiKey = document.getElementById('edit-model-api-key').value.trim();
    const maxTokens = parseInt(document.getElementById('edit-model-max-tokens').value);
    
    if (provider === 'custom') {
        if (!customProvider) {
            showToast('请输入自定义提供商名称', 'warning');
            return;
        }
        provider = customProvider.toLowerCase().replace(/[^a-z0-9-]/g, '-');
    }
    
    if (!modelName || !apiBase) {
        showToast('请填写模型名称和API地址', 'warning');
        return;
    }
    
    try {
        if (isNew) {
            const newKey = modelName.toLowerCase().replace(/[^a-z0-9-]/g, '-');
            const response = await fetch(`${API_BASE}/ai/models/custom`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model_key: newKey,
                    provider: provider,
                    model_name: modelName,
                    display_name: displayName || null,
                    api_base: apiBase,
                    api_key: apiKey || null,
                    max_tokens: maxTokens
                })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                showToast('模型添加成功', 'success');
                document.getElementById('edit-model-modal').classList.remove('active');
                await loadAllModels();
                await loadModels();
            } else {
                let errorMsg = data.message || '添加失败';
                if (data.detail) {
                    if (Array.isArray(data.detail)) {
                        errorMsg = data.detail.map(e => {
                            const field = e.loc ? e.loc.join('.') : '';
                            return `${field}: ${e.msg}`;
                        }).join(', ');
                    } else if (typeof data.detail === 'string') {
                        errorMsg = data.detail;
                    }
                }
                showToast(errorMsg, 'error');
            }
        } else {
            const configResponse = await fetch(`${API_BASE}/ai/models/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model_key: modelKey,
                    max_tokens: maxTokens
                })
            });
            
            const configData = await configResponse.json();
            
            if (apiBase) {
                await fetch(`${API_BASE}/ai/models/${modelKey}/api-base`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_base: apiBase })
                });
            }
            
            if (apiKey) {
                await fetch(`${API_BASE}/ai/models/api-key`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        model_key: modelKey, 
                        api_key: apiKey 
                    })
                });
            }
            
            showToast('配置已保存', 'success');
            document.getElementById('edit-model-modal').classList.remove('active');
            await loadAllModels();
            await loadModels();
        }
    } catch (error) {
        console.error('保存模型失败:', error);
        showToast('保存模型失败', 'error');
    }
}

async function handleHideModel(modelKey) {
    try {
        const response = await fetch(`${API_BASE}/ai/models/${modelKey}/hide`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(data.message, 'success');
            await loadAllModels();
            await loadModels();
        } else {
            showToast(data.message || '隐藏失败', 'error');
        }
    } catch (error) {
        console.error('隐藏模型失败:', error);
        showToast('隐藏模型失败', 'error');
    }
}

async function handleShowModel(modelKey) {
    try {
        const response = await fetch(`${API_BASE}/ai/models/${modelKey}/show`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(data.message, 'success');
            await loadAllModels();
            await loadModels();
        } else {
            showToast(data.message || '显示失败', 'error');
        }
    } catch (error) {
        console.error('显示模型失败:', error);
        showToast('显示模型失败', 'error');
    }
}

async function handleDeleteModelFromList(modelKey) {
    showConfirmModal('确定要删除此模型吗？此操作不可恢复！', async () => {
        try {
            const response = await fetch(`${API_BASE}/ai/models/${modelKey}`, {
                method: 'DELETE'
            });
            
            const data = await response.json();
            
            if (data.success) {
                showToast('模型已删除', 'success');
                await loadAllModels();
                await loadModels();
            } else {
                showToast(data.message || '删除失败', 'error');
            }
        } catch (error) {
            console.error('删除模型失败:', error);
            showToast('删除模型失败', 'error');
        }
    }, '删除模型');
}

async function handleResetHiddenModels() {
    showConfirmModal('确定要恢复所有隐藏的模型吗？', async () => {
        try {
            const response = await fetch(`${API_BASE}/ai/models/reset-hidden`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                showToast(data.message, 'success');
                await loadAllModels();
                await loadModels();
            } else {
                showToast(data.message || '恢复失败', 'error');
            }
        } catch (error) {
            console.error('恢复隐藏模型失败:', error);
            showToast('恢复隐藏模型失败', 'error');
        }
    }, '恢复隐藏模型');
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function showLoading() {
    const overlay = document.createElement('div');
    overlay.className = 'loading-overlay';
    overlay.id = 'loading-overlay';
    overlay.innerHTML = '<div class="loading-spinner"></div>';
    document.body.appendChild(overlay);
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.remove();
    }
}

function showConfirmModal(message, callback, title = '确认操作') {
    document.getElementById('confirm-modal-title').textContent = title;
    document.getElementById('confirm-modal-message').textContent = message;
    confirmCallback = callback;
    document.getElementById('confirm-modal').classList.add('active');
}

async function showSessionsModal() {
    const modal = document.getElementById('sessions-modal');
    const list = document.getElementById('sessions-list');
    list.innerHTML = '<p>加载中...</p>';
    modal.classList.add('active');
    
    try {
        const response = await fetch(`${API_BASE}/sessions`);
        const data = await response.json();
        
        if (data.success && data.sessions.length > 0) {
            list.innerHTML = data.sessions.map(s => `
                <div class="session-item" data-session-id="${s.session_id}">
                    <div class="session-info">
                        <span class="session-id">会话: ${s.session_id.substring(0, 8)}...</span>
                        <span class="session-count">${s.message_count} 条消息</span>
                    </div>
                    <div class="session-time">${new Date(s.updated_at).toLocaleString()}</div>
                </div>
            `).join('');
            
            list.querySelectorAll('.session-item').forEach(item => {
                item.addEventListener('click', () => showSessionDetail(item.dataset.sessionId));
            });
        } else {
            list.innerHTML = '<p class="empty-message">暂无对话记录</p>';
        }
    } catch (error) {
        console.error('加载对话记录失败:', error);
        list.innerHTML = '<p class="error-message">加载失败</p>';
    }
}

async function showSessionDetail(sessionId) {
    const modal = document.getElementById('session-detail-modal');
    const content = document.getElementById('session-detail-content');
    content.innerHTML = '<p>加载中...</p>';
    currentSessionId = sessionId;
    modal.classList.add('active');
    
    try {
        const response = await fetch(`${API_BASE}/session/${sessionId}`);
        const data = await response.json();
        
        if (data.success && data.session) {
            const session = data.session;
            content.innerHTML = session.messages.map(m => `
                <div class="message ${m.role}">
                    <div class="message-role">${m.role === 'user' ? '👤 用户' : '🤖 AI'}</div>
                    <div class="message-content">${escapeHtml(m.content)}</div>
                </div>
            `).join('');
        } else {
            content.innerHTML = '<p class="error-message">加载失败</p>';
        }
    } catch (error) {
        console.error('加载对话详情失败:', error);
        content.innerHTML = '<p class="error-message">加载失败</p>';
    }
}

async function showCorrectionsModal() {
    const modal = document.getElementById('corrections-modal');
    const list = document.getElementById('corrections-list');
    list.innerHTML = '<p>加载中...</p>';
    modal.classList.add('active');
    
    try {
        const response = await fetch(`${API_BASE}/corrections/pending`);
        const data = await response.json();
        
        if (data.success && data.corrections.length > 0) {
            list.innerHTML = data.corrections.map(c => `
                <div class="correction-item" data-correction-id="${c.correction_id || c.knowledge_id}">
                    <div class="correction-header">
                        <span class="knowledge-id">知识ID: ${c.knowledge_id}</span>
                        <span class="correction-time">${new Date(c.applied_at).toLocaleString()}</span>
                    </div>
                    <div class="correction-body">
                        <p><strong>字段:</strong> ${c.correction.field}</p>
                        <p><strong>原值:</strong> <span class="old-value">${escapeHtml(String(c.correction.old_value))}</span></p>
                        <p><strong>新值:</strong> <span class="new-value">${escapeHtml(String(c.correction.new_value))}</span></p>
                        <p><strong>原因:</strong> ${c.correction.reason}</p>
                        <p><strong>置信度:</strong> ${(c.correction.confidence * 100).toFixed(0)}%</p>
                    </div>
                    <div class="correction-actions">
                        <button class="btn-primary approve-correction" data-id="${c.correction_id || c.knowledge_id}">✅ 批准</button>
                        <button class="btn-danger reject-correction" data-id="${c.correction_id || c.knowledge_id}">❌ 拒绝</button>
                    </div>
                </div>
            `).join('');
            
            list.querySelectorAll('.approve-correction').forEach(btn => {
                btn.addEventListener('click', () => handleApproveCorrection(btn.dataset.id));
            });
            list.querySelectorAll('.reject-correction').forEach(btn => {
                btn.addEventListener('click', () => handleRejectCorrection(btn.dataset.id));
            });
        } else {
            list.innerHTML = '<p class="empty-message">暂无待审核的纠正</p>';
        }
    } catch (error) {
        console.error('加载纠正列表失败:', error);
        list.innerHTML = '<p class="error-message">加载失败</p>';
    }
}

async function handleApproveCorrection(correctionId) {
    try {
        const response = await fetch(`${API_BASE}/corrections/${correctionId}/approve`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            showToast('纠正已批准', 'success');
            showCorrectionsModal();
        } else {
            showToast(data.message || '批准失败', 'error');
        }
    } catch (error) {
        console.error('批准纠正失败:', error);
        showToast('批准失败', 'error');
    }
}

async function handleRejectCorrection(correctionId) {
    try {
        const response = await fetch(`${API_BASE}/corrections/${correctionId}/reject`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            showToast('纠正已拒绝', 'success');
            showCorrectionsModal();
        } else {
            showToast(data.message || '拒绝失败', 'error');
        }
    } catch (error) {
        console.error('拒绝纠正失败:', error);
        showToast('拒绝失败', 'error');
    }
}

async function handleExtractCurrentChat() {
    const conversation = conversations[currentConversationId];
    if (!conversation || conversation.messages.length < 2) {
        showToast('对话内容太少，无法提取知识', 'warning');
        return;
    }
    
    showLoading();
    
    try {
        let sessionId = currentSessionId;
        
        if (!sessionId) {
            const createResponse = await fetch(`${API_BASE}/session/create`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ metadata: { source: 'chat' } })
            });
            const createData = await createResponse.json();
            sessionId = createData.session_id;
            currentSessionId = sessionId;
        }
        
        for (const msg of conversation.messages) {
            await fetch(`${API_BASE}/session/message`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    role: msg.role,
                    content: msg.content
                })
            });
        }
        
        const extractResponse = await fetch(`${API_BASE}/session/${sessionId}/extract`, {
            method: 'POST'
        });
        const extractData = await extractResponse.json();
        
        hideLoading();
        
        if (extractData.success && extractData.extraction_count > 0) {
            lastExtractionResult = extractData;
            showExtractionResult(extractData);
        } else {
            showToast('未提取到有效知识', 'info');
        }
    } catch (error) {
        hideLoading();
        console.error('提取知识失败:', error);
        showToast('提取知识失败', 'error');
    }
}

async function handleExtractSession() {
    if (!currentSessionId) {
        showToast('请先选择一个会话', 'warning');
        return;
    }
    
    showLoading();
    
    try {
        const response = await fetch(`${API_BASE}/session/${currentSessionId}/extract`, {
            method: 'POST'
        });
        const data = await response.json();
        
        hideLoading();
        
        if (data.success && data.extraction_count > 0) {
            lastExtractionResult = data;
            document.getElementById('session-detail-modal').classList.remove('active');
            showExtractionResult(data);
        } else {
            showToast('未提取到有效知识', 'info');
        }
    } catch (error) {
        hideLoading();
        console.error('提取知识失败:', error);
        showToast('提取知识失败', 'error');
    }
}

function showExtractionResult(data) {
    const modal = document.getElementById('extraction-result-modal');
    const content = document.getElementById('extraction-result-content');
    
    content.innerHTML = `
        <p class="extraction-summary">共提取 ${data.extraction_count} 条知识:</p>
        <div class="extractions-list">
            ${data.extractions.map((e, i) => `
                <div class="extraction-item">
                    <div class="extraction-header">
                        <span class="extraction-type">${e.knowledge_type}</span>
                        <span class="extraction-confidence">置信度: ${(e.confidence * 100).toFixed(0)}%</span>
                    </div>
                    <h4>${escapeHtml(e.name)}</h4>
                    <p class="extraction-desc">${escapeHtml(e.description)}</p>
                    ${e.tags && e.tags.length > 0 ? `
                        <div class="extraction-tags">
                            ${e.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}
                        </div>
                    ` : ''}
                </div>
            `).join('')}
        </div>
    `;
    
    modal.classList.add('active');
}

async function handleImportExtractions() {
    if (!lastExtractionResult || !lastExtractionResult.extractions) {
        showToast('没有可导入的知识', 'warning');
        return;
    }
    
    showLoading();
    
    try {
        let importedCount = 0;
        
        for (const extraction of lastExtractionResult.extractions) {
            const knowledgeData = {
                knowledge_type: extraction.knowledge_type,
                name: extraction.name,
                description: extraction.description,
                source_type: 'conversation',
                tags: extraction.tags || [],
                metadata: extraction.content || {}
            };
            
            const response = await fetch(`${API_BASE}/knowledge/import`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    source_path: `session:${lastExtractionResult.session_id}`,
                    recursive: false
                })
            });
            
            if (response.ok) {
                importedCount++;
            }
        }
        
        hideLoading();
        showToast(`已导入 ${importedCount} 条知识`, 'success');
        document.getElementById('extraction-result-modal').classList.remove('active');
        await loadStatistics();
    } catch (error) {
        hideLoading();
        console.error('导入知识失败:', error);
        showToast('导入知识失败', 'error');
    }
}


let requirementSessionId = null;
let currentClarificationQuestions = [];

async function processRequirementWithDivergentConvergent(message) {
    try {
        const response = await fetch(`${API_BASE}/requirement/process`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                requirement: message,
                session_id: requirementSessionId,
                conversation_history: conversations[currentConversationId]?.messages?.slice(-6) || [],
                max_context_tokens: 2000
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            requirementSessionId = data.context_id;
            
            return {
                phase: data.phase,
                narrativeContext: data.narrative_context,
                structuredContext: data.structured_context,
                primaryKnowledge: data.primary_knowledge,
                supportingKnowledge: data.supporting_knowledge,
                totalTokens: data.total_tokens,
                relevanceScore: data.relevance_score,
                suggestedActions: data.suggested_actions,
                nextQuestions: data.next_questions
            };
        }
        
        return null;
    } catch (error) {
        console.error('需求处理失败:', error);
        return null;
    }
}

async function analyzeRequirementIntent(message) {
    try {
        const response = await fetch(`${API_BASE}/requirement/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                requirement: message
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            return {
                phase: data.phase,
                intent: data.intent,
                keywords: data.keywords,
                knowledgeTypes: data.knowledge_types,
                clarityScore: data.clarity_score,
                completenessScore: data.completeness_score,
                ambiguities: data.ambiguities,
                suggestedClarifications: data.suggested_clarifications
            };
        }
        
        return null;
    } catch (error) {
        console.error('需求分析失败:', error);
        return null;
    }
}

async function getClarificationQuestions(message) {
    try {
        const response = await fetch(`${API_BASE}/requirement/clarifications`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                requirement: message,
                session_id: requirementSessionId
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentClarificationQuestions = data.questions;
            return data.questions;
        }
        
        return [];
    } catch (error) {
        console.error('获取澄清问题失败:', error);
        return [];
    }
}

async function submitClarificationResponses(responses) {
    try {
        const response = await fetch(`${API_BASE}/requirement/clarifications/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: requirementSessionId,
                responses: responses
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            return {
                phase: data.phase,
                clarityScore: data.clarity_score,
                completenessScore: data.completeness_score,
                updatedKeywords: data.updated_keywords,
                contextEntities: data.context_entities
            };
        }
        
        return null;
    } catch (error) {
        console.error('提交澄清回答失败:', error);
        return null;
    }
}

function formatPhaseDisplay(phase) {
    const phaseMap = {
        'divergent': { text: '发散阶段', icon: '🌀', color: '#f39c12' },
        'clarifying': { text: '澄清阶段', icon: '❓', color: '#3498db' },
        'convergent': { text: '收敛阶段', icon: '🎯', color: '#2ecc71' },
        'confirmed': { text: '已确认', icon: '✅', color: '#27ae60' }
    };
    
    return phaseMap[phase] || { text: phase, icon: '📝', color: '#95a5a6' };
}

function generateRequirementResponse(analysis, processedResult) {
    const phaseInfo = formatPhaseDisplay(processedResult?.phase || analysis?.phase);
    
    let response = `### ${phaseInfo.icon} 需求分析结果 (${phaseInfo.text})\n\n`;
    
    if (analysis) {
        if (analysis.intent?.primary) {
            response += `**识别意图**: ${analysis.intent.primary}\n`;
            if (analysis.intent.confidence) {
                response += `**置信度**: ${(analysis.intent.confidence * 100).toFixed(0)}%\n`;
            }
        }
        
        if (analysis.keywords?.primary?.length > 0) {
            response += `\n**关键词**: ${analysis.keywords.primary.join(', ')}\n`;
        }
        
        if (analysis.clarityScore !== undefined) {
            response += `\n**清晰度**: ${(analysis.clarityScore * 100).toFixed(0)}%\n`;
        }
    }
    
    if (processedResult?.narrativeContext) {
        response += `\n---\n\n### 📚 相关知识上下文\n\n`;
        response += processedResult.narrativeContext;
    }
    
    if (processedResult?.suggestedActions?.length > 0) {
        response += `\n\n### 💡 建议操作\n\n`;
        processedResult.suggestedActions.forEach(action => {
            response += `- ${action}\n`;
        });
    }
    
    if (processedResult?.nextQuestions?.length > 0) {
        response += `\n\n### ❓ 进一步问题\n\n`;
        processedResult.nextQuestions.forEach(q => {
            response += `- ${q}\n`;
        });
    }
    
    return response;
}

function showClarificationModal(questions, onResolve) {
    const modal = document.getElementById('clarification-modal');
    const container = document.getElementById('clarification-questions-container');
    
    if (!modal || !container) {
        onResolve({});
        return;
    }
    
    container.innerHTML = questions.map((q, idx) => `
        <div class="clarification-question" data-question-id="${q.id}">
            <div class="clarification-question-text">
                <span class="question-number">${idx + 1}.</span>
                ${escapeHtml(q.question)}
            </div>
            ${q.options && q.options.length > 0 ? `
                <div class="clarification-options">
                    ${q.options.map(opt => `
                        <label class="clarification-option">
                            <input type="radio" name="q_${q.id}" value="${escapeHtml(opt)}">
                            <span>${escapeHtml(opt)}</span>
                        </label>
                    `).join('')}
                    ${q.allows_free_input ? `
                        <div class="clarification-free-input">
                            <input type="text" class="clarification-text-input" 
                                   data-question-id="${q.id}" 
                                   placeholder="或输入其他答案...">
                        </div>
                    ` : ''}
                </div>
            ` : `
                <input type="text" class="clarification-text-input full-width" 
                       data-question-id="${q.id}" 
                       placeholder="请输入您的回答...">
            `}
        </div>
    `).join('');
    
    const submitBtn = document.getElementById('submit-clarification-btn');
    const cancelBtn = document.getElementById('cancel-clarification-btn');
    
    const handleSubmit = () => {
        const responses = {};
        
        questions.forEach(q => {
            const selectedOption = container.querySelector(`input[name="q_${q.id}"]:checked`);
            const freeInput = container.querySelector(`.clarification-text-input[data-question-id="${q.id}"]`);
            
            if (selectedOption) {
                responses[q.id] = selectedOption.value;
            } else if (freeInput && freeInput.value.trim()) {
                responses[q.id] = freeInput.value.trim();
            }
        });
        
        modal.classList.remove('active');
        onResolve(responses);
        
        submitBtn?.removeEventListener('click', handleSubmit);
        cancelBtn?.removeEventListener('click', handleCancel);
    };
    
    const handleCancel = () => {
        modal.classList.remove('active');
        onResolve({});
        
        submitBtn?.removeEventListener('click', handleSubmit);
        cancelBtn?.removeEventListener('click', handleCancel);
    };
    
    submitBtn?.addEventListener('click', handleSubmit);
    cancelBtn?.addEventListener('click', handleCancel);
    
    modal.classList.add('active');
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
