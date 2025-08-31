const socket = io();
let currentUsername = '';
let activeChat = null; // null = общий чат

const loginForm = document.getElementById('login-form');
const chatInterface = document.getElementById('chat-interface');
const usernameInput = document.getElementById('username');
const messageInput = document.getElementById('message-text');
const messagesContainer = document.getElementById('messages-container');
const loginError = document.getElementById('login-error');
const contactsDiv = document.getElementById('contacts');
const addContactInput = document.getElementById('add-contact-input');

// Вход
function setUsername() {
    const username = usernameInput.value.trim();
    if (!username) {
        showLoginError('Логин не может быть пустым');
        return;
    }
    socket.emit('set_username', { username });
}

// Добавление контакта
function addContact() {
    const name = addContactInput.value.trim();
    if (!name) return;
    socket.emit('add_contact', { username: name });
    addContactInput.value = '';
}

// Открытие чата
function openChat(username) {
    activeChat = username;
    messagesContainer.innerHTML = '';
    if (username) {
        socket.emit('load_chat', { with: username });
    }
}

// Отправка сообщения
function sendMessage() {
    const text = messageInput.value.trim();
    if (!text) return;
    socket.emit('send_message', { text, to: activeChat });
    messageInput.value = '';
}

// Показ ошибки
function showLoginError(msg) {
    loginError.textContent = msg;
    setTimeout(() => loginError.textContent = '', 3000);
}

// --- Socket Events ---
socket.on('connection_status', (data) => console.log('Connected:', data));

socket.on('login_success', (data) => {
    currentUsername = data.username;
    loginForm.style.display = 'none';
    chatInterface.style.display = 'flex';
    addContactElement('#general'); // общий чат

    data.messages.forEach(addMessage);
});

socket.on('login_failed', (data) => showLoginError(data.reason));
socket.on('user_joined', (d) => addSystemMessage(`${d.username} вошёл`));
socket.on('user_left', (d) => addSystemMessage(`${d.username} вышел`));

socket.on('contact_added', (data) => addContactElement(data.username));

socket.on('chat_history', (data) => {
    data.messages.forEach(addMessage);
});

socket.on('new_message', (data) => {
    if (!data) return;
    if (!activeChat && data.sender !== currentUsername) {
        // общий чат
        addMessage(data);
    } else if (activeChat && (data.sender === activeChat || data.sender === currentUsername)) {
        addMessage(data);
    }
});

// --- Helpers ---
function addMessage(msg) {
    const div = document.createElement('div');
    div.className = 'message';
    div.innerHTML = `
        <div class="sender">${msg.sender}</div>
        <div class="text">${msg.text}</div>
        <div class="time">${msg.time}</div>
    `;
    messagesContainer.appendChild(div);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function addSystemMessage(text) {
    const div = document.createElement('div');
    div.className = 'system-message';
    div.textContent = text;
    messagesContainer.appendChild(div);
}

function addContactElement(username) {
    const div = document.createElement('div');
    div.className = 'contact';
    div.textContent = username;
    div.onclick = () => {
        document.querySelectorAll('.contact').forEach(c => c.classList.remove('active'));
        div.classList.add('active');
        openChat(username === '#general' ? null : username);
    };
    contactsDiv.appendChild(div);
}
