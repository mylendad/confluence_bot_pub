const API_BASE = '';
const STORED_SESSION_KEY = 'chat_session_id';

// DOM элементы
const mainApp = document.getElementById('mainApp');
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
const clearLogsDisplayBtn = document.getElementById('clearLogsDisplayBtn');
const downloadLogsBtn = document.getElementById('downloadLogsBtn');
const logsArea = document.getElementById('logsArea');
const lastUpdateRagDateSpan = document.getElementById('lastUpdateRagDate');
const refreshUpdateRagDateBtn = document.getElementById('refreshUpdateRagDateBtn');
const clearHistoryBtn = document.getElementById('clearHistoryBtn');
const infoBtn = document.getElementById('infoBtn');
const infoModal = document.getElementById('infoModal');
const closeInfoModalBtn = document.getElementById('closeInfoModalBtn');
const qqBtn = document.getElementById('qqBtn');

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
let clearedLogsDisplay = false; // Флаг очистки логов

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
    let buttonsContainerId = 'btns_' + Math.random().toString(36).substr(2, 9);

    if (extraButtons && extraButtons.length) {
        buttonsHtml = `<div class="inline-buttons" id="${buttonsContainerId}">` + extraButtons.map(btn => 
            `<button class="inline-btn-bubble" data-value="${btn.value}" data-type="${btn.type}" data-template-id="${btn.templateId || ''}" data-template="${btn.template || ''}">${btn.label}</button>`
        ).join('') + '</div>';
    }
    messageDiv.innerHTML = `
        <div class="avatar">${avatar}</div>
        <div class="message-content">
            <div class="bubble">${formattedText}</div>
            ${buttonsHtml}
        </div>
    `;
    chatArea.appendChild(messageDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
    
    // Привязываем обработчики к кнопкам после добавления в DOM
    if (extraButtons && extraButtons.length) {
        const container = document.getElementById(buttonsContainerId);
        messageDiv.querySelectorAll('.inline-btn-bubble').forEach(btn => {
            btn.addEventListener('click', async () => {
                const value = btn.getAttribute('data-value');
                const type = btn.getAttribute('data-type');
                const templateId = btn.getAttribute('data-template-id');
                const templateText = btn.getAttribute('data-template');
                
                // Удаляем или скрываем контейнер с кнопками и текстом призыва
                if (container) container.remove();
                const bubble = messageDiv.querySelector('.bubble');
                if (bubble && bubble.innerHTML.includes('Выберите из списка:')) {
                    messageDiv.remove(); // Удаляем все сообщение с призывом, если это был просто призыв
                } else if (bubble && bubble.innerHTML.includes('Выберите витрину')) {
                    messageDiv.remove();
                }

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
                addMessage('bot', '❌ Нет доступных витрин. Сначала выполните Обновить RAG.');
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
    // Используем расширенный список шаблонов локально
    const templates = [
        {id: "owner", label: "Владелец витрины", template: "Кто владелец витрины {datamart}?"},
        {id: "business_owner", label: "Заинтересованное лицо от бизнеса", template: "Кто Заинтересованное лицо от бизнеса (бизнес-заказчик) витрины {datamart}?"},
        {id: "attributes", label: "Состав атрибутов", template: "Какие атрибуты входят в витрину {datamart}?"},
        {id: "logic", label: "Логика расчета атрибута", template: "Какая логика расчета у атрибута {attribute} в витрине {datamart}?"},
        {id: "history", label: "История изменений", template: "Какие последние изменения были в витрине {datamart}?"},
        {id: "location", label: "Место публикации", template: "Какое место публикации витрины: источник в СМД/источник для АС Навигатор для {datamart}?"},
        {id: "category", label: "Категория данных", template: "Какая Категория данных на дата-продукте для {datamart}?"},
        {id: "process", label: "В рамках какого банковского процесса создана", template: "В рамках какого зарегистрированного банковского-процесса (из реестра) создана {datamart}?"},
        {id: "periodicity", label: "Периодичность и глубина", template: "Какая периодичность и глубина (на какую глубину тянет данные) у {datamart}?"},
        {id: "ke", label: "КЭ витрины", template: "Какой КЭ у {datamart}?"},
        {id: "link_meta", label: "Ссылка на МЕТА", template: "Ссылка на МЕТА по {datamart}?"},
        {id: "link_product", label: "Ссылка на дата-продукт в СМД", template: "Ссылка на дата-продукт в СМД для {datamart}?"}
    ];

    const buttons = templates.map(t => ({ 
        label: t.label, 
        value: t.id, 
        type: 'template',
        templateId: t.id,
        template: t.template
    }));
    addMessage('bot', '📝 Напишите вопрос или выберите из списка:', buttons);
}

// --- Управление боковой панелью логов ---
function openLogsSidebar() { logsSidebar.classList.add('open'); overlay.classList.add('show'); clearedLogsDisplay = false; startLogsUpdates(); }
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
            
            // Если API говорит, что всё еще идет синхронизация, а мы об этом не знали
            if (data.status === 'running' && !pendingCommand) {
                pendingCommand = 'update-rag';
                showPendingSyncMessage();
            } else if (data.status === 'ok' && pendingCommand === 'update-rag') {
                // Если API говорит, что всё закончилось, а мы всё еще ждем по логам
                // Это может случиться, если логи проскочили мимо фронтенда
                if (pendingCommandMessageDiv) {
                    pendingCommandMessageDiv.remove();
                    pendingCommandMessageDiv = null;
                }
                addMessage('bot', `✅ Обновление RAG завершено (подтверждено сервером)`);
                pendingCommand = null;
            }
        } else throw new Error();
    } catch (err) { 
        if (lastUpdateRagDateSpan) lastUpdateRagDateSpan.innerText = 'Ошибка'; 
    }
}

function showPendingSyncMessage() {
    if (pendingCommandMessageDiv) return;
    
    pendingCommandMessageDiv = document.createElement('div');
    pendingCommandMessageDiv.className = `message bot`;
    pendingCommandMessageDiv.innerHTML = `
        <div class="avatar">🔄</div>
        <div class="message-content">
            <div class="bubble" style="display: flex; align-items: center; justify-content: space-between; min-width: 250px;">
                <span>Обновление RAG выполняется в фоне... <span class="typing" style="display:inline-block; padding:0;"><span>●</span><span>●</span><span>●</span></span></span>
                <button class="icon-btn stop-update-btn" style="color: #ff3b30; padding: 2px 6px; margin-left: 10px;" title="Прервать обновление">✖</button>
            </div>
        </div>
    `;
    chatArea.appendChild(pendingCommandMessageDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
    
    const stopBtn = pendingCommandMessageDiv.querySelector('.stop-update-btn');
    if (stopBtn) stopBtn.onclick = interruptUpdate;
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
            
            // Если токен де-факто есть, ставим заглушку "точки" в интерфейсе (чтобы не сбивать с толку пустой инпут)
            if (data.confluence && !confluenceTokenInput.value) { confluenceTokenInput.type = 'password'; confluenceTokenInput.value = '********'; }
            if (data.jira && !jiraTokenInput.value) { jiraTokenInput.type = 'password'; jiraTokenInput.value = '********'; }
            if (data.gigachat && !gigachatTokenInput.value) { gigachatTokenInput.type = 'password'; gigachatTokenInput.value = '********'; }
            
            if (!data.configured) {
                settingsPanel.classList.add('show');
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

async function interruptUpdate() {
    try {
        const resp = await fetch(`${API_BASE}/api/interrupt-update`, { method: 'POST' });
        if (resp.ok) {
            if (pendingCommandMessageDiv) {
                const bubble = pendingCommandMessageDiv.querySelector('.bubble');
                if (bubble) bubble.innerHTML = `⚠️ Обновление RAG прервано пользователем.`;
                pendingCommandMessageDiv = null;
            }
            pendingCommand = null;
        }
    } catch(e) {
        console.error("Failed to interrupt", e);
    }
}

// --- Логи ---
async function fetchLogs() {
    if (clearedLogsDisplay) return; // Если нажали очистить, не тянем старые логи пока не перезагрузят или не нажмут обновить (если бы кнопка была)
    
    try {
        const resp = await fetch(`${API_BASE}/api/logs`);
        if (resp.ok) {
            const logs = await resp.json();
            let logsHtml = '';
            // Подсветка даты/времени
            const dateRegex = /^(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2},\d{3})/gm;
            
            logs.forEach(logLine => {
                // Экранируем HTML
                let safeLine = logLine.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                safeLine = safeLine.replace(dateRegex, '<span class="log-date">$1</span>');
                logsHtml += safeLine + '\n';
            });
            
            logsArea.innerHTML = logsHtml || '(пусто)';
            logsArea.scrollTop = logsArea.scrollHeight;
            
            if (pendingCommand) {
                const logsText = logs.join('\n');
                const success = new RegExp(`✅ Команда ${pendingCommand} завершена`).test(logsText);
                const error = new RegExp(`❌ Команда ${pendingCommand} завершена с кодом`).test(logsText);
                const cancelled = new RegExp(`Команда ${pendingCommand} была отменена`).test(logsText);
                
                if (success || error || cancelled) {
                    if (pendingCommandMessageDiv) {
                        pendingCommandMessageDiv.remove();
                        pendingCommandMessageDiv = null;
                    }
                    if (success) {
                        addMessage('bot', `✅ Обновление RAG завершено`);
                        if (pendingCommand === 'update-rag') loadLastEvents();
                    } else if (cancelled) {
                        addMessage('bot', `⚠️ Обновление RAG прервано.`);
                    } else if (error) {
                        addMessage('bot', `❌ Ошибка при выполнении обновления RAG`);
                    }
                    pendingCommand = null;
                }
            }
        } else logsArea.innerText = 'Не удалось загрузить логи';
    } catch (err) { logsArea.innerText = `Ошибка: ${err.message}`; }
}
function clearLogsDisplay() { 
    clearedLogsDisplay = true;
    logsArea.innerHTML = ''; 
}
function downloadLogs() { window.location.href = `${API_BASE}/api/logs/download`; }

// --- Запуск команд ---
async function runCommand(endpoint, commandName, displayName) {
    if (pendingCommand) { showStatusMessage(`Предыдущая команда ${pendingCommand} ещё выполняется`, 'error'); return; }
    pendingCommand = commandName;
    
    // Создаем сообщение с кнопкой отмены
    pendingCommandMessageDiv = document.createElement('div');
    pendingCommandMessageDiv.className = `message bot`;
    pendingCommandMessageDiv.innerHTML = `
        <div class="avatar">🔄</div>
        <div class="message-content">
            <div class="bubble" style="display: flex; align-items: center; justify-content: space-between; min-width: 250px;">
                <span>Обновление RAG запущено. Ожидайте <span class="typing" style="display:inline-block; padding:0;"><span>●</span><span>●</span><span>●</span></span></span>
                <button class="icon-btn stop-update-btn" style="color: #ff3b30; padding: 2px 6px; margin-left: 10px;" title="Прервать обновление">✖</button>
            </div>
        </div>
    `;
    chatArea.appendChild(pendingCommandMessageDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
    
    // Биндим кнопку отмены
    const stopBtn = pendingCommandMessageDiv.querySelector('.stop-update-btn');
    if (stopBtn) {
        stopBtn.onclick = interruptUpdate;
    }

    try {
        const resp = await fetch(`${API_BASE}${endpoint}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || data.message || 'Ошибка');
    } catch (err) {
        if (pendingCommandMessageDiv) {
             pendingCommandMessageDiv.querySelector('.bubble').innerHTML = `❌ Ошибка при запуске: ${err.message}`;
             pendingCommandMessageDiv = null;
        }
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
    div.innerHTML = `<div class="avatar">🤖</div><div class="bubble typing">🤖 <span>●</span><span>●</span><span>●</span> печатает...</div>`;
    chatArea.appendChild(div);
    chatArea.scrollTop = chatArea.scrollHeight;
    return div;
}
function removeTypingIndicator(element) { if (element && element.remove) element.remove(); }

// --- Модальное окно "Что это?" ---
function openInfoModal() {
    mainApp.classList.add('blur');
    infoModal.style.display = 'block';
    overlay.classList.add('show');
}

function closeInfoModal() {
    mainApp.classList.remove('blur');
    infoModal.style.display = 'none';
    overlay.classList.remove('show');
}

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
qqBtn.onclick = loadQuestionTemplates;
infoBtn.onclick = openInfoModal;
closeInfoModalBtn.onclick = closeInfoModal;

overlay.onclick = () => {
    closeLogsSidebar();
    closeInfoModal();
};

updateRagBtn.onclick = () => runCommand('/api/update-rag', 'update-rag', 'Обновить RAG');
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
