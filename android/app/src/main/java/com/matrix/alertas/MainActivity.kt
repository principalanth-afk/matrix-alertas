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
import android.widget.LinearLayout
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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Una sola pantalla: arriba el panel de partidos del día (lo que manda la PC)
 * y abajo, plegados, los ajustes y los permisos.
 */
class MainActivity : AppCompatActivity() {

    /** Partidos cuya ficha está desplegada, por nombre. */
    private val abiertos = HashSet<String>()

    private lateinit var campoCanal: EditText
    private lateinit var campoServidor: EditText
    private lateinit var campoPc: EditText
    private lateinit var estado: TextView
    private lateinit var botonEncender: Button
    private lateinit var contenedor: LinearLayout
    private lateinit var reloj: TextView
    private lateinit var lineaEstado: TextView
    private lateinit var bloqueAjustes: LinearLayout
    private lateinit var botonAjustes: Button

    private val mano = Handler(Looper.getMainLooper())
    private var firmaPintada = ""

    private val latir = object : Runnable {
        override fun run() {
            refrescar()
            mano.postDelayed(this, 1_000)
        }
    }

    private val pedirNotificaciones =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { firmaPintada = "" }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        AlertaService.crearCanales(this)

        campoCanal = findViewById(R.id.campo_canal)
        campoServidor = findViewById(R.id.campo_servidor)
        campoPc = findViewById(R.id.campo_pc)
        estado = findViewById(R.id.estado)
        botonEncender = findViewById(R.id.boton_encender)
        contenedor = findViewById(R.id.contenedor)
        reloj = findViewById(R.id.reloj)
        lineaEstado = findViewById(R.id.linea_estado)
        bloqueAjustes = findViewById(R.id.bloque_ajustes)
        botonAjustes = findViewById(R.id.boton_ajustes)

        campoCanal.setText(canal)
        campoServidor.setText(servidor)
        campoPc.setText(enlaceLan.removePrefix("http://").removeSuffix(":${Red.PUERTO}"))
        findViewById<Button>(R.id.boton_buscar_pc).setOnClickListener { buscarPc() }

        // Si todavía no hay canal, los ajustes se abren solos: es lo primero que hace falta.
        if (canal.isBlank()) alternarAjustes(true)

