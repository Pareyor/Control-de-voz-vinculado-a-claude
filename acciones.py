"""Música y volumen: órdenes que se resuelven aquí, sin Claude, al instante y sin gastar tokens.

interpretar() solo reconoce frases completas. Lo demás ("sube el archivo a Drive",
"pon algo para estudiar") no coincide y sigue su camino hacia Claude.
"""
import asyncio
import ctypes
import difflib
import os
import re
import subprocess
import time
from urllib.parse import quote

TECLA_PLAY_PAUSA = 0xB3
TECLA_SIGUIENTE = 0xB0
TECLA_ANTERIOR = 0xB1

UNIDADES = {"uno": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9}
DECENAS = {"diez": 10, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "cero": 0, "quince": 15, "veinticinco": 25}

CANTIDAD = r"(?: un poco| un poquito| mucho| mas)?"
OBJETO = r"(?: el| la)?(?: volumen| sonido| musica)?"
BUSQUEDA = re.compile(r"(?:pon|ponme|reproduce|busca)(?: la cancion| el album| el disco| musica de| musica para| canciones de| algo de| algo para) (.+?)(?: en spotify)?")
BUSQUEDA_SPOTIFY = re.compile(r"(?:pon|ponme|reproduce|busca) (.+) en spotify")

FRASES = [
    ("subir", r"(?:sube|subele|subelo|aumenta)" + CANTIDAD + OBJETO + CANTIDAD + r"|mas alto|mas volumen|mas fuerte"),
    ("bajar", r"(?:baja|bajale|bajalo|reduce)" + CANTIDAD + OBJETO + CANTIDAD + r"|mas bajo|menos volumen"),
    ("silenciar", r"silencia" + OBJETO + r"|quita(?: el)? (?:sonido|volumen)|sin sonido"),
    ("activar", r"(?:activa|devuelve|pon)(?: el)? sonido|quita el silencio"),
    ("consultar", r"(?:que|cuanto) volumen(?: hay| tengo| tenemos)?|a cuanto esta el volumen"),
    ("pausa", r"pausa(?: la)?(?: musica| cancion)?|pausar(?: la)?(?: musica| cancion)?|para la (?:musica|cancion)|deten la (?:musica|cancion)"),
    ("reproducir", r"(?:pon|reproduce|reanuda|continua|sigue con|dale a)(?: la)? (?:musica|cancion)|reanuda|play"),
    ("siguiente", r"siguiente(?: cancion| tema)?|(?:pasa|cambia)(?: de)?(?: la| esta)? (?:cancion|tema)|otra cancion"),
    ("anterior", r"anterior(?: cancion| tema)?|(?:cancion|tema) anterior|(?:vuelve a|pon) la(?: cancion)? anterior"),
]


PARECIDAS = {
    "sube el volumen": "subir", "baja el volumen": "bajar", "silencia el sonido": "silenciar", "activa el sonido": "activar",
    "pon la musica": "reproducir", "pausa la musica": "pausa", "para la musica": "pausa",
    "siguiente cancion": "siguiente", "cancion anterior": "anterior",
}


def _numero(texto):
    if texto.isdigit():
        return int(texto)
    if texto in DECENAS:
        return DECENAS[texto]
    m = re.fullmatch(r"(\w+) y (\w+)", texto)
    if m and m.group(1) in DECENAS and m.group(2) in UNIDADES:
        return DECENAS[m.group(1)] + UNIDADES[m.group(2)]
    return None


