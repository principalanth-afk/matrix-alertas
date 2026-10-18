package com.matrix.alertas

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Pantalla única: pegar el canal, encender, y una lista de permisos con su
 * botón al lado. Cada permiso explica para qué es, porque sin ellos la alarma
 * no se muestra sobre otras aplicaciones.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var campoCanal: EditText
    private lateinit var campoServidor: EditText
    private lateinit var estado: TextView
    private lateinit var botonEncender: Button

    private val mano = Handler(Looper.getMainLooper())
    private val refrescar = object : Runnable {
        override fun run() {
            pintarEstado()
            mano.postDelayed(this, 1_500)
        }
    }

    private val pedirNotificaciones =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { pintarEstado() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        AlertaService.crearCanales(this)

        campoCanal = findViewById(R.id.campo_canal)
        campoServidor = findViewById(R.id.campo_servidor)
        estado = findViewById(R.id.estado)
        botonEncender = findViewById(R.id.boton_encender)

        campoCanal.setText(canal)
        campoServidor.setText(servidor)

        botonEncender.setOnClickListener {
            if (AlertaService.corriendo) {
                AlertaService.parar(this)
            } else {
                val c = campoCanal.text.toString().trim()
                if (c.isBlank()) {
                    aviso("Falta pegar el canal que te dio la PC")
                    return@setOnClickListener
                }
                canal = c
                servidor = campoServidor.text.toString()
                AlertaService.arrancar(this)
            }
            mano.postDelayed({ pintarEstado() }, 400)
        }

        findViewById<Button>(R.id.boton_probar).setOnClickListener { probar() }

        findViewById<Button>(R.id.boton_notificaciones).setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                pedirNotificaciones.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else {
                abrirAjustesApp()
            }
        }

        findViewById<Button>(R.id.boton_superponer).setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                abrir(
                    Intent(
                        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:$packageName")
                    )
                )
            }
        }

        findViewById<Button>(R.id.boton_pantalla_completa).setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                abrir(
                    Intent(
                        Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT,
                        Uri.parse("package:$packageName")
                    )
                )
            } else {
                aviso("Tu versión de Android no necesita este permiso")
            }
        }

        findViewById<Button>(R.id.boton_bateria).setOnClickListener {
            abrir(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }

        findViewById<Button>(R.id.boton_autoarranque).setOnClickListener { abrirAutoarranque() }
    }

    /**
     * Cada marca esconde el "inicio automático" en su propia pantalla, y no hay
     * forma estándar de abrirla. Se prueban las conocidas y, si ninguna existe,
     * se abre la ficha de la app para que lo busque a mano.
     */
    private fun abrirAutoarranque() {
        val candidatos = listOf(
            "com.miui.securitycenter" to "com.miui.permcenter.autostart.AutoStartManagementActivity",
            "com.letv.android.letvsafe" to "com.letv.android.letvsafe.AutobootManageActivity",
            "com.huawei.systemmanager" to "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity",
            "com.huawei.systemmanager" to "com.huawei.systemmanager.optimize.process.ProtectActivity",
            "com.coloros.safecenter" to "com.coloros.safecenter.permission.startup.StartupAppListActivity",
            "com.coloros.safecenter" to "com.coloros.safecenter.startupapp.StartupAppListActivity",
            "com.oppo.safe" to "com.oppo.safe.permission.startup.StartupAppListActivity",
            "com.vivo.permissionmanager" to "com.vivo.permissionmanager.activity.BgStartUpManagerActivity",
            "com.iqoo.secure" to "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity",
            "com.asus.mobilemanager" to "com.asus.mobilemanager.autostart.AutoStartActivity",
            "com.samsung.android.lool" to "com.samsung.android.sm.battery.ui.BatteryActivity",
            "com.transsion.phonemaster" to "com.cyin.himgr.autostart.AutoStartActivity"
        )
        for ((paquete, clase) in candidatos) {
            val i = Intent().setClassName(paquete, clase)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (packageManager.resolveActivity(i, 0) != null) {
                if (runCatching { startActivity(i) }.isSuccess) {
                    aviso("Busca MATRIX Alertas en la lista y actívalo")
                    return
                }
            }
        }
        aviso("Tu teléfono no tiene esa pantalla; se abre la ficha de la app")
        abrirAjustesApp()
    }

    override fun onResume() {
        super.onResume()
        mano.post(refrescar)
    }

    override fun onPause() {
        mano.removeCallbacks(refrescar)
        super.onPause()
    }

    // ------------------------------------------------------------------ estado

    private fun pintarEstado() {
        val lineas = StringBuilder()
        lineas.append(
            when {
                !AlertaService.corriendo -> "● Apagado\n"
                AlertaService.conectado -> "● Conectado: esperando avisos de la PC\n"
                else -> "● Encendido, reconectando…\n"
            }
        )
        lineas.append("\nPermisos:\n")
        lineas.append(marca(notificacionesOk()) + " Notificaciones\n")
        lineas.append(marca(superponerOk()) + " Mostrar sobre otras apps\n")
        lineas.append(marca(pantallaCompletaOk()) + " Alarma a pantalla completa\n")
        lineas.append(marca(bateriaOk()) + " Sin ahorro de batería\n")
        estado.text = lineas.toString()
        botonEncender.text = if (AlertaService.corriendo) "APAGAR" else "ENCENDER"
    }

    private fun marca(ok: Boolean) = if (ok) "  ✔" else "  ✖"

    private fun notificacionesOk(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                ContextCompat.checkSelfPermission(
                    this, Manifest.permission.POST_NOTIFICATIONS
                ) == PackageManager.PERMISSION_GRANTED

    private fun superponerOk(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(this)

    private fun pantallaCompletaOk(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE ||
                getSystemService(NotificationManager::class.java).canUseFullScreenIntent()

    private fun bateriaOk(): Boolean =
        (getSystemService(Context.POWER_SERVICE) as PowerManager)
            .isIgnoringBatteryOptimizations(packageName)

    // ------------------------------------------------------------------ probar

    /** Se manda un aviso a uno mismo por el canal, para ver la alarma de verdad. */
    private fun probar() {
        val c = campoCanal.text.toString().trim()
        if (c.isBlank()) {
            aviso("Primero pega el canal")
            return
        }
        canal = c
        servidor = campoServidor.text.toString()
        if (!AlertaService.corriendo) AlertaService.arrancar(this)

        val cuerpo = JSONObject()
            .put("topic", c)
            .put("title", "PRUEBA")
            .put("message", "Si ves esta pantalla con sonido, las alertas funcionan.")
            .put("priority", 5)
            .toString()

        Thread {
            val ok = runCatching {
                val cliente = OkHttpClient.Builder()
                    .callTimeout(20, TimeUnit.SECONDS).build()
                val peticion = Request.Builder()
                    .url(servidor)
                    .post(cuerpo.toRequestBody("application/json".toMediaType()))
                    .build()
                cliente.newCall(peticion).execute().use { it.isSuccessful }
            }.getOrDefault(false)
            mano.post {
                aviso(if (ok) "Aviso enviado, debe sonar en unos segundos" else "No se pudo enviar: revisa internet")
            }
        }.start()
    }

    // ------------------------------------------------------------------ varios

    private fun abrir(i: Intent) {
        runCatching { startActivity(i) }.onFailure { abrirAjustesApp() }
    }

    private fun abrirAjustesApp() {
        runCatching {
            startActivity(
                Intent(
                    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:$packageName")
                )
            )
        }
    }

    private fun aviso(t: String) = Toast.makeText(this, t, Toast.LENGTH_LONG).show()
}
