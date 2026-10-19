# MATRIX Alertas

Tu celular te muestra **todos los partidos del día** de la pestaña **CONSTRUCK** del
registro de omega (por comenzar, en juego y terminados) con su **marcador en vivo,
minuto y estadísticas**, y te lanza **alarma** con:

- ⚽ el aviso **15 minutos antes** de cada partido,
- ⚽ cada **gol** y ❌ cuando **se cae el Under 2.5**,
- 🟥 cada **tarjeta roja**,
- ↩️ si el **VAR anula** un gol o una roja,
- 🏁 el **resultado final** cuando aparece en GL/GV.

Al tocar un partido se despliegan sus **estadísticas en vivo** (tarjetas, córners,
posesión, xG, remates…) y la **previa** que omega ya tiene en el Excel (posiciones,
cuotas 1-X-2, Under/Over, medias de goles, xG, H2H, últimos 5…).

## Cómo está armado (v1.2)

```
Excel (CONSTRUCK) ──► vigilante.py (PC) ◄── extensión Scarlet 3.4 (Edge, BetMines en vivo)
                           │
          ┌────────────────┴──────────────────┐
   directo (sin límite)                 ntfy.sh (respaldo)
   wifi de la casa o túnel Cloudflare   solo si el celular no llega a la PC
          └────────────────┬──────────────────┘
                     app MATRIX Alertas
```

- **Directo:** la app le pide a la PC los datos cada 15 s (5 s con la app abierta).
  En casa por el wifi; fuera de casa por un túnel gratis de Cloudflare que el
  vigilante abre solo (descarga `cloudflared.exe` la primera vez, no pide cuenta).
- **ntfy de respaldo:** si la app no recoge una alarma en 45 s, sale por ntfy.
  ntfy.sh gratis permite ~250 mensajes al día; antes el resumen salía cada minuto
  y se agotaba a media tarde (y dejaban de salir las alarmas). Ya no.
- **Pestañas:** la extensión abre una pestaña de BetMines **solo para los partidos
  que se están jugando**, a su hora, en una **ventana aparte y minimizada**, y la
  cierra al terminar el partido. Máximo `max_pestanas` (8) a la vez.

## 1. El celular

1. Descarga `MATRIX-Alertas.apk` de **Releases** e instálalo encima del anterior
   (no hace falta desinstalar: el canal y los permisos se conservan).
2. Si es la primera vez: pega el canal que muestra el vigilante, toca **ENCENDER**
   y da los 4 permisos (notificaciones, mostrar sobre otras apps, alarma a
   pantalla completa, sin ahorro de batería).
3. En **Ajustes** de la app verás «Conexión directa con la PC»: wifi ✔ / internet ✔
   cuando el vigilante ya le mandó las direcciones.

## 2. La PC

1. Copia la carpeta `pc` donde quieras y doble clic en `INICIAR_ALERTAS.bat`.
2. La primera vez Windows pregunta si Python puede usar la red: **Permitir**
   (es para que el celular entre por el wifi).
3. La primera vez se descarga `cloudflared.exe` (~50 MB) para el túnel.
4. Deja la ventana abierta. Abajo del panel dice si la app está conectada, por
   dónde, la dirección del túnel y cuántos mensajes de ntfy van hoy.

La extensión Scarlet 3.4 se instala en Edge: `edge://extensions` → Modo de
desarrollador → **Cargar descomprimida** (o **Volver a cargar** si ya la tenías).

Comandos útiles:

```
python vigilante.py --hoy        lista los partidos de hoy
python vigilante.py --probar     manda un aviso de prueba al celular
python vigilante.py --simular    enseña qué avisaría ahora mismo, sin mandar nada
```

## Configuración (`pc/config.ini`, se crea solo)

| Opción | Para qué |
|---|---|
| `excel` | Ruta del registro. Por defecto, la de omega. |
| `prioridad_gol`, `prioridad_roja` | `4` alarma (por defecto), `3` notificación normal. |
| `avisar_anulados` | Aviso cuando el VAR anula un gol o una roja. |
| `enlace_directo` | `si`: la app lee directo de la PC. |
| `tunel` | `cloudflared` · `localhost.run` · `ninguno` (solo wifi). |
| `max_pestanas` | Partidos en juego seguidos a la vez por la extensión. |
| `mandar_estado_cada_minutos` | Resumen por ntfy (solo si la app no llega a la PC). |
| `solo_competiciones` | Vacío = todos. O: `Prim B Nacional, Liga Pro Serie B`. |

`config.ini` lleva tu canal privado: **no se sube a GitHub** (está en `.gitignore`).

## El APK

Lo compila GitHub Actions (`.github/workflows/apk.yml`) en cada cambio de `android/`.
Solo lo que llega a `main` se publica en **Releases**. Va firmado siempre con la misma
clave (`android/matrix.keystore`), así las actualizaciones se instalan encima.