def interpretar(n):
    """Recibe la orden normalizada (minúsculas, sin acentos ni signos). Devuelve (acción, dato) o None."""
    n = re.sub(r"\s*\b(?:por favor|porfa)\b", "", n).strip()

    m = re.fullmatch(r"(?:(?:pon|ajusta|deja|sube|baja)(?: el)? )?volumen (?:al? |en )?(.+?)(?: por ciento)?", n)
    if m:
        numero = _numero(m.group(1))
        if numero is not None:
            return "fijar", max(0, min(100, numero))

    for accion, patron in FRASES:
        if re.fullmatch(patron, n):
            paso = 5 if "poco" in n or "poquito" in n else 20 if "mucho" in n else 10
            return accion, paso

    m = BUSQUEDA.fullmatch(n) or BUSQUEDA_SPOTIFY.fullmatch(n)
    if m:
        return "buscar", m.group(1)

    # Transcripción con un error pequeño: "baje el volumen", "siguientes canciones".
    parecida = difflib.get_close_matches(n, PARECIDAS, n=1, cutoff=0.85)
    return (PARECIDAS[parecida[0]], 10) if parecida else None


class Sistema:
    """Lo que toca de verdad el equipo. Las pruebas lo sustituyen para no interrumpir tu música."""

    def _volumen(self):
        import comtypes
        from comtypes import CLSCTX_ALL, POINTER, cast
        from pycaw.constants import CLSID_MMDeviceEnumerator
        from pycaw.pycaw import EDataFlow, ERole, IAudioEndpointVolume, IMMDeviceEnumerator

        comtypes.CoInitialize()
        # Se pide cada vez: la salida por defecto cambia al conectar o quitar los cascos.
        enumerador = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
        salida = enumerador.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eMultimedia.value)
        return cast(salida.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))

    def leer_volumen(self):
        return round(self._volumen().GetMasterVolumeLevelScalar() * 100)

    def fijar_volumen(self, porcentaje):
        v = self._volumen()
        v.SetMasterVolumeLevelScalar(porcentaje / 100, None)
        v.SetMute(0, None)

    def silenciar(self, activo):
        self._volumen().SetMute(1 if activo else 0, None)

    def pulsar(self, tecla):
        usuario = ctypes.WinDLL("user32")
        usuario.keybd_event(tecla, 0, 1, 0)  # KEYEVENTF_EXTENDEDKEY
        usuario.keybd_event(tecla, 0, 3, 0)  # y KEYEVENTF_KEYUP

    def spotify_abierto(self):
        salida = subprocess.run(["tasklist", "/fi", "imagename eq Spotify.exe", "/nh"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return "spotify.exe" in salida.stdout.lower()

    def abrir(self, uri):
        os.startfile(uri)

    def _ventana_spotify(self, ua):
        salida = subprocess.run(["tasklist", "/fi", "imagename eq Spotify.exe", "/nh", "/fo", "csv"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        pids = {int(m) for m in re.findall(r'"Spotify\.exe","(\d+)"', salida.stdout, re.I)}
        for v in ua.GetRootControl().GetChildren():
            if v.ProcessId in pids and v.Name and v.ClassName == "Chrome_WidgetWin_1":
                return v
        return None

    @staticmethod
    def _buscar(raiz, condicion, limite=1500):
        """Recorre los controles en orden de pantalla y devuelve el primero que cumpla la condición."""
        pendientes = [raiz]
        vistos = 0
        while pendientes and vistos < limite:
            c = pendientes.pop()
            vistos += 1
            if c is not raiz and condicion(c):
                return c
            pendientes.extend(reversed(c.GetChildren()))
        return None

    def _estado_busqueda(self, ventana):
        """Devuelve el botón de reproducir del primer resultado y una firma para saber si la página ya cambió."""
        pagina = self._buscar(ventana, lambda c: c.ControlTypeName == "GroupControl" and (c.Name or "").startswith("Spotify") and ("Buscar" in c.Name or "Search" in c.Name))
        if pagina is None:
            return None, None
        firma = []

        def es_reproducir(c):
            if c.ControlTypeName in ("HyperlinkControl", "ButtonControl") and c.Name:
                firma.append(c.Name)
            return c.ControlTypeName == "ButtonControl" and bool(re.fullmatch(r"(Reproducir|Play)( .*)?", c.Name or ""))

        boton = self._buscar(pagina, es_reproducir)
        return boton, tuple(firma)

    def _barra(self, ventana, ua):
        barra = self._buscar(ventana, lambda c: c.ControlTypeName == "GroupControl" and c.Name in ("Barra Sonando", "Now playing bar"))
        return barra

    def sonando(self, ventana):
        barra = self._barra(ventana, None)
        return barra is not None and self._buscar(barra, lambda c: c.ControlTypeName == "ButtonControl" and c.Name in ("Pausa", "Pause")) is not None

    def reproducir_en_spotify(self, consulta):
        """Abre la búsqueda y pulsa reproducir en el primer resultado. Solo devuelve True si comprueba que suena."""
        import uiautomation as ua

        with ua.UIAutomationInitializerInThread():
            ventana = self._ventana_spotify(ua)
            antes = self._estado_busqueda(ventana)[1] if ventana else None
            self.abrir("spotify:search:" + quote(consulta))
            limite = time.monotonic() + (6 if ventana else 20)  # si estaba cerrado, tarda en arrancar
            inicio = time.monotonic()
            boton = None
            while time.monotonic() < limite:
                time.sleep(0.3)
                ventana = ventana or self._ventana_spotify(ua)
                if ventana is None:
                    continue
                boton, firma = self._estado_busqueda(ventana)
                # Mientras cambia de página aún se ven los resultados anteriores. Si no cambian
                # es que se repite la misma búsqueda, y pasado un rato ya se puede pulsar.
                if boton is not None and (firma != antes or time.monotonic() - inicio > 2.5):
                    break
                boton = None
            if boton is None:
                return False
            titulo_antes, sonaba_antes = ventana.Name, self.sonando(ventana)
            boton.GetInvokePattern().Invoke()
            # "Está sonando" no basta si ya sonaba otra cosa: debe haber cambiado la canción.
            for _ in range(15):
                time.sleep(0.2)
                if self.sonando(ventana) and (not sonaba_antes or ventana.Name != titulo_antes):
                    return True
            # Sin cambios: solo vale si ya sonaba justo lo que se ha pedido.
            palabras = [p for p in consulta.lower().split() if len(p) > 3]
            return self.sonando(ventana) and any(p in ventana.Name.lower() for p in palabras)


async def ejecutar(accion, dato, sistema, espera_arranque=3.0):
    """Hace la acción y devuelve la frase que debe decir Jarvis, o None si el propio sonido ya lo deja claro."""
    if accion in ("subir", "bajar", "fijar"):
        actual = sistema.leer_volumen()
        nuevo = dato if accion == "fijar" else actual + dato if accion == "subir" else actual - dato
        nuevo = max(0, min(100, nuevo))
        sistema.fijar_volumen(nuevo)
        return f"Volumen al {nuevo} por ciento, señor."
    if accion == "consultar":
        return f"El volumen está al {sistema.leer_volumen()} por ciento, señor."
    if accion == "silenciar":
        sistema.silenciar(True)
        return None
    if accion == "activar":
        sistema.silenciar(False)
        return "Sonido activado, señor."
    if accion == "siguiente":
        sistema.pulsar(TECLA_SIGUIENTE)
        return None
    if accion == "anterior":
        sistema.pulsar(TECLA_ANTERIOR)
        return None
    if accion == "pausa":
        sistema.pulsar(TECLA_PLAY_PAUSA)
        return None
    if accion == "reproducir":
        if sistema.spotify_abierto():
            sistema.pulsar(TECLA_PLAY_PAUSA)
            return None
        sistema.abrir("spotify:")
        for _ in range(20):  # hasta 10 s
            await asyncio.sleep(0.5)
            if sistema.spotify_abierto():
                break
        await asyncio.sleep(espera_arranque)  # si se pulsa antes, Spotify no llega a recibir la tecla
        sistema.pulsar(TECLA_PLAY_PAUSA)
        return None
    if accion == "buscar":
        if await asyncio.to_thread(sistema.reproducir_en_spotify, dato):
            return None
        return f"Le dejo {dato} buscado en Spotify, señor, pero no he conseguido que empiece a sonar."
    raise ValueError(accion)
