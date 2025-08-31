from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
from datetime import datetime
from threading import Lock
import os
from collections import defaultdict

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

socketio = SocketIO(app,
                    async_mode='eventlet',
                    cors_allowed_origins="*",
                    ping_timeout=30,
                    ping_interval=15,
                    max_http_buffer_size=50 * 1024)

# Структуры данных
active_users = {}  # user_id -> username
user_sessions = {}  # username -> user_id
user_rooms = defaultdict(list)  # user_id -> list of rooms
user_contacts = defaultdict(list)  # user_id -> list of contacts
messages = defaultdict(list)  # chat_id -> list of messages
private_chats = defaultdict(set)  # chat_id -> set of participants
users_lock = Lock()
MAX_MESSAGES = 500


def get_private_chat_id(user1, user2):
    """Генерирует уникальный ID для личного чата"""
    users = sorted([user1.lower(), user2.lower()])
    return f"private_{users[0]}_{users[1]}"


def get_chat_participants(chat_id):
    """Получает участников чата по его ID"""
    if chat_id == 'general':
        return list(active_users.values())
    elif chat_id.startswith('private_'):
        parts = chat_id.split('_')[1:]
        return parts if len(parts) == 2 else []
    return []


def can_access_chat(user_id, chat_id):
    """Проверяет, имеет ли пользователь доступ к чату"""
    if chat_id == 'general':
        return True

    if chat_id.startswith('private_'):
        username = active_users.get(user_id)
        if not username:
            return False
        participants = get_chat_participants(chat_id)
        return username.lower() in [p.lower() for p in participants]

    return False


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")


@socketio.on('disconnect')
def handle_disconnect():
    user_id = session.get('user_id')
    if user_id and user_id in active_users:
        with users_lock:
            username = active_users[user_id]

            # Удаляем из активных пользователей
            active_users.pop(user_id, None)
            user_sessions.pop(username, None)

            # Выходим из всех комнат
            for room in user_rooms[user_id]:
                leave_room(room)
            user_rooms.pop(user_id, None)

            print(f"User {username} disconnected")

            # Уведомляем об уходе пользователя
            emit('user_left', {
                'username': username,
                'timestamp': datetime.now().isoformat()
            }, broadcast=True, room='general')


@socketio.on('set_username')
def handle_set_username(data):
    username = data.get('username', '').strip()[:20]

    if not username:
        emit('login_failed', {'reason': 'Введите имя пользователя'})
        return

    with users_lock:
        if username in user_sessions:
            emit('login_failed', {'reason': 'Имя уже занято'})
            return

        # Создаем новую сессию
        user_id = str(uuid.uuid4())
        session['user_id'] = user_id
        active_users[user_id] = username
        user_sessions[username] = user_id

        # Присоединяем к общему чату
        join_room('general')
        user_rooms[user_id].append('general')

        print(f"User {username} joined with ID: {user_id}")

    # Загружаем контакты пользователя
    user_contacts[user_id] = []  # Можно добавить сохранение контактов в БД

    # Отправляем успешный логин
    emit('login_success', {
        'username': username,
        'user_id': user_id,
        'online_count': len(active_users),
        'recent_messages': messages.get('general', [])[-20:]
    })

    # Уведомляем всех о новом пользователе
    emit('user_joined', {
        'username': username,
        'timestamp': datetime.now().isoformat()
    }, broadcast=True, room='general')


@socketio.on('get_chat_history')
def handle_get_chat_history(data):
    user_id = session.get('user_id')
    if user_id not in active_users:
        return

    chat_id = data.get('chat_id', 'general')

    if not can_access_chat(user_id, chat_id):
        return

    # Отправляем историю сообщений
    chat_history = messages.get(chat_id, [])[-100:]
    emit('chat_history', {
        'chat_id': chat_id,
        'messages': chat_history
    })


