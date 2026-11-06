# Jarvis: control por voz vinculado a Claude

Asistente de voz para Windows, en castellano de España. Dices «Jarvis», le pides algo y **Claude Code** hace la tarea en tu PC y te responde en voz alta.

No usa un modelo local ni un asistente ya hecho: este programa solo pone el oído y la voz, y el cerebro es Claude Code con tu propia cuenta.

> **Estado:** funciona el circuito de voz, la memoria, el volumen y el control de música. «Pausa» y «pon música» envían la misma tecla, así que si ya estaba en ese estado hacen lo contrario. Poner una canción pulsa el botón de la app de Spotify en español o inglés, y podría dejar de funcionar si Spotify cambia su interfaz.

## Cómo funciona

```mermaid
flowchart LR
    A[Micrófono] --> B[Detecta voz<br/>y ajusta volumen]
    B --> C[Voz a texto<br/>faster-whisper]
    C --> D{¿Ha dicho<br/>Jarvis?}
    D -- No --> X[Se ignora]
    D -- Solo me llama --> E[Respuesta<br/>instantánea]
    D -- Me pide algo --> F[Claude Code]
    F -- Acción delicada --> G{¿Confirmas?<br/>por voz}
    G --> F
    F --> H[Texto a voz<br/>Piper]
    E --> H
    H --> I[Altavoces]
```

## Qué puedes decirle

| Dices | Qué hace | ¿Gasta tokens? |
|---|---|---|
| «Jarvis», «hola Jarvis», «Jarvis, ¿estás ahí?» | Responde al momento y te escucha unos segundos | No |
| «Jarvis, ¿qué hora es?», «oye Jarvis, busca…» | Se lo pasa a Claude | Sí |
| «Jarvis, ¿cuánto consumo llevo?» | Dice el porcentaje de sesión y semanal | No |
| «Jarvis, sube un poco el volumen», «… volumen al 40», «… silencia», «… activa el sonido» | Cambia el volumen de Windows | No |
| «Jarvis, pon música», «… pausa», «… siguiente», «… canción anterior» | Controla la música con las teclas multimedia | No |
| «Jarvis, pon música de Queen», «… pon The Killers en Spotify» | Busca en Spotify y reproduce el primer resultado | No |
| «Jarvis, pon esa canción de los Killers que empieza con…» | Claude deduce cuál es y la reproduce | Sí |
| «Jarvis, recuerda lo que hablamos el martes», «… la conversación sobre X» | Busca en vuestras conversaciones anteriores | Sí, solo lo que lee |
| «Jarvis, para» | Corta lo que esté haciendo | No |
| «Jarvis, apágate» | Da el resumen de consumo y se cierra | No |

Tras cada respuesta puedes seguir hablando unos segundos sin repetir su nombre. Reacciona a «Jarvis» al principio de la frase, incluso tras un «mira» o un «oye», y al final, y responde a cualquier voz, no solo a la tuya. Reconoce lo que suena parecido («Yarvis», «Jurais»), porque la transcripción no siempre acierta el nombre.

**Peticiones largas:** cuanto más hablas, más pausa te permite antes de darte por terminado. Si aun así sigue en marcha cuando continúas, lo que digas en los 10 segundos siguientes se añade a la petición, sin repetir su nombre. Más tarde, otra orden con «Jarvis» queda en cola, y lo que digas sin llamarle se ignora.

## Instalación

