# evaluador_icpc_con_tiempo.py

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from datetime import datetime, timedelta
import pytz
import re

app = Flask(__name__)
socketio = SocketIO(app)

# =====================
# CONFIGURACIÓN
# =====================
anno=2025; dia=7; mes=7;  hora=19; minuto=50
#START_TIME = datetime.now()#.replace(second=0, microsecond=0) + timedelta(minutes)  # Empieza en 1 minuto desde que corre
#START_TIME = datetime(2025,07,07,15,10)
#START_TIME = datetime(year=anno, month=mes, day=dia, hour=hora, minute=minuto, second=0, microsecond=0)
DURATION = timedelta(minutes=20)  # Duración del concurso
LOCAL_TIMEZONE = pytz.timezone("America/Mexico_City")  # Cambia según tu ubicación
START_TIME = LOCAL_TIMEZONE.localize(datetime(year=anno, month=mes, day=dia, hour=hora, minute=minuto, second=0, microsecond=0))
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

def cargar_problemas_desde_latex(archivo):
    problemas = {}
    with open(archivo, encoding="utf-8") as f:
        for line in f:
            match = re.match(r"\\problem\{(.*?)\}\{(.*?)\}\{(.*?)\}", line.strip())
            if match:
                pid, enunciado, respuesta = match.groups()
                problemas[pid] = {
                    "enunciado": enunciado,
                    "respuesta": respuesta.strip()
                }
    return problemas

problems = cargar_problemas_desde_latex("problemas.tex")


def get_status():
    now = datetime.now(LOCAL_TIMEZONE)
    if now < START_TIME:
        return "before"
    elif now > START_TIME + DURATION:
        return "after"
    else:
        return "running"

def get_elapsed_time():
    now = datetime.now(LOCAL_TIMEZONE)
    return max((now - START_TIME).total_seconds(), 0)

participants = {}

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

@app.route("/register", methods=["POST"])
def register_route():
    name = request.form.get("name", "").strip()
    if not name:
        return jsonify({"error": "Nombre requerido"}), 400
    register(name)
    return jsonify({"success": True})

@app.route("/participants")
def get_participants():
    return jsonify(list(participants.keys()))

# =====================
# RUTAS PRINCIPALES
# =====================

@app.route("/")
def index():
    status = get_status()
    start_time_iso = START_TIME.isoformat()
    duration_seconds = int(DURATION.total_seconds())
    return render_template("index.html", status=status, start_time_iso=start_time_iso, duration=duration_seconds,problems=problems)

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
