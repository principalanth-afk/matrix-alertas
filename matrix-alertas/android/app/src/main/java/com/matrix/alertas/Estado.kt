package com.matrix.alertas

import java.util.Calendar

/** Un partido del día, tal como lo manda la PC. */
data class Partido(
    val nombre: String,
    val competicion: String,
    val inicioMin: Int,          // minutos desde medianoche; -1 si no trae hora
    val gl: Int?,
    val gv: Int?,
    val suspendido: Boolean
) {
    val hora: String
        get() = if (inicioMin < 0) "--:--"
        else String.format("%02d:%02d", inicioMin / 60, inicioMin % 60)

    val tieneResultado: Boolean get() = gl != null && gv != null
    val total: Int get() = (gl ?: 0) + (gv ?: 0)
    val esUnder: Boolean get() = total <= 2

    /** Hora a la que debería terminar, en minutos desde medianoche. */
    fun finMin(duracion: Int) = if (inicioMin < 0) -1 else inicioMin + duracion
}

/** El resumen completo del día. */
data class EstadoDia(
    val enviado: String,
    val fecha: String,
    val partidos: List<Partido>
)

/** Las cinco situaciones en que puede estar un partido. */
enum class Situacion { EN_CURSO, POR_JUGAR, ESPERANDO, LISTO, SUSPENDIDO }

fun situacionDe(p: Partido, ahoraMin: Int, duracion: Int): Situacion = when {
    p.suspendido -> Situacion.SUSPENDIDO
    p.tieneResultado -> Situacion.LISTO
    p.inicioMin < 0 -> Situacion.POR_JUGAR
    ahoraMin < p.inicioMin -> Situacion.POR_JUGAR
    ahoraMin <= p.inicioMin + duracion -> Situacion.EN_CURSO
    else -> Situacion.ESPERANDO
}

/** Minutos que hay ahora mismo desde medianoche. */
fun minutosDeAhora(): Int {
    val c = Calendar.getInstance()
    return c.get(Calendar.HOUR_OF_DAY) * 60 + c.get(Calendar.MINUTE)
}

/**
 * Lee el mensaje que manda la PC:
 *
 *     MATRIX1|15:30|17/10/2026
 *     08:00|1|2|0|Kedus Giorgis vs Ethiopia Bunna|Premier League
 *
 * Devuelve null si no es un resumen válido.
 */
fun parsearEstado(texto: String?): EstadoDia? {
    if (texto.isNullOrBlank()) return null
    val lineas = texto.trim().lines()
    if (lineas.isEmpty()) return null

    val cab = lineas[0].split("|")
    if (cab.size < 3 || cab[0] != "MATRIX1") return null

    val partidos = ArrayList<Partido>()
    for (i in 1 until lineas.size) {
        val c = lineas[i].split("|")
        if (c.size < 6) continue
        val hm = c[0].split(":")
        val min = if (hm.size == 2) {
            (hm[0].toIntOrNull() ?: -1).let { h ->
                val m = hm[1].toIntOrNull() ?: -1
                if (h in 0..23 && m in 0..59) h * 60 + m else -1
            }
        } else -1
        partidos.add(
            Partido(
                nombre = c[4],
                competicion = c[5],
                inicioMin = min,
                gl = c[1].toIntOrNull(),
                gv = c[2].toIntOrNull(),
                suspendido = c[3] == "1"
            )
        )
    }
    return EstadoDia(enviado = cab[1], fecha = cab[2], partidos = partidos)
}

/**
 * Minuto de juego aproximado, descontando los 15 del entretiempo.
 * Devuelve el texto que se muestra en la etiqueta.
 */
fun relojDe(minutosJugados: Int): String = when {
    minutosJugados <= 45 -> "$minutosJugados'"
    minutosJugados <= 60 -> "DESC"
    minutosJugados - 15 >= 90 -> "90+"
    else -> "${minutosJugados - 15}'"
}

/** '95' -> '1 h 35 min' ; '40' -> '40 min' */
fun faltaTexto(minutos: Int): String =
    if (minutos < 60) "$minutos min"
    else "${minutos / 60} h ${String.format("%02d", minutos % 60)} min"
