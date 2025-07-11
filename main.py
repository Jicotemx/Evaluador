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
anno=2025; dia=11; mes=7;  hora=12; minuto=18
duracion=30
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

@app.route("/estado_configuracion")
def estado_configuracion():
    return jsonify({
        "start_time": START_TIME.isoformat(),
        "duration": int(DURATION.total_seconds()),
        "problems": problems
    })



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

problems = cargar_problemas_desde_latex("/etc/secrets/problemas.txt")


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
    if now < START_TIME:
        return 0
    elif now > START_TIME + DURATION:
        return int(DURATION.total_seconds())
    else:
        return int((now - START_TIME).total_seconds())


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

current_attempt = 1
attempt_history = {}
import copy
def reevaluar_todos():   
    global current_attempt, attempt_history
    
    # 1. Guardar el estado actual antes de reiniciar
    attempt_history[current_attempt] = {
        'participants': participants.copy(),
        'historial_envios': historial_envios.copy()
    }
    print(f"Intento {current_attempt} guardado en historial")
    # 2. Incrementar el número de intento
    current_attempt += 1
    
    # 3. Reiniciar estado de todos los participantes
    for name in participants:
        participants[name] = {
            "name": name,
            "password": participants[name]["password"],  # Mantener la contraseña
            "start_time": datetime.now(),
            "responses": {},
            "attempts": {pid: 0 for pid in problems},
            "status": {pid: "" for pid in problems},
            "score": 0,
            "penalty": 0
        }
    
    # 4. RE-EVALUAR TODAS LAS RESPUESTAS
    for entry in historial_envios:
        nombre = entry[0]
        problema = entry[1]
        respuesta = entry[2]
        intento = entry[4]
        tiempo = entry[5]
        
        if nombre not in participants:
            continue
        
        p = participants[nombre]
        p["attempts"][problema] += 1
        
        try:
            user_answer = float(respuesta)
            correct = abs(user_answer - float(problems[problema]["respuesta"])) < 1e-6
        except ValueError:
            correct = respuesta.strip() == str(problems[problema]["respuesta"]).strip()
        
        if correct:
            if p["status"][problema] != "✔":  # Solo si no estaba ya correcto
                p["status"][problema] = "✔"
                p["score"] += 1
                # Penalización: tiempo + 5 min por cada intento fallido previo
                p["penalty"] += tiempo + 5*60 * (intento - 1)
        else:
            if p["status"][problema] != "✔":  # Solo si no está correcto
                p["status"][problema] = "✖"
    socketio.emit('reevaluate_done', broadcast=True)
@app.route("/admin/reevaluar", methods=["POST"])
def admin_reevaluar():
    clave = request.form.get("clave")
    if clave != "TU_CLAVE_ADMIN":
        return jsonify({"error": "No autorizado"}), 403
    
    reevaluar_todos()
    socketio.emit('reevaluate_done', broadcast=True)  # Notificar a todos
    return jsonify({"mensaje": "Reevaluación completa"})    

@app.route("/status")
def status():
    return jsonify({"status": get_status(), "time": get_elapsed_time()})

# Nueva ruta para obtener histórico
@app.route("/attempt_history/<int:attempt_id>")
def get_attempt_history(attempt_id):
    if attempt_id in attempt_history:
        return jsonify(attempt_history[attempt_id])
    return jsonify({"error": "Intento no encontrado"}), 404


@app.route("/ranking")
def ranking():
    attempt = request.args.get('attempt', 'current')
    
    if attempt == 'current':
        data_source = participants
        attempt_id = current_attempt
    else:
        try:
            attempt_id = int(attempt)
            if attempt_id not in attempt_history:
                return jsonify({"error": "Intento no válido"}), 400
            data_source = attempt_history[attempt_id]['participants']
        except ValueError:
            return jsonify({"error": "Intento no válido"}), 400
    
    ranking_data = []
    for name, info in data_source.items():
        # Asegurar que el status tenga todas las claves de problemas
        status = {pid: info["status"].get(pid, "") for pid in problems}
        
        ranking_data.append({
            "name": name,
            "score": info["score"],
            "penalty": info["penalty"],
            "status": status,  # Usar el diccionario corregido
            "attempts": info["attempts"],
            "attempt_id": attempt_id
        })

    ranking_data.sort(key=lambda x: (-x["score"], x["penalty"]))
    return jsonify({
        'data': ranking_data,
        'current_attempt': current_attempt,
        'total_attempts': list(attempt_history.keys())
    })

@socketio.on('connect')
def handle_connect():
    print('Cliente conectado')

@app.route("/admin/ejecutar_accion", methods=["POST"])
# Modificar la función ejecutar_accion
@app.route("/admin/ejecutar_accion", methods=["POST"])
def ejecutar_accion():
    global START_TIME, DURATION, problems
    clave = request.form.get("clave")
    if clave != os.environ.get("ADMIN_PASSWORD"):
        return jsonify({"error": "Acceso denegado"}), 403
    
    acciones = request.form.getlist("acciones")
    mensajes = []
    
    # Cambiar hora de inicio
    if "cambiar_hora" in acciones:
        nueva_hora = request.form.get("hora_inicio")
        if nueva_hora:
            try:
                tz = pytz.timezone("America/Mexico_City")
                # Convertir a datetime y localizar
                START_TIME = tz.localize(datetime.strptime(nueva_hora, "%Y-%m-%d %H:%M"))
                mensajes.append("Hora de inicio actualizada")
                
                # Emitir actualización
                socketio.emit('config_update', {
                    'type': 'start_time',
                    'value': START_TIME.isoformat()
                }, broadcast=True)
            except ValueError as e:
                mensajes.append(f"Error en formato de hora: {str(e)}")
    
    # Cambiar duración
    if "cambiar_duracion" in acciones:
        duracion_min = request.form.get("duracion_min")
        if duracion_min:
            try:
                DURATION = timedelta(minutes=int(duracion_min))
                mensajes.append("Duración actualizada")
                
                # Emitir actualización
                socketio.emit('config_update', {
                    'type': 'duration',
                    'value': int(DURATION.total_seconds())
                }, broadcast=True)
            except ValueError:
                mensajes.append("Duración debe ser un número entero")
    
    # Recargar problemas y reevaluar
    if "recargar_problemas" in acciones:
        try:
            # Recargar problemas desde archivo
            problems = cargar_problemas_desde_latex("/etc/secrets/problemas.txt")
            mensajes.append("Problemas recargados")
            
            # Reevaluar todos los envíos
            reevaluar_todos()
            mensajes.append("Reevaluación completada")
            
            # Emitir actualización
            socketio.emit('config_update', {
                'type': 'problems',
                'value': problems
            }, broadcast=True)
        except Exception as e:
            mensajes.append(f"Error recargando problemas: {str(e)}")
    
    return jsonify({
        "mensaje": " | ".join(mensajes) if mensajes else "No se seleccionó ninguna acción",
        "acciones": acciones
    })

    

# =====================
# INICIO
# =====================

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=81, debug=True, use_reloader=False)
