const API_BASE = '';
const STORED_SESSION_KEY = 'chat_session_id';

// DOM элементы
const settingsPanel = document.getElementById('settingsPanel');
const toggleSettingsBtn = document.getElementById('toggleSettingsBtn');
const toggleLogsBtn = document.getElementById('toggleLogsBtn');
const logsSidebar = document.getElementById('logsSidebar');
const overlay = document.getElementById('overlay');
const closeLogsBtn = document.getElementById('closeLogsBtn');
const confluenceTokenInput = document.getElementById('confluenceToken');
const jiraTokenInput = document.getElementById('jiraToken');
const gigachatTokenInput = document.getElementById('gigachatToken');
const saveBtn = document.getElementById('saveSettingsBtn');
const clearBtn = document.getElementById('clearSettingsBtn');
const testBtn = document.getElementById('testConnectionBtn');
const sendBtn = document.getElementById('sendBtn');
const questionInput = document.getElementById('questionInput');
const chatArea = document.getElementById('chatArea');
const confluenceStatusDot = document.getElementById('confluence-status-dot');
const jiraStatusDot = document.getElementById('jira-status-dot');
const llmStatusDot = document.getElementById('llm-status-dot');
const updateRagBtn = document.getElementById('updateRagBtn');
const refreshLogsBtn = document.getElementById('refreshLogsBtn');
const clearLogsDisplayBtn = document.getElementById('clearLogsDisplayBtn');
const downloadLogsBtn = document.getElementById('downloadLogsBtn');
const logsArea = document.getElementById('logsArea');
const lastUpdateRagDateSpan = document.getElementById('lastUpdateRagDate');
const refreshUpdateRagDateBtn = document.getElementById('refreshUpdateRagDateBtn');
const clearHistoryBtn = document.getElementById('clearHistoryBtn');

let isTyping = false;
let currentSessionId = localStorage.getItem(STORED_SESSION_KEY);
if (!currentSessionId) {
    currentSessionId = 'session_' + Math.random().toString(36).substr(2, 9);
    localStorage.setItem(STORED_SESSION_KEY, currentSessionId);
}
let logsUpdateInterval = null;
let pendingCommand = null;

// Хранение состояния для инлайн-кнопок
let selectedTemplate = null;  // { id, label, template }
let currentQuestion = null;    // сформированный вопрос для отправки