        botonAjustes.setOnClickListener { alternarAjustes(bloqueAjustes.visibility != android.view.View.VISIBLE) }

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
                val pc = Red.normalizar(campoPc.text.toString())
                if (pc.isNotBlank()) enlaceLan = pc
                AlertaService.arrancar(this)
            }
            mano.postDelayed({ firmaPintada = ""; refrescar() }, 400)
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
                abrir(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            }
        }
        findViewById<Button>(R.id.boton_pantalla_completa).setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                abrir(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:$packageName")))
            } else {
                aviso("Tu versión de Android no necesita este permiso")
            }
        }
        findViewById<Button>(R.id.boton_bateria).setOnClickListener {
            abrir(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
        findViewById<Button>(R.id.boton_autoarranque).setOnClickListener { abrirAutoarranque() }
    }

    override fun onResume() {
        super.onResume()
        AlertaService.rapido = true          // con la app abierta, datos cada 5 s
        firmaPintada = ""
        mano.post(latir)
    }

    override fun onPause() {
        AlertaService.rapido = false
        mano.removeCallbacks(latir)
        super.onPause()
    }

    private fun alternarAjustes(abrir: Boolean) {
        bloqueAjustes.visibility = if (abrir) android.view.View.VISIBLE else android.view.View.GONE
        botonAjustes.text = getString(if (abrir) R.string.ajustes_cerrar else R.string.ajustes_abrir)
        if (abrir) firmaPintada = ""
    }

    // ------------------------------------------------------------- el panel

    private fun refrescar() {
        val ahora = minutosDeAhora()
        reloj.text = SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date())

        // Lo que llega directo de la PC manda si es reciente (menos de 3 min);
        // si no, se usa el resumen que llegó por ntfy.
        val directoEn = datosEn
        val directoFresco = System.currentTimeMillis() - directoEn < 180_000L
        val crudoDirecto = if (directoFresco) datosApp else ""
        val crudo = ultimoEstado
        // Solo se vuelve a dibujar si cambió algo o pasó un minuto.
        val crudoFichas = ultimasFichas
        val firma = "${crudoDirecto.hashCode()}|${crudo.hashCode()}|${crudoFichas.hashCode()}|$ahora|" +
                "${AlertaService.corriendo}|${AlertaService.conectado}|${AlertaService.via}|${abiertos.sorted()}"
        if (firma == firmaPintada) return
        firmaPintada = firma

        lineaEstado.text = lineaDeEstado()
        if (bloqueAjustes.visibility == android.view.View.VISIBLE) pintarAjustes()

        contenedor.removeAllViews()
        val directo = parsearDatos(crudoDirecto)
        val fichas = directo?.fichas ?: parsearFichas(crudoFichas)
        val dia = directo?.dia ?: parsearEstado(crudo)
        if (dia == null) {
            if (canal.isBlank()) {
                contenedor.addView(Panel.aviso(this,
                    "Pega el canal en Ajustes y enciende. En cuanto la app llegue a tu PC, aquí salen los partidos del día.",
                    Panel.SUAVE))
                return
            }
            // Qué está pasando, para que nunca quede la pantalla vacía sin explicación.
            val ip = Red.ipLocal(this)
            val diag = StringBuilder("Todavía no llego a tu PC.\n\n")
            diag.append(if (AlertaService.corriendo) "✔ Alertas encendidas\n" else "✖ Alertas apagadas: abre Ajustes y toca ENCENDER\n")
            diag.append(if (ip != null) "✔ Conectado al wifi ($ip)\n" else "✖ No estás en un wifi: fuera de casa necesito la dirección de internet de la PC\n")
            diag.append(if (enlaceLan.isNotBlank()) "• PC en el wifi: ${enlaceLan.removePrefix("http://")}\n" else "• Dirección de la PC en el wifi: todavía no la sé\n")
            diag.append(if (enlacePublico.isNotBlank()) "• PC por internet: ${enlacePublico.removePrefix("https://")}\n" else "• Dirección por internet: todavía no la sé\n")
            diag.append("\nEn la PC: el vigilante (ventana negra) tiene que estar abierto. Abajo dice «dirección para el celular». " +
                    "Si con el botón no la encuentro, escribe esa dirección en Ajustes, o corre PERMITIR_CELULAR.bat en la PC (permiso del firewall).")
            contenedor.addView(Panel.aviso(this, diag.toString(), Panel.SUAVE).apply { maxLines = 20 })
            contenedor.addView(Button(this).apply {
                text = getString(R.string.buscar_pc)
                setOnClickListener { buscarPc() }
            })
            return
        }

        val duracion = 115
        val enCurso = ArrayList<Pair<Partido, Int>>()
        val porJugar = ArrayList<Pair<Partido, Int>>()
        val esperando = ArrayList<Pair<Partido, Int>>()
        val listos = ArrayList<Partido>()
        val susp = ArrayList<Partido>()
        val manana = ArrayList<Pair<Partido, Int>>()

        for (p in dia.partidos) {
            if (p.dia > 0) {                       // los de mañana van aparte
                manana.add(p to faltaPara(p, ahora))
                continue
            }
            when (situacionDe(p, ahora, duracion)) {
                Situacion.EN_CURSO -> enCurso.add(p to (ahora - p.inicioMin))
                Situacion.POR_JUGAR -> porJugar.add(p to (p.inicioMin - ahora).coerceAtLeast(0))
                Situacion.ESPERANDO -> esperando.add(p to (ahora - p.finMin(duracion)))
                Situacion.LISTO -> listos.add(p)
                Situacion.SUSPENDIDO -> susp.add(p)
            }
        }
        enCurso.sortByDescending { it.second }
        porJugar.sortBy { it.second }
        esperando.sortByDescending { it.second }
        manana.sortBy { it.second }

        contenedor.addView(Panel.seccion(this, "EN VIVO",
            if (enCurso.isEmpty()) "ninguno" else "${enCurso.size}",
            if (enCurso.isEmpty()) Panel.TENUE else Panel.ROJO))
        if (enCurso.isEmpty()) {
            contenedor.addView(Panel.aviso(this, "Nada en juego en este momento."))
        } else {
            // Si hay partidos en juego sin marcador real, se dice por qué (y qué hacer en la PC).
            val sinDato = enCurso.count { !it.first.hayVivo }
            if (directo != null && sinDato > 0) {
                val e = directo.extension
                val msg = when {
                    e == null -> "El marcador real no está llegando: la PC tiene el programa viejo. Actualiza la carpeta pc (MATRIX v3)."
                    !e.ok && e.hace == null -> "⚠ La extensión Scarlet no le está mandando nada a la PC.\n" +
                            "En la PC: instala Scarlet 3.5 en el navegador que usas (Chrome) y déjalo abierto. Arranca sola."
                    !e.ok -> "⚠ La extensión Scarlet dejó de hablar con la PC hace ${(e.hace ?: 0) / 60} min.\n" +
                            "En la PC: abre ${e.navegador.ifBlank { "el navegador" }} (donde está Scarlet) y déjalo abierto."
                    else -> "Scarlet está buscando ${if (sinDato == 1) "el partido" else "los $sinDato partidos"} en BetMines" +
                            (if (e.ultima.isNotBlank()) ":\n${e.ultima}" else ".")
                }
                contenedor.addView(Panel.aviso(this, msg, if (e != null && e.ok) Panel.AMBAR else Panel.ROJO).apply { maxLines = 6 })
            }
            for ((p, m) in enCurso) agregarConFicha(p, Panel.filaEnCurso(this, p, m, duracion, fichas[p.nombre]), fichas, enJuego = true)
        }

        contenedor.addView(Panel.seccion(this, "VIENEN HOY",
            if (porJugar.isEmpty()) "ninguno" else "${porJugar.size}",
            if (porJugar.isEmpty()) Panel.TENUE else Panel.CIAN))
        if (porJugar.isEmpty()) {
            contenedor.addView(Panel.aviso(this, "Ya salieron todos los de hoy."))
        } else {
            for ((p, f) in porJugar) agregarConFicha(p, Panel.filaPorJugar(this, p, f), fichas, porJugar = true)
        }

        if (manana.isNotEmpty()) {
            contenedor.addView(Panel.seccion(this, "MAÑANA", "${manana.size}", Panel.MAGENTA))
            for ((p, f) in manana) contenedor.addView(Panel.filaManana(this, p, f))
        }

        if (esperando.isNotEmpty()) {
            contenedor.addView(Panel.seccion(this, "ESPERANDO RESULTADO", "${esperando.size}", Panel.MAGENTA))
            for ((p, d) in esperando) agregarConFicha(p, Panel.filaEsperando(this, p, duracion, d), fichas)
        }

        if (listos.isNotEmpty()) {
            val unders = listos.count { it.esUnder }
            contenedor.addView(Panel.seccion(
                this, "FINALIZADOS",
                "$unders/${listos.size} under", Panel.VERDE
            ))
            for (p in listos) agregarConFicha(p, Panel.filaFinal(this, p), fichas)
        }

        if (susp.isNotEmpty()) {
            contenedor.addView(Panel.seccion(this, "SUSPENDIDOS", "${susp.size}", Panel.MAGENTA))
            for (p in susp) contenedor.addView(Panel.filaSuspendido(this, p))
        }

        contenedor.addView(Panel.aviso(
            this,
            if (directo != null)
                "Datos directos de la PC (${AlertaService.via.ifBlank { "última lectura" }}) · ${dia.fecha} ${dia.enviado}\n" +
                        "Toca cualquier partido para ver sus estadísticas."
            else
                "Resumen de la PC de las ${dia.enviado} · ${dia.fecha} (por ntfy)\n" +
                        "Sin conexión directa con la PC: el minuto puede ser estimado por la hora de inicio."
        ))
    }

    /**
     * Pone la fila y, si está desplegada, el bloque de estadísticas debajo.
     * Tocar la fila la abre o la cierra.
     */
    private fun agregarConFicha(
        p: Partido, fila: android.view.View, fichas: Map<String, Ficha>, porJugar: Boolean = false,
        enJuego: Boolean = false
    ) {
        fila.setOnClickListener {
            if (!abiertos.remove(p.nombre)) abiertos.add(p.nombre)
            firmaPintada = ""          // obliga a redibujar en el siguiente tic
            refrescar()
        }
        contenedor.addView(fila)
        if (!abiertos.contains(p.nombre)) return
        val f = fichas[p.nombre]
        contenedor.addView(Panel.cabeceraPartido(this, p))
        contenedor.addView(
            when {
                f != null -> Panel.bloqueFicha(this, f, enJuego && !f.hayTarjetas && f.datos.isEmpty(), p.nota)
                enJuego -> Panel.sinFicha(this, "Las estadísticas en vivo todavía no llegan de BetMines." +
                        if (p.nota.isNotBlank()) "\nScarlet: ${p.nota}" else "")
                porJugar -> Panel.sinFicha(
                    this, "Empieza a las ${p.hora}${if (p.competicion.isNotBlank()) " · " + p.competicion else ""}.\n" +
                            "Sus estadísticas salen aquí en cuanto arranque."
                )
                else -> Panel.sinFicha(this)
            }
        )
    }

    private fun lineaDeEstado(): String {
        val conexion = when {
            !AlertaService.corriendo -> "apagado"
            AlertaService.conectado -> "conectado"
            else -> "reconectando…"
        }
        val directo = datosEn
        if (AlertaService.via.isNotBlank() && System.currentTimeMillis() - directo < 60_000L) {
            val seg = ((System.currentTimeMillis() - directo) / 1000L).toInt()
            return "$conexion · directo por ${AlertaService.via} · hace $seg s"
        }
        val recibido = estadoRecibidoEn
        val edad = if (recibido == 0L) "sin datos todavía" else {
            val min = ((System.currentTimeMillis() - recibido) / 60000L).toInt()
            when {
                min < 2 -> "actualizado ahora"
                min < 60 -> "actualizado hace $min min"
                else -> "actualizado hace ${min / 60} h"
            }
        }
        return "$conexion · $edad"
    }

    // ------------------------------------------------------------- ajustes

    private fun pintarAjustes() {
        val l = StringBuilder()
        l.append(
            when {
                !AlertaService.corriendo -> "● Apagado\n"
                AlertaService.conectado -> "● Conectado: esperando avisos de la PC\n"
                else -> "● Encendido, reconectando…\n"
            }
        )
        l.append("\nConexión directa con la PC:\n")
        l.append(marca(enlaceLan.isNotBlank()) + " Wifi de la casa ${enlaceLan.ifBlank { "(todavía no llega)" }}\n")
        l.append(marca(enlacePublico.isNotBlank()) + " Internet ${enlacePublico.removePrefix("https://").ifBlank { "(todavía no llega)" }}\n")
        l.append(if (AlertaService.via.isNotBlank()) "  → leyendo directo por ${AlertaService.via}\n"
                 else "  → sin conexión directa: todo llega por ntfy\n")
        l.append("\nPermisos:\n")
        l.append(marca(notificacionesOk()) + " Notificaciones\n")
        l.append(marca(superponerOk()) + " Mostrar sobre otras apps\n")
        l.append(marca(pantallaCompletaOk()) + " Alarma a pantalla completa\n")
        l.append(marca(bateriaOk()) + " Sin ahorro de batería\n")
        estado.text = l.toString()
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
                OkHttpClient.Builder().callTimeout(20, TimeUnit.SECONDS).build()
                    .newCall(
                        Request.Builder().url(servidor)
                            .post(cuerpo.toRequestBody("application/json".toMediaType())).build()
                    ).execute().use { it.isSuccessful }
            }.getOrDefault(false)
            mano.post {
                aviso(if (ok) "Aviso enviado, debe sonar en unos segundos" else "No se pudo enviar: revisa internet")
            }
        }.start()
    }

    /** Busca la PC: la dirección escrita en Ajustes si hay, si no recorre el wifi. */
    private fun buscarPc() {
        val c = campoCanal.text.toString().trim().ifBlank { canal }
        if (c.isBlank()) {
            aviso("Primero pega el canal")
            return
        }
        val escrita = Red.normalizar(campoPc.text.toString())
        aviso(if (escrita.isNotBlank()) "Probando $escrita…" else "Buscando tu PC en el wifi… (unos segundos)")
        Thread {
            val hallada = if (escrita.isNotBlank()) escrita.takeIf { Red.responde(it, c) }
            else runCatching { Red.buscarPc(this, c) }.getOrNull()
            mano.post {
                if (hallada != null) {
                    enlaceLan = hallada
                    campoPc.setText(hallada.removePrefix("http://").removeSuffix(":${Red.PUERTO}"))
                    if (canal.isBlank()) canal = c
                    if (!AlertaService.corriendo) AlertaService.arrancar(this)
                    aviso("¡Encontré tu PC! ${hallada.removePrefix("http://")}. En segundos salen los partidos.")
                } else {
                    aviso(
                        when {
                            Red.ipLocal(this) == null -> "No estás conectado a un wifi."
                            escrita.isNotBlank() -> "Esa dirección no contesta. ¿El vigilante está abierto? En la PC corre PERMITIR_CELULAR.bat"
                            else -> "No la encontré. ¿Vigilante abierto y mismo wifi? En la PC corre PERMITIR_CELULAR.bat"
                        }
                    )
                }
                firmaPintada = ""
            }
        }.start()
    }

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
            val i = Intent().setClassName(paquete, clase).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (packageManager.resolveActivity(i, 0) != null &&
                runCatching { startActivity(i) }.isSuccess
            ) {
                aviso("Busca MATRIX Alertas en la lista y actívalo")
                return
            }
        }
        aviso("Tu teléfono no tiene esa pantalla; se abre la ficha de la app")
        abrirAjustesApp()
    }

    private fun abrir(i: Intent) {
        runCatching { startActivity(i) }.onFailure { abrirAjustesApp() }
    }

    private fun abrirAjustesApp() {
        runCatching {
            startActivity(
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
            )
        }
    }

    private fun aviso(t: String) = Toast.makeText(this, t, Toast.LENGTH_LONG).show()
}
