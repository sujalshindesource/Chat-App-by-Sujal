from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from model import db, User
import jwt
from datetime import datetime, timedelta
from flask_socketio import SocketIO , emit
from model import Message
app = Flask(__name__)
CORS(app, origins=["https://chat-app-front-by-sujal-d34j.vercel.app/", "http://localhost:3000"])
socketio = SocketIO(app, 
                   cors_allowed_origins="*",
                   async_mode='threading',
                   logger=True, 
                   engineio_logger=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'supersecretkey'  

db.init_app(app)

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return "Backend running"

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    username = data.get('username')
    number = data.get('number')
    password = data.get('password')

    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already registered'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'message': 'Username taken'}), 400
    if User.query.filter_by(number=number).first():
        return jsonify({'success': False, 'message': 'Number already used'}), 400

    new_user = User(email=email, username=username, number=number, password=password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Signup successful'})

# -------- LOGIN with JWT --------
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user = User.query.filter_by(email=email, password=password).first()
    if not user:
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

    # Create JWT Token (valid for 1 day)
    payload = {
        'email': user.email,
        'exp': datetime.utcnow() + timedelta(days=1)
    }
    token = jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')

    return jsonify({'success': True, 'token': token, 'email': user.email})

# -------- VERIFY TOKEN --------
@app.route('/verify', methods=['POST'])
def verify():
    data = request.get_json()
    token = data.get('token')

    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        return jsonify({'success': True, 'email': payload['email']})
    except jwt.ExpiredSignatureError:
        return jsonify({'success': False, 'message': 'Token expired'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'success': False, 'message': 'Invalid token'}), 401

@app.route('/users')
def get_users():
    users = User.query.all()
    user_list = [{'name': u.username, 'email': u.email} for u in users]
    return jsonify(user_list)

@socketio.on('connect')
def connect():
    print("user connected")

@socketio.on('disconnect')
def disconnect():
    print("user disconnected")


@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', data, broadcast=True, include_self=False)

@socketio.on('stopped_typing') 
def handle_stopped_typing(data):
    emit('user_stopped_typing', data, broadcast=True, include_self=False)

@socketio.on('msg_status') 
def handle_msg_status(data):
    emit('get_msg_status', data, broadcast=True, include_self=False)

@socketio.on('send_message')
def handle_send_message(data):
    print("Message received:", data)
    
    sender = data.get('sender')
    receiver = data.get('receiver')
    text = data.get('text')
    status = data.get('status', 'sent')
    
    if not sender or not receiver or not text:
        return
    
    # Save message to database
    message = Message(sender=sender, receiver=receiver, text=text, status=status)
    db.session.add(message)
    db.session.commit()
    
    # Only send to receiver, not back to sender
    socketio.emit('receive_message', {
        'sender': sender,
        'receiver': receiver,
        'text': text,
        'timestamp': message.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        'status': 'sent'
    }, room=None)

# Fixed delivery confirmation handler
@socketio.on('message_delivered')
def handle_message_delivered(data):
    timestamp_str = data.get('timestamp')
    sender = data.get('sender')
    
    if timestamp_str and sender:
        try:
            # Parse timestamp and update database
            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            message = Message.query.filter_by(
                sender=sender,
                timestamp=timestamp
            ).first()
            
            if message:
                message.status = 'delivered'
                db.session.commit()
                
                # Notify sender about delivery
                # Notify sender about delivery
            socketio.emit('message_status_update', {
                'timestamp': timestamp_str,
                'status': 'delivered'
            }, broadcast=True)
        except Exception as e:
            print("Error updating message status:", e)


@app.route('/messages', methods=['POST'])
def get_messages():
    data = request.get_json()
    user1 = data.get('user1')
    user2 = data.get('user2')
    time_str = data.get('time')

    if time_str:
        try:
            timestamp = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            message = Message.query.filter(
                (((Message.sender == user1) & (Message.receiver == user2)) |
                 ((Message.sender == user2) & (Message.receiver == user1))) &
                (Message.timestamp == timestamp)
            ).first()

            if message:
                db.session.delete(message)
                db.session.commit()
        except Exception as e:
            print("Delete error:", e)

    messages = Message.query.filter(
        ((Message.sender == user1) & (Message.receiver == user2)) |
        ((Message.sender == user2) & (Message.receiver == user1))
    ).order_by(Message.timestamp).all()

    return jsonify([{
        'sender': m.sender,
        'receiver': m.receiver,
        'text': m.text,
        'timestamp': m.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        'status': getattr(m, 'status', 'sent')
        } for m in messages])



# if __name__ == '__main__':
#     socketio.run(app, debug=True, host='0.0.0.0', port=5000)
import os
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
