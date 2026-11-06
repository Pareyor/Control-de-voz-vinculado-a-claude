"""Filtro de permisos de Jarvis.

Cada herramienta que Claude quiere usar pasa por clasificar(). Devuelve None si
se puede ejecutar sin preguntar, o un texto con lo que hay que confirmar por voz.
Criterio: lo que no se reconoce como seguro, se confirma.
"""
import os
import re

# Herramientas que solo leen o no tocan nada fuera de la conversación.
SIEMPRE_OK = {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite", "ToolSearch", "ListMcpResourcesTool", "ReadMcpResourceTool", "mcp__jarvis__reproducir_en_spotify", "mcp__jarvis__abrir_web", "mcp__jarvis__ver_videos_en_pantalla", "mcp__jarvis__entrar_en_video", "mcp__jarvis__saltar_anuncio","mcp__claude-in-chrome__navigate", "mcp__claude-in-chrome__tabs_create_mcp"}

# Comandos de shell que solo consultan información, filtran resultados o abren algo.
SHELL_OK = {
    "date", "dir", "echo", "hostname", "ipconfig", "ls", "nvidia-smi", "ping", "pwd", "systeminfo",
    "tasklist", "tree", "type", "cat", "head", "tail", "wc", "where", "whoami", "ver", "which", "findstr",
    "explorer", "explorer.exe", "notepad", "notepad.exe", "calc", "calc.exe", "mspaint", "mspaint.exe", "chrome", "chrome.exe",
    "start", "start-process", "saps", "invoke-item", "ii",
    "select-object", "select", "where-object", "?", "foreach-object", "%", "sort-object", "sort", "measure-object",
    "group-object", "format-table", "ft", "format-list", "fl", "out-string", "out-null", "convertto-json",
    "select-string", "sls", "test-path", "resolve-path", "split-path", "join-path", "test-connection",
    "write-output", "write-host", "if", "else", "elseif", "foreach", "for", "while",
}
ABRIR = {"start", "start-process", "saps", "invoke-item", "ii"}
EJECUTABLES_OK = {"explorer.exe", "notepad.exe", "calc.exe", "mspaint.exe", "chrome.exe"}

# Intérpretes o elevación: nunca sin preguntar, aunque vayan dentro de un comando permitido.
# El lookbehind evita confundir "*.py" o "C:\bash\x" con lanzar el programa.
INTERPRETE = re.compile(
    r"(?<![.\\/\w-])(powershell|pwsh|cmd|bash|sh|wscript|cscript|mshta|rundll32|regsvr32|python\w*|py|node|iex|invoke-expression)(\.exe)?\b"
    r"|-verb\s+runas|-encodedcommand|\s-enc\b|\bipconfig\s+/(release|renew)|\bsort\b.*\s-o\b",
    re.I,
)
EXTENSION_EJECUTABLE = re.compile(r"[\w-]+\.(bat|cmd|ps1|vbs|js|msi|exe|com|scr|reg)\b", re.I)
REDIRECCION_INOFENSIVA = re.compile(r"\s*2>\s*(\$null|&1|nul)\b", re.I)
SEPARADORES = re.compile(r"\|\||&&|[;|\n(){}=]")
INICIO_EXPRESION = "$@[0123456789-,+*/!"
VERBO_NOMBRE = re.compile(r"\b[a-z]+-[a-z]+\b", re.I)
METODOS_OK = {"tostring", "trim", "trimend", "trimstart", "replace", "split", "substring", "tolower", "toupper", "contains", "startswith", "endswith", "indexof", "gettype", "join"}
ESTATICOS_OK = {"math", "string", "datetime", "char", "int"}

MCP_LECTURA = re.compile(r"(^|_)(get|list|read|search|query|find|tabs_context\w*)(_|$)", re.I)


def _quitar_cadenas(cmd):
    """Quita el texto literal: lo único ejecutable dentro de una cadena es $(...) en comillas dobles."""
    salida = []
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if c == "'":
            fin = cmd.find("'", i + 1)
            i = len(cmd) if fin < 0 else fin + 1
            salida.append(" ")
        elif c == '"':
            i += 1
            while i < len(cmd) and cmd[i] != '"':
                if cmd.startswith("$(", i):
                    nivel = 0
                    inicio = i
                    i += 1
                    while i < len(cmd):
                        nivel += (cmd[i] == "(") - (cmd[i] == ")")
                        i += 1
                        if nivel == 0:
                            break
                    salida.append(" " + cmd[inicio:i].replace('"', " ") + " ")
                else:
                    i += 1
            i += 1
        else:
            salida.append(c)
            i += 1
    return "".join(salida)


def _quitar_claves(cmd):
    """En @{ Nombre = valor } la clave no es un comando. Solo se quita en el primer nivel:
    dentro de un bloque { } anidado, "rm = x" sí ejecutaría rm."""
    salida = []
    i = 0
    while i < len(cmd):
        if not cmd.startswith("@{", i):
            salida.append(cmd[i])
            i += 1
            continue
        salida.append("@{ ")
        i += 2
        nivel = 1
        inicio_valor = True  # justo tras "@{" o ";" de primer nivel es donde va una clave
        while i < len(cmd) and nivel:
            clave = re.match(r"\s*[a-z_]\w*\s*=(?!=)", cmd[i:], re.I) if inicio_valor and nivel == 1 else None
            if clave:
                i += clave.end()
                inicio_valor = False
                continue
            c = cmd[i]
            nivel += (c == "{") - (c == "}")
            inicio_valor = c == ";" and nivel == 1
            salida.append(c)
            i += 1
    return "".join(salida)


def _comando_conocido(palabra):
    palabra = palabra.lower()
    return palabra in SHELL_OK or re.fullmatch(r"get-[a-z-]+", palabra) is not None


def _segmento_seguro(seg):
    # ".Count" tras un paréntesis lee una propiedad; ". x.ps1" y ".\x.bat" no entran aquí y se confirman.
    if seg[0] in INICIO_EXPRESION or re.match(r"\.[a-z_]\w*(\s|$)", seg, re.I):
        # Una expresión no puede esconder comandos: "$x in Remove-Item" o "$_ Remove-Item y".
        if any(not _comando_conocido(m) for m in VERBO_NOMBRE.findall(seg)):
            return False
        destino = re.search(r"\bin\s+([^\s$]\S*)", seg, re.I)
        return destino is None or _comando_conocido(destino.group(1))
    return _comando_conocido(seg.split()[0])


def shell_seguro(cmd):
    # Una URL no es un ejecutable (.com). Entre comillas puede llevar & (?a=1&b=2), salvo en comillas
    # dobles con $ o `, que sí se evalúan. Sin comillas no absorbe ; & | para no esconder otro comando.
    cmd = re.sub(r"""'https?://[^']*'|"https?://[^"$`]*\"""", "URL", cmd)
    cmd = REDIRECCION_INOFENSIVA.sub(" ", re.sub(r"""https?://[^\s;&|$`()"']+""", "URL", cmd))
    if INTERPRETE.search(cmd):
        return False

    limpio = _quitar_claves(_quitar_cadenas(cmd))
    if ">" in limpio or "`" in limpio or "${" in limpio or re.search(r"\$env:\w+\s*\+?=", limpio, re.I):
        return False
    if re.search(r"(?<!&)&(?!&)", limpio):  # operador de llamada: "& $x" ejecuta lo que sea
        return False
    if any(m.lower() not in METODOS_OK for m in re.findall(r"\.(\w+)\s*\(", limpio)):  # p. ej. $_.Delete()
        return False
    if any(m.lower() not in ESTATICOS_OK for m in re.findall(r"\[([\w.]+)\]\s*::", limpio)):  # p. ej. [IO.File]::Delete
        return False

    segmentos = [s.strip() for s in SEPARADORES.split(limpio) if s.strip()]
    if not all(_segmento_seguro(s) for s in segmentos):
        return False

    # Abrir algo: el destino debe estar escrito tal cual y no ser un ejecutable desconocido.
    if any(s.split()[0].lower() in ABRIR for s in segmentos if s[0] not in INICIO_EXPRESION):
        if re.search(r"[$(+]", cmd):
            return False
        if any(m.group(0).lower() not in EJECUTABLES_OK for m in EXTENSION_EJECUTABLE.finditer(cmd)):
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
