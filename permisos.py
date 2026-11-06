"""Filtro de permisos de Jarvis.

Cada herramienta que Claude quiere usar pasa por clasificar(). Devuelve None si
se puede ejecutar sin preguntar, o un texto con lo que hay que confirmar por voz.
Criterio: lo que no se reconoce como seguro, se confirma.
"""
import os
import re

# Herramientas que solo leen o no tocan nada fuera de la conversación.
SIEMPRE_OK = {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite", "ToolSearch", "ListMcpResourcesTool", "ReadMcpResourceTool"}

# Primeros comandos de shell que solo consultan información o abren algo.
SHELL_OK = {
    "date", "dir", "echo", "hostname", "ipconfig", "ls", "nvidia-smi", "ping", "pwd", "systeminfo",
    "tasklist", "tree", "type", "cat", "head", "tail", "wc", "where", "whoami", "ver", "which",
    "explorer", "explorer.exe", "notepad", "notepad.exe", "calc", "calc.exe", "mspaint", "mspaint.exe",
    "start", "start-process", "saps", "invoke-item", "ii",
    "select-object", "select", "where-object", "foreach-object", "sort-object", "sort", "measure-object",
    "group-object", "format-table", "ft", "format-list", "fl", "out-string", "convertto-json",
    "test-path", "resolve-path", "split-path", "join-path", "test-connection", "write-output",
}

# Nada de esto se lanza sin preguntar, aunque vaya dentro de un comando permitido.
PELIGROSO = re.compile(
    r"powershell|pwsh|\bcmd\b|cmd\.exe|\bbash\b|\bsh\b|wscript|cscript|mshta|rundll32|regsvr32|"
    r"\bpython\w*\b|\bnode\b|\bpy\b|invoke-expression|\biex\b|-verb\s+runas|-encodedcommand|\s-enc\b|"
    r"\.(bat|cmd|ps1|vbs|js|msi|exe|com|scr|reg)\b(?<!explorer\.exe)(?<!notepad\.exe)(?<!calc\.exe)(?<!mspaint\.exe)",
    re.I,
)

# Sin esto un comando "seguro" podría escribir en disco o colar otro comando.
ESTRUCTURA_RIESGO = re.compile(r">|\$\(|`|\n|\bforeach-object\b.*\b(remove|set|stop|new|clear)-", re.I)

MCP_LECTURA = re.compile(r"(^|_)(get|list|read|search|query|find|tabs_context\w*)(_|$)", re.I)


def _segmentos(cmd):
    return [s.strip() for s in re.split(r"\|\||&&|[;|&]", cmd) if s.strip()]


def _primer_comando(seg):
    primero = seg.split()[0].strip("\"'").lower()
    return primero.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


def shell_seguro(cmd):
    # Una URL no es un ejecutable (.com). No absorbe ; & | para no esconder un segundo comando.
    cmd = re.sub(r"https?://[^\s;&|]+", "URL", cmd)
    if ESTRUCTURA_RIESGO.search(cmd) or PELIGROSO.search(cmd):
        return False
    for seg in _segmentos(cmd):
        primero = _primer_comando(seg)
        if primero not in SHELL_OK and not re.fullmatch(r"get-[a-z-]+", primero):
            return False
    return True


def clasificar(herramienta, datos):
    if herramienta in SIEMPRE_OK:
        return None

    if herramienta in ("Bash", "PowerShell"):
        cmd = datos.get("command", "")
        if shell_seguro(cmd):
            return None
        return datos.get("description") or f"ejecutar el comando {cmd[:60]}"

    if herramienta == "Write":
        ruta = datos.get("file_path", "")
        if os.path.exists(ruta):
            return f"sobrescribir el archivo {os.path.basename(ruta)}"
        return None

    if herramienta in ("Edit", "NotebookEdit"):
        return f"modificar el archivo {os.path.basename(datos.get('file_path') or datos.get('notebook_path') or '')}"

    if herramienta.startswith("mcp__"):
        accion = herramienta.rsplit("__", 1)[-1]
        if MCP_LECTURA.search(accion):
            return None
        return f"usar la acción externa {accion.replace('_', ' ')}"

    return f"usar la herramienta {herramienta}"
