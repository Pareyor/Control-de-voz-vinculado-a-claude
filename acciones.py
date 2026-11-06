"""Música y volumen: órdenes que se resuelven aquí, sin Claude, al instante y sin gastar tokens.

interpretar() solo reconoce frases completas. Lo demás ("sube el archivo a Drive",
"pon algo para estudiar") no coincide y sigue su camino hacia Claude.
"""
import asyncio
import difflib
import re
import unicodedata

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
    ("saltar", r".*\b(?:salta|saltar|saltate|omite|omitir|quita|quitar|pasa|pasar)\b.*\banuncios?\b.*|dale a saltar|saltar|salta"),
]
ORDEN_VIDEO = re.compile(
    r"(?:quiero que |puedes )?(?:entra|entres|entrar|abre|abras|abrir|pon|ponme|pongas|poner|reproduce|reproduzcas|dale|mete|metete|ve|vete)"
    r"(?: a| en| al)?(?: el| ese| este| aquel)? (?:video|short) (.+)"
)

# Acción que no se ha podido resolver aquí: la decide Claude.
PASAR_A_CLAUDE = object()

PALABRAS_VACIAS = {
    "video", "videos", "quiero", "que", "del", "los", "las", "una", "uno", "con", "por", "para", "pantalla", "estoy",
    "viendo", "veo", "tengo", "ahi", "ese", "este", "llama", "titulo", "dice", "titulado", "tiene", "esta", "sobre", "porfa", "favor",
}


def _normalizar(texto):
    sin_acentos = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^\w\s]", " ", sin_acentos)


def _palabras(texto):
    return [p for p in _normalizar(texto).split() if len(p) >= 3 and p not in PALABRAS_VACIAS]


def elegir_video(consulta, videos):
    """Devuelve el (título, url) que mejor encaja, tolerando errores de transcripción.
    Si ninguno encaja bien o hay dos casi iguales, devuelve None en vez de arriesgarse."""
    buscadas = _palabras(consulta)
    if not buscadas:
        return None
    puntuados = []
    for video in videos:
        del_titulo = _palabras(video[0])
        aciertos = sum(1 for p in buscadas if difflib.get_close_matches(p, del_titulo, n=1, cutoff=0.8))
        puntuados.append((aciertos / len(buscadas), video))
    puntuados.sort(key=lambda x: -x[0])
    if not puntuados or puntuados[0][0] < 0.6:
        return None
    if len(puntuados) > 1 and puntuados[0][0] - puntuados[1][0] < 0.15:
        return None
    return puntuados[0][1]


PARECIDAS = {
    "sube el volumen": "subir", "baja el volumen": "bajar", "silencia el sonido": "silenciar", "activa el sonido": "activar",
    "pon la musica": "reproducir", "pausa la musica": "pausa", "para la musica": "pausa",
    "siguiente cancion": "siguiente", "cancion anterior": "anterior", "salta el anuncio": "saltar",
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

    m = ORDEN_VIDEO.fullmatch(n)
    if m:
        return "video", m.group(1)

    m = BUSQUEDA.fullmatch(n) or BUSQUEDA_SPOTIFY.fullmatch(n)
    if m:
        return "buscar", m.group(1)

    # Transcripción con un error pequeño: "baje el volumen", "siguientes canciones".
    parecida = difflib.get_close_matches(n, PARECIDAS, n=1, cutoff=0.85)
    return (PARECIDAS[parecida[0]], 10) if parecida else None


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
    if accion == "video":
        # Sin un claro ganador en pantalla, que lo resuelva Claude: puede buscarlo y comparar.
        return None if await asyncio.to_thread(sistema.entrar_en_video, dato) else PASAR_A_CLAUDE
    if accion == "saltar":
        if await asyncio.to_thread(sistema.saltar_anuncio):
            return None
        return "No veo ningún botón de saltar, señor. Puede que este anuncio aún no se pueda omitir."
    if accion == "buscar":
        if await asyncio.to_thread(sistema.reproducir_en_spotify, dato):
            return None
        return f"Le dejo {dato} buscado en Spotify, señor, pero no he conseguido que empiece a sonar."
    raise ValueError(accion)
