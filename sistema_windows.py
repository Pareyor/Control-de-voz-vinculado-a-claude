"""Lo que toca de verdad el equipo en Windows: volumen, teclas multimedia, Spotify y Chrome."""
import ctypes
import os
import re
import subprocess
import time
from urllib.parse import quote, urlsplit

from acciones import elegir_video


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

    @staticmethod
    def _pids(programa):
        salida = subprocess.run(["tasklist", "/fi", f"imagename eq {programa}", "/nh", "/fo", "csv"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return {int(m) for m in re.findall(rf'"{re.escape(programa)}","(\d+)"', salida.stdout, re.I)}

    def abrir_web(self, sitio, url):
        """Cambia a una pestaña de Chrome de ese sitio si ya existe; si no, abre la web."""
        import uiautomation as ua

        buscado = sitio.lower()
        with ua.UIAutomationInitializerInThread():
            pids = self._pids("chrome.exe")
            ventanas = [v for v in ua.GetRootControl().GetChildren() if v.ProcessId in pids and v.ClassName == "Chrome_WidgetWin_1" and v.Name]
            for v in ventanas:
                pestana = self._buscar(v, lambda c: c.ControlTypeName == "TabItemControl" and buscado in (c.Name or "").lower(), limite=800, desde_el_final=True)
                if pestana is not None:
                    v.SetActive()
                    pestana.GetSelectionItemPattern().Select()
                    partes = urlsplit(url)
                    if partes.path in ("", "/") and not partes.query:  # solo el sitio: ya estamos en él
                        return f"He cambiado a la pestaña de {sitio} que ya estaba abierta."
                    time.sleep(0.2)
                    if self._ir_a(v, url, ua):
                        return f"He cargado esa dirección en la pestaña de {sitio} que ya estaba abierta."
                    break
        self.abrir(url)
        return "La he abierto en una pestaña nueva."

    def _ventana_youtube(self, ua):
        """La ventana de Chrome con YouTube a la vista. Las pestañas de fondo no exponen su página."""
        pids = self._pids("chrome.exe")
        for v in ua.GetRootControl().GetChildren():
            if v.ProcessId not in pids or v.ClassName != "Chrome_WidgetWin_1" or not v.Name:
                continue
            if "youtube" in v.Name.lower():
                return v
            pestana = self._buscar(v, lambda c: c.ControlTypeName == "TabItemControl" and "youtube" in (c.Name or "").lower(), limite=800, desde_el_final=True)
            if pestana is not None:
                v.SetActive()
                pestana.GetSelectionItemPattern().Select()
                time.sleep(0.6)
                return v
        return None

    def videos_en_pantalla(self):
        """Lista de (título, url) de los vídeos que hay en la página de YouTube."""
        import uiautomation as ua

        with ua.UIAutomationInitializerInThread():
            ventana = self._ventana_youtube(ua)
            if ventana is None:
                return []
            videos, vistos, pendientes, recorridos = [], set(), [ventana], 0
            while pendientes and recorridos < 6000:
                c = pendientes.pop()
                recorridos += 1
                if c.ControlTypeName == "HyperlinkControl" and c.Name:
                    try:
                        url = c.GetValuePattern().Value
                    except Exception:
                        url = ""
                    if re.match(r"https://(www\.)?youtube\.com/(watch\?|shorts/)", url) and url not in vistos:
                        vistos.add(url)
                        videos.append((re.sub(r"\s+(\d+ (horas?|minutos?|segundos?)( y \d+ (minutos?|segundos?))?)$", "", c.Name), url))
                pendientes.extend(reversed(c.GetChildren()))
            return videos

    def entrar_en_video(self, consulta):
        """Abre en la misma pestaña el vídeo en pantalla que mejor encaje. Devuelve su título, o None."""
        import uiautomation as ua

        elegido = elegir_video(consulta, self.videos_en_pantalla())
        if elegido is None:
            return None
        with ua.UIAutomationInitializerInThread():
            ventana = self._ventana_youtube(ua)
            if ventana is None:
                return None
            ventana.SetActive()
            return elegido[0] if self._ir_a(ventana, elegido[1], ua) else None

    def saltar_anuncio(self):
        """Pulsa el botón de saltar del reproductor, esperando unos segundos a que aparezca."""
        import uiautomation as ua

        def es_saltar(c):
            nombre = (c.Name or "").lower()
            if c.ControlTypeName != "ButtonControl" or "naveg" in nombre or "navig" in nombre:  # "Saltar navegación" es otra cosa
                return False
            return re.fullmatch(r"(saltar|omitir|skip)( anuncios?| ads?)?", nombre.strip()) is not None

        with ua.UIAutomationInitializerInThread():
            ventana = self._ventana_youtube(ua)
            if ventana is None:
                return False
            limite = time.monotonic() + 7
            while time.monotonic() < limite:
                boton = self._buscar(ventana, es_saltar, limite=6000)
                if boton is not None:
                    boton.GetInvokePattern().Invoke()
                    return True
                time.sleep(0.5)
            return False

    def _ir_a(self, ventana, url, ua):
        """Escribe la dirección en la barra de Chrome. Devuelve False si no la encuentra."""
        barra = self._buscar(
            ventana,
            lambda c: c.ControlTypeName == "EditControl" and any(p in (c.Name or "").lower() for p in ("address", "direcciones", "dirección")),
            limite=800,
            desde_el_final=True,
        )
        if barra is None:
            return False
        barra.SetFocus()
        barra.GetValuePattern().SetValue(url)
        ua.SendKeys("{Enter}", waitTime=0)
        return True

    def _ventana_spotify(self, ua):
        pids = self._pids("Spotify.exe")
        for v in ua.GetRootControl().GetChildren():
            if v.ProcessId in pids and v.Name and v.ClassName == "Chrome_WidgetWin_1":
                return v
        return None

    @staticmethod
    def _buscar(raiz, condicion, limite=1500, desde_el_final=False):
        """Recorre los controles en orden de pantalla y devuelve el primero que cumpla la condición.
        En Chrome las pestañas van al final del árbol y el contenido de la página, enorme, antes."""
        pendientes = [raiz]
        vistos = 0
        while pendientes and vistos < limite:
            c = pendientes.pop()
            vistos += 1
            if c is not raiz and condicion(c):
                return c
            hijos = c.GetChildren()
            pendientes.extend(hijos if desde_el_final else reversed(hijos))
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
