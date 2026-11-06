"""Guarda las conversaciones de Jarvis en texto, un archivo por sesión.

Claude los consulta con sus herramientas de búsqueda cuando se le pide recordar algo,
así que guardarlas no gasta tokens: solo se gastan al leerlas.
"""
import datetime
from pathlib import Path

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


class Memoria:
    def __init__(self, carpeta):
        self.carpeta = Path(carpeta)
        self.archivo = None  # se crea con el primer turno: una sesión sin charla no deja rastro

    def guardar(self, orden, respuesta, ahora=None):
        """Añade un turno y lo escribe en el acto, para no perderlo si el programa se cierra."""
        ahora = ahora or datetime.datetime.now()
        if self.archivo is None:
            self.carpeta.mkdir(parents=True, exist_ok=True)
            self.archivo = self.carpeta / f"{ahora:%Y-%m-%d_%H%M%S}.md"
            fecha = f"{DIAS[ahora.weekday()]} {ahora.day} de {MESES[ahora.month - 1]} de {ahora.year}"
            self.archivo.write_text(f"# Conversación del {fecha}, a las {ahora:%H:%M}\n", encoding="utf-8")
        with self.archivo.open("a", encoding="utf-8") as f:
            f.write(f"\n[{ahora:%H:%M}] Usuario: {orden}\n[{ahora:%H:%M}] Jarvis: {respuesta or '(sin respuesta hablada)'}\n")
