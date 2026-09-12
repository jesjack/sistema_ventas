# DVR real (producción) -- Dahua XVR51xxHS-S2

Notas de hardware/firmware del DVR que usa `camera_viewer` en producción
(IP `192.168.1.108`), reunidas para explicar por qué el cliente serializa
sus conexiones (ver `CONNECTION_SERIALIZATION_GAP` en `dvr_client.py`) y
para no tener que rehacer esta investigación en el futuro.

## Identificación

Obtenida directamente del propio DVR (`magicBox.cgi?action=getSystemInfo`):

```
processor=ST7108
serialNumber=6L00943PAZ627B4
updateSerial=XVR5x04-S2
```

Es un **Dahua XVR de la línea de entrada "Lite"**, familia `XVR5104HS-S2` /
`XVR5108HS-S2` (4 u 8 canales; `cameras/vivo.py`, el script más antiguo del
proyecto, ya lo documentaba como "DVR Dahua"). El datasheet específico de
la variante `-S2` ya no está disponible en línea (el enlace encontrado
devuelve 404), pero `-S2` es una generación **anterior y más económica**
que `-I2`/`-I3` (WizSense) -- así que sus specs de red son, como mínimo,
igual de limitadas que las del hermano `-I2` de la misma familia, cuyo
datasheet oficial sí se pudo consultar completo:

- Fuente: [DH-XVR5104HS-I2 Datasheet (Dahua/sourcesecurity.com, PDF)](https://www.sourcesecurity.com/datasheets/dahua-technology-xvr5104hs-i2-digital-video-recorder-dvr/co-4261-ga/dh-xvr5104hs-i2-datasheet-20201019.pdf)
- [Dahua XVR5104HS-S2 -- manuales (ManualsLib)](https://www.manualslib.com/products/Dahua-Xvr5104hs-S2-8875614.html)

## Especificaciones relevantes (del datasheet DH-XVR5104HS-I2)

| Especificación | Valor |
|---|---|
| Procesador principal | "Embedded Processor" (genérico, un solo SoC, sin detalle de núcleos) |
| Sistema operativo | Embedded Linux |
| Interfaz de red | **1 puerto RJ-45 a 100 Mbps** (Fast Ethernet, ni siquiera Gigabit) |
| Max. User Access | 128 usuarios (cuentas/sesiones web registradas -- NO es el número de streams RTSP simultáneos que puede negociar) |
| Reproducción simultánea (local) | 1/4 canales |
| Protocolos de red | HTTP, HTTPS, TCP/IP, RTSP, UDP, ONVIF, CGI, P2P, etc. |

Dahua no publica una cifra oficial de "streams RTSP concurrentes que puede
negociar sin degradarse" para esta línea de entrada.

## Por qué esto importa (el bug que motivó investigar esto)

`camera_viewer` originalmente arrancaba los 4 canales (vivo o grabaciones)
**casi al mismo tiempo** -- 4 hilos, cada uno abriendo su propia conexión
(RTSP con autenticación digest, o HTTP `loadfile.cgi`) sin ningún
escalonamiento entre ellos. En producción esto dejaba al DVR **sin
responder a nada**, ni siquiera a un cliente externo y no relacionado con
la app (confirmado con `curl`/`nc` puros, sin ningún código del proyecto
de por medio): ni HTTP CGI ni RTSP contestaban, con timeouts de ~30s.

Dado el perfil de hardware (un solo SoC embebido genérico, Ethernet de
100 Mbps, sin nada que sugiera un stack de red pensado para atender varias
negociaciones de conexión a la vez), la hipótesis con más respaldo es que
el firmware del DVR no tolera una ráfaga de varias negociaciones RTSP/HTTP
simultáneas -- cada una implica levantar en tiempo real un pipeline nuevo
de captura/codificación, algo costoso para un SoC de gama baja.

**Solución aplicada:** `DVRClient._open_capture_serialized()` (en
`dvr_client.py`) usa un candado (`threading.Lock`) compartido por TODOS
los canales (vivo y grabaciones) para que nunca haya más de un intento de
conexión nuevo en curso contra el DVR a la vez -- ni entre canales
distintos, ni entre un canal y su propio reintento. Además, tras concluir
cada intento (con éxito o con error) se espera un margen fijo
(`CONNECTION_SERIALIZATION_GAP`, 1.5s) antes de permitir el siguiente, por
si el firmware necesita un instante para liberar los recursos de la sesión
anterior antes de aceptar otra.

El ancho de banda (100 Mbps) no es la limitante -- 4 substreams caben de
sobra ahí; el cuello de botella parece ser de cómputo/gestión interna del
SoC al montar/desmontar sesiones, no de red.

Ver `camera_viewer/DVR_STRESS_TEST_RESULTS.md` para los resultados
completos de las pruebas escalonadas (con `cameras/dvr_stress_test.py`)
que confirmaron esto y llevaron al diseño actual de descarga por bloques
+ reproducción local para grabaciones.
