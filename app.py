from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import uuid
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'random-chat-secret-2024'
socketio = SocketIO(app, cors_allowed_origins="*")

waiting_queue = []   # 대기 중인 sid 목록
pairs = {}           # sid → room_id
rooms = {}           # room_id → [sid1, sid2]


def get_partner(sid):
    room_id = pairs.get(sid)
    if not room_id or room_id not in rooms:
        return None
    for s in rooms[room_id]:
        if s != sid:
            return s
    return None


def leave_room_cleanup(sid):
    """방에서 나가고 상대방에게 알림"""
    partner = get_partner(sid)
    room_id = pairs.pop(sid, None)
    if room_id and room_id in rooms:
        rooms.pop(room_id)
    if partner:
        pairs.pop(partner, None)
        emit('partner_left', to=partner)


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def on_connect():
    pass


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    if sid in waiting_queue:
        waiting_queue.remove(sid)
    leave_room_cleanup(sid)


@socketio.on('find_partner')
def on_find_partner():
    sid = request.sid

    # 기존 방에서 나가기
    leave_room_cleanup(sid)

    # 대기열 중복 제거
    if sid in waiting_queue:
        waiting_queue.remove(sid)

    # 매칭 시도
    if waiting_queue:
        partner_sid = waiting_queue.pop(0)
        room_id = str(uuid.uuid4())[:8]

        rooms[room_id] = [sid, partner_sid]
        pairs[sid] = room_id
        pairs[partner_sid] = room_id

        socketio.server.enter_room(sid, room_id, namespace='/')
        socketio.server.enter_room(partner_sid, room_id, namespace='/')

        emit('matched', to=sid)
        emit('matched', to=partner_sid)
    else:
        waiting_queue.append(sid)
        emit('waiting')


@socketio.on('cancel_wait')
def on_cancel():
    sid = request.sid
    if sid in waiting_queue:
        waiting_queue.remove(sid)
    leave_room_cleanup(sid)


@socketio.on('send_message')
def on_message(data):
    sid = request.sid
    msg = str(data.get('message', '')).strip()
    if not msg or sid not in pairs:
        return
    partner = get_partner(sid)
    if partner:
        emit('receive_message', {'message': msg}, to=partner)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
