package com.matrix.alertas

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
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
 * No usa Firebase: habla directo con el servidor (ntfy) por una conexión HTTP
 * que queda abierta. Por eso corre en primer plano con su propia notificación,
 * que es lo que impide que Android lo mate al rato.
 */
class AlertaService : Service() {

    companion object {
        const val CANAL_SERVICIO = "matrix_servicio"
        const val CANAL_AVISOS = "matrix_avisos"
        const val CANAL_ALARMA = "matrix_alarma"
        private const val ID_SERVICIO = 1
        private const val TAG = "MatrixAlertas"

        const val ACCION_PARAR = "com.matrix.alertas.PARAR"

        /** Para que la pantalla principal pueda mostrar si está conectado. */
        @Volatile
        var conectado: Boolean = false

        @Volatile
        var corriendo: Boolean = false

        fun arrancar(ctx: Context) {
            val i = Intent(ctx, AlertaService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) ctx.startForegroundService(i)
            else ctx.startService(i)
        }

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
        // START_STICKY: si Android mata el servicio por memoria, lo vuelve a levantar.
        return START_STICKY
    }

    override fun onDestroy() {
        pararTodo()
        super.onDestroy()
    }

    private fun pararTodo() {
        seguir = false
        conectado = false
        corriendo = false
        hilo?.interrupt()
        hilo = null
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
                if (prioridad >= 4) mostrarAlarma(titulo, texto) else mostrarAviso(titulo, texto)
            }
            // "open" y "keepalive" solo confirman que la conexión sigue viva.
            "open", "keepalive" -> conectado = true
        }
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
