# evaluador_icpc_con_tiempo.py

import eventlet
import string
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from datetime import datetime, timedelta
import pytz
import re
import csv
import os
import smtplib
from email.message import EmailMessage

app = Flask(__name__)
socketio = SocketIO(app)




# =====================
# CONFIGURACIÓN
# =====================
anno=2025; dia=10; mes=7;  hora=8; minuto=30
duracion=3
DURATION = timedelta(minutes=duracion)  # Duración del concurso
LOCAL_TIMEZONE = pytz.timezone("America/Mexico_City")  # Cambia según tu ubicación
START_TIME = LOCAL_TIMEZONE.localize(datetime(year=anno, month=mes, day=dia, hour=hora, minute=minuto, second=0, microsecond=0))

# Almacén de resultados y participantes
participants = {}  # nombre -> info
historial_envios = []  # Lista de envíos para guardar luego en historial.csv
informe_subido=False


@app.route('/enviar_resultado')
def enviar_resultado():
  global informe_subido
  now = datetime.now(LOCAL_TIMEZONE)  
  end_time = START_TIME + DURATION
  if now >= end_time and not informe_subido:         
    fecha = START_TIME.strftime("%y%m%d%H%M")
    cuerpo = generar_csv(participants)
    cuerpo2 = generar_historial_csv(historial_envios)  
    msg = EmailMessage()
    msg["Subject"] = f"Resultados concurso {fecha}"
    msg["From"] = "odavalos@up.edu.mx"
    msg["To"] = "odavalos@up.edu.mx"
    msg.set_content("Adjunto los resultados del concurso.")

    # Convertir el contenido a bytes
    contenido_bytes = cuerpo.encode("utf-8")
    contenido_bytes2 = cuerpo2.encode("utf-8") 
    # Adjuntar correctamente
    msg.add_attachment(contenido_bytes, maintype="text", subtype="csv", filename=f"{fecha}.csv")
    msg.add_attachment(contenido_bytes2, maintype="text", subtype="csv", filename=f"historial_{fecha}.csv")
    smtp_password = os.environ.get("GMAIL_PASSWORD")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login("odavalos@up.edu.mx", smtp_password)  # Considera usar una variable de entorno
        smtp.send_message(msg)
    informe_subido=True 
    return "Ya enviado o concurso no terminado"

def generar_csv(participantes):
    from io import StringIO
    import csv
    output = StringIO()
    writer = csv.writer(output)
    # Encabezado
    encabezado = ["Participante"] + list(problems.keys()) + ["Puntos", "Penalización"]
    writer.writerow(encabezado)
    # Filas
    for p in participantes.values():
        fila = [p["name"]]
        for pid in problems:
            fila.append(p["status"].get(pid, ""))
        fila += [p["score"], p["penalty"]]
        writer.writerow(fila)     
    return output.getvalue()
        
def generar_historial_csv(historial):
    from io import StringIO
    import csv
    output = StringIO()
    writer = csv.writer(output)
    
    # Encabezado
    writer.writerow(["Nombre", "Problema", "Respuesta", "Estado", "Intento", "Tiempo"])

    # Filas
    for entrada in historial:
        # Asumiendo que historial es una lista de tuplas o listas en orden:
        # (nombre, problema, respuesta, estado, intento, tiempo)
        writer.writerow(entrada)
    
    return output.getvalue()





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
            "name":name,
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
    global informe_subido
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


def register(name):
    if name not in participants:
        participants[name] = {
            "name": name,
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
        elapsed = int(get_elapsed_time() )
        info["status"][pid] = "✔"
        info["score"] += 1
        info["penalty"] += elapsed + 5*60 * (info["attempts"][pid] - 1)
    else:
        info["status"][pid] = "✖"
    estado = "aceptado" if correct else "rechazado"
    tiempo_concurso = int(get_elapsed_time())
    # Añadir al historial
    historial_envios.append([name, pid, answer, estado, info["attempts"][pid], tiempo_concurso])

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
