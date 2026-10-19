package com.matrix.alertas

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Mantiene abierta una conexión con el canal de avisos y, cuando llega uno,
 * levanta la pantalla de alarma por encima de lo que sea que esté abierto.
 *
 * Dos caminos (v1.2):
 *  1. DIRECTO a la PC (servidor_app.py): cada 15 s (5 s con la app abierta) se
 *     piden los partidos, las estadísticas y las alarmas nuevas. Primero por el
 *     wifi de la casa y, si no, por el túnel de internet. Sin límite de mensajes.
 *  2. ntfy, como siempre: de respaldo (si el celular no llega a la PC, la PC
 *     manda la alarma por ntfy a los 45 s) y para recibir la dirección del túnel.
 * Una misma alarma que llegue por los dos caminos se muestra una sola vez.
 *
 * Corre en primer plano con su propia notificación, que es lo que impide que
 * Android lo mate al rato.
 */
class AlertaService : Service() {

    companion object {
        const val CANAL_SERVICIO = "matrix_servicio"
        const val CANAL_AVISOS = "matrix_avisos"
        const val CANAL_ALARMA = "matrix_alarma"
        private const val ID_SERVICIO = 1
        private const val TAG = "MatrixAlertas"

        const val ACCION_PARAR = "com.matrix.alertas.PARAR"
        /** Título reservado: marca el mensaje que trae la lista del día. */
        const val TITULO_ESTADO = "__ESTADO__"
        const val TITULO_FICHAS = "__FICHAS__"
        /** Título reservado: trae las direcciones de la PC (wifi y túnel). */
        const val TITULO_ENLACE = "__ENLACE__"

        /** Con la app abierta se piden los datos más seguido. */
        @Volatile
        var rapido: Boolean = false

        /** Por dónde se llegó a la PC la última vez: «wifi», «internet» o "" (no se llegó). */
        @Volatile
        var via: String = ""

        /** Para que la pantalla principal pueda mostrar si está conectado. */
        @Volatile
        var conectado: Boolean = false

        @Volatile
        var corriendo: Boolean = false

        /** Cada cuánto comprueba el vigía que el servicio sigue vivo. */
        private const val VIGIA_MS = 10 * 60 * 1000L

        fun arrancar(ctx: Context) {
            val i = Intent(ctx, AlertaService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) ctx.startForegroundService(i)
            else ctx.startService(i)
        }

        private fun avisoVigia(ctx: Context, codigo: Int): PendingIntent =
            PendingIntent.getBroadcast(
                ctx, codigo,
                Intent(ctx, BootReceiver::class.java).setAction(BootReceiver.ACCION_REVIVIR),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

        fun parar(ctx: Context) {
            ctx.startService(Intent(ctx, AlertaService::class.java).setAction(ACCION_PARAR))
        }

        fun crearCanales(ctx: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val nm = ctx.getSystemService(NotificationManager::class.java)

            // Canal del servicio: silencioso, es solo el aviso fijo de "estoy activo".
            nm.createNotificationChannel(
                NotificationChannel(
                    CANAL_SERVICIO, "Servicio de alertas", NotificationManager.IMPORTANCE_LOW
                ).apply {
                    description = "Aviso fijo de que la vigilancia está encendida"
                    setShowBadge(false)
                }
            )

            // Canal de la alarma: máxima importancia; es el que permite la
            // pantalla completa aunque el celular esté en otra aplicación.
            nm.createNotificationChannel(
                NotificationChannel(
                    CANAL_ALARMA, "Alarma de partido", NotificationManager.IMPORTANCE_HIGH
                ).apply {
                    description = "Suena y se muestra sobre cualquier aplicación"
                    enableVibration(true)
                    setBypassDnd(true)
                    lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                }
            )

            // Canal normal, para avisos que no ameritan alarma.
            nm.createNotificationChannel(
                NotificationChannel(
                    CANAL_AVISOS, "Avisos", NotificationManager.IMPORTANCE_DEFAULT
                ).apply { description = "Mensajes informativos" }
            )
        }
    }

    private var hilo: Thread? = null
    private var hiloDirecto: Thread? = null

    @Volatile
    private var seguir = false
    private var wakeLock: PowerManager.WakeLock? = null

    private val cliente: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)   // la conexión queda abierta
            .retryOnConnectionFailure(true)
            .build()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        crearCanales(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACCION_PARAR) {
            encendido = false
            pararTodo()
            return START_NOT_STICKY
        }

