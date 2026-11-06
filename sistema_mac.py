"""Lo que toca de verdad el equipo en macOS: volumen, Spotify y Chrome, por AppleScript.

Los datos llegan al script como argumentos, nunca pegados en su texto: un título raro no puede romperlo.
"""
import json
import re
import subprocess
import time
from urllib.parse import quote, urlsplit

from acciones import TECLA_ANTERIOR, TECLA_PLAY_PAUSA, TECLA_SIGUIENTE, elegir_video

COMANDOS_MUSICA = {TECLA_PLAY_PAUSA: "playpause", TECLA_SIGUIENTE: "next track", TECLA_ANTERIOR: "previous track"}

AVISO_JAVASCRIPT = "Chrome no deja leer la página. Hay que activar en Chrome: Ver, Opciones para desarrolladores, Permitir JavaScript desde Eventos de Apple."

ELEGIR_PESTANA = """on run argv
    tell application "Google Chrome"
        repeat with v from 1 to count of windows
            repeat with p from 1 to count of tabs of window v
                if (title of tab p of window v contains item 1 of argv) or (URL of tab p of window v contains item 1 of argv) then
                    set active tab index of window v to p
                    set index of window v to 1
                    activate
                    return "si"
                end if
            end repeat
        end repeat
    end tell
    return "no"
end run"""
CARGAR_URL = 'on run argv\ntell application "Google Chrome" to set URL of active tab of front window to item 1 of argv\nend run'
EJECUTAR_JS = 'on run argv\ntell application "Google Chrome" to return execute active tab of front window javascript (item 1 of argv)\nend run'
ESTADO_SPOTIFY = 'tell application "Spotify" to return (player state as string) & "|" & (spotify url of current track) & "|" & (name of current track) & " " & (artist of current track)'
PLAY_SPOTIFY = 'on run argv\ntell application "Spotify" to play track (item 1 of argv)\nend run'

JS_VIDEOS = """JSON.stringify((() => {
    const vistos = new Map();
    for (const a of document.querySelectorAll('a[href*="/watch?"], a[href*="/shorts/"]')) {
        const titulo = (a.getAttribute('title') || a.textContent || a.getAttribute('aria-label') || '').trim();
        if (titulo && a.offsetParent !== null && !vistos.has(a.href)) vistos.set(a.href, titulo);
    }
    return [...vistos].map(([url, titulo]) => [titulo, url]);
})())"""
JS_SALTAR = """(() => {
    const es = b => /^(saltar|omitir|skip)( anuncios?| ads?)?$/i.test((b.textContent || b.getAttribute('aria-label') || '').trim());
    const boton = [...document.querySelectorAll('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, #movie_player button')].find(es);
    if (boton) boton.click();
    return boton ? 'si' : 'no';
})()"""


def _applescript(script, *argumentos):
    r = subprocess.run(["osascript", "-", *argumentos], input=script, capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def _proceso_abierto(nombre):
    return subprocess.run(["pgrep", "-x", nombre], capture_output=True).returncode == 0


class Sistema:
    """Misma interfaz que el Sistema de Windows. Las pruebas lo sustituyen para no interrumpir tu música."""

    def leer_volumen(self):
        return int(_applescript("output volume of (get volume settings)"))

    def fijar_volumen(self, porcentaje):
        _applescript(f"set volume output volume {int(porcentaje)} without output muted")

    def silenciar(self, activo):
        _applescript(f"set volume {'with' if activo else 'without'} output muted")

    def pulsar(self, tecla):
        """macOS no deja simular las teclas multimedia sin permisos: se le pide a la app que esté abierta."""
        for app in ("Spotify", "Music"):
            if _proceso_abierto(app):
                _applescript(f'tell application "{app}" to {COMANDOS_MUSICA[tecla]}')
                return

    def spotify_abierto(self):
        return _proceso_abierto("Spotify")

    def abrir(self, uri):
        subprocess.run(["open", uri], check=True)

    def _elegir_pestana(self, buscado):
        return _proceso_abierto("Google Chrome") and _applescript(ELEGIR_PESTANA, buscado) == "si"

    def abrir_web(self, sitio, url):
        """Cambia a una pestaña de Chrome de ese sitio si ya existe; si no, abre la web."""
        if self._elegir_pestana(sitio):
            partes = urlsplit(url)
            if partes.path in ("", "/") and not partes.query:  # solo el sitio: ya estamos en él
                return f"He cambiado a la pestaña de {sitio} que ya estaba abierta."
            _applescript(CARGAR_URL, url)
            return f"He cargado esa dirección en la pestaña de {sitio} que ya estaba abierta."
        self.abrir(url)
        return "La he abierto en una pestaña nueva."

    def _js_en_youtube(self, codigo):
        """Ejecuta JavaScript en la pestaña de YouTube. Devuelve None si no hay ninguna."""
        if not self._elegir_pestana("youtube.com"):
            return None
        try:
            return _applescript(EJECUTAR_JS, codigo)
        except RuntimeError as e:
            if "JavaScript" in str(e):  # desactivado en Chrome por defecto
                raise RuntimeError(AVISO_JAVASCRIPT) from e
            raise

    def videos_en_pantalla(self):
        """Lista de (título, url) de los vídeos que hay en la página de YouTube."""
        salida = self._js_en_youtube(JS_VIDEOS)
        if not salida:
            return []
        return [(re.sub(r"\s+(\d+ (horas?|minutos?|segundos?)( y \d+ (minutos?|segundos?))?)$", "", t), u) for t, u in json.loads(salida)]

    def entrar_en_video(self, consulta):
        """Abre en la misma pestaña el vídeo en pantalla que mejor encaje. Devuelve su título, o None."""
        elegido = elegir_video(consulta, self.videos_en_pantalla())
        if elegido is None:
            return None
        _applescript(CARGAR_URL, elegido[1])
        return elegido[0]

    def saltar_anuncio(self):
        """Pulsa el botón de saltar del reproductor, esperando unos segundos a que aparezca."""
        limite = time.monotonic() + 7
        while time.monotonic() < limite:
            salida = self._js_en_youtube(JS_SALTAR)
            if salida is None:
                return False
            if salida == "si":
                return True
            time.sleep(0.5)
        return False

    def _estado_spotify(self):
        """Devuelve (estado, url de la canción, nombre y artista), o Nones si aún no responde."""
        try:
            estado, url, nombre = _applescript(ESTADO_SPOTIFY).split("|", 2)
            return estado, url, nombre.lower()
        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
            return None, None, ""

    def reproducir_en_spotify(self, consulta):
        """Abre la búsqueda y le pide que la reproduzca. Solo devuelve True si comprueba que suena."""
        estaba_abierto = self.spotify_abierto()
        antes = self._estado_spotify()[1] if estaba_abierto else None
        self.abrir("spotify:search:" + quote(consulta))
        time.sleep(1 if estaba_abierto else 6)  # si estaba cerrado, tarda en arrancar
        try:
            _applescript(PLAY_SPOTIFY, "spotify:search:" + quote(consulta))
        except (RuntimeError, subprocess.TimeoutExpired):
            return False
        # "Está sonando" no basta si ya sonaba otra cosa: debe haber cambiado la canción.
        for _ in range(15):
            time.sleep(0.2)
            estado, url, _nombre = self._estado_spotify()
            if estado == "playing" and url != antes:
                return True
        # Sin cambios: solo vale si ya sonaba justo lo que se ha pedido.
        estado, _url, nombre = self._estado_spotify()
        palabras = [p for p in consulta.lower().split() if len(p) > 3]
        return estado == "playing" and any(p in nombre for p in palabras)
