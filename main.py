# evaluador_icpc_con_tiempo.py (modificado y corregido)

import eventlet
eventlet.monkey_patch() # ¡IMPORTANTE! Esta línea debe ser la primera ejecución
import string
import os
import csv
import base64
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, jsonify, session # Importar session
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
anno, mes, dia, hora, minuto = 2049, 12, 31, 23, 59
LOCAL_TIMEZONE = pytz.timezone("America/Mexico_City")
START_TIME = LOCAL_TIMEZONE.localize(datetime(year=anno, month=mes, day=dia, hour=hora, minute=minuto))
DURATION = timedelta(minutes=20)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'una_clave_secreta_por_defecto_si_no_esta_en_env') # Necesario para sesiones
socketio = SocketIO(app)

# Estructuras de datos en memoria (considerar persistencia en producción)
participants = {}
# Ejemplo de estructura de participants:
# {
#     "NombreParticipante": {
#         "name": "NombreParticipante",
#         "password": "hashed_password", # Idealmente
#         "status": {"A": "", "B": "✖", "C": "✔"}, # Estado por problema
#         "attempts": {"A": 0, "B": 2, "C": 1}, # Intentos por problema
#         "score": 1,
#         "penalty": 120 # tiempo del primer acierto + 5*60*(intentos-1)
#     }
# }
historial_envios = [] # Lista de listas: [nombre, problema, respuesta, estado, intento, tiempo]
informe_subido = False

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
                    respuesta = int(respuesta_str) # Intenta int si no es float
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
        logging.error(f"Error: El archivo de problemas '{archivo}' no se encontró.")
        # Crear un problema de ejemplo si el archivo no existe
        return {"A": {"nombre": "A", "enunciado": "Problema A (Ejemplo): ¿Cuánto es $1+1$?", "respuesta": 2}}
    except Exception as e:
        logging.error(f"Error al cargar problemas desde {archivo}: {e}")
        return {} # Retornar un diccionario vacío si hay un error grave

problems = cargar_problemas_desde_latex("/etc/secrets/problemas.txt")

# =====================
# AUXILIARES
# =====================
def get_status():
    global informe_subido
    now = datetime.now(LOCAL_TIMEZONE)
    end_time = START_TIME + DURATION

    if now < START_TIME:
        return "before"
    elif now > end_time:
        # Esto asegura que el envío solo ocurra una vez al finalizar.
        # Podrías querer que un admin lo fuerce manualmente después.
        if not informe_subido:
            # Asegúrate de no llamar a enviar_resultado aquí si es una ruta Flask
            # La ruta /enviar_resultado puede ser llamada por un admin o un proceso cron
            # Aquí solo cambiamos el estado y la bandera.
            pass # La bandera de informe_subido se controla en la función enviar_resultado por la ruta
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
            fila.append(p["status"].get(pid, ""))
        fila += [p["score"], p["penalty"]]
        writer.writerow(fila)
    return output.getvalue()

def generar_historial_csv(historial):
    output = StringIO()
    writer = csv.writer(output)

    # Encabezado
    writer.writerow(["Nombre", "Problema", "Respuesta", "Estado", "Intento", "Tiempo"])

    # Filas
    for entrada in historial:
        # Asegurarse de que cada entrada sea una lista/iterable de longitud adecuada
        # Esto previene errores si historial_envios tiene un formato inesperado
        if len(entrada) == 6: # Esperamos 6 elementos: [nombre, problema, respuesta, estado, intento, tiempo]
            writer.writerow(entrada)
        else:
            logging.warning(f"Entrada de historial con formato incorrecto, saltando: {entrada}")

    return output.getvalue()
