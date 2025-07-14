# evaluador_icpc_con_tiempo.py

import eventlet # ¡IMPORTANTE! Importar eventlet primero
eventlet.monkey_patch() # ¡IMPORTANTE! Esta línea debe ser la primera ejecución

import string
import os
import csv
import base64
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, jsonify, session, redirect, url_for # Importar session y redirect
from flask_socketio import SocketIO
from datetime import datetime, timedelta
import pytz
import re
from io import StringIO
import logging # Para logging más robusto

# Configurar logging básico
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =====================
# CONFIGURACIÓN
# =====================
# Hora de inicio por defecto (se puede cambiar desde admin)
anno, mes, dia, hora, minuto = 2025, 7, 14, 12, 58
LOCAL_TIMEZONE = pytz.timezone("America/Mexico_City")
START_TIME = LOCAL_TIMEZONE.localize(datetime(year=anno, month=mes, day=dia, hour=hora, minute=minuto))
DURATION = timedelta(minutes=2)

app = Flask(__name__)
# Necesario para sesiones, obtén de ENV o usa un valor seguro por defecto
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'una_clave_secreta_muy_segura_por_defecto_cambiala_en_produccion')
# Especificar async_mode='eventlet' (esto ya lo habíamos añadido)
socketio = SocketIO(app, async_mode='eventlet') 

# Estructuras de datos en memoria (considerar persistencia en producción)
participants = {}
historial_envios = [] # Lista de listas: [nombre, problema, respuesta, estado, intento, tiempo_transcurrido_segundos]
informe_subido = False # Bandera para controlar el envío del informe por correo

