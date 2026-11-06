"""Prueba Jarvis de extremo a extremo sin micrófono ni altavoces.

Genera frases con voz sintética, las baja de volumen para imitar a alguien hablando
bajo y las mete por el mismo camino que el micro real. Uso: python prueba.py [--rapida]
"""
import asyncio
import datetime
import os
import sys
import tempfile
import time
from pathlib import Path

# Las pruebas no deben mezclarse con las conversaciones reales.
os.environ["JARVIS_CONVERSACIONES"] = tempfile.mkdtemp(prefix="jarvis_conversaciones_")

import edge_tts
import miniaudio
import numpy as np

import jarvis as J
from acciones import TECLA_PLAY_PAUSA, ejecutar, interpretar
from memoria import Memoria
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
        # Lo que suena a Jarvis, incluidos errores reales de transcripción.
        ("¡Jurais!", True, ""), ("Jarbis, abre Spotify.", True, "abre Spotify"), ("Jar vis, ¿qué hora es?", True, "qué hora es"),
        ("Hola Harvis.", True, ""), ("Jervis, pausa.", True, "pausa"), ("Jarvi, pausa.", True, "pausa"),
        ("Mira Jarvis, busca vuelos.", True, "busca vuelos"), ("Bueno, pues Jarvis, abre Spotify.", True, "abre Spotify"),
        ("Busca vuelos, Jarvis, por favor.", True, "Busca vuelos"), ("Busca vuelos, Jarvis, gracias.", True, "Busca vuelos"),
        # Lo que no debe activarlo.
        ("París es muy bonita.", False, ""), ("Davis ganó ayer.", False, ""), ("Nos vemos el jueves.", False, ""),
        ("Me gusta el gris.", False, ""), ("Ya es tarde.", False, ""), ("Gracias.", False, ""), ("Hoy es lunes.", False, ""),
        ("Jamás lo haría.", False, ""), ("Las horas pasan.", False, ""), ("Chris viene mañana.", False, ""), ("¿Tú lo harías?", False, ""),
    ]
    for texto, clave, orden in casos:
        r = J.analizar_llamada(texto)
        comprobar(f"llamada {texto!r}", r == (clave, orden), str(r))
    for orden in ("dime el uso de esta sesion", "cuanto consumo llevo", "dime el uso semanal"):
        comprobar(f"consumo sin Claude {orden!r}", J.CONSUMO.search(orden) is not None)
    comprobar("«el uso de la fuerza» no es consumo", J.CONSUMO.search("explicame el uso de la fuerza") is None)
    for texto, esperado in [("Sí.", True), ("Sí, adelante", True), ("No.", False), ("No, mejor no", False), ("Sí, bueno, no", False), ("El coche", None)]:
        comprobar(f"confirmación {texto!r}", J.interpretar_confirmacion(texto) is esperado)


