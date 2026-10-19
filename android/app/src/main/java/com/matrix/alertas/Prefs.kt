package com.matrix.alertas

import android.content.Context

/**
 * Guarda el canal privado y el servidor. Nada más: la app no almacena partidos,
 * solo escucha lo que le manda la PC.
 */
private const val ARCHIVO_PREFS = "matrix_alertas"

private fun Context.prefs() = getSharedPreferences(ARCHIVO_PREFS, Context.MODE_PRIVATE)

var Context.canal: String
    get() = prefs().getString("canal", "") ?: ""
    set(v) {
        prefs().edit().putString("canal", v.trim()).apply()
    }

var Context.servidor: String
    get() = prefs().getString("servidor", "https://ntfy.sh") ?: "https://ntfy.sh"
    set(v) {
        val limpio = v.trim().trimEnd('/').ifBlank { "https://ntfy.sh" }
        prefs().edit().putString("servidor", limpio).apply()
    }

/** Si el usuario encendió las alertas, para volver a levantar el servicio al reiniciar. */
var Context.encendido: Boolean
    get() = prefs().getBoolean("encendido", false)
    set(v) {
        prefs().edit().putBoolean("encendido", v).apply()
    }

/** Marca de tiempo del último aviso recibido, para no perder ninguno al reconectar. */
var Context.ultimoMensaje: Long
    get() = prefs().getLong("ultimo", 0L)
    set(v) {
        prefs().edit().putLong("ultimo", v).apply()
    }

/** Último resumen del día que mandó la PC, para pintarlo al abrir la app. */
var Context.ultimoEstado: String
    get() = prefs().getString("estado", "") ?: ""
    set(v) {
        prefs().edit().putString("estado", v).apply()
    }

/** Cuándo llegó ese resumen (para avisar si está viejo). */
var Context.estadoRecibidoEn: Long
    get() = prefs().getLong("estado_en", 0L)
    set(v) {
        prefs().edit().putLong("estado_en", v).apply()
    }

/** Las estadísticas de los partidos en juego, para desplegarlas al tocarlos. */
var Context.ultimasFichas: String
    get() = prefs().getString("fichas", "") ?: ""
    set(v) {
        prefs().edit().putString("fichas", v).apply()
    }

// ------------------------------------------------ conexión directa con la PC (v1.2)

/** Dirección de la PC en el wifi de la casa, p. ej. http://192.168.1.20:8782 (la manda el vigilante). */
var Context.enlaceLan: String
    get() = prefs().getString("enlace_lan", "") ?: ""
    set(v) {
        prefs().edit().putString("enlace_lan", v.trim().trimEnd('/')).apply()
    }

/** Dirección del túnel, p. ej. https://algo.trycloudflare.com (cambia cuando la PC se reinicia). */
var Context.enlacePublico: String
    get() = prefs().getString("enlace_publico", "") ?: ""
    set(v) {
        prefs().edit().putString("enlace_publico", v.trim().trimEnd('/')).apply()
    }

/** Lo último que se leyó directo de la PC (JSON con todos los partidos y sus estadísticas). */
var Context.datosApp: String
    get() = prefs().getString("datos_app", "") ?: ""
    set(v) {
        prefs().edit().putString("datos_app", v).apply()
    }

var Context.datosEn: Long
    get() = prefs().getLong("datos_en", 0L)
    set(v) {
        prefs().edit().putLong("datos_en", v).apply()
    }

/** Hasta qué alarma del buzón de la PC ya se mostró. */
var Context.ackApp: Long
    get() = prefs().getLong("ack_app", 0L)
    set(v) {
        prefs().edit().putLong("ack_app", v).apply()
    }

/** Identidad de la PC (si cambia, la cuenta de alarmas vuelve a empezar). */
var Context.pcId: String
    get() = prefs().getString("pc_id", "") ?: ""
    set(v) {
        prefs().edit().putString("pc_id", v).apply()
    }
