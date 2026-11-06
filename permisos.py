"""Filtro de permisos de Jarvis.

Cada herramienta que Claude quiere usar pasa por clasificar(). Devuelve None si
se ejecuta sin preguntar, o un texto con lo que hay que confirmar por voz.

Criterio, elegido por el usuario: todo se hace directamente salvo lo importante, es decir,
lo que no se puede deshacer: borrar o machacar datos, cambios graves del sistema y enviar
cosas a otras personas. También lo que no se puede inspeccionar y podría esconder lo anterior.
"""
import os
import re
from pathlib import Path

# Órdenes que borran o dañan, cuando aparecen como comando.
COMANDOS_DELICADOS = {
    "rm", "ri", "del", "erase", "rd", "rmdir", "remove-item", "clear-content", "clear-item", "clear-recyclebin", "remove-itemproperty",
    "format", "format-volume", "diskpart", "clear-disk", "remove-partition", "initialize-disk", "cipher", "sdelete", "vssadmin", "dd", "shred",
    "shutdown", "stop-computer", "restart-computer", "logoff", "uninstall-package", "remove-appxpackage", "uninstall-module",
    "send-mailmessage",
    "trash", "srm", "truncate", "halt", "reboot", "poweroff",  # macOS
}

# Delante de la orden real, sin cambiar lo que hace: "sudo rm x" sigue siendo borrar.
PREFIJOS = {"sudo", "command", "builtin", "env", "nohup", "exec", "time", "xargs"}

# Inconfundibles aunque vayan dentro de un script o de otra orden entre comillas.
BORRADO_EN_CUALQUIER_SITIO = re.compile(
    r"remove-item|remove-itemproperty|clear-content|clear-recyclebin|format-volume|clear-disk|remove-partition|"
    r"os\.(remove|unlink|rmdir|removedirs)|shutil\.rmtree|\.unlink\s*\(|\brmtree\b|\.delete\s*\(|::\s*delete|invokeverb|"
    r"fs\.(unlink|rm|rmdir)|git\s+clean\b|git\s+reset\s+--hard|git\s+push\b[^;|&]*(--force|\s-f\b)|"
    r"\b(winget|choco|pip|npm|msiexec|brew)\b[^;|&]*\s(uninstall|remove|rm|/x)\b|\breg(\.exe)?\s+delete\b|\bwmic\b[^;|&]*\bdelete\b|"
    r"shutdown(\.exe)?\s+/|remove-appxpackage|send-mailmessage|"
    r"\bfind\b[^;|&]*\s(-delete\b|-exec(dir)?\s+\S*rm\b)|\bdiskutil\s+(erase|reformat|partition|secureerase|apfs\s+delete)|"
    r"\bosascript\b.*\b(delete|empty trash|send|shut down|restart|log out)\b",
    re.I,
)

# Cuando una orden lanza a otra, su contenido entre comillas también se ejecuta.
LANZADOR = re.compile(r"(?<![.\\/\w-])(powershell|pwsh|cmd|bash|zsh|sh|wsl|start-process|saps|start)(\.exe)?\b", re.I)
BORRADO_CORTO = re.compile(r"(?<![\w.-])(rm|ri|del|erase|rd|rmdir|format)(?![\w.-])", re.I)

# Lo que no se puede leer antes de ejecutarlo.
OPACO = re.compile(
    r"-encodedcommand|\s-enc\b|\s-e\s+[a-z0-9+/=]{20,}|(?<![\w-])(iex|invoke-expression|mshta|regsvr32|rundll32)(?![\w-])|"
    r"\|\s*(bash|zsh|sh|pwsh|powershell|cmd|python\w*|node)\b",
    re.I,
)

SEPARADORES = re.compile(r"\|\||&&|[;|\n(){}=`&]|%\s*\{")
# Escribir un archivo entero: crear uno nuevo es normal; solo preocupa si ya existe.
DESTINO_ESCRITURA = re.compile(
    r"""(?:(?<![\d>])>(?!>)|\b(?:set-content|out-file|tee-object)\b(?:\s+-(?:literal)?(?:file)?path)?)\s+["']?([^\s"'|;&$()]+)""",
    re.I,
)

# Acciones externas que no se pueden deshacer o llegan a otras personas.
MCP_DELICADO = re.compile(r"delete|trash|remove|send|forward|reply|share|purchase|pay|buy", re.I)


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


def _machaca_archivo(cmd):
    """True si escribe sobre un archivo que ya existe, cuando la ruta está escrita tal cual.
    Claude trabaja desde la carpeta de usuario, y con una variable no se puede saber el destino."""
    for m in DESTINO_ESCRITURA.finditer(cmd):
        destino = m.group(1)
        if destino.lower() not in ("nul", "null") and not destino.startswith("-") and (Path.home() / Path(destino).expanduser()).is_file():
            return True
    return False


def _orden_real(palabras):
    """La orden que se ejecuta de verdad, sin prefijos como sudo ni la carpeta donde está."""
    for i, palabra in enumerate(palabras):
        palabra = palabra.strip("&").lower()
        if palabra in PREFIJOS or (i > 0 and palabra.startswith("-")):
            continue
        return palabra.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].removesuffix(".exe")
    return ""


def shell_delicado(cmd):
    """True si el comando borra, daña o no se puede inspeccionar. Lo demás se ejecuta sin preguntar."""
    # El texto de una dirección web no son órdenes (buscar "del rubius" no es borrar), salvo que lleve $ o `.
    cmd = re.sub(r"""'https?://[^']*'|"https?://[^"$`]*\"""", "URL", cmd)
    cmd = re.sub(r"""https?://[^\s;&|$`()"']+""", "URL", cmd)

    if OPACO.search(cmd) or BORRADO_EN_CUALQUIER_SITIO.search(cmd):
        return True
    if LANZADOR.search(cmd) and BORRADO_CORTO.search(cmd):
        return True

    limpio = _quitar_cadenas(cmd)
    if _machaca_archivo(cmd) or re.search(r"(?<!&)&\s*[$(]", limpio):  # "& $x" ejecuta lo que sea
        return True
    for segmento in SEPARADORES.split(limpio):
        if _orden_real(segmento.split()) in COMANDOS_DELICADOS:
            return True
    return False


def clasificar(herramienta, datos):
    if herramienta in ("Bash", "PowerShell"):
        cmd = datos.get("command", "")
        if not shell_delicado(cmd):
            return None
        return datos.get("description") or f"ejecutar el comando {cmd[:60]}"

    if herramienta == "Write":
        ruta = datos.get("file_path", "")
        return f"sobrescribir el archivo {os.path.basename(ruta)}" if os.path.exists(ruta) else None

    if herramienta.startswith("mcp__") and not herramienta.startswith("mcp__jarvis__"):
        accion = herramienta.rsplit("__", 1)[-1]
        if MCP_DELICADO.search(accion):
            return f"usar la acción externa {accion.replace('_', ' ')}"

    return None
