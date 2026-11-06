"""Música y volumen: órdenes que se resuelven aquí, sin Claude, al instante y sin gastar tokens.

interpretar() solo reconoce frases completas. Lo demás ("sube el archivo a Drive",
"pon algo para estudiar") no coincide y sigue su camino hacia Claude.
"""
import asyncio
import ctypes
import os
import re
import subprocess
from urllib.parse import quote

TECLA_PLAY_PAUSA = 0xB3
TECLA_SIGUIENTE = 0xB0
TECLA_ANTERIOR = 0xB1

UNIDADES = {"uno": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9}
DECENAS = {"diez": 10, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "cero": 0, "quince": 15, "veinticinco": 25}

CANTIDAD = r"(?: un poco| un poquito| mucho| mas)?"
OBJETO = r"(?: el| la)?(?: volumen| sonido| musica)?"
BUSQUEDA = re.compile(r"(?:pon|ponme|reproduce|busca)(?: la cancion| la canción| el album| el disco| musica de| canciones de| algo de) (.+?)(?: en spotify)?")
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
    return None


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
        sistema.abrir("spotify:search:" + quote(dato))
        return f"Le dejo {dato} buscado en Spotify, señor."
    raise ValueError(accion)
