from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit
import uuid
import os
import time
import anthropic

app = Flask(__name__)
app.config['SECRET_KEY'] = 'random-chat-secret-2024'
socketio = SocketIO(app, cors_allowed_origins="*")

waiting_queue = []
pairs = {}
rooms = {}
nicknames = {}

# AI 보호 설정
AI_MAX_MESSAGES = 20
AI_COOLDOWN = {}
ai_counts = {}
ai_histories = {}

SYSTEM_PROMPT = """너는 수다공원이라는 랜덤 채팅 앱에서 상대방을 기다리는 동안 대화 상대가 되어주는 AI 친구야.

규칙:
- 친한 친구한테 말하듯 편하게 반말로 대화해
- 짧게 1~3문장으로 답해, 길게 쓰지 마
- 검색해주거나 정보 알려주거나 뭔가 만들어주는 건 안 해
- 그냥 일상 수다만 - 오늘 있었던 일, 취미, 기분, 좋아하는 거 같은 거
- 가끔 ㅎㅎ ㅋㅋ 이모지 써도 됨
- 질문으로 대화 계속 이어가기
- 상대방 기다리는 상황이니까 가볍고 재미있게"""


def get_partner(sid):
    room_id = pairs.get(sid)
    if not room_id or room_id not in rooms:
        return None
    for s in rooms[room_id]:
        if s != sid:
            return s
    return None


def leave_room_cleanup(sid):
    partner = get_partner(sid)
    room_id = pairs.pop(sid, None)
    if room_id and room_id in rooms:
        rooms.pop(room_id)
    if partner:
        pairs.pop(partner, None)
        emit('partner_left', to=partner)


def cleanup_ai(sid):
    ai_counts.pop(sid, None)
    ai_histories.pop(sid, None)
    AI_COOLDOWN.pop(sid, None)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/park.png')
def park_image():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(base_dir, 'park.png')


@socketio.on('connect')
def on_connect():
    pass


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    if sid in waiting_queue:
        waiting_queue.remove(sid)
    leave_room_cleanup(sid)
    nicknames.pop(sid, None)
    cleanup_ai(sid)


@socketio.on('find_partner')
def on_find_partner(data=None):
    sid = request.sid
    nickname = (data or {}).get('nickname', '익명') or '익명'
    nickname = nickname[:10]
    nicknames[sid] = nickname

    leave_room_cleanup(sid)
    cleanup_ai(sid)

    if sid in waiting_queue:
        waiting_queue.remove(sid)

    if waiting_queue:
        partner_sid = waiting_queue.pop(0)
        room_id = str(uuid.uuid4())[:8]

        rooms[room_id] = [sid, partner_sid]
        pairs[sid] = room_id
        pairs[partner_sid] = room_id

        socketio.server.enter_room(sid, room_id, namespace='/')
        socketio.server.enter_room(partner_sid, room_id, namespace='/')

        emit('matched', {'partner_nickname': nicknames.get(partner_sid, '익명')}, to=sid)
        emit('matched', {'partner_nickname': nickname}, to=partner_sid)
    else:
        waiting_queue.append(sid)
        emit('waiting')


@socketio.on('cancel_wait')
def on_cancel():
    sid = request.sid
    if sid in waiting_queue:
        waiting_queue.remove(sid)
    leave_room_cleanup(sid)
    cleanup_ai(sid)


@socketio.on('send_message')
def on_message(data):
    sid = request.sid
    msg = str(data.get('message', '')).strip()
    if not msg or sid not in pairs:
        return
    partner = get_partner(sid)
    if partner:
        emit('receive_message', {'message': msg}, to=partner)


@socketio.on('chat_with_ai')
def on_chat_with_ai(data):
    sid = request.sid
    message = str(data.get('message', '')).strip()

    if not message:
        return

    # 메시지 길이 제한
    if len(message) > 200:
        message = message[:200]

    # AI 메시지 횟수 제한
    count = ai_counts.get(sid, 0)
    if count >= AI_MAX_MESSAGES:
        emit('ai_response', {
            'message': 'ㅎㅎ 오늘 나랑 너무 많이 얘기했다~ 이제 진짜 상대방 기다려봐! 곧 올 거야 😄'
        })
        return

    # Rate limiting (2초)
    now = time.time()
    if now - AI_COOLDOWN.get(sid, 0) < 2:
        return
    AI_COOLDOWN[sid] = now

    # 대화 기록
    if sid not in ai_histories:
        ai_histories[sid] = []
    ai_histories[sid].append({'role': 'user', 'content': message})
    if len(ai_histories[sid]) > 10:
        ai_histories[sid] = ai_histories[sid][-10:]

    try:
        api_key = os.environ.get('CLAUDE_API_KEY')
        if not api_key:
            emit('ai_response', {'message': 'AI 친구가 지금 자리 비웠어 ㅠ 잠깐만 기다려!'})
            return

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=150,
            system=SYSTEM_PROMPT,
            messages=ai_histories[sid]
        )

        reply = response.content[0].text
        ai_histories[sid].append({'role': 'assistant', 'content': reply})
        ai_counts[sid] = count + 1

        emit('ai_response', {'message': reply})

    except Exception:
        emit('ai_response', {'message': '어 잠깐, 뭔가 잘못됐어 ㅠ 다시 말해봐!'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
