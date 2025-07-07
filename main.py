from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, disconnect, join_room, leave_room, send
import time
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'muy-secreto'
socketio = SocketIO(app, cors_allowed_origins="*")

NUM_PROBLEMS = 3
correct = {"p1":"10", "p2":"22","p3":"33"
   # f"p{i}": "0" for i in range(1, NUM_PROBLEMS + 1)
   # correct = {"10", "21", "5"}
}
# Cambia "0" por tus respuestas reales, ejemplo:
# correct = {"p1":"3.14", "p2":"42", ...}

students = {}
lock = threading.Lock()

@app.route('/')
def index():
    return render_template('index.html', num=NUM_PROBLEMS)

@socketio.on('submit')
def handle_submit(data):
    sid = request.sid
    name = data['name']
    prob = data['problem']
    ans = data['answer']

    with lock:
        s = students.setdefault(sid, {
            'name': name,
            'start_time': time.time(),
            'penalty': 0,
            'scores': {},          # {problem: time_of_correct}
            'attempts': {},        # {problem: count_attempts}
        })

        # Registrar intento
        s['attempts'][prob] = s['attempts'].get(prob, 0) + 1

        # Si ya acertó ese problema, no reevalúa
        if prob in s['scores']:
            return

        # Comparar respuesta
        try:
            if abs(float(correct[prob]) - float(ans)) <= 1e-6:
                s['scores'][prob] = time.time()
            else:
                s['penalty'] += 20 * 60  # 20 minutos penalización por error
        except:
            pass

        update_ranking()

def update_ranking():
    arr = []
    for sid, s in students.items():
        solved = len(s['scores'])
        total_time = sum(s['scores'].values()) - s['start_time'] if solved else 0
        total = total_time + s['penalty']
        attempts_total = sum(s['attempts'].values())
        solved_list = sorted(s['scores'].keys())  # lista como ['p1', 'p3']
        arr.append((sid, s['name'], solved, attempts_total, total, solved_list))

    arr.sort(key=lambda x: (-x[2], x[4], x[3]))
    rankings = [
        {
            'name': n,
            'solved': sol,
            'attempts': att,
            'time': int(t),
            'solved_problems': ', '.join(solved_list)
        }
        for _, n, sol, att, t, solved_list in arr
    ]
    socketio.emit('ranking', rankings)


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=False)
