# evaluador_icpc_con_tiempo.py

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)
socketio = SocketIO(app)

# =====================
# CONFIGURACIÓN
# =====================
HoraEmpieza=13
MinutoEmpieza=31
minutes=HoraEmpieza*60+MinutoEmpieza
#START_TIME = datetime.now()#.replace(second=0, microsecond=0) + timedelta(minutes)  # Empieza en 1 minuto desde que corre
#START_TIME = datetime(2025,07,07,15,10)
#START_TIME = datetime(year=2025, month=7, day=7, hour=15, minute=20, second=0, microsecond=0)
DURATION = timedelta(minutes=20)  # Duración del concurso
LOCAL_TIMEZONE = pytz.timezone("America/Mexico_City")  # Cambia según tu ubicación
START_TIME = LOCAL_TIMEZONE.localize(datetime(2025, 1, 2, 16, 35, 0, 0))
# Lista de problemas
problems = {
    "A": 42,
    "B": 3.1416,
    "C": 2024
}

# Almacén de resultados y participantes
participants = {}  # nombre -> info

# =====================
# FUNCIONES AUXILIARES
# =====================

def get_status():
    now = datetime.now()
    if now < START_TIME:
        return "before"
    elif now > START_TIME + DURATION:
        return "after"
    else:
        return "running"

def get_elapsed_time():
    now = datetime.now()
    return max((now - START_TIME).total_seconds(), 0)

def register(name):
    if name not in participants:
        participants[name] = {
            "start_time": datetime.now(),
            "responses": {},
            "attempts": {pid: 0 for pid in problems},
            "status": {pid: "" for pid in problems},
            "score": 0,
            "penalty": 0
        }

# =====================
# RUTAS PRINCIPALES
# =====================

@app.route("/")
def index():
    status = get_status()
    start_time_str = START_TIME.astimezone(LOCAL_TIMEZONE).strftime("%H:%M:%S")
    return render_template("index.html", status=status, start_time=start_time_str, duration=DURATION.seconds)

@app.route("/submit", methods=["POST"])
def submit():
    if get_status() != "running":
        return jsonify({"error": "Concurso no activo"}), 403

    name = request.form["name"].strip()
    pid = request.form["problem"].strip()
    answer = request.form["answer"].strip()

    register(name)

    info = participants[name]
    if info["status"][pid] == "✔":
        return jsonify({"message": "Ya resuelto"})

    info["attempts"][pid] += 1
    correct = str(problems[pid]) == answer

    if correct:
        elapsed = int(get_elapsed_time() // 60)
        info["status"][pid] = "✔"
        info["score"] += 1
        info["penalty"] += elapsed + 20 * (info["attempts"][pid] - 1)
    else:
        info["status"][pid] = "✖"

    return jsonify({"message": "Respuesta recibida"})

@app.route("/status")
def status():
    return jsonify({"status": get_status(), "time": get_elapsed_time()})

@app.route("/ranking")
def ranking():
    ranking_data = []
    for name, info in participants.items():
        ranking_data.append({
            "name": name,
            "score": info["score"],
            "penalty": info["penalty"],
            "status": info["status"],
            "attempts": info["attempts"]
        })

    ranking_data.sort(key=lambda x: (-x["score"], x["penalty"]))
    return jsonify(ranking_data)

# =====================
# INICIO
# =====================

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=81, debug=True, use_reloader=False)
