package com.matrix.alertas

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.Inet4Address
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Encontrar la PC del vigilante sin depender de ntfy.
 *
 * En la casa, el celular y la PC están en el mismo wifi: se prueban las 254
 * direcciones de esa red (192.168.1.1 … 192.168.1.254) buscando la que conteste
 * en el puerto 8782 con TU canal. Tarda unos segundos y no necesita internet.
 */
object Red {

    const val PUERTO = 8782

    /** La IP del celular en el wifi (o cable), o null si no está en un wifi. */
    fun ipLocal(ctx: Context): String? {
        val cm = ctx.getSystemService(ConnectivityManager::class.java) ?: return null
        val red = cm.activeNetwork ?: return null
        val caps = cm.getNetworkCapabilities(red) ?: return null
        val enCasa = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
        if (!enCasa) return null
        val lp = cm.getLinkProperties(red) ?: return null
        return lp.linkAddresses.map { it.address }
            .filterIsInstance<Inet4Address>()
            .firstOrNull { !it.isLoopbackAddress }
            ?.hostAddress
    }

    /** «192.168.1.20» → «http://192.168.1.20:8782». Acepta también la dirección completa. */
    fun normalizar(texto: String): String {
        var s = texto.trim().trimEnd('/')
        if (s.isBlank()) return ""
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://$s"
        val resto = s.substringAfter("://")
        if (!Regex(":\\d+$").containsMatchIn(resto) && s.startsWith("http://")) s += ":$PUERTO"
        return s
    }

    private val cliente: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(700, TimeUnit.MILLISECONDS)
            .readTimeout(1500, TimeUnit.MILLISECONDS)
            .callTimeout(2500, TimeUnit.MILLISECONDS)
            .retryOnConnectionFailure(false)
            .build()
    }

    /** ¿En esa dirección está el vigilante con ESTE canal? */
    fun responde(base: String, canal: String): Boolean = runCatching {
        cliente.newCall(Request.Builder().url("$base/m/${Uri.encode(canal)}/ping").build())
            .execute().use { it.isSuccessful }
    }.getOrDefault(false)

    /**
     * Recorre la red del wifi buscando la PC. Devuelve «http://ip:8782» o null.
     * Tarda entre 3 y 10 segundos. No llamar desde el hilo de la pantalla.
     */
    fun buscarPc(ctx: Context, canal: String): String? {
        if (canal.isBlank()) return null
        val ip = ipLocal(ctx) ?: return null
        val red = ip.substringBeforeLast(".")
        val propio = ip.substringAfterLast(".").toIntOrNull()
        val encontrado = AtomicReference<String?>(null)
        val pool = Executors.newFixedThreadPool(48)
        for (n in 1..254) {
            if (n == propio) continue
            pool.execute {
                if (encontrado.get() == null) {
                    val base = "http://$red.$n:$PUERTO"
                    if (responde(base, canal)) encontrado.compareAndSet(null, base)
                }
            }
        }
        pool.shutdown()
        runCatching { pool.awaitTermination(25, TimeUnit.SECONDS) }
        pool.shutdownNow()
        return encontrado.get()
    }
}