def pruebas_permisos():
    sin_preguntar = [
        ("Read", {"file_path": "x"}), ("WebSearch", {"query": "x"}),
        ("PowerShell", {"command": "Get-Date"}), ("PowerShell", {"command": "Get-Process | Sort-Object CPU | Select-Object -First 5"}),
        ("PowerShell", {"command": "Start-Process notepad"}), ("PowerShell", {"command": "start https://google.com"}),
        ("Write", {"file_path": str(Path(tempfile.gettempdir()) / "no_existe_jarvis.txt")}),
        ("mcp__claude_ai_Gmail__search_threads", {}),
        # Tareas complejas de solo lectura.
        ("PowerShell", {"command": 'Get-ChildItem C:\\x -Filter *.py | ForEach-Object { "$($_.Name): $((Get-Content $_.FullName).Count)" }'}),
        ("PowerShell", {"command": "Get-ChildItem -Recurse *.py | Measure-Object"}),
        ("PowerShell", {"command": "$f = Get-Content a.txt; $f.Count"}),
        ("PowerShell", {"command": "Get-Process 2>$null | Select-Object -First 3"}),
        ("PowerShell", {"command": "Get-Date\nGet-Process"}),
        ("PowerShell", {"command": "Get-Content app.js"}),
        ("PowerShell", {"command": "Get-ChildItem | Where-Object { $_.Name -like 'a-b*' }"}),
        ("PowerShell", {"command": "foreach ($f in Get-ChildItem) { $f.Name.ToUpper() }"}),
        ("PowerShell", {"command": "[math]::Round((Get-Item a).Length / 1MB, 2)"}),
        ("PowerShell", {"command": "Select-String -Path *.py -Pattern 'a|b;c'"}),
        ("PowerShell", {"command": "Start-Process notepad.exe"}),
        ("PowerShell", {"command": 'Start-Process "spotify:search:the%20killers"'}),
        ("PowerShell", {"command": "Get-ChildItem *.py | ForEach-Object { [PSCustomObject]@{ Nombre = $_.Name; Lineas = (Get-Content -LiteralPath $_.FullName).Count } } | Sort-Object Lineas"}),
        ("PowerShell", {"command": "Get-ChildItem | Select-Object Name, @{N='KB';E={$_.Length / 1KB}}"}),
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
        # Borrados y ejecuciones camuflados dentro de comandos de aspecto inofensivo.
        ("PowerShell", {"command": "Get-ChildItem | ForEach-Object { $_.Delete() }"}),
        ("PowerShell", {"command": "(Get-Item x).Delete()"}),
        ("PowerShell", {"command": "$c = 'rm'; & $c x"}),
        ("PowerShell", {"command": "$x = Remove-Item y"}),
        ("PowerShell", {"command": "$x = rm y"}),
        ("PowerShell", {"command": "[IO.File]::Delete('x')"}),
        ("PowerShell", {"command": "${C:\\x} = 'y'"}),
        ("PowerShell", {"command": "$env:PATH = 'x'"}),
        ("PowerShell", {"command": "foreach ($f in Remove-Item x) { }"}),
        ("PowerShell", {"command": 'Write-Output "$(Remove-Item x)"'}),
        ("PowerShell", {"command": "Get-Date | Out-File a"}),
        ("PowerShell", {"command": "Get-Content a | Set-Content b"}),
        ("PowerShell", {"command": "Start-Process 'powershell'"}),
        ("PowerShell", {"command": 'Start-Process ("pow" + "ershell")'}),
        ("PowerShell", {"command": "$p = 'x'; start $p"}),
        ("PowerShell", {"command": "Invoke-WebRequest http://x -Method Post"}),
        ("PowerShell", {"command": "Get-Date; iex 'x'"}),
        ("PowerShell", {"command": ". .\\x.ps1"}),
        ("PowerShell", {"command": ".\\x.bat"}),
        ("PowerShell", {"command": "C:\\malo\\notepad.exe"}),
        ("PowerShell", {"command": "start C:\\malo\\virus.exe"}),
        ("PowerShell", {"command": "Get-Date `; rm x"}),
        ("PowerShell", {"command": "New-Object -ComObject WScript.Shell"}),
        ("PowerShell", {"command": "ipconfig /release"}),
        ("PowerShell", {"command": "@{a=1}; rm = x"}),
        ("PowerShell", {"command": "Get-Date | Select-Object @{E={rm = x}}"}),
        ("PowerShell", {"command": "@{a=Remove-Item x}"}),
        ("PowerShell", {"command": "Get-Date | Select-Object @{E={Remove-Item x}}"}),
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


def pruebas_memoria():
    carpeta = Path(tempfile.mkdtemp(prefix="jarvis_memoria_")) / "sub"
    m = Memoria(carpeta)
    comprobar("memoria: sin charla no crea nada", not carpeta.exists())
    fecha = datetime.datetime(2026, 11, 3, 18, 30, 5)
    m.guardar("¿Qué es un sinónimo?", "Una palabra equivalente, señor.", fecha)
    m.guardar("Gracias", "", fecha)
    archivos = list(carpeta.glob("*.md"))
    comprobar("memoria: un archivo por sesión con su fecha", [a.name for a in archivos] == ["2026-11-03_183005.md"], str(archivos))
    texto = archivos[0].read_text(encoding="utf-8")
    comprobar("memoria: fecha legible en español", "martes 3 de noviembre de 2026" in texto, texto[:60])
    comprobar("memoria: guarda los dos turnos", "¿Qué es un sinónimo?" in texto and "Una palabra equivalente" in texto and "(sin respuesta hablada)" in texto)
    Memoria(carpeta).guardar("Otra sesión", "Vale.", fecha.replace(second=9))
    comprobar("memoria: otra sesión, otro archivo", len(list(carpeta.glob("*.md"))) == 2)


async def pruebas_peticiones_largas():
    """Con un Claude falso: nada de lo que se diga mientras trabaja debe perderse. No gasta tokens."""
    jv = J.Jarvis(J.Voz(sin_sonido=True), None)
    ordenes = []
    seguir = asyncio.Event()

    async def falso(orden):
        ordenes.append(orden)
        await seguir.wait()
        seguir.clear()

    jv._consultar = falso
    await jv.atender("Jarvis, busca un vuelo a Lisboa.")
    await asyncio.sleep(0)
    await jv.atender("Y mira el tiempo del sábado.")
    comprobar("larga: la continuación no se pierde", jv.pendientes == ["Y mira el tiempo del sábado."], str(jv.pendientes))
    seguir.set()
    await asyncio.sleep(0.01)
    comprobar("larga: se atiende después", len(ordenes) == 2 and "sábado" in ordenes[1], str(ordenes))
    jv.t_consulta = 0
    await jv.atender("Se ha ido la luz en casa de mi vecino.")
    comprobar("larga: mucho después y sin llamarle, se ignora", jv.pendientes == [], str(jv.pendientes))
    jv.voz.dicho.clear()
    await jv.atender("Jarvis.")
    comprobar("larga: si le llamas mientras trabaja, contesta", jv.voz.dicho == [J.RESP_SIGUE] and not jv.pendientes, str(jv.voz.dicho))
    jv.voz.dicho.clear()
    await jv.atender("Jarvis, abre el correo.")
    comprobar("larga: otra orden queda en cola y lo dice", jv.pendientes == ["abre el correo"] and jv.voz.dicho == [J.RESP_EN_COLA], str((jv.pendientes, jv.voz.dicho)))
    await jv.atender("Jarvis, para.")
    comprobar("larga: «para» vacía la cola", jv.pendientes == [])
    seguir.set()
    await asyncio.sleep(0.01)
    comprobar("larga: al acabar queda libre", not jv.ocupado())

    # El segmentador no corta a media explicación, pero una orden corta sigue siendo rápida.
    tono = (0.05 * np.sin(np.arange(J.SR * 6) * 0.2)).astype(np.float32)

    class VadFalso:
        def is_speech(self, pcm, sr):
            return np.abs(np.frombuffer(pcm, dtype=np.int16)).max() > 500

    def contar(x):
        s = J.Segmentador()
        s.vad = VadFalso()
        frases = 0
        fin = None
        for i in range(0, len(x) - J.TRAMA, J.TRAMA):
            if s.alimentar(x[i : i + J.TRAMA]) is not None:
                frases += 1
                fin = i / J.SR
        return frases, fin

    silencio = lambda t: np.zeros(int(J.SR * t), dtype=np.float32) + 1e-5
    voz_de = lambda t: tono[: int(J.SR * t)]
    frases, fin = contar(np.concatenate([silencio(1), voz_de(1), silencio(2)]))
    comprobar("frase corta: se cierra con 0,45 s", frases == 1 and fin < 1 + 1 + 0.6, f"{frases} {fin}")
    frases, _ = contar(np.concatenate([silencio(1), voz_de(5), silencio(0.9), voz_de(2), silencio(2)]))
    comprobar("frase larga: una pausa de 0,9 s no la corta", frases == 1, str(frases))

    # Un error en una frase no puede dejarlo sordo.
    jv = J.Jarvis(J.Voz(sin_sonido=True), None)

    class TranscriptorRoto:
        veces = 0

        def transcribir(self, audio):
            self.veces += 1
            if self.veces == 1:
                raise RuntimeError("fallo de la gráfica")
            return "Jarvis, ¿qué hora es?"

    jv.transcriptor = TranscriptorRoto()
    oidas = []

    async def atender(texto):
        oidas.append(texto)

    jv.atender = atender
    bucle = asyncio.create_task(jv.bucle_frases())
    jv.frases.put_nowait((np.zeros(10), time.monotonic()))
    jv.frases.put_nowait((np.zeros(10), time.monotonic()))
    await asyncio.sleep(0.1)
    comprobar("tras un error sigue escuchando", oidas == ["Jarvis, ¿qué hora es?"] and not bucle.done(), str(oidas))
    bucle.cancel()
    await jv.voz.esperar()


async def pruebas_senal():
    jv = J.Jarvis(J.Voz(sin_sonido=True), None)
    jv.uso = Uso(Path(tempfile.mkdtemp(prefix="jarvis_uso_")) / "uso.json")
    silencio = np.zeros(J.TRAMA, dtype=np.float32)
    voz_baja = silencio + 0.001
    for _ in range(3000):  # 90 s de silencio absoluto
        jv.vigilar_senal(silencio)
    comprobar("micro: el silencio absoluto nunca se dice en voz alta", not jv.voz.dicho, str(jv.voz.dicho))
    comprobar("micro: queda una nota en la ventana", jv.sin_senal_avisado)
    jv.vigilar_senal(voz_baja)
    comprobar("micro: la señal reinicia la cuenta", jv.tramas_sin_senal == 0)
    await jv.voz.esperar()


class SistemaFalso:
    """Registra lo que se haría, sin tocar el volumen ni la música reales."""

    def __init__(self, volumen=50, abierto=True):
        self.volumen = volumen
        self.abierto = abierto
        self.suena = True
        self.hecho = []

    def leer_volumen(self):
        return self.volumen

    def fijar_volumen(self, porcentaje):
        self.volumen = porcentaje

    def silenciar(self, activo):
        self.hecho.append(("silenciar", activo))

    def pulsar(self, tecla):
        self.hecho.append(("tecla", tecla))

    def spotify_abierto(self):
        return self.abierto

    def abrir(self, uri):
        self.hecho.append(("abrir", uri))
        self.abierto = True

    def reproducir_en_spotify(self, consulta):
        self.hecho.append(("reproducir", consulta))
        return self.suena


async def pruebas_acciones():
    reconocidas = {
        "pon algo para estudiar": ("buscar", "estudiar"), "sube el volumen": ("subir", 10), "subele un poco": ("subir", 5), "sube mucho el volumen": ("subir", 20), "sube el volumen mucho": ("subir", 20), "sube un poco el volumen": ("subir", 5), "baja un poco la musica": ("bajar", 5),
        "baja el volumen por favor": ("bajar", 10), "mas alto": ("subir", 10), "mas bajo": ("bajar", 10),
        "pon el volumen al 40": ("fijar", 40), "volumen al 40 por ciento": ("fijar", 40), "baja el volumen a treinta": ("fijar", 30),
        "pon el volumen al treinta y cinco": ("fijar", 35), "volumen 150": ("fijar", 100),
        "silencia": ("silenciar", 10), "quita el sonido": ("silenciar", 10), "activa el sonido": ("activar", 10),
        "que volumen hay": ("consultar", 10), "pausa": ("pausa", 10), "para la musica": ("pausa", 10),
        "pon musica": ("reproducir", 10), "reanuda": ("reproducir", 10), "siguiente": ("siguiente", 10), "siguiente cancion": ("siguiente", 10),
        "cambia de cancion": ("siguiente", 10), "cancion anterior": ("anterior", 10), "pon la anterior": ("anterior", 10),
        "pon musica de queen": ("buscar", "queen"), "ponme la cancion bohemian rhapsody": ("buscar", "bohemian rhapsody"),
        "pon the killers en spotify": ("buscar", "the killers"),
        # Errores de transcripción.
        "baje el volumen": ("bajar", 10), "suba el volumen": ("subir", 10), "siguientes canciones": ("siguiente", 10), "cancion anteriores": ("anterior", 10),
    }
    for frase, esperado in reconocidas.items():
        if esperado is not None:
            comprobar(f"acción {frase!r}", interpretar(frase) == esperado, str(interpretar(frase)))
    # Estas deben seguir llegando a Claude.
    for frase in ("sube el archivo a drive", "baja las notas de la web", "pon un temporizador de cinco minutos", "para", "sigue", "continua", "que hora es", "pon el pc en suspension", "busca el tiempo de mañana", "sube el resumen", "pon mucha sal", "silencia a juan", "baja el telon"):
        comprobar(f"sigue hacia Claude {frase!r}", interpretar(frase) is None, str(interpretar(frase)))

    s = SistemaFalso()
    comprobar("volumen: sube y lo dice", await ejecutar("subir", 10, s) == "Volumen al 60 por ciento, señor." and s.volumen == 60)
    s = SistemaFalso(volumen=95)
    await ejecutar("subir", 10, s)
    comprobar("volumen: no pasa de 100", s.volumen == 100, str(s.volumen))
    s = SistemaFalso(volumen=5)
    await ejecutar("bajar", 10, s)
    comprobar("volumen: no baja de 0", s.volumen == 0, str(s.volumen))
    s = SistemaFalso()
    frase = await ejecutar("silenciar", 10, s)
    comprobar("silenciar: no habla porque estaría silenciado", frase is None and s.hecho == [("silenciar", True)])
    s = SistemaFalso(abierto=True)
    await ejecutar("reproducir", 10, s)
    comprobar("música con Spotify abierto: solo pulsa", s.hecho == [("tecla", TECLA_PLAY_PAUSA)], str(s.hecho))
    s = SistemaFalso(abierto=False)
    await ejecutar("reproducir", 10, s, espera_arranque=0)
    comprobar("música con Spotify cerrado: lo abre y pulsa", s.hecho == [("abrir", "spotify:"), ("tecla", TECLA_PLAY_PAUSA)], str(s.hecho))
    s = SistemaFalso()
    frase = await ejecutar("buscar", "the killers", s)
    comprobar("reproducir: si suena no dice nada", frase is None and s.hecho == [("reproducir", "the killers")], str(s.hecho))
    s = SistemaFalso()
    s.suena = False
    frase = await ejecutar("buscar", "the killers", s)
    comprobar("reproducir: si no suena lo admite", frase is not None and "no he conseguido" in frase, str(frase))
    comprobar("permisos: reproducir no pide confirmación", clasificar("mcp__jarvis__reproducir_en_spotify", {"consulta": "x"}) is None)

    # El camino completo, desde la frase hasta la acción, sin Claude ni tokens.
    jv = J.Jarvis(J.Voz(sin_sonido=True), None)
    jv.sistema = SistemaFalso()
    await jv.atender("Jarvis, sube el volumen.")
    comprobar("orden de volumen no pasa por Claude", jv.sistema.volumen == 60 and not jv.ocupado() and jv.cliente is None, str(jv.voz.dicho))
    await jv.atender("Más alto.")
    comprobar("seguimiento: «más alto» sin repetir Jarvis", jv.sistema.volumen == 70, str(jv.sistema.volumen))
    jv.escucha_hasta = 0
    await jv.atender("Siguiente canción.")
    comprobar("sin Jarvis no cambia la canción", jv.sistema.hecho == [], str(jv.sistema.hecho))
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

    # Tarea de varios pasos: debe contar el proceso, no solo dar el resultado.
    jv.voz.dicho.clear()
    await jv.atender(f"Jarvis, mira qué archivos py hay directamente en la carpeta {J.RAIZ}, sin entrar en subcarpetas, y dime cuál tiene más líneas y qué hace.")
    await terminar(jv)
    comprobar("tarea compleja cuenta el proceso", len(jv.voz.dicho) >= 3, str(jv.voz.dicho))
    comprobar("tarea de solo lectura no pide confirmación", not any("visto bueno" in f for f in jv.voz.dicho), str(jv.voz.dicho))

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
    pruebas_memoria()
    asyncio.run(pruebas_senal())
    asyncio.run(pruebas_acciones())
    asyncio.run(pruebas_peticiones_largas())
    if "--rapida" not in sys.argv:
        asyncio.run(pruebas_completas())
    print(f"\n{'TODO OK' if not fallos else 'FALLOS: ' + str(fallos)}", flush=True)
    J.salir_del_proceso(1 if fallos else 0)