        startForeground(ID_SERVICIO, notificacionServicio("Conectando…"))
        corriendo = true
        encendido = true

        if (hilo?.isAlive != true) {
            seguir = true
            hilo = Thread { escuchar() }.also { it.isDaemon = true; it.start() }
        }
        if (hiloDirecto?.isAlive != true) {
            seguir = true
            hiloDirecto = Thread { sondear() }.also { it.isDaemon = true; it.start() }
        }
        programarVigia()
        // START_STICKY: si Android mata el servicio por memoria, lo vuelve a levantar.
        return START_STICKY
    }

    /**
     * En muchos teléfonos (sobre todo Xiaomi, Oppo, Vivo, Huawei) deslizar la
     * app fuera de "recientes" mata el servicio aunque esté en primer plano.
     * Aquí se pide que lo revivan en dos segundos.
     */
    override fun onTaskRemoved(rootIntent: Intent?) {
        if (encendido) {
            runCatching {
                getSystemService(AlarmManager::class.java).set(
                    AlarmManager.RTC_WAKEUP,
                    System.currentTimeMillis() + 2_000,
                    avisoVigia(this, 98)
                )
            }
        }
        super.onTaskRemoved(rootIntent)
    }

    /** Comprobación periódica: si el servicio se cayó, se vuelve a levantar solo. */
    private fun programarVigia() {
        runCatching {
            getSystemService(AlarmManager::class.java).setInexactRepeating(
                AlarmManager.RTC_WAKEUP,
                System.currentTimeMillis() + VIGIA_MS,
                VIGIA_MS,
                avisoVigia(this, 99)
            )
        }
    }

    private fun cancelarVigia() {
        runCatching {
            getSystemService(AlarmManager::class.java).cancel(avisoVigia(this, 99))
        }
    }

    override fun onDestroy() {
        pararTodo()
        super.onDestroy()
    }

    private fun pararTodo() {
        cancelarVigia()
        seguir = false
        conectado = false
        corriendo = false
        hilo?.interrupt()
        hilo = null
        hiloDirecto?.interrupt()
        hiloDirecto = null
        via = ""
        runCatching { wakeLock?.takeIf { it.isHeld }?.release() }
        wakeLock = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    // ---------------------------------------------------------------- conexión

    /**
     * Se queda leyendo el canal. Si la conexión se cae (datos, wifi, el celular
     * durmiendo) espera un poco y vuelve a conectar, cada vez un poco más tarde
     * hasta un máximo de un minuto, para no gastar batería reintentando.
     */
    private fun escuchar() {
        var espera = 2_000L
        while (seguir) {
            val canalActual = canal
            if (canalActual.isBlank()) {
                actualizarNotificacion("Falta configurar el canal")
                dormir(5_000)
                continue
            }
            try {
                // since=<marca> recupera los avisos que llegaron mientras no había
                // conexión, para no perder un partido por quedarse sin señal.
                val desde = if (ultimoMensaje > 0) ultimoMensaje.toString() else "10m"
                val url = "$servidor/$canalActual/json?since=$desde"
                val peticion = Request.Builder().url(url).header("Accept", "application/x-ndjson").build()

                cliente.newCall(peticion).execute().use { respuesta ->
                    if (!respuesta.isSuccessful) throw IllegalStateException("HTTP ${respuesta.code}")
                    conectado = true
                    espera = 2_000L
                    actualizarNotificacion("Vigilando los partidos")

                    val cuerpo = respuesta.body ?: throw IllegalStateException("respuesta vacía")
                    val lector = cuerpo.source()
                    while (seguir && !lector.exhausted()) {
                        val linea = lector.readUtf8Line() ?: break
                        if (linea.isBlank()) continue
                        procesarLinea(linea)
                    }
                }
            } catch (e: Exception) {
                if (!seguir) return
                Log.w(TAG, "conexión caída: ${e.message}")
            }
            conectado = false
            if (!seguir) return
            actualizarNotificacion("Sin conexión, reintentando…")
            dormir(espera)
            espera = (espera * 2).coerceAtMost(60_000L)
        }
    }

    private fun dormir(ms: Long) {
        try {
            Thread.sleep(ms)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
        }
    }

    private fun procesarLinea(linea: String) {
        val j = runCatching { JSONObject(linea) }.getOrNull() ?: return
        when (j.optString("event")) {
            "message" -> {
                val hora = j.optLong("time", 0L)
                if (hora > 0) ultimoMensaje = hora + 1
                val titulo = j.optString("title").ifBlank { "MATRIX" }
                val texto = j.optString("message")
                val prioridad = j.optInt("priority", 3)
                if (titulo == TITULO_ESTADO) {
                    // No es un aviso: es la lista de partidos del día para la
                    // pantalla. Se guarda y se le avisa a la pantalla si está abierta.
                    ultimoEstado = texto
                    estadoRecibidoEn = System.currentTimeMillis()
                } else if (titulo == TITULO_FICHAS) {
                    // Tampoco es un aviso: son las estadísticas que se
                    // despliegan al tocar un partido. No suena ni se muestra.
                    ultimasFichas = texto
                } else if (titulo == TITULO_ENLACE) {
                    // Las direcciones para hablar directo con la PC: «MATRIXE|{"lan":…,"publico":…}»
                    runCatching { JSONObject(texto.substringAfter("|")) }.getOrNull()?.let { o ->
                        enlaceLan = o.optString("lan")
                        enlacePublico = o.optString("publico")
                    }
                } else {
                    mostrarUnaVez(titulo, texto, prioridad)
                }
            }
            // "open" y "keepalive" solo confirman que la conexión sigue viva.
            "open", "keepalive" -> conectado = true
        }
    }

    // ------------------------------------------------------ directo a la PC

    private val clienteCorto: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(4, TimeUnit.SECONDS)
            .readTimeout(12, TimeUnit.SECONDS)
            .callTimeout(15, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build()
    }

    /** Si el wifi de la casa no contestó, no se vuelve a probar en 2 min (fuera de casa, con datos). */
    private var lanFalloHasta = 0L
    private var ultimaBuena = ""

    private fun pedir(url: String): String? =
        clienteCorto.newCall(Request.Builder().url(url).build()).execute().use { r ->
            if (r.isSuccessful) r.body?.string() else null
        }

    /**
     * Cada 15 s (5 s con la app abierta) le pide a la PC los partidos y las
     * alarmas nuevas. Primero por donde funcionó la última vez, después el wifi
     * de la casa y por último el túnel de internet.
     */
    private fun sondear() {
        while (seguir) {
            val c = canal
            var ok = false
            if (c.isNotBlank()) {
                val lan = enlaceLan
                val pub = enlacePublico
                val orden = ArrayList<String>()
                if (ultimaBuena.isNotBlank() && (ultimaBuena == lan || ultimaBuena == pub)) orden.add(ultimaBuena)
                if (lan.isNotBlank() && System.currentTimeMillis() >= lanFalloHasta && lan !in orden) orden.add(lan)
                if (pub.isNotBlank() && pub !in orden) orden.add(pub)
                for (base in orden) {
                    if (!seguir) break
                    val url = "$base/m/${Uri.encode(c)}/datos?ack=$ackApp&id=${Uri.encode(pcId)}"
                    val cuerpo = runCatching { pedir(url) }.getOrNull()
                    if (cuerpo == null) {
                        if (base == lan) lanFalloHasta = System.currentTimeMillis() + 120_000L
                        continue
                    }
                    if (procesarDatos(base, c, cuerpo)) {
                        ultimaBuena = base
                        via = if (base == lan) "wifi" else "internet"
                        ok = true
                        break
                    }
                }
            }
            if (!ok) via = ""
            dormir(if (rapido) 5_000 else 15_000)
        }
    }

    /** Guarda los datos para la pantalla y muestra las alarmas nuevas del buzón de la PC. */
    private fun procesarDatos(base: String, c: String, cuerpo: String): Boolean {
        val j = runCatching { JSONObject(cuerpo) }.getOrNull() ?: return false
        if (!j.has("partidos")) return false
        datosApp = cuerpo
        datosEn = System.currentTimeMillis()

        val serie = j.optLong("serie", 0L)
        val id = j.optString("id")
        if (id != pcId || ackApp > serie) {
            // Primera vez con esta PC (o la PC empezó de cero): no se repiten alarmas viejas.
            pcId = id
            ackApp = serie
            return true
        }
        var maximo = ackApp
        val eventos = j.optJSONArray("eventos")
        if (eventos != null) {
            for (i in 0 until eventos.length()) {
                val e = eventos.optJSONObject(i) ?: continue
                val n = e.optLong("n", 0L)
                if (n <= ackApp) continue
                mostrarUnaVez(e.optString("titulo").ifBlank { "MATRIX" }, e.optString("texto"), e.optInt("prioridad", 3))
                if (n > maximo) maximo = n
            }
        }
        if (maximo > ackApp) {
            ackApp = maximo
            // Se confirma en el acto, para que la PC no la mande también por ntfy.
            runCatching { pedir("$base/m/${Uri.encode(c)}/ack?n=$maximo&id=${Uri.encode(id)}") }
        }
        return true
    }

    /** Una alarma que llegó por los dos caminos (directo y ntfy) se muestra una sola vez. */
    private val mostrados = LinkedHashMap<Int, Long>()

    @Synchronized
    private fun yaMostrado(titulo: String, texto: String): Boolean {
        val ahora = System.currentTimeMillis()
        val it = mostrados.entries.iterator()
        while (it.hasNext()) if (ahora - it.next().value > 3_600_000L) it.remove()
        val k = (titulo + "\n" + texto).hashCode()
        if (mostrados.containsKey(k)) return true
        mostrados[k] = ahora
        return false
    }

    private fun mostrarUnaVez(titulo: String, texto: String, prioridad: Int) {
        if (yaMostrado(titulo, texto)) return
        if (prioridad >= 4) mostrarAlarma(titulo, texto) else mostrarAviso(titulo, texto)
    }

    // ------------------------------------------------------------ mostrar algo

    /**
     * Dos caminos, porque ninguno funciona solo en todos los teléfonos:
     *  1. Abrir la pantalla directamente. Android lo permite desde segundo plano
     *     solo si el usuario dio el permiso de "mostrar sobre otras apps".
     *  2. Una notificación de pantalla completa (la que usan las llamadas). En
     *     Android 14 hay que concederla aparte; si no, al menos salta arriba.
     */
    private fun mostrarAlarma(titulo: String, texto: String) {
        despertarPantalla()

        val intent = Intent(this, AlarmaActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra(AlarmaActivity.EXTRA_TITULO, titulo)
            .putExtra(AlarmaActivity.EXTRA_TEXTO, texto)

        val puedeSuperponer = Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(this)
        if (puedeSuperponer) {
            runCatching { startActivity(intent) }
                .onFailure { Log.w(TAG, "no se pudo abrir la alarma: ${it.message}") }
        }

        val pi = PendingIntent.getActivity(
            this, titulo.hashCode(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val n = NotificationCompat.Builder(this, CANAL_ALARMA)
            .setSmallIcon(R.drawable.ic_aviso)
            .setContentTitle(titulo)
            .setContentText(texto)
            .setStyle(NotificationCompat.BigTextStyle().bigText(texto))
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .setFullScreenIntent(pi, true)
            .build()

        notificar(texto.hashCode(), n)
    }

    private fun mostrarAviso(titulo: String, texto: String) {
        val n = NotificationCompat.Builder(this, CANAL_AVISOS)
            .setSmallIcon(R.drawable.ic_aviso)
            .setContentTitle(titulo)
            .setContentText(texto)
            .setStyle(NotificationCompat.BigTextStyle().bigText(texto))
            .setAutoCancel(true)
            .build()
        notificar(texto.hashCode(), n)
    }

    private fun notificar(id: Int, n: Notification) {
        runCatching {
            getSystemService(NotificationManager::class.java).notify(id, n)
        }.onFailure { Log.w(TAG, "sin permiso de notificaciones: ${it.message}") }
    }

    /** Enciende la pantalla unos segundos para que la alarma se vea, no solo se oiga. */
    private fun despertarPantalla() {
        runCatching {
            val pm = getSystemService(POWER_SERVICE) as PowerManager
            @Suppress("DEPRECATION")
            val wl = pm.newWakeLock(
                PowerManager.FULL_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP
                        or PowerManager.ON_AFTER_RELEASE,
                "$TAG:alarma"
            )
            wl.acquire(10_000)
            wakeLock = wl
        }
    }

    // ------------------------------------------------------- aviso fijo propio

    private fun notificacionServicio(estado: String): Notification {
        val abrir = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val parar = PendingIntent.getService(
            this, 1, Intent(this, AlertaService::class.java).setAction(ACCION_PARAR),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CANAL_SERVICIO)
            .setSmallIcon(R.drawable.ic_aviso)
            .setContentTitle("MATRIX Alertas")
            .setContentText(estado)
            .setOngoing(true)
            .setSilent(true)
            .setContentIntent(abrir)
            .addAction(0, "Apagar", parar)
            .build()
    }

    private fun actualizarNotificacion(estado: String) {
        runCatching {
            getSystemService(NotificationManager::class.java)
                .notify(ID_SERVICIO, notificacionServicio(estado))
        }
    }
}
