# evaluador_icpc_con_tiempo.py

import eventlet
import string
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
anno=2025; dia=8; mes=7;  hora=8; minuto=44
duracion=1000
#START_TIME = datetime.now()#.replace(second=0, microsecond=0) + timedelta(minutes)  # Empieza en 1 minuto desde que corre
#START_TIME = datetime(2025,07,07,15,10)
#START_TIME = datetime(year=anno, month=mes, day=dia, hour=hora, minute=minuto, second=0, microsecond=0)
DURATION = timedelta(minutes=duracion)  # Duración del concurso
LOCAL_TIMEZONE = pytz.timezone("America/Mexico_City")  # Cambia según tu ubicación
START_TIME = LOCAL_TIMEZONE.localize(datetime(year=anno, month=mes, day=dia, hour=hora, minute=minuto, second=0, microsecond=0))

# Almacén de resultados y participantes
participants = {}  # nombre -> info



# =====================
# FUNCIONES AUXILIARES
# =====================

@app.route("/login", methods=["POST"])
def login():
    name = request.form["name"].strip()
    password = request.form["password"].strip()

    # Puedes usar un archivo JSON o diccionario para gestionar usuarios registrados
    if name not in participants:
        # Nuevo usuario
        participants[name] = {
            "password": password,  # En producción, deberías hashear esto
            "start_time": datetime.now(),
            "responses": {},
            "attempts": {pid: 0 for pid in problems},
            "status": {pid: "" for pid in problems},
            "score": 0,
            "penalty": 0
        }
        return jsonify({"message": "Registrado y conectado"})
    else:
        # Ya existe
        if participants[name]["password"] != password:
            return jsonify({"error": "Contraseña incorrecta"})
        return jsonify({"message": "Acceso concedido"})




def cargar_problemas_desde_latex(archivo):
    problemas = {}
    with open(archivo, encoding="utf-8") as f:
        contenido = f.read()  # Leer TODO el contenido, no línea por línea
    
    partes = contenido.split("|||")
    partes = [p.strip() for p in partes if p.strip() != ""]  # Elimina vacíos

    if len(partes) % 2 != 0:
        raise ValueError("El archivo tiene un número impar de bloques. Faltan enunciados o respuestas.")
    letras = string.ascii_uppercase  # 'A', 'B', 'C', ...
    for i in range(0, len(partes), 2):
        letra = letras[i // 2]
        enunciado = partes[i]
        respuesta_str = partes[i + 1]
        try:
            respuesta = int(respuesta_str)
        except ValueError:
            try:
                respuesta = float(respuesta_str)
            except ValueError:
                respuesta = respuesta_str.strip()
        problemas[letra] = {
                    "nombre": letra,
                    "enunciado": enunciado,
                    "respuesta": respuesta
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
    try:
       user_answer = float(answer)
       correct = abs(user_answer - float(problems[pid]["respuesta"])) < 1e-6
    except ValueError:
       try: 
          correct = answer==problems[pid]["respuesta"]
       except ValueError:
              correct=False
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
