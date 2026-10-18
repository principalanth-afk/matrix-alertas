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