def califica(name,pid, elapsed,answer,problem_correct_answer):
    correct = False
    estado="✖"
    try:
        # Intenta comparar como flotantes si ambas respuestas parecen numéricas
        submitted_val = float(answer)
        correct_val = float(problem_correct_answer)
        correct = abs(submitted_val - correct_val) < 1e-6
    except ValueError:
        # Si no son numéricas o la conversión falla, compara como cadenas
        correct = answer.lower() == str(problem_correct_answer).lower() # Comparación insensible a mayúsculas

    estado = "✔" if correct else "✖"
    
    # Solo actualizar score y penalty si el problema no había sido resuelto correctamente antes
    if correct and p["status"][pid] != "✔":        
        p["status"][pid] = "✔"
        p["score"] += 1
        p["penalty"] += elapsed + 5 * 60 * (p["attempts"][pid] - 1)
        logging.info(f"Participante {name} acertó problema {pid}. Score: {p['score']}, Penalty: {p['penalty']}")
    elif not correct and p["status"][pid] != "✔":
        # Marcar como '✖' solo si aún no está resuelto correctamente
        p["status"][pid] = "✖"
        logging.info(f"Participante {name} falló problema {pid}. Intento {p['attempts'][pid]}.")   
    return estado    
def reevaluar_todos():
    """
    Reevalúa todos los envíos históricos para recalcular los scores y penalizaciones
    de los participantes, útil si las respuestas de los problemas cambian.
    """
    global participants, historial_envios

    logging.info("Iniciando reevaluación de todos los participantes y envíos.")

    # Resetear el estado de todos los participantes
    for name, p_data in participants.items():
        p_data["score"] = 0
        p_data["penalty"] = 0
        p_data["status"] = {pid: "" for pid in problems} # Resetear el estado de cada problema
        p_data["attempts"] = {pid: 0 for pid in problems} # Resetear intentos

    # Procesar el historial de envíos cronológicamente
    # Asegúrate de que historial_envios está ordenado por tiempo si el orden importa
    # (actualmente se añade al final, por lo que debería ser cronológico)
    for entry in historial_envios:
        try:
            name, pid, answer_submitted, _, _, timestamp = entry
            
            if name not in participants:
                logging.warning(f"Participante '{name}' no encontrado durante reevaluación. Saltando envío.")
                continue # Saltar si el participante no existe (quizás fue eliminado o nunca se registró)

            if pid not in problems:
                logging.warning(f"Problema '{pid}' no encontrado durante reevaluación. Saltando envío.")
                continue # Saltar si el problema ya no existe

            p = participants[name]

            # Incrementar los intentos (ahora basado en el historial, no en el submit original)
            p["attempts"][pid] += 1

            # Obtener la respuesta correcta actual del problema
            correct_answer = problems[pid]["respuesta"]

            correct = False
            try:
                # Intenta comparación numérica si ambas son numéricas
                # Es crucial que 'answer_submitted' se convierta a un tipo que permita la comparación
                # Si el historial guarda la respuesta como string, convertir a float
                correct_submitted_val = float(answer_submitted)
                correct_problem_val = float(correct_answer)
                correct = abs(correct_submitted_val - correct_problem_val) < 1e-6
            except ValueError:
                # Si alguna no es numérica, compara como string
                correct = str(answer_submitted).strip() == str(correct_answer).strip()
            except TypeError: # Manejar caso donde correct_answer no sea comparable como float
                 correct = str(answer_submitted).strip() == str(correct_answer).strip()


            # Solo sumar puntos y penalización si no había acertado antes
            if correct and p["status"][pid] != "✔":
                p["status"][pid] = "✔"
                p["score"] += 1
                # Recalcular penalización usando el timestamp del envío original
                # El timestamp en historial_envios debe ser segundos transcurridos desde START_TIME
                # Asegúrate de que el formato de 'timestamp' en historial_envios sea adecuado (int segundos)
                p["penalty"] += int(timestamp) + 5 * 60 * (p["attempts"][pid] - 1)
            elif not correct and p["status"][pid] != "✔":
                # Marcar como '✖' si no es correcta Y no ha sido acertada antes
                p["status"][pid] = "✖" # Solo marca si aún no está resuelto
            # Si ya está en ✔, no cambia aunque haya envíos incorrectos posteriores
        except Exception as e:
            logging.error(f"Error procesando entrada de historial '{entry}': {e}")
            continue # Continuar con la siguiente entrada

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

    # Esto es una validación extremadamente básica y NO SEGURA para producción.
    # En un entorno real, usarías una base de datos y un hash de la contraseña.
    # Aquí, simplemente registramos al participante si no existe.
    if name not in participants:
        # Para simplificar, la contraseña es el nombre por ahora.
        # Idealmente, deberías almacenar un hash de la contraseña real aquí.
        participants[name] = {
            "name": name,
            "password": password, # NO HACER ESTO EN PRODUCCIÓN
            "status": {pid: "" for pid in problems},
            "attempts": {pid: 0 for pid in problems},
            "score": 0,
            "penalty": 0
        }
        logging.info(f"Nuevo participante registrado: {name}")
    
    # Validar que la contraseña coincida con la registrada (si existe)
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

@app.before_request
def check_login():
    # Permitir acceso a la página de login y a los recursos estáticos sin estar logueado
    if request.endpoint in ['login', 'static', 'index']:
        return # Permite el acceso
    
    # Si no hay usuario en sesión y no es una de las rutas permitidas, redirigir o denegar
    if 'logged_in_user' not in session:
        # Para API calls, retornar un error JSON; para rutas HTML, redirigir al login
        if request.path.startswith('/submit') or request.path.startswith('/ranking'):
            return jsonify({"error": "No autorizado. Por favor inicie sesión."}), 401
        # Para la ruta principal si el usuario no está logueado, redirigir al login (manejar esto en JS)
        # Esto es más relevante si index() no incluye el formulario de login.
        # Como index.html maneja el login/mainDiv, no necesitamos una redirección de Flask aquí.
        pass # El frontend JS se encarga de mostrar el loginDiv

@app.route("/admin")
def admin_panel():
    """Ruta para servir el panel de administración."""
    # En un entorno real, esta página también debería requerir autenticación de admin
    # antes de ser servida, no solo para las acciones POST.
    return render_template("admin.html")


@app.route("/admin/ejecutar_accion", methods=["POST"])
def ejecutar_accion():
    global START_TIME, DURATION, problems, informe_subido
    clave = request.form.get("clave")
    admin_pass = os.environ.get("ADMIN_PASSWORD")
    
    # Validación robusta de contraseña
    if not admin_pass:
        logging.error("ADMIN_PASSWORD no configurada en las variables de entorno.")
        return jsonify({"error": "Error de configuración del servidor."}), 500
    
    if clave != admin_pass:
        logging.warning(f"Intento de acceso no autorizado. Clave recibida: '{clave}', esperada: '********'")
        return jsonify({"error": "Acceso denegado"}), 403
    
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
                # Asegurarse de que el formato de entrada sea compatible con strptime
                START_TIME = tz.localize(datetime.strptime(nueva_hora, "%Y-%m-%d %H:%M"))
                mensajes.append(f"Hora de inicio actualizada a {START_TIME.strftime('%Y-%m-%d %H:%M')}")
                cambios_realizados = True
                
                socketio.emit('config_update', {
                    'type': 'start_time',
                    'value': START_TIME.isoformat()
                }, to='*')
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
                
                socketio.emit('config_update', {
                    'type': 'duration',
                    'value': int(DURATION.total_seconds())
                }, to='*')
                logging.info(f"Duración cambiada a: {DURATION}")
            except ValueError as e:
                mensajes.append(f"Error con duración (debe ser un número entero): {str(e)}")
                app.logger.error(f"Error cambiando duración: {str(e)}")
            except Exception as e:
                mensajes.append(f"Error inesperado al cambiar duración: {str(e)}")
                app.logger.error(f"Error inesperado cambiando duración: {str(e)}")
    
    # Recargar problemas y reevaluar
    if "recargar_problemas" in acciones:
        try:
            old_problems_keys = set(problems.keys())
            new_problems = cargar_problemas_desde_latex("/etc/secrets/problemas.txt")
            if not new_problems:
                raise Exception("No se pudieron cargar nuevos problemas. Manteniendo los problemas actuales.")
            
            problems = new_problems
            mensajes.append(f"Problemas recargados: {list(problems.keys())}")
            cambios_realizados = True
            informe_subido = False # Resetear la bandera si se recargan los problemas

            # Reevaluar todos los envíos con las nuevas definiciones de problemas
            reevaluar_todos()
            mensajes.append("Reevaluación completada")
            logging.info("Problemas recargados y reevaluación forzada.")

            # Emitir la actualización de problemas (normalmente implica una recarga de página)
            socketio.emit('config_update', {
                'type': 'problems',
                'value': {k: {'enunciado': v['enunciado'], 'respuesta': str(v['respuesta'])} for k, v in problems.items()}
            }, to='*')
            socketio.emit('force_reload', {}, to='*') # Forzar recarga para el frontend
            
        except Exception as e:
            mensajes.append(f"Error recargando problemas: {str(e)}")
            app.logger.error(f"Error recargando problemas: {str(e)}")
    
    # Forzar recarga si hubo cambios
    if cambios_realizados and "recargar_problemas" not in acciones: # No duplicar si ya se hizo por problemas
        socketio.emit('force_reload', {}, to='*')
    
    return jsonify({
        "mensaje": " | ".join(mensajes) if mensajes else "No se realizaron cambios",
        "acciones": acciones
    })

@app.route("/submit", methods=["POST"])
def submit():
    # Asegurarse de que el usuario esté logueado
    if 'logged_in_user' not in session:
        return jsonify({"error": "No autorizado. Por favor inicie sesión."}), 401
    
    name = session['logged_in_user'] # Usar el nombre de la sesión para seguridad
    
    if get_status() != "running":
        return jsonify({"error": "Concurso no activo"}), 403

    pid = request.form["problem"].strip()
    answer = request.form["answer"].strip()

    if name not in participants:
        # Esto no debería ocurrir si el check_login funciona, pero es una buena salvaguarda
        return jsonify({"error": "Participante no registrado"}), 400

    if pid not in problems:
        return jsonify({"error": "Problema no válido"}), 400

    p = participants[name]
    p["attempts"][pid] = p["attempts"].get(pid, 0) + 1 # Inicializar si no existe

    # Normalizar respuestas para comparación
    problem_correct_answer = problems[pid]["respuesta"]
    estado=califica(name,pid, int(get_elapsed_time()),answer,problem_correct_answer)
    """
    correct = False
    try:
        # Intenta comparar como flotantes si ambas respuestas parecen numéricas
        submitted_val = float(answer)
        correct_val = float(problem_correct_answer)
        correct = abs(submitted_val - correct_val) < 1e-6
    except ValueError:
        # Si no son numéricas o la conversión falla, compara como cadenas
        correct = answer.lower() == str(problem_correct_answer).lower() # Comparación insensible a mayúsculas

    estado = "✔" if correct else "✖"
    
    # Solo actualizar score y penalty si el problema no había sido resuelto correctamente antes
    if correct and p["status"][pid] != "✔":
        elapsed = int(get_elapsed_time())
        p["status"][pid] = "✔"
        p["score"] += 1
        p["penalty"] += elapsed + 5 * 60 * (p["attempts"][pid] - 1)
        logging.info(f"Participante {name} acertó problema {pid}. Score: {p['score']}, Penalty: {p['penalty']}")
    elif not correct and p["status"][pid] != "✔":
        # Marcar como '✖' solo si aún no está resuelto correctamente
        p["status"][pid] = "✖"
        logging.info(f"Participante {name} falló problema {pid}. Intento {p['attempts'][pid]}.")
    """ 
    # Registrar en el historial de envíos
    # Asegúrate de que el timestamp sea segundos transcurridos para la reevaluación
    historial_envios.append([name, pid, answer, estado, p["attempts"][pid], int(get_elapsed_time())])
    
    # Emitir actualización a todos los clientes
    socketio.emit('ranking_update', get_ranking_data())
    return jsonify({"message": "Respuesta registrada", "status": estado})

def get_ranking_data():
    """Helper para obtener los datos del ranking de forma consistente."""
    data = [
        {
            "name": p["name"],
            "score": p["score"],
            "penalty": p["penalty"],
            "status": p["status"]
        } for p in participants.values()
    ]
    data.sort(key=lambda x: (-x["score"], x["penalty"]))
    return data

@app.route("/ranking")
def ranking():
    # El frontend lo pide continuamente, no necesita login para verlo.
    return jsonify(get_ranking_data())

@app.route("/")
def index():
    # Si el usuario ya está logueado, podríamos pasar su nombre a la plantilla
    # para que el JS lo ponga directamente en submitName.
    logged_in_user = session.get('logged_in_user', None)
    return render_template(
        "index.html",
        status=get_status(),
        start_time_iso=START_TIME.isoformat(),
        duration=int(DURATION.total_seconds()),
        problems=problems,
        logged_in_user=logged_in_user # Pasar el usuario logueado
    )

@app.route('/enviar_resultado')
def enviar_resultado_route():
    global informe_subido
    now = datetime.now(LOCAL_TIMEZONE)
    end_time = START_TIME + DURATION
    
    # Esta ruta debería ser idealmente protegida por autenticación de administrador
    # o activada por un proceso en background, no por una simple solicitud GET.
    # Aquí, simplemente la protegemos por el estado del concurso.
    
    if now < end_time:
        return "El concurso aún no ha terminado", 403 # Cambiado a 403 para indicar prohibido
    
    if informe_subido:
        return "El informe ya fue enviado anteriormente", 200
    
    try:
        fecha = START_TIME.strftime("%y%m%d%H%M")
        cuerpo_participantes_csv = generar_csv(participants)
        cuerpo_historial_csv = generar_historial_csv(historial_envios)
        
        msg = EmailMessage()
        msg["Subject"] = f"Resultados concurso {fecha}"
        msg["From"] = "odavalos@up.edu.mx"
        msg["To"] = "odavalos@up.edu.mx" # Podría ser una lista de correos
        msg.set_content("Adjunto los resultados del concurso y el historial de envíos.")

        msg.add_attachment(cuerpo_participantes_csv.encode("utf-8"), maintype="text", subtype="csv", filename=f"resultados_{fecha}.csv")
        msg.add_attachment(cuerpo_historial_csv.encode("utf-8"), maintype="text", subtype="csv", filename=f"historial_{fecha}.csv")
        
        smtp_password = os.environ.get("GMAIL_PASSWORD")
        if not smtp_password:
            logging.error("Error: Variable de entorno GMAIL_PASSWORD no configurada.")
            return "Error: No se configuró la contraseña de Gmail en el servidor.", 500
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login("odavalos@up.edu.mx", smtp_password)
            smtp.send_message(msg)
        
        informe_subido = True
        logging.info("Correo de resultados enviado con éxito.")
        return "Correo enviado con éxito", 200
    
    except Exception as e:
        app.logger.error(f"Error al enviar correo: {str(e)}", exc_info=True) # exc_info para traceback
        return f"Error al enviar el correo: {str(e)}", 500


if __name__ == "__main__":
    # Asegúrate de que eventlet.monkey_patch() se llame si realmente necesitas que Flask-SocketIO
    # use eventlet para manejar la concurrencia de forma asíncrona.
    # Si no lo haces, por defecto usará el threading de Python.
    # Para despliegues de producción, Gunicorn con Eventlet workers es común.
    eventlet.monkey_patch() # Parchear librerías estándar para que sean compatibles con eventlet

    if not problems:
        logging.critical("No se pudieron cargar los problemas. La aplicación puede no funcionar como se espera.")

    socketio.run(app, host="0.0.0.0", port=81, debug=True, use_reloader=False)
