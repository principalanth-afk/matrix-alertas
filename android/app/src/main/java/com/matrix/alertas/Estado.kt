package com.matrix.alertas

import org.json.JSONObject
import java.util.Calendar

/** Un partido del día, tal como lo manda la PC. */
data class Partido(
    val nombre: String,
    val competicion: String,
    val inicioMin: Int,          // minutos desde medianoche; -1 si no trae hora
    val gl: Int?,                // del Excel: lo que tú cargas, el registro oficial
    val gv: Int?,
    val suspendido: Boolean,
    val vivoGl: Int? = null,     // del marcador en vivo, solo para mirar
    val vivoGv: Int? = null,
    val vivoEstado: String = "", // vivo · descanso · fin · suspendido · "" (sin dato)
    val vivoMinuto: Int? = null,
    val dia: Int = 0             // 0 = hoy, 1 = mañana
) {
    val hayVivo: Boolean get() = vivoGl != null && vivoGv != null && vivoEstado.isNotEmpty()

    /** El marcador a mostrar: el del Excel si ya está, si no el de en vivo. */
    val marcadorGl: Int? get() = gl ?: vivoGl
    val marcadorGv: Int? get() = gv ?: vivoGv

    /** true si el marcador que se muestra viene del vivo y el Excel aún no lo tiene. */
    val soloVivo: Boolean get() = gl == null && vivoGl != null

    val hora: String
        get() = if (inicioMin < 0) "--:--"
        else String.format("%02d:%02d", inicioMin / 60, inicioMin % 60)

    val tieneResultado: Boolean get() = gl != null && gv != null
    val total: Int get() = (marcadorGl ?: 0) + (marcadorGv ?: 0)
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

/**
 * Minutos que faltan para que empiece, contando los días de por medio.
 * Para uno de mañana a las 15:30, visto a las 22:00 de hoy, son 17 h 30 min.
 */
fun faltaPara(p: Partido, ahoraMin: Int): Int =
    if (p.inicioMin < 0) 0 else (p.dia * 24 * 60 + p.inicioMin - ahoraMin).coerceAtLeast(0)

fun situacionDe(p: Partido, ahoraMin: Int, duracion: Int): Situacion = when {
    // Los de otro día no se juegan hoy: siempre están por jugar, aunque su
    // hora ya haya pasado en el reloj de hoy.
    p.dia > 0 -> Situacion.POR_JUGAR
    p.suspendido || p.vivoEstado == "suspendido" -> Situacion.SUSPENDIDO
    p.tieneResultado -> Situacion.LISTO
    // El marcador en vivo manda sobre el reloj estimado: si dice que terminó,
    // va a finalizados aunque el Excel todavía no lo tenga; si dice que sigue
    // en juego, se queda en vivo aunque ya hayan pasado los 115 minutos.
    p.vivoEstado == "fin" -> Situacion.LISTO
    p.vivoEstado == "vivo" || p.vivoEstado == "descanso" -> Situacion.EN_CURSO
    p.inicioMin < 0 -> Situacion.POR_JUGAR
    ahoraMin < p.inicioMin -> Situacion.POR_JUGAR
    ahoraMin <= p.inicioMin + duracion -> Situacion.EN_CURSO
    else -> Situacion.ESPERANDO
}

/** Un dato de la ficha: «Posesión  44 %  56 %». */
data class Dato(val nombre: String, val local: String, val visitante: String)

/** Las estadísticas de un partido, leídas de su página en BetMines. */
data class Ficha(
    val nombre: String,
    val gl: Int?,
    val gv: Int?,
    val minuto: Int?,
    val corners: Int?, val cambios: Int?, val amarillas: Int?, val rojas: Int?,
    val cornersV: Int?, val cambiosV: Int?, val amarillasV: Int?, val rojasV: Int?,
    val datos: List<Dato>,
    val rojasAnuladas: Int = 0,     // rojas que el VAR anuló (ya descontadas de rojas/rojasV)
    val previa: List<Dato> = emptyList()   // datos de antes del partido (del Excel de omega)
) {
    val hayTarjetas: Boolean get() = amarillas != null || rojas != null
}

/**
 * Lee el mensaje de estadísticas que manda la PC:
 *
 *     MATRIXF|22:15
 *     Belgrano vs River Plate|0|0|38|1,0,0,1|5,0,0,0|Posesión~35 %~65 %;...
 *
 * La llave es el nombre del partido, el mismo que va en el resumen del día.
 */
fun parsearFichas(texto: String?): Map<String, Ficha> {
    if (texto.isNullOrBlank()) return emptyMap()
    val lineas = texto.trim().lines()
    if (lineas.isEmpty() || !lineas[0].startsWith("MATRIXF")) return emptyMap()

    val salida = HashMap<String, Ficha>()
    for (i in 1 until lineas.size) {
        val c = lineas[i].split("|")
        if (c.size < 7) continue
        val cl = c[4].split(",")
        val cv = c[5].split(",")
        fun n(l: List<String>, j: Int) = l.getOrNull(j)?.trim()?.toIntOrNull()
        val datos = c[6].split(";").mapNotNull { d ->
            val t = d.split("~")
            if (t.size < 3 || t[0].isBlank()) null else Dato(t[0], t[1], t[2])
        }
        val nombre = c[0]
        salida[nombre] = Ficha(
            nombre = nombre,
            gl = c[1].toIntOrNull(), gv = c[2].toIntOrNull(), minuto = c[3].toIntOrNull(),
            corners = n(cl, 0), cambios = n(cl, 1), amarillas = n(cl, 2), rojas = n(cl, 3),
            cornersV = n(cv, 0), cambiosV = n(cv, 1), amarillasV = n(cv, 2), rojasV = n(cv, 3),
            datos = datos
        )
    }
    return salida
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
    // MATRIX1 fue el formato sin marcador en vivo y MATRIX2 el que no traía
    // los partidos de mañana; los dos se siguen aceptando.
    if (cab.size < 3 || (cab[0] != "MATRIX3" && cab[0] != "MATRIX2" && cab[0] != "MATRIX1")) return null

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
                suspendido = c[3] == "1",
                vivoGl = c.getOrNull(6)?.toIntOrNull(),
                vivoGv = c.getOrNull(7)?.toIntOrNull(),
                vivoEstado = c.getOrNull(8).orEmpty(),
                vivoMinuto = c.getOrNull(9)?.toIntOrNull(),
                dia = c.getOrNull(10)?.toIntOrNull() ?: 0
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


// ------------------------------------------------ lo que se lee directo de la PC (v1.2)

/** Todo lo que manda servidor_app.py: los partidos del día con su ficha. */
data class DatosApp(val dia: EstadoDia, val fichas: Map<String, Ficha>, val generado: String)

private fun JSONObject.entero(k: String): Int? {
    if (!has(k) || isNull(k)) return null
    return when (val v = opt(k)) {
        is Number -> v.toInt()
        is String -> v.trim().toIntOrNull()
        else -> null
    }
}

/**
 * Lee el JSON de /m/<canal>/datos:
 *   {"hoy":"19/10/2026","hora":"13:40","partidos":[{"nombre":…,"hora":"19:15","gl":null,…,
 *     "vivo":{"gl":0,"gv":0,"estado":"vivo","minuto":37},"ficha":{"rojas":0,…,"stats":[…]}}]}
 */
fun parsearDatos(texto: String?): DatosApp? {
    if (texto.isNullOrBlank()) return null
    val j = runCatching { JSONObject(texto) }.getOrNull() ?: return null
    val arr = j.optJSONArray("partidos") ?: return null
    val partidos = ArrayList<Partido>()
    val fichas = HashMap<String, Ficha>()
    for (i in 0 until arr.length()) {
        val o = arr.optJSONObject(i) ?: continue
        val nombre = o.optString("nombre")
        if (nombre.isBlank()) continue
        val hm = o.optString("hora").split(":")
        val min = if (hm.size == 2) {
            val h = hm[0].toIntOrNull() ?: -1
            val m = hm[1].toIntOrNull() ?: -1
            if (h in 0..23 && m in 0..59) h * 60 + m else -1
        } else -1
        val v = o.optJSONObject("vivo")
        partidos.add(
            Partido(
                nombre = nombre,
                competicion = o.optString("competicion"),
                inicioMin = min,
                gl = o.entero("gl"),
                gv = o.entero("gv"),
                suspendido = o.optBoolean("susp", false),
                vivoGl = v?.entero("gl"),
                vivoGv = v?.entero("gv"),
                vivoEstado = v?.optString("estado").orEmpty(),
                vivoMinuto = v?.entero("minuto"),
                dia = o.optInt("dia", 0)
            )
        )
        val previa = ArrayList<Dato>()
        val pr = o.optJSONArray("previa")
        if (pr != null) {
            for (k in 0 until pr.length()) {
                val d = pr.optJSONObject(k) ?: continue
                val n = d.optString("nombre")
                if (n.isNotBlank()) previa.add(Dato(n, d.optString("local"), d.optString("visitante")))
            }
        }
        val f = o.optJSONObject("ficha")
        if (f == null) {
            if (previa.isNotEmpty()) {
                fichas[nombre] = Ficha(nombre, null, null, null, null, null, null, null,
                    null, null, null, null, emptyList(), 0, previa)
            }
            continue
        }
        val datos = ArrayList<Dato>()
        val st = f.optJSONArray("stats")
        if (st != null) {
            for (k in 0 until st.length()) {
                val d = st.optJSONObject(k) ?: continue
                val n = d.optString("nombre")
                if (n.isNotBlank()) datos.add(Dato(n, d.optString("local"), d.optString("visitante")))
            }
        }
        fichas[nombre] = Ficha(
            nombre = nombre,
            gl = f.entero("gl"), gv = f.entero("gv"), minuto = f.entero("minuto"),
            corners = f.entero("corners"), cambios = f.entero("cambios"),
            amarillas = f.entero("amarillas"), rojas = f.entero("rojas"),
            cornersV = f.entero("cornersV"), cambiosV = f.entero("cambiosV"),
            amarillasV = f.entero("amarillasV"), rojasV = f.entero("rojasV"),
            datos = datos,
            rojasAnuladas = f.entero("rojasAnuladas") ?: 0,
            previa = previa
        )
    }
    return DatosApp(EstadoDia(j.optString("hora"), j.optString("hoy"), partidos), fichas, j.optString("generado"))
}