# =====================
# CARGA DE PROBLEMAS
# =====================
def cargar_problemas_desde_latex(archivo):
    problemas = {}
    try:
        with open(archivo, encoding="utf-8") as f:
            partes = [p.strip() for p in f.read().split("|||") if p.strip()]
        if len(partes) % 2 != 0:
            raise ValueError("Número impar de bloques. Faltan enunciados o respuestas.")
        letras = string.ascii_uppercase
        for i in range(0, len(partes), 2):
            letra = letras[i // 2]
            try:
                # Intenta convertir a float, si falla, mantén como string
                respuesta_str = partes[i+1].strip()
                if "." in respuesta_str or "e" in respuesta_str.lower(): # Comprobar si parece un float
                    respuesta = float(respuesta_str)
                else:
                    respuesta = int(respuesta_str) # Intenta int si no es numérico
            except ValueError:
                respuesta = respuesta_str # Si no es numérico, déjalo como string
            problemas[letra] = {
                "nombre": letra,
                "enunciado": partes[i].strip(), # Limpiar espacios extra
                "respuesta": respuesta
            }
        logging.info(f"Problemas cargados exitosamente: {list(problemas.keys())}")
        return problemas
    except FileNotFoundError:
        logging.error(f"Error: El archivo de problemas '{archivo}' no se encontró. Cargando problemas de ejemplo.")
        # Crear un problema de ejemplo si el archivo no existe
        return {"A": {"nombre": "A", "enunciado": "Problema A (Ejemplo): ¿Cuánto es $1+1$?", "respuesta": 2},
                "B": {"nombre": "B", "enunciado": "Problema B (Ejemplo): Evalúa $e^{i\\pi}$", "respuesta": -1}}
    except Exception as e:
        logging.error(f"Error al cargar problemas desde {archivo}: {e}")
        return {} # Retornar un diccionario vacío si hay un error grave

# Cargar problemas. Asume que problemas.txt está en la misma carpeta que main.py
problems = cargar_problemas_desde_latex("problemas.txt")

# =====================
# AUXILIARES
# =====================
def get_status():
    now = datetime.now(LOCAL_TIMEZONE)
    end_time = START_TIME + DURATION

    if now < START_TIME:
        return "before"
    elif now > end_time:
        return "after"
    return "running"

def get_elapsed_time():
    now = datetime.now(LOCAL_TIMEZONE)
    # Asegurarse de que el tiempo transcurrido no sea negativo si el concurso no ha iniciado
    return max((now - START_TIME).total_seconds(), 0)

def generar_csv(participantes):
    output = StringIO()
    writer = csv.writer(output)
    # Encabezado
    encabezado = ["Participante"] + list(problems.keys()) + ["Puntos", "Penalización"]
    writer.writerow(encabezado)
    # Filas
    for p in participantes.values():
        fila = [p["name"]]
        for pid in problems:
            # Usar .get para manejar problemas que un participante no ha intentado
            fila.append(p["status"].get(pid, ""))
        fila += [p["score"], p["penalty"]]
        writer.writerow(fila)
    return output.getvalue()

def generar_historial_csv(historial):
    output = StringIO()
    writer = csv.writer(output)

    # Encabezado
    writer.writerow(["Nombre", "Problema", "Respuesta", "Estado", "Intento", "Tiempo_Transcurrido_Segundos"])

    # Filas
    for entrada in historial:
        if len(entrada) == 6: # Esperamos 6 elementos: [nombre, problema, respuesta, estado, intento, tiempo]
            writer.writerow(entrada)
        else:
            logging.warning(f"Entrada de historial con formato incorrecto, saltando: {entrada}")

    return output.getvalue()

def reevaluar_todos():
    """
    Reevalúa todos los envíos históricos para recalcular los scores y penalizaciones
    de los participantes, útil si las respuestas de los problemas cambian.
    """
    global participants, historial_envios

    logging.info("Iniciando reevaluación de todos los participantes y envíos.")

    # Resetear el estado de todos los participantes
    # NOTA: Los participantes que se registraron pero no hicieron envíos no se "resetean" aquí
    # pero sus scores son 0 y estatus vacío por defecto si nunca enviaron.
    for name, p_data in participants.items():
        p_data["score"] = 0
        p_data["penalty"] = 0
        p_data["status"] = {pid: "" for pid in problems} # Resetear el estado de cada problema
        p_data["attempts"] = {pid: 0 for pid in problems} # Resetear intentos

    # Procesar el historial de envíos cronológicamente
    # Asegúrate de que historial_envios está ordenado por tiempo
    # (se asume que se añade cronológicamente)
    for entry in historial_envios:
        try:
            name, pid, answer_submitted, _, _, timestamp = entry
            
            if name not in participants:
                # Re-crear participante si no existe (ej. se borró la memoria y se reevalúa historial guardado)
                # Esto es una simplificación; en una DB, el participante existiría.
                participants[name] = {
                    "name": name,
                    "password": "temp_password", # Dummy password para reevaluación
                    "status": {p_id: "" for p_id in problems},
                    "attempts": {p_id: 0 for p_id in problems},
                    "score": 0,
                    "penalty": 0
                }
                logging.info(f"Re-creando participante '{name}' durante reevaluación.")
            
            p = participants[name]

            # Si el problema no existe después de recargar, o ya está resuelto, no lo procesamos
            if pid not in problems:
                logging.warning(f"Problema '{pid}' no encontrado en la nueva lista de problemas. Saltando envío de '{name}'.")
                continue
            if p["status"][pid] == "✔": # Ya resuelto, no cambiar el estado
                continue

            # Incrementar los intentos
            p["attempts"][pid] += 1

            correct_answer = problems[pid]["respuesta"]
            correct = False
            try:
                submitted_val = float(answer_submitted)
                correct_val = float(correct_answer)
                correct = abs(submitted_val - correct_val) < 1e-6
            except (ValueError, TypeError):
                correct = str(answer_submitted).strip().lower() == str(correct_answer).strip().lower()

            if correct:
                p["status"][pid] = "✔"
                p["score"] += 1
                p["penalty"] += int(timestamp) + 5 * 60 * (p["attempts"][pid] - 1)
            else:
                p["status"][pid] = "✖" # Marcar solo si no estaba resuelto y es incorrecto
        except Exception as e:
            logging.error(f"Error procesando entrada de historial '{entry}': {e}", exc_info=True)
            continue

    logging.info("Reevaluación completada.")
    # Emitir actualización de ranking a todos los clientes después de reevaluar
    socketio.emit('ranking_update', get_ranking_data())


# =====================
# FLASK ENDPOINTS
# =====================

@app.route("/login", methods=["POST"])
def login():
    name = request.form["name"].strip()
    password = request.form["password"].strip()

    if not name or not password:
        return jsonify({"error": "Nombre o contraseña no pueden estar vacíos."}), 400

    if name not in participants:
        # Para simplificar, la contraseña es el nombre por ahora.
        # En producción: ¡NUNCA HAGAS ESTO! Usa hashing de contraseñas (ej. bcrypt).
        participants[name] = {
            "name": name,
            "password": password, # ESTO ES INSEGURO PARA PRODUCCIÓN
            "status": {pid: "" for pid in problems},
            "attempts": {pid: 0 for pid in problems},
            "score": 0,
            "penalty": 0
        }
        logging.info(f"Nuevo participante registrado: {name}")
    
    # Validar que la contraseña coincida con la registrada
    if participants[name]["password"] != password:
        return jsonify({"error": "Contraseña incorrecta."}), 401

    session['logged_in_user'] = name # Guardar el nombre del usuario en la sesión
    logging.info(f"Participante '{name}' ha iniciado sesión.")
    return jsonify({"message": "Login exitoso"})

# RUTA PARA CERRAR SESIÓN
@app.route("/logout", methods=["POST"])
def logout():
    session.pop('logged_in_user', None) # Eliminar el usuario de la sesión
    logging.info("Usuario ha cerrado sesión.")
    return jsonify({"message": "Cierre de sesión exitoso."})

# NUEVA RUTA PARA VERIFICAR SESIÓN
@app.route("/check_session")
def check_session():
    if 'logged_in_user' in session:
        return jsonify({"logged_in": True, "user_name": session['logged_in_user']})
    return jsonify({"logged_in": False})


@app.before_request
def check_login():
    # Rutas que no requieren autenticación
    # MODIFICADO: Se añadió 'check_session' a la lista de rutas permitidas.
    if request.endpoint in ['login', 'static', 'index', 'admin_panel', 'logout', 'check_session', 'contest_config', 'ranking', 'submit']: 
        return # Permite el acceso
    
    # Si no hay usuario en sesión y no es una de las rutas permitidas, denegar acceso.
    # El frontend se encargará de redirigir o mostrar el formulario de login.
    if 'logged_in_user' not in session:
        return jsonify({"error": "No autorizado. Por favor inicie sesión."}), 401
    

@app.route("/admin")
def admin_panel():
    """Ruta para servir el panel de administración."""
    # En un entorno real, esta página también debería requerir autenticación de admin
    # antes de ser servida, no solo para las acciones POST.
    return render_template("admin.html")


@app.route("/admin/ejecutar_accion", methods=["POST"])
def ejecutar_accion():
    global START_TIME, DURATION, problems, informe_subido
    try: # <-- Inicio del bloque try (ya lo habíamos añadido)
        clave = request.form.get("clave")
        admin_pass = os.environ.get("ADMIN_PASSWORD")
        
        # Validación de contraseña de administrador
        if not admin_pass:
            logging.critical("ADMIN_PASSWORD no configurada en las variables de entorno del servidor.")
            return jsonify({"error": "Error de configuración del servidor: Contraseña de administrador no establecida."}), 500
        
        if clave != admin_pass:
            logging.warning(f"Intento de acceso no autorizado al panel de administración. Clave recibida: '{clave}', esperada: '********'")
            return jsonify({"error": "Acceso denegado. Contraseña de administrador incorrecta."}), 403
        
        acciones = request.form.getlist("acciones")
        mensajes = []
        cambios_realizados = False
        
        logging.info(f"Acciones solicitadas por admin: {acciones}")
        
        # Cambiar hora de inicio
        if "cambiar_hora" in acciones:
            nueva_hora = request.form.get("hora_inicio")
            if nueva_hora:
                try:
                    tz = pytz.timezone("America/Mexico_City")
                    # El formato esperado es YYYY-MM-DD HH:MM
                    START_TIME = tz.localize(datetime.strptime(nueva_hora, "%Y-%m-%d %H:%M"))
                    mensajes.append(f"Hora de inicio actualizada a {START_TIME.strftime('%Y-%m-%d %H:%M')}")
                    cambios_realizados = True
                    
                    # Emitir a todos los clientes la nueva hora de inicio
                    # MODIFICADO: Eliminado broadcast=True
                    socketio.emit('config_update', {
                        'type': 'start_time',
                        'value': START_TIME.isoformat()
                    }) 
                    logging.info(f"Hora de inicio cambiada a: {START_TIME}")
                except ValueError as e:
                    mensajes.append(f"Error en formato de hora (esperado AAAA-MM-DD HH:MM): {str(e)}")
                    app.logger.error(f"Error cambiando hora: {str(e)}")
                except Exception as e:
                    mensajes.append(f"Error inesperado al cambiar hora: {str(e)}")
                    app.logger.error(f"Error inesperado cambiando hora: {str(e)}")
        
        # Cambiar duración
        if "cambiar_duracion" in acciones:
            duracion_min = request.form.get("duracion_min")
            if duracion_min:
                try:
                    duracion_int = int(duracion_min)
                    if duracion_int <= 0:
                        raise ValueError("La duración debe ser un número positivo de minutos.")
                    DURATION = timedelta(minutes=duracion_int)
                    mensajes.append(f"Duración actualizada a {duracion_int} minutos")
                    cambios_realizados = True
                    
                    # Emitir a todos los clientes la nueva duración
                    # MODIFICADO: Eliminado broadcast=True
                    socketio.emit('config_update', {
                        'type': 'duration',
                        'value': int(DURATION.total_seconds()) # Enviar segundos para el JS
                    }) 
                    logging.info(f"Duración cambiada a: {DURATION}")
                except ValueError as e:
                    mensajes.append(f"Error con duración (debe ser un número entero > 0): {str(e)}")
                    app.logger.error(f"Error cambiando duración: {str(e)}")
                except Exception as e:
                    mensajes.append(f"Error inesperado al cambiar duración: {str(e)}")
                    app.logger.error(f"Error inesperado cambiando duración: {str(e)}")
        
        # Recargar problemas y reevaluar
        if "recargar_problemas" in acciones:
            try:
                # Cargar problemas. Asume que problemas.txt está en la misma carpeta que main.py
                new_problems = cargar_problemas_desde_latex("problemas.txt")
                if not new_problems:
                    raise Exception("No se pudieron cargar nuevos problemas. Manteniendo los problemas actuales.")
                
                problems = new_problems
                mensajes.append(f"Problemas recargados: {list(problems.keys())}")
                cambios_realizados = True
                informe_subido = False # Resetear la bandera si se recargan los problemas

                # Reevaluar todos los envíos con las nuevas definiciones de problemas
                reevaluar_todos()
                mensajes.append("Reevaluación de envíos completada.")
                logging.info("Problemas recargados y reevaluación forzada.")

                # Emitir la actualización de problemas (normalmente implica una recarga de página en el frontend)
                # MODIFICADO: Eliminado broadcast=True
                socketio.emit('config_update', {
                    'type': 'problems',
                    'value': {k: {'enunciado': v['enunciado']} for k, v in problems.items()} # No enviar la respuesta aquí
                })
                # MODIFICADO: Eliminado broadcast=True
                socketio.emit('force_reload', {}) 
                
            except Exception as e:
                mensajes.append(f"Error recargando problemas: {str(e)}")
                app.logger.error(f"Error recargando problemas: {str(e)}")
        
        # Forzar recarga si hubo cambios y no se hizo ya por recargar_problemas
        # MODIFICADO: Eliminado broadcast=True
        if cambios_realizados and "recargar_problemas" not in acciones: 
            socketio.emit('force_reload', {})
        
        return jsonify({
            "mensaje": " | ".join(mensajes) if mensajes else "No se realizaron cambios.",
            "acciones": acciones
        })
    except Exception as e: # <-- Bloque catch-all para cualquier excepción no esperada (ya lo habíamos añadido)
        logging.error(f"Error inesperado en /admin/ejecutar_accion: {str(e)}", exc_info=True)
        return jsonify({"error": f"Ocurrió un error inesperado en el servidor: {str(e)}"}), 500 

# =====================
# RUTAS DEL CONCURSO
# =====================
# Definir la ruta raíz para servir el HTML principal
@app.route("/")
def index():
    return render_template("index.html")

# Obtener la configuración del concurso
@app.route("/contest_config")
def contest_config():
    return jsonify({
        "start_time": START_TIME.isoformat(),
        "duration": int(DURATION.total_seconds()),
        "problems": {k: {"enunciado": v["enunciado"]} for k, v in problems.items()}
    })

@app.route("/submit", methods=["POST"])
def submit_answer():
    name = request.form["name"].strip()
    pid = request.form["problem"].strip()
    answer = request.form["answer"].strip()

    if name not in participants:
        return jsonify({"error": "Participante no registrado"}), 400

    if pid not in problems:
        return jsonify({"error": "Problema no encontrado"}), 400

    p = participants[name]

    # Si ya resolvió el problema, no permitir más envíos correctos para sumar puntos
    if p["status"][pid] == "✔":
        return jsonify({"message": "Ya has resuelto este problema correctamente."})

    p["attempts"][pid] += 1

    correct_answer = problems[pid]["respuesta"]
    correct = False
    try:
        # Intentar comparación numérica si ambas pueden ser flotantes
        submitted_val = float(answer)
        correct_val = float(correct_answer)
        correct = abs(submitted_val - correct_val) < 1e-6
    except (ValueError, TypeError):
        # Si no son numéricas o hay error, comparar como strings (ignorando mayúsculas/minúsculas y espacios extra)
        correct = str(answer).strip().lower() == str(correct_answer).strip().lower()

    estado = "✔" if correct else "✖"
    
    if correct:
        elapsed = int(get_elapsed_time())
        p["status"][pid] = "✔" # Marcar como resuelto
        p["score"] += 1
        p["penalty"] += elapsed + 5 * 60 * (p["attempts"][pid] - 1)
        message = "Respuesta CORRECTA. ¡Bien hecho!"
    else:
        p["status"][pid] = "✖" # Marcar como incorrecto
        message = "Respuesta INCORRECTA. Intenta de nuevo."

    # Registrar el intento en el historial
    historial_envios.append([name, pid, answer, estado, p["attempts"][pid], int(get_elapsed_time())])
    
    # Emitir actualización de ranking
    socketio.emit('ranking_update', get_ranking_data())

    return jsonify({"message": message})


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
    # Ordenar por score (desc) y luego por penalty (asc)
    data.sort(key=lambda x: (-x["score"], x["penalty"]))
    return jsonify(data)

# =====================
# MANEJO DE WEBSOCKETS
# =====================
@socketio.on('connect')
def test_connect():
    logging.info("Cliente conectado")

@socketio.on('disconnect')
def test_disconnect():
    logging.info("Cliente desconectado")

# =====================
# ENVÍO DE CORREO (ADMIN)
# =====================

@app.route("/send_email", methods=["POST"])
def send_email():
    global informe_subido
    try:
        clave = request.form.get("clave")
        admin_pass = os.environ.get("ADMIN_PASSWORD")

        if not admin_pass:
            return jsonify({"error": "Error de configuración del servidor: Contraseña de administrador no establecida."}), 500
        
        if clave != admin_pass:
            return jsonify({"error": "Acceso denegado. Contraseña incorrecta."}), 403

        if informe_subido:
            return jsonify({"message": "El informe ya fue enviado anteriormente."})

        email_to = request.form.get("email_to")
        if not email_to:
            return jsonify({"error": "Destinatario de correo no especificado."}), 400

        email_host = os.environ.get("EMAIL_HOST")
        email_port = int(os.environ.get("EMAIL_PORT", 587))
        email_user = os.environ.get("EMAIL_USER")
        email_pass = os.environ.get("EMAIL_PASS")

        if not all([email_host, email_user, email_pass]):
            return jsonify({"error": "Faltan credenciales de correo en el servidor."}), 500

        msg = EmailMessage()
        msg["From"] = email_user
        msg["To"] = email_to
        msg["Subject"] = "Informe Final de Resultados del Concurso"
        msg.set_content("Adjunto encontrarás el informe detallado de los resultados y el historial de envíos del concurso.")

        # Adjuntar CSV de resultados
        csv_data_resultados = generar_csv(participants)
        msg.add_attachment(csv_data_resultados, filename="resultados_concurso.csv", subtype="csv", maintype="text")

        # Adjuntar CSV de historial de envíos
        csv_data_historial = generar_historial_csv(historial_envios)
        msg.add_attachment(csv_data_historial, filename="historial_envios.csv", subtype="csv", maintype="text")

        with smtplib.SMTP(email_host, email_port) as smtp:
            smtp.starttls()
            smtp.login(email_user, email_pass)
            smtp.send_message(msg)

        informe_subido = True
        return jsonify({"message": f"Informe enviado exitosamente a {email_to}"})

    except Exception as e:
        app.logger.error(f"Error al enviar correo: {e}", exc_info=True)
        return jsonify({"error": f"Error al enviar correo: {str(e)}"}), 500

# =====================
# EJECUCIÓN DE LA APP
# =====================
if __name__ == "__main__":
    # app.run(debug=True) # Para desarrollo local sin websockets
    # Usar socketio.run para integrar Flask con Socket.IO
    socketio.run(app, debug=True, host='0.0.0.0', port=os.environ.get("PORT", 5000))
