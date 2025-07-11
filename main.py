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
anno, mes, dia, hora, minuto = 2025, 7, 9, 17, 6
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

# Mover estas funciones ANTES de enviar_resultado

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
        
# Versión corregida
def generar_historial_csv(historial):
    from io import StringIO
    import csv
    output = StringIO()
    writer = csv.writer(output)
    
    # Encabezado
    writer.writerow(["Nombre", "Problema", "Respuesta", "Estado", "Intento", "Tiempo"])

    # Filas - asegurarse de que cada entrada sea una lista/iterable
    for entrada in historial:
        if isinstance(entrada, (list, tuple)):
            writer.writerow(entrada)
        else:
            # Convertir a lista si es necesario
            writer.writerow([
                entrada[0],  # nombre
                entrada[1],  # problema
                entrada[2],  # respuesta
                entrada[3],  # estado
                entrada[4],  # intento
                entrada[5]   # tiempo
            ])
    
    return output.getvalue()
    
    return output.getvalue()

@app.route('/enviar_resultado')
def enviar_resultado():
    global informe_subido
    now = datetime.now(LOCAL_TIMEZONE)  
    end_time = START_TIME + DURATION
    
    # Siempre retornar una respuesta válida en todos los casos
    if now < end_time:
        return "El concurso aún no ha terminado", 200
    
    if informe_subido:
        return "El informe ya fue enviado anteriormente", 200
    
    try:
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
        if not smtp_password:
            return "Error: No se configuró la contraseña de Gmail", 500
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login("odavalos@up.edu.mx", smtp_password)
            smtp.send_message(msg)
        
        informe_subido = True
        return "Correo enviado con éxito", 200
    
    except Exception as e:
        app.logger.error(f"Error al enviar correo: {str(e)}")
        return f"Error al enviar el correo: {str(e)}", 500

# =====================
# FLASK ENDPOINTS
# =====================

@app.route("/admin/ejecutar_accion", methods=["POST"])
def ejecutar_accion():
    global START_TIME, DURATION, problems
    clave = request.form.get("clave")
    admin_pass = os.environ.get("ADMIN_PASSWORD")
    
    # Validación robusta de contraseña
    if not admin_pass or clave != admin_pass:
        app.logger.warning(f"Intento de acceso no autorizado. Clave recibida: '{clave}', esperada: '{admin_pass}'")
        return jsonify({"error": "Acceso denegado"}), 403
    
    acciones = request.form.getlist("acciones")
    mensajes = []
    cambios_realizados = False
    
    app.logger.info(f"Acciones solicitadas: {acciones}")
    
    # Cambiar hora de inicio
    if "cambiar_hora" in acciones:
        nueva_hora = request.form.get("hora_inicio")
        if nueva_hora:
            try:
                tz = pytz.timezone("America/Mexico_City")
                START_TIME = tz.localize(datetime.strptime(nueva_hora, "%Y-%m-%d %H:%M"))
                mensajes.append("Hora de inicio actualizada")
                cambios_realizados = True
                
                socketio.emit('config_update', {
                    'type': 'start_time',
                    'value': START_TIME.isoformat()
                }, broadcast=True)
            except Exception as e:
                mensajes.append(f"Error en formato de hora: {str(e)}")
                app.logger.error(f"Error cambiando hora: {str(e)}")
    
    # Cambiar duración
    if "cambiar_duracion" in acciones:
        duracion_min = request.form.get("duracion_min")
        if duracion_min:
            try:
                duracion_int = int(duracion_min)
                DURATION = timedelta(minutes=duracion_int)
                mensajes.append("Duración actualizada")
                cambios_realizados = True
                
                socketio.emit('config_update', {
                    'type': 'duration',
                    'value': int(DURATION.total_seconds())
                }, broadcast=True)
            except Exception as e:
                mensajes.append(f"Error con duración: {str(e)}")
                app.logger.error(f"Error cambiando duración: {str(e)}")
    
    # Recargar problemas y reevaluar
    if "recargar_problemas" in acciones:
        try:
            # Recargar problemas desde archivo
            new_problems = cargar_problemas_desde_latex("/etc/secrets/problemas.txt")
            problems = new_problems
            mensajes.append("Problemas recargados")
            cambios_realizados = True
            
            # Reevaluar todos los envíos
            reevaluar_todos()
            mensajes.append("Reevaluación completada")
            
            socketio.emit('config_update', {
                'type': 'problems',
                'value': problems
            }, broadcast=True)
        except Exception as e:
            mensajes.append(f"Error recargando problemas: {str(e)}")
            app.logger.error(f"Error recargando problemas: {str(e)}")
    
    # Forzar recarga si hubo cambios
    if cambios_realizados:
        socketio.emit('force_reload', {}, broadcast=True)
    
    return jsonify({
        "mensaje": " | ".join(mensajes) if mensajes else "No se realizaron cambios",
        "acciones": acciones
    })



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
