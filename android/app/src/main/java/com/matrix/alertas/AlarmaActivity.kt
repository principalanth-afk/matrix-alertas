package com.matrix.alertas

import android.app.KeyguardManager
import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * La pantalla que aparece encima de todo: título grande, el partido y un botón.
 * Suena con el tono de alarma del teléfono y vibra hasta que se toca el botón
 * o hasta que pasan dos minutos, para no quedar sonando si no está cerca.
 */
class AlarmaActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_TITULO = "titulo"
        const val EXTRA_TEXTO = "texto"
        private const val CORTE_MS = 120_000L
    }

    private var player: MediaPlayer? = null
    private var vibrador: Vibrator? = null
    private val mano = Handler(Looper.getMainLooper())
    private val cortar = Runnable { cerrar() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        mostrarAunqueEsteBloqueado()
        setContentView(R.layout.activity_alarma)

        pintar(intent)

        findViewById<Button>(R.id.boton_ok).setOnClickListener { cerrar() }

        sonar()
        vibrar()
        mano.postDelayed(cortar, CORTE_MS)
    }

    /** Si llega otro aviso mientras esta pantalla está abierta, se reemplaza el texto. */
    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        pintar(intent)
        mano.removeCallbacks(cortar)
        mano.postDelayed(cortar, CORTE_MS)
    }

    private fun pintar(intent: android.content.Intent?) {
        findViewById<TextView>(R.id.titulo).text =
            intent?.getStringExtra(EXTRA_TITULO) ?: "MATRIX"
        findViewById<TextView>(R.id.texto).text =
            intent?.getStringExtra(EXTRA_TEXTO) ?: ""
    }

    private fun mostrarAunqueEsteBloqueado() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            (getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager)
                .requestDismissKeyguard(this, null)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                        or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                        or WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
            )
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun sonar() {
        runCatching {
            val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
                ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
                ?: return
            player = MediaPlayer().apply {
                setDataSource(this@AlarmaActivity, uri)
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build()
                )
                isLooping = true
                prepare()
                start()
            }
        }
    }

    private fun vibrar() {
        runCatching {
            vibrador = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                (getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            }
            val patron = longArrayOf(0, 600, 400, 600, 400)
            vibrador?.vibrate(VibrationEffect.createWaveform(patron, 0))
        }
    }

    private fun cerrar() {
        mano.removeCallbacks(cortar)
        runCatching { player?.stop() }
        runCatching { player?.release() }
        player = null
        runCatching { vibrador?.cancel() }
        vibrador = null
        finish()
    }

    override fun onDestroy() {
        cerrar()
        super.onDestroy()
    }
}