// --- Вспомогательные функции ---
async function sendQuestionToBot(question) {
    if (!question || isTyping) return;
    
    // Добавляем сообщение пользователя в чат
    addMessage('user', question);
    
    isTyping = true;
    sendBtn.disabled = true;
    
    const typingDiv = addTypingIndicator();
    
    try {
        const response = await fetch(`${API_BASE}/ask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: question, session_id: currentSessionId })
        });
        
        removeTypingIndicator(typingDiv);
        
        if (!response.ok) {
            const errorText = await response.text();
            addMessage('bot', `❌ Ошибка ${response.status}: ${errorText}`);
            return;
        }
        
        const data = await response.json();
        let answerText = data.answer || 'Ответ не получен';
        if (data.sources && data.sources.length) {
            answerText += '\n\n📎 Источники:\n' + data.sources.slice(0,3).map(s => `- ${s.datamart || s.datamart_name || '?'}`).join('\n');
        }
        addMessage('bot', answerText);
    } catch (err) {
        removeTypingIndicator(typingDiv);
        addMessage('bot', `❌ Ошибка сети: ${err.message}`);
    } finally {
        isTyping = false;
        sendBtn.disabled = false;
        questionInput.focus();
    }
}

function addMessage(role, text, extraButtons = null) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    const avatar = role === 'user' ? '👤' : '🤖';
    const formattedText = text.replace(/\n/g, '<br>').replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    let buttonsHtml = '';
    if (extraButtons && extraButtons.length) {
        buttonsHtml = '<div class="inline-buttons">' + extraButtons.map(btn => 
            `<button class="inline-btn" data-value="${btn.value}" data-type="${btn.type}" data-template-id="${btn.templateId || ''}" data-template="${btn.template || ''}">${btn.label}</button>`
        ).join('') + '</div>';
    }
    messageDiv.innerHTML = `
        <div class="avatar">${avatar}</div>
        <div class="bubble">
            ${formattedText}
            ${buttonsHtml}
        </div>
    `;
    chatArea.appendChild(messageDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
    
    // Привязываем обработчики к кнопкам после добавления в DOM
    if (extraButtons && extraButtons.length) {
        messageDiv.querySelectorAll('.inline-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const value = btn.getAttribute('data-value');
                const type = btn.getAttribute('data-type');
                const templateId = btn.getAttribute('data-template-id');
                const templateText = btn.getAttribute('data-template');
                
                if (type === 'template') {
                    // Сохраняем выбранный шаблон
                    selectedTemplate = {
                        id: templateId,
                        label: btn.innerText,
                        template: templateText
                    };
                    // Показываем список витрин
                    await showDatamartButtons();
                } else if (type === 'datamart') {
                    // Формируем полный вопрос, подставляя витрину в шаблон
                    if (selectedTemplate && selectedTemplate.template) {
                        const fullQuestion = selectedTemplate.template.replace('{datamart}', value);
                        // Отправляем вопрос боту
                        await sendQuestionToBot(fullQuestion);
                        // Сбрасываем выбранный шаблон
                        selectedTemplate = null;
                    } else {
                        addMessage('bot', '❌ Ошибка: не выбран шаблон вопроса.');
                    }
                }
            });
        });
    }
}

async function showDatamartButtons() {
    if (!selectedTemplate) return;
    
    try {
        const resp = await fetch(`${API_BASE}/api/datamarts/list`);
        if (resp.ok) {
            const datamarts = await resp.json();
            if (datamarts.length === 0) {
                addMessage('bot', '❌ Нет доступных витрин. Сначала выполните Update RAG.');
                selectedTemplate = null;
                return;
            }
            const buttons = datamarts.map(dm => ({ 
                label: dm, 
                value: dm, 
                type: 'datamart',
                templateId: selectedTemplate.id,
                template: selectedTemplate.template
            }));
            addMessage('bot', `📌 Выберите витрину для вопроса: "${selectedTemplate.label}"`, buttons);
        } else {
            addMessage('bot', '❌ Не удалось получить список витрин.');
            selectedTemplate = null;
        }
    } catch (err) {
        addMessage('bot', `❌ Ошибка: ${err.message}`);
        selectedTemplate = null;
    }
}

async function loadQuestionTemplates() {
    try {
        const resp = await fetch(`${API_BASE}/api/questions/templates`);
        if (resp.ok) {
            const templates = await resp.json();
            const buttons = templates.map(t => ({ 
                label: t.label, 
                value: t.id, 
                type: 'template',
                templateId: t.id,
                template: t.template
            }));
            addMessage('bot', '📝 Напишите вопрос или выберите из списка:', buttons);
        }
    } catch (err) {
        console.error('Failed to load templates', err);
    }
}

// --- Управление боковой панелью логов ---
function openLogsSidebar() { logsSidebar.classList.add('open'); overlay.classList.add('show'); startLogsUpdates(); }
function closeLogsSidebar() { logsSidebar.classList.remove('open'); overlay.classList.remove('show'); stopLogsUpdates(); }
function startLogsUpdates() { if (logsUpdateInterval) clearInterval(logsUpdateInterval); fetchLogs(); logsUpdateInterval = setInterval(fetchLogs, 1000); }
function stopLogsUpdates() { if (logsUpdateInterval) clearInterval(logsUpdateInterval); logsUpdateInterval = null; }

// --- Загрузка истории чата ---
async function loadChatHistory() {
    try {
        const resp = await fetch(`${API_BASE}/api/chat/history/${currentSessionId}`);
        if (resp.ok) {
            const history = await resp.json();
            while (chatArea.children.length > 1) chatArea.removeChild(chatArea.lastChild);
            for (const msg of history) {
                addMessage('user', msg.user);
                let botText = msg.bot;
                if (msg.sources && msg.sources.length) botText += '\n\n📎 Источники: ' + msg.sources.join(', ');
                addMessage('bot', botText);
            }
        }
    } catch (err) { console.error('Failed to load chat history', err); }
}

// --- Загрузка даты последнего RAG ---
async function loadLastEvents() {
    try {
        const resp = await fetch(`${API_BASE}/api/sync/last-events`);
        if (resp.ok) {
            const data = await resp.json();
            lastUpdateRagDateSpan.innerText = data.last_rag_update ? new Date(data.last_rag_update).toLocaleString() : 'Не выполнялся';
        } else throw new Error();
    } catch (err) { lastUpdateRagDateSpan.innerText = 'Ошибка'; }
}

// --- Проверка статусов ---
async function updateStatusIndicators() {
    const dots = [confluenceStatusDot, jiraStatusDot, llmStatusDot];
    dots.forEach(dot => dot.classList.add('pulse'));
    try {
        const resp = await fetch(`${API_BASE}/api/health/external`);
        if (resp.ok) {
            const data = await resp.json();
            confluenceStatusDot.className = data.confluence?.status === 'ok' ? 'status-dot green' : 'status-dot red';
            jiraStatusDot.className = data.jira?.status === 'ok' ? 'status-dot green' : 'status-dot red';
            llmStatusDot.className = data.gigachat?.status === 'ok' ? 'status-dot green' : 'status-dot red';
            addMessage('bot', '✅ Проверка подключения завершена. Индикаторы обновлены.');
        } else throw new Error();
    } catch(e) {
        confluenceStatusDot.className = 'status-dot red';
        jiraStatusDot.className = 'status-dot red';
        llmStatusDot.className = 'status-dot red';
        addMessage('bot', '❌ Ошибка при проверке подключения.');
    } finally {
        dots.forEach(dot => dot.classList.remove('pulse'));
    }
}

// --- Работа с токенами ---
async function saveTokens() {
    const confluenceToken = confluenceTokenInput.value;
    const jiraToken = jiraTokenInput.value;
    const gigachatToken = gigachatTokenInput.value;
    try {
        const resp = await fetch(`${API_BASE}/api/save-tokens`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confluence_token: confluenceToken, jira_token: jiraToken, gigachat_token: gigachatToken })
        });
        const data = await resp.json();
        if (resp.ok) {
            showStatusMessage(data.message || 'Настройки сохранены на сервере', 'info');
            await updateStatusIndicators();
            await checkTokensConfigured();
            loadQuestionTemplates();
        } else showStatusMessage(`Ошибка: ${data.detail || data.message}`, 'error');
    } catch (err) { showStatusMessage(`Ошибка сети: ${err.message}`, 'error'); }
}

async function clearTokens() {
    try {
        const resp = await fetch(`${API_BASE}/api/clear-tokens`, { method: 'POST' });
        const data = await resp.json();
        if (resp.ok) {
            showStatusMessage(data.message || 'Токены удалены с сервера', 'info');
            await updateStatusIndicators();
            await checkTokensConfigured();
        } else showStatusMessage(`Ошибка: ${data.detail || data.message}`, 'error');
    } catch (err) { showStatusMessage(`Ошибка сети: ${err.message}`, 'error'); }
}

async function checkTokensConfigured() {
    try {
        const resp = await fetch(`${API_BASE}/api/tokens-status`);
        if (resp.ok) {
            const data = await resp.json();
            sendBtn.disabled = !data.configured || isTyping;
            if (!data.configured) settingsPanel.classList.add('show');
            else if (data.configured && !window._templatesShown) {
                window._templatesShown = true;
                loadQuestionTemplates();
            }
        }
    } catch (err) { console.error(err); }
}

function showStatusMessage(text, type) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message bot`;
    msgDiv.innerHTML = `<div class="avatar">ℹ️</div><div class="bubble" style="background:#fff3cd">${text}</div>`;
    chatArea.appendChild(msgDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
    setTimeout(() => msgDiv.remove(), 5000);
}

async function testConnection() { await updateStatusIndicators(); }

// --- Логи ---
async function fetchLogs() {
    try {
        const resp = await fetch(`${API_BASE}/api/logs`);
        if (resp.ok) {
            const logs = await resp.json();
            logsArea.innerText = logs.join('\n') || '(пусто)';
            logsArea.scrollTop = logsArea.scrollHeight;
            if (pendingCommand) {
                const logsText = logs.join('\n');
                const success = new RegExp(`✅ Команда ${pendingCommand} завершена`).test(logsText);
                const error = new RegExp(`❌ Команда ${pendingCommand} завершена с кодом`).test(logsText);
                if (success || error) {
                    if (success) {
                        addMessage('bot', `✅ ${pendingCommand === 'update-rag' ? 'Update RAG' : pendingCommand} завершён`);
                        if (pendingCommand === 'update-rag') loadLastEvents();
                    } else if (error) addMessage('bot', `❌ Ошибка при выполнении ${pendingCommand}`);
                    pendingCommand = null;
                }
            }
        } else logsArea.innerText = 'Не удалось загрузить логи';
    } catch (err) { logsArea.innerText = `Ошибка: ${err.message}`; }
}
function clearLogsDisplay() { logsArea.innerText = '(очищено локально)'; }
function downloadLogs() { window.location.href = `${API_BASE}/api/logs/download`; }

// --- Запуск команд ---
async function runCommand(endpoint, commandName, displayName) {
    if (pendingCommand) { showStatusMessage(`Предыдущая команда ${pendingCommand} ещё выполняется`, 'error'); return; }
    pendingCommand = commandName;
    addMessage('bot', `🔄 ${displayName} запущен... (следите за логами)`);
    try {
        const resp = await fetch(`${API_BASE}${endpoint}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || data.message || 'Ошибка');
        showStatusMessage(data.message || 'Команда запущена', 'info');
    } catch (err) {
        addMessage('bot', `❌ Ошибка при запуске ${displayName}: ${err.message}`);
        pendingCommand = null;
    }
}

// --- Отправка сообщения из текстового поля ---
async function sendMessage() {
    const question = questionInput.value.trim();
    if (!question || isTyping) return;
    
    await sendQuestionToBot(question);
    questionInput.value = '';
    questionInput.style.height = 'auto';
}

function addTypingIndicator() {
    const div = document.createElement('div');
    div.className = 'message bot typing-message';
    div.innerHTML = `<div class="avatar">🤖</div><div class="typing">🤖 <span>●</span><span>●</span><span>●</span> печатает...</div>`;
    chatArea.appendChild(div);
    chatArea.scrollTop = chatArea.scrollHeight;
    return div;
}
function removeTypingIndicator(element) { if (element && element.remove) element.remove(); }

// Инициализация
async function init() {
    loadChatHistory();
    await loadLastEvents();
    await updateStatusIndicators();
    await checkTokensConfigured();
}
function initFieldIcons() {
    document.querySelectorAll('.toggle-visibility').forEach(icon => {
        icon.addEventListener('click', () => {
            const targetId = icon.getAttribute('data-target');
            const input = document.getElementById(targetId);
            if (input.type === 'password') { input.type = 'text'; icon.textContent = '🙈'; }
            else { input.type = 'password'; icon.textContent = '👁️'; }
        });
    });
    document.querySelectorAll('.clear-field').forEach(icon => {
        icon.addEventListener('click', () => {
            const targetId = icon.getAttribute('data-target');
            document.getElementById(targetId).value = '';
        });
    });
}

// Обработчики событий
questionInput.addEventListener('input', function() { this.style.height = 'auto'; this.style.height = Math.min(this.scrollHeight, 100) + 'px'; });
questionInput.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
saveBtn.onclick = saveTokens;
clearBtn.onclick = clearTokens;
testBtn.onclick = testConnection;
sendBtn.onclick = sendMessage;
toggleSettingsBtn.onclick = () => settingsPanel.classList.toggle('show');
toggleLogsBtn.onclick = openLogsSidebar;
closeLogsBtn.onclick = closeLogsSidebar;
overlay.onclick = closeLogsSidebar;
updateRagBtn.onclick = () => runCommand('/api/update-rag', 'update-rag', 'Update RAG');
refreshLogsBtn.onclick = () => { fetchLogs(); startLogsUpdates(); };
clearLogsDisplayBtn.onclick = clearLogsDisplay;
downloadLogsBtn.onclick = downloadLogs;
refreshUpdateRagDateBtn.onclick = loadLastEvents;
clearHistoryBtn.onclick = async () => {
    if (confirm('Удалить историю чата?')) {
        await fetch(`${API_BASE}/api/clear-chat-history`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: currentSessionId }) });
        while (chatArea.children.length > 1) chatArea.removeChild(chatArea.lastChild);
        showStatusMessage('История чата очищена', 'info');
    }
};
const shutdownBtn = document.getElementById('shutdownBtn');
shutdownBtn.onclick = async () => {
    if (confirm('Остановить сервер бота?')) {
        await fetch(`${API_BASE}/api/shutdown`, { method: 'POST' });
        showStatusMessage('Сервер останавливается...', 'info');
        setTimeout(() => { document.body.innerHTML = '<h2>Бот остановлен</h2>'; }, 1000);
    }
};

init();
initFieldIcons();
