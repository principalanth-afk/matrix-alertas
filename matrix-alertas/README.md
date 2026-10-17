# MATRIX Alertas

> **Primero: subir esto a GitHub para que compile el APK.**
> 1. Entra a <https://github.com/new>, nombre `matrix-alertas`, marca **Private**
>    y marca también **Add a README file**. Crea el repo.
> 2. Dentro del repo: **Add file → Upload files**.
> 3. Arrastra las **carpetas** `android`, `pc`, `.github` y los archivos
>    `README.md` y `.gitignore` (todo lo que viene en el zip). Arrastrar carpetas
>    enteras respeta la estructura; no hace falta subir archivo por archivo.
> 4. Abajo, **Commit changes**.
> 5. Pestaña **Actions**: verás "Compilar APK" corriendo. Tarda unos 3 o 4 minutos.
> 6. Cuando termine, pestaña **Releases** → `MATRIX-Alertas.apk`. Abre esa página
>    desde el celular y descárgalo ahí directamente.
>
> Si `.github` no te aparece al arrastrar (Windows esconde las carpetas que
> empiezan con punto), activa "Elementos ocultos" en la pestaña Vista del
> explorador.


Avisos al celular de los partidos del día que están en la pestaña **CONSTRUCK**
del registro de omega:

- **15 minutos antes** de cada partido.
- **El marcador final** en cuanto aparece en las columnas GL/GV, con el veredicto
  Under 2.5 o Over 2.5.

El aviso entra como alarma: suena, vibra y se muestra **por encima de cualquier
aplicación**, también con el celular bloqueado.

## Cómo está armado

```
   PC (vigilante.py)  ──►  ntfy.sh  ──►  celular (MATRIX Alertas)
   lee el Excel            el cartero     muestra la alarma
```

La PC solo manda; el celular solo escucha. No hay cuenta que crear, ni Firebase,
ni servidor propio. Lo único privado es el **canal**: una cadena al azar que
genera el vigilante la primera vez. Quien la conozca puede ver tus avisos, así
que no se publica en ningún lado.

## 1. El celular

1. Descarga `MATRIX-Alertas.apk` desde la pestaña **Releases** de este repo.
2. Instálalo. Android te va a preguntar si permites instalar de origen
   desconocido: acepta.
3. Abre la app, pega el canal que te muestra el vigilante de la PC y toca
   **ENCENDER**.
4. Concede los **4 permisos** de la lista. Sin ellos la alarma no se ve encima de
   otras aplicaciones ni suena con la pantalla apagada:
   - Notificaciones
   - Mostrar sobre otras apps
   - Alarma a pantalla completa
   - Quitar el ahorro de batería
5. Toca **Mandarme un aviso de prueba**. Debe sonar y aparecer la pantalla roja.

## 2. La PC

1. Copia la carpeta `pc` donde quieras (por ejemplo al lado de `omega`).
2. Doble clic en `INICIAR_ALERTAS.bat`.
3. La primera vez te muestra tu canal. Pégalo en la app del celular.
4. Deja la ventana abierta, minimizada. Mientras esté abierta, vigila.

Comandos útiles:

```
python vigilante.py --hoy        lista los partidos de hoy y cuántos avisos saldrían
python vigilante.py --probar     manda un aviso de prueba al celular
python vigilante.py --simular    enseña qué avisaría ahora mismo, sin mandar nada
```

## Configuración

Se edita en `config.ini`, que se crea solo la primera vez. Lo que más se toca:

| Opción | Para qué |
|---|---|
| `excel` | Ruta del registro. Por defecto, la de omega. |
| `minutos_antes` | 15 por defecto. |
| `prioridad_resultado` | `4` alarma, `3` notificación normal, `2` silenciosa. |
| `solo_competiciones` | Vacío = todos. O una lista: `Prim B Nacional, Liga Pro Serie B`. |
| `recordar_pendientes_cada_horas` | Recordatorio de los que terminaron y siguen sin resultado. |

**Si son demasiados avisos:** un día con 35 partidos son 35 alarmas previas más
35 de resultado. Para bajarlo, pon `prioridad_resultado = 3` (el marcador llega
como notificación normal, sin alarma) o filtra con `solo_competiciones`.

## Detalles que conviene saber

- El vigilante **no toca el registro**: lo copia a un temporal y lee la copia, así
  que puedes tener el Excel abierto mientras corre.
- El resultado se avisa cuando aparece en el Excel, no cuando termina el partido
  de verdad. Si cargas los resultados al rato, el aviso llega al rato.
- Si la PC estuvo apagada y un partido ya empezó hace más de 10 minutos, ese aviso
  previo se deja pasar: ya no sirve.
- Los partidos marcados `SR` (suspendidos) llegan como aviso informativo.
- `estado_avisos.json` recuerda lo ya avisado, para que reiniciar no repita nada.
  Si lo borras, el vigilante vuelve a marcar como vistos los resultados que ya
  están cargados y empieza limpio.

## El APK

Lo compila GitHub Actions en cada cambio (`.github/workflows/apk.yml`) y lo
publica en Releases. Va firmado con la clave de depuración, que es lo normal para
instalar a mano; por eso Android pide confirmación al instalarlo.