Necesitas Windows, Python 3.12, un micrófono y [Claude Code](https://claude.com/claude-code) con la sesión iniciada.

```powershell
git clone https://github.com/Pareyor/Control-de-voz-vinculado-a-claude.git jarvis
cd jarvis
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\jarvis.bat
```

La primera vez descarga los modelos de voz y transcripción. Después arranca en unos 4 segundos.

Para que arranque al iniciar sesión, crea un acceso directo a `jarvis.bat` en la carpeta que abre `shell:startup`. Solo puede haber una copia abierta: si ya está en marcha, las siguientes se cierran.

| Opción de `jarvis.bat` | Para qué sirve |
|---|---|
| `--dispositivos` | Lista los micrófonos disponibles |
| `--micro 3` | Usa un micrófono concreto |
| `--interrumpir` | Te escucha también mientras habla (solo con cascos) |
| `--voz edge` | Usa la voz de Microsoft: más natural, pero 1 s más lenta y con internet |

## Qué hay en cada archivo

| Archivo | Qué contiene |
|---|---|
| [`jarvis.py`](jarvis.py) | El programa: oído, voz, conexión con Claude y decisión de qué hacer con cada frase |
| [`permisos.py`](permisos.py) | Decide qué se ejecuta directamente y qué pide confirmación |
| [`uso.py`](uso.py) | Sigue el consumo del plan y genera los avisos |
| [`memoria.py`](memoria.py) | Guarda cada conversación en un archivo con su fecha |
| [`acciones.py`](acciones.py) | Música y volumen, resueltos sin pasar por Claude |
| [`prueba.py`](prueba.py) | Pruebas de extremo a extremo sin micrófono ni altavoces |
| `jarvis.bat` / `jarvis.ico` | Lanzador e icono para Windows |

Lo que más se suele querer cambiar está al principio de `jarvis.py`: el modelo, la voz, los tiempos de espera, las respuestas fijas y la personalidad (`SISTEMA`).

## Permisos

Todo lo que Claude intenta hacer pasa antes por `permisos.py`, un filtro de código que está fuera del modelo. No depende de que Claude se acuerde de preguntar.

| Sin preguntar | Pide un «sí» por voz |
|---|---|
| Leer archivos y buscar en la web | Borrar o sobrescribir archivos |
| Crear archivos nuevos | Modificar archivos existentes |
| Abrir programas y enlaces | Enviar correos o usar acciones externas |
| Consultar información del sistema | Cualquier comando que no reconozca como seguro |

Si no respondes en 12 segundos o hay dudas, la acción se rechaza.

**Limitaciones:** la confirmación identifica a quien dice «sí» solo por estar cerca del micro, no por su voz. Y una lista de comandos seguros reduce el riesgo, pero no es una garantía absoluta. Vigila lo que le pides.

## Velocidad

Medida desde que dejas de hablar hasta que suena la respuesta, con voz simulada:

| Tipo de orden | Tiempo |
|---|---|
| Respuestas sin Claude («¿estás ahí?») | unos 1,2 s |
| Pregunta normal | unos 2,5 s |
| Tarea compleja | más, pero te cuenta el proceso mientras trabaja |

Reparto aproximado de una pregunta normal: 0,45 s o más esperando a que termines de hablar, 0,8 s de transcripción con el modelo `medium` en GPU (GTX 1650), de 0,5 a 0,7 s hasta las primeras palabras de Claude y 0,07 s de voz. Se usa `medium` y no `small`, que tarda 0,5 s menos, porque comete muchos menos errores. Claude se mantiene en un proceso abierto para no pagar 2,3 s de arranque en cada orden.

Usa Claude Opus 5.5 (`MODELO_CLAUDE` en `jarvis.py`), el modelo más capaz, porque está pensado también para tareas complejas. En esas tareas dice qué va a hacer antes de cada paso y, si se queda callado 12 segundos, avisa de que sigue trabajando.

## Consumo

Usa el plan de la cuenta con la que hayas iniciado Claude Code, y Opus gasta más que Sonnet. Jarvis avisa cada 10 % de uso de la sesión (ventana de 5 horas) y del semanal, y da un resumen al cerrarse. Los porcentajes son los que envía Claude Code, no estimaciones, aunque solo se actualizan cuando Jarvis hace una consulta.

## Privacidad

- **Tu voz** se transcribe en tu PC y no sale de él. Se envía a Claude el texto de lo que le pides a Jarvis.
- **Las respuestas** se generan en local con Piper. Con `--voz edge`, el texto se envía a Microsoft.
- **El micrófono** se escucha continuamente mientras Jarvis esté abierto, pero el audio no se guarda.
- **Las conversaciones** se guardan como texto sin cifrar en `conversaciones/`, en tu PC, y no se suben a GitHub. Para que olvide algo, borra el archivo. Solo se envía a Claude lo que lea al pedirle que recuerde.

## Pruebas

```powershell
.\.venv\Scripts\python.exe prueba.py --rapida   # lógica, sin red ni tokens de Claude
.\.venv\Scripts\python.exe prueba.py            # completa: gasta algo de tu plan
```

La prueba completa genera frases con voz sintética, las baja de volumen para simular a alguien hablando bajo y las pasa por el mismo camino que el micro real. Con un archivo temporal, comprueba además que un «no» impide borrarlo y un «sí» lo permite.

## Créditos

Usa [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Piper](https://github.com/OHF-Voice/piper1-gpl) con la voz `es_ES-davefx-medium`, [edge-tts](https://github.com/rany2/edge-tts) y el [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python). Es un proyecto personal sin relación con Marvel ni Anthropic: el nombre es un homenaje y la voz no copia a ningún actor.
