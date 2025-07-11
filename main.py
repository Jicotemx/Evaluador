# evaluador_icpc_con_tiempo.py (modificado)

import eventlet
import string
import os
import csv
import base64
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from datetime import datetime, timedelta
import pytz
import re
from io import StringIO

# =====================
# CONFIGURACIÓN
# =====================
anno, mes, dia, hora, minuto = 2025, 7, 9, 13, 18
LOCAL_TIMEZONE = pytz.timezone("America/Mexico_City")
START_TIME = LOCAL_TIMEZONE.localize(datetime(year=anno, month=mes, day=dia, hour=hora, minute=minuto))
DURATION = timedelta(minutes=2)

app = Flask(__name__)
socketio = SocketIO(app)

participants = {}
historial_envios = []
informe_subido = False

# =====================
# CARGA DE PROBLEMAS
# =====================
def cargar_problemas_desde_latex(archivo):
    problemas = {}
    with open(archivo, encoding="utf-8") as f:
        partes = [p.strip() for p in f.read().split("|||") if p.strip()]
    if len(partes) % 2 != 0:
        raise ValueError("Número impar de bloques. Faltan enunciados o respuestas.")
    letras = string.ascii_uppercase
    for i in range(0, len(partes), 2):
        letra = letras[i // 2]
        try:
            respuesta = float(partes[i+1]) if "." in partes[i+1] else int(partes[i+1])
        except:
            respuesta = partes[i+1]
        problemas[letra] = {
            "nombre": letra,
            "enunciado": partes[i],
            "respuesta": respuesta
        }
    return problemas

problems = cargar_problemas_desde_latex("/etc/secrets/problemas.txt")

# =====================
# AUXILIARES
# =====================
def get_status():
    global informe_subido
    now = datetime.now(LOCAL_TIMEZONE)
    if now < START_TIME:
        return "before"
    elif now > START_TIME + DURATION:
        if not informe_subido:
            enviar_resultado()
            informe_subido = True
        return "after"
    return "running"

def get_elapsed_time():
    now = datetime.now(LOCAL_TIMEZONE)
    return max((now - START_TIME).total_seconds(), 0)

def guardar_historial_csv(historial, fecha):
    nombre_archivo = f"historial_{fecha}.csv"
    with open(nombre_archivo, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Nombre", "Problema", "Respuesta", "Estado", "Intento", "Tiempo"])
        writer.writerows(historial)
    return nombre_archivo

def generar_csv(participantes):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Participante"] + list(problems.keys()) + ["Puntos", "Penalización"])
    for p in participants.values():
        fila = [p["name"]] + [p["status"].get(pid, "") for pid in problems] + [p["score"], p["penalty"]]
        writer.writerow(fila)
    return output.getvalue()

def enviar_resultado():
    global informe_subido
    now = datetime.now(LOCAL_TIMEZONE)
    if now < START_TIME + DURATION or informe_subido:
        return "No enviado (aún en curso o ya enviado)"
    fecha = START_TIME.strftime("%y%m%d%H%M")
    cuerpo = generar_csv(participants)
    historial_file = guardar_historial_csv(historial_envios, fecha)

    msg = EmailMessage()
    msg["Subject"] = f"Resultados concurso {fecha}"
    msg["From"] = os.environ.get("MAIL_FROM")
    msg["To"] = os.environ.get("MAIL_TO")
    msg.set_content("Adjunto los resultados del concurso.")
    msg.add_attachment(cuerpo.encode("utf-8"), maintype="text", subtype="csv", filename=f"{fecha}.csv")
    with open(historial_file, "rb") as f:
        msg.add_attachment(f.read(), maintype="text", subtype="csv", filename=historial_file)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(os.environ.get("MAIL_FROM"), os.environ.get("MAIL_PASS"))
            smtp.send_message(msg)
            informe_subido = True
    except Exception as e:
        return f"Error al enviar correo: {e}"

    return "Correo enviado"

# =====================
# FLASK ENDPOINTS
# =====================

@app.route("/submit", methods=["POST"])
def submit():
    if get_status() != "running":
        return jsonify({"error": "Concurso no activo"}), 403
    name = request.form["name"].strip()
    pid = request.form["problem"].strip()
    answer = request.form["answer"].strip()

    if name not in participants:
        return jsonify({"error": "Participante no registrado"})

    p = participants[name]
    p["attempts"][pid] += 1

    try:
        correct = abs(float(answer) - float(problems[pid]["respuesta"])) < 1e-6
    except:
        correct = answer.strip() == str(problems[pid]["respuesta"]).strip()

    estado = "✔" if correct else "✖"
    if correct and p["status"][pid] != "✔":
        elapsed = int(get_elapsed_time())
        p["status"][pid] = "✔"
        p["score"] += 1
        p["penalty"] += elapsed + 5 * 60 * (p["attempts"][pid] - 1)
    elif not correct:
        p["status"][pid] = "✖"

    historial_envios.append([name, pid, answer, estado, p["attempts"][pid], int(get_elapsed_time())])
    return jsonify({"message": "Respuesta registrada"})

@app.route("/ranking")
def ranking():
    data = [
        {
            "name": p["name"],
            "score": p["score"],
            "penalty": p["penalty"],
            "status": p["status"]
        } for p in participants.values()
    ]
    data.sort(key=lambda x: (-x["score"], x["penalty"]))
    return jsonify(data)

@app.route("/")
def index():
    return render_template("index.html", status=get_status(), start_time_iso=START_TIME.isoformat(), duration=int(DURATION.total_seconds()), problems=problems)

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=81, debug=True, use_reloader=False)
