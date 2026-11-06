"""Consumo del plan: avisa cada 10 % y al terminar cada sesión o semana.

Los porcentajes vienen de Claude Code (evento rate_limit_event), no son estimaciones.
Claude Code solo los envía cuando cambian y siempre con una consulta de por medio.
El estado se guarda en disco para no repetir avisos entre arranques.
"""
import json
import os
from pathlib import Path

VENTANAS = {"five_hour": "la sesión", "seven_day": "el uso semanal"}
ANTERIOR = {"five_hour": "La sesión anterior", "seven_day": "La semana anterior"}


class Uso:
    def __init__(self, ruta):
        self.ruta = Path(ruta)
        try:
            self.estado = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.estado = {}

    def _guardar(self):
        temporal = self.ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(self.estado, indent=2), encoding="utf-8")
        os.replace(temporal, self.ruta)

    def actualizar(self, datos):
        """Recibe el contenido del evento y devuelve las frases de aviso que tocan."""
        avisos = []
        ventanas = datos.get("unifiedWindows") or {}
        if not ventanas and datos.get("rateLimitType") and datos.get("utilization") is not None:
            ventanas = {datos["rateLimitType"]: {"utilization": datos["utilization"], "resetsAt": datos.get("resetsAt")}}
        for clave, nombre in VENTANAS.items():
            v = ventanas.get(clave)
            if not v or v.get("utilization") is None:
                continue
            pct = round(v["utilization"] * 100)
            tramo = pct // 10 * 10
            previo = self.estado.get(clave)
            if previo is None:
                # Primer dato: los tramos ya pasados no se avisan.
                self.estado[clave] = {"pct": pct, "avisado": tramo, "reinicio": v.get("resetsAt")}
                continue
            if v.get("resetsAt") != previo.get("reinicio") and (v.get("resetsAt") or 0) > (previo.get("reinicio") or 0):
                avisos.append(f"{ANTERIOR[clave]} terminó en el {previo['pct']} por ciento.")
                previo["avisado"] = 0
            if tramo > previo["avisado"] and tramo > 0:
                avisos.append(f"Aviso de consumo, señor: {nombre} ha llegado al {tramo} por ciento.")
                previo["avisado"] = tramo
            previo.update(pct=pct, reinicio=v.get("resetsAt"))
        self._guardar()
        return avisos

    def resumen(self):
        sesion = self.estado.get("five_hour")
        semana = self.estado.get("seven_day")
        if not sesion or not semana:
            return "Aún no tengo datos de consumo, señor."
        return f"Lleva el {sesion['pct']} por ciento de la sesión y el {semana['pct']} por ciento del uso semanal, señor."