@socketio.on('send_message')
def handle_send_message(data):
    user_id = session.get('user_id')
    if user_id not in active_users:
        return

    username = active_users[user_id]
    text = data.get('text', '').strip()[:500]
    chat_id = data.get('chat_id', 'general')
    recipient = data.get('recipient')

    if not text:
        return

    # Проверяем доступ к чату
    if not can_access_chat(user_id, chat_id):
        return

    # Для личных сообщений проверяем получателя
    if chat_id.startswith('private_') and recipient:
        actual_chat_id = get_private_chat_id(username, recipient)
        if chat_id != actual_chat_id:
            return
    else:
        actual_chat_id = chat_id

    # Создаем сообщение
    message = {
        'id': str(uuid.uuid4()),
        'sender': username,
        'text': text,
        'timestamp': datetime.now().isoformat(),
        'time': datetime.now().strftime('%H:%M'),
        'chat_id': actual_chat_id
    }

    with users_lock:
        # Сохраняем сообщение
        messages[actual_chat_id].append(message)

        # Ограничиваем историю
        if len(messages[actual_chat_id]) > MAX_MESSAGES:
            messages[actual_chat_id] = messages[actual_chat_id][-MAX_MESSAGES:]

        print(f"Message from {username} in {actual_chat_id}: {text[:50]}...")

    # Отправляем сообщение в соответствующий чат
    if actual_chat_id == 'general':
        emit('new_message', {
            'chat_id': actual_chat_id,
            'message': message
        }, room=actual_chat_id)
    else:
        # Для личных чатов отправляем только участникам
        participants = get_chat_participants(actual_chat_id)
        for participant in participants:
            participant_id = user_sessions.get(participant)
            if participant_id and actual_chat_id in user_rooms[participant_id]:
                emit('new_message', {
                    'chat_id': actual_chat_id,
                    'message': message
                }, room=participant_id)


@socketio.on('add_contact')
def handle_add_contact(data):
    user_id = session.get('user_id')
    if user_id not in active_users:
        return

    username = active_users[user_id]
    contact_username = data.get('contact_username', '').strip()

    if not contact_username or contact_username == username:
        emit('contact_error', {'reason': 'Нельзя добавить самого себя'})
        return

    # Проверяем, существует ли пользователь
    if contact_username not in user_sessions:
        emit('contact_error', {'reason': 'Пользователь не найден'})
        return

    # Проверяем, не добавлен ли уже контакт
    if contact_username in user_contacts[user_id]:
        emit('contact_error', {'reason': 'Контакт уже добавлен'})
        return

    # Добавляем контакт
    user_contacts[user_id].append(contact_username)

    # Создаем ID чата
    chat_id = get_private_chat_id(username, contact_username)

    # Добавляем чат в систему
    private_chats[chat_id].update([username.lower(), contact_username.lower()])

    # Присоединяем участников к комнате
    for participant in [username, contact_username]:
        participant_id = user_sessions.get(participant)
        if participant_id and chat_id not in user_rooms[participant_id]:
            join_room(chat_id)
            user_rooms[participant_id].append(chat_id)

    emit('contact_added', {
        'contact_username': contact_username,
        'chat_id': chat_id
    })


@socketio.on('remove_contact')
def handle_remove_contact(data):
    user_id = session.get('user_id')
    if user_id not in active_users:
        return

    username = active_users[user_id]
    contact_username = data.get('contact_username', '').strip()

    if not contact_username:
        return

    # Удаляем контакт из списка
    if contact_username in user_contacts[user_id]:
        user_contacts[user_id].remove(contact_username)

        # Выходим из комнаты приватного чата
        chat_id = get_private_chat_id(username, contact_username)
        if chat_id in user_rooms[user_id]:
            leave_room(chat_id)
            user_rooms[user_id].remove(chat_id)

        emit('contact_removed', {
            'contact_username': contact_username
        })
    else:
        emit('contact_error', {'reason': 'Контакт не найден'})


@socketio.on('join_private_chat')
def handle_join_private_chat(data):
    user_id = session.get('user_id')
    if user_id not in active_users:
        return

    username = active_users[user_id]
    contact_username = data.get('contact_username', '').strip()

    if not contact_username:
        return

    chat_id = get_private_chat_id(username, contact_username)

    if chat_id not in user_rooms[user_id]:
        join_room(chat_id)
        user_rooms[user_id].append(chat_id)
        print(f"User {username} joined private chat {chat_id}")

        # Отправляем историю чата
        chat_history = messages.get(chat_id, [])[-50:]
        emit('chat_history', {
            'chat_id': chat_id,
            'messages': chat_history
        })


@socketio.on('get_online_users')
def handle_get_online_users():
    with users_lock:
        online_users = list(active_users.values())

    emit('online_users', {
        'users': online_users,
        'count': len(online_users)
    })


@socketio.on('get_user_contacts')
def handle_get_user_contacts():
    user_id = session.get('user_id')
    if user_id not in active_users:
        return

    contacts = user_contacts.get(user_id, [])
    emit('user_contacts', {
        'contacts': contacts
    })


@socketio.on('get_user_status')
def handle_get_user_status(data):
    username = data.get('username', '').strip()
    is_online = username in user_sessions

    emit('user_status', {
        'username': username,
        'online': is_online
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting NavyChat server on port {port}...")
    socketio.run(app, host='0.0.0.0', port=port, debug=False)