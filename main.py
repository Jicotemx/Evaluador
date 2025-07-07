<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8" />
    <title>Evaluador ICPC Mejorado</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 900px; margin: auto; padding: 20px; }
        h1 { text-align: center; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: center; }
        th { background-color: #f4f4f4; }
        #statusMsg { font-size: 1.2em; margin-bottom: 10px; text-align: center; }
        #timer { font-weight: bold; font-size: 1.4em; margin-bottom: 20px; text-align: center; }
        .disabled { opacity: 0.5; pointer-events: none; }
        .correct { color: green; font-weight: bold; }
        .wrong { color: red; font-weight: bold; }
    </style>
</head>
<body>
    <h1>Evaluador ICPC Mejorado</h1>
    <div id="statusMsg"></div>
    <div id="timer"></div>

    <form id="submitForm">
        <label>Nombre: <input type="text" id="name" required /></label>
        <label>Problema:
            <select id="problem" required>
                <option value="A">A</option>
                <option value="B">B</option>
                <option value="C">C</option>
            </select>
        </label>
        <label>Respuesta: <input type="text" id="answer" required /></label>
        <button type="submit">Enviar</button>
    </form>

    <table id="rankingTable">
        <thead>
            <tr>
                <th>Participante</th>
                <th>Puntaje</th>
                <th>Penalización</th>
                <th>A</th>
                <th>B</th>
                <th>C</th>
                <th>Intentos A</th>
                <th>Intentos B</th>
                <th>Intentos C</th>
            </tr>
        </thead>
        <tbody>
            <!-- Se llena dinámicamente -->
        </tbody>
    </table>

<script>
    const statusMsg = document.getElementById("statusMsg");
    const timerElem = document.getElementById("timer");
    const form = document.getElementById("submitForm");
    const rankingBody = document.querySelector("#rankingTable tbody");

    let status = "";
    let startTime = null;
    let durationSeconds = null;

    function secondsToHMS(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return `${h.toString().padStart(2,"0")}:${m.toString().padStart(2,"0")}:${s.toString().padStart(2,"0")}`;
    }

    async function fetchStatus() {
        try {
            const res = await fetch("/status");
            const data = await res.json();
            status = data.status;
            const elapsed = Math.floor(data.time);
            return { status, elapsed };
        } catch(e) {
            statusMsg.textContent = "Error conectando con el servidor.";
            return null;
        }
    }

    async function fetchRanking() {
        try {
            const res = await fetch("/ranking");
            const data = await res.json();
            return data;
        } catch(e) {
            console.error("Error al cargar ranking", e);
            return [];
        }
    }

    function updateFormAndStatus(status, elapsed) {
        if(status === "before") {
            statusMsg.textContent = "El concurso comenzará pronto.";
            timerElem.textContent = `Tiempo para inicio: ${secondsToHMS(Math.max(0, Math.floor((startTimeEpoch - Date.now()/1000))))}`;
            form.classList.add("disabled");
        } else if(status === "running") {
            statusMsg.textContent = "Concurso en curso";
            timerElem.textContent = `Tiempo transcurrido: ${secondsToHMS(elapsed)}`;
            form.classList.remove("disabled");
        } else if(status === "after") {
            statusMsg.textContent = "Concurso finalizado.";
            timerElem.textContent = "";
            form.classList.add("disabled");
        }
    }

    async function updateRankingTable() {
        const ranking = await fetchRanking();
        rankingBody.innerHTML = "";
        for(const p of ranking) {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${p.name}</td>
                <td>${p.score}</td>
                <td>${p.penalty}</td>
                <td class="${p.status.A === '✔' ? 'correct' : p.status.A === '✖' ? 'wrong' : ''}">${p.status.A || ''}</td>
                <td class="${p.status.B === '✔' ? 'correct' : p.status.B === '✖' ? 'wrong' : ''}">${p.status.B || ''}</td>
                <td class="${p.status.C === '✔' ? 'correct' : p.status.C === '✖' ? 'wrong' : ''}">${p.status.C || ''}</td>
                <td>${p.attempts.A}</td>
                <td>${p.attempts.B}</td>
                <td>${p.attempts.C}</td>
            `;
            rankingBody.appendChild(tr);
        }
    }

    form.addEventListener("submit", async e => {
        e.preventDefault();
        if(form.classList.contains("disabled")) return;

        const name = document.getElementById("name").value.trim();
        const problem = document.getElementById("problem").value;
        const answer = document.getElementById("answer").value.trim();

        if(!name || !answer) return alert("Completa todos los campos.");

        const res = await fetch("/submit", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: `name=${encodeURIComponent(name)}&problem=${encodeURIComponent(problem)}&answer=${encodeURIComponent(answer)}`
        });
        const data = await res.json();

        alert(data.message || "Respuesta enviada.");
        document.getElementById("answer").value = "";
        updateRankingTable();
    });

    // Inicialización
    let startTimeEpoch = null;
    async function init() {
        // Para obtener start_time y duration (desde Flask)
        const htmlStart = "{{ start_time }}";  // Ejemplo: "14:03:00"
        const htmlDuration = {{ duration }};   // segundos

        // Convierte hora local a epoch para usar en JS (ajustamos hoy)
        const [h,m,s] = htmlStart.split(":").map(Number);
        const now = new Date();
        const startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m, s);
        startTimeEpoch = startDate.getTime()/1000;
        durationSeconds = htmlDuration;

        // Actualiza cada segundo
        setInterval(async () => {
            const st = await fetchStatus();
            if(!st) return;
            updateFormAndStatus(st.status, Math.floor(st.elapsed));
            updateRankingTable();
        }, 5000);

        // Actualiza tabla inmediatamente y status
        const st = await fetchStatus();
        if(st) updateFormAndStatus(st.status, Math.floor(st.elapsed));
        updateRankingTable();
    }

    window.onload = init;
</script>
</body>
</html>
