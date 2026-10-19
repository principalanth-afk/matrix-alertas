package com.matrix.alertas

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Arma a mano las filas del panel de partidos. Se hace por código y no con
 * XML porque la cantidad de filas cambia cada vez que llega un resumen nuevo.
 */
object Panel {

    const val CIAN = 0xFF22D3EE.toInt()
    const val VERDE = 0xFF3ECF8E.toInt()
    const val AMBAR = 0xFFFFB84D.toInt()
    const val ROJO = 0xFFFF5C5C.toInt()
    const val MAGENTA = 0xFFC084FC.toInt()
    const val TEXTO = 0xFFE6E8EF.toInt()
    const val SUAVE = 0xFF9AA2B8.toInt()
    const val TENUE = 0xFF4A5268.toInt()
    const val FONDO_FILA = 0xFF141821.toInt()

    private fun dp(c: Context, v: Int) = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), c.resources.displayMetrics
    ).toInt()

    private fun texto(
        c: Context, t: String, tam: Float, color: Int,
        negrita: Boolean = false, mono: Boolean = false
    ) = TextView(c).apply {
        text = t
        setTextSize(TypedValue.COMPLEX_UNIT_SP, tam)
        setTextColor(color)
        if (negrita) setTypeface(typeface, android.graphics.Typeface.BOLD)
        if (mono) typeface = android.graphics.Typeface.MONOSPACE
        maxLines = 1
        ellipsize = android.text.TextUtils.TruncateAt.END
    }

    private fun pastilla(c: Context, t: String, fondo: Int, letra: Int): TextView =
        texto(c, t, 11f, letra, negrita = true, mono = true).apply {
            background = GradientDrawable().apply {
                cornerRadius = dp(c, 6).toFloat()
                setColor(fondo)
            }
            setPadding(dp(c, 7), dp(c, 3), dp(c, 7), dp(c, 3))
            gravity = Gravity.CENTER
        }

    private fun fila(c: Context): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        background = GradientDrawable().apply {
            cornerRadius = dp(c, 9).toFloat()
            setColor(FONDO_FILA)
        }
        setPadding(dp(c, 10), dp(c, 9), dp(c, 10), dp(c, 9))
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(c, 6) }
    }

    /** Encabezado de sección: punto de color, título y cantidad. */
    fun seccion(c: Context, titulo: String, cantidad: String, color: Int): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(c, 14); bottomMargin = dp(c, 8) }

            addView(View(c).apply {
                background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(color)
                }
                layoutParams = LinearLayout.LayoutParams(dp(c, 8), dp(c, 8))
                    .apply { marginEnd = dp(c, 8) }
            })
            addView(texto(c, titulo, 12.5f, color, negrita = true).apply {
                letterSpacing = 0.09f
            })
            addView(View(c).apply {
                setBackgroundColor(0xFF232838.toInt())
                layoutParams = LinearLayout.LayoutParams(0, dp(c, 1), 1f)
                    .apply { marginStart = dp(c, 10); marginEnd = dp(c, 10) }
            })
            addView(texto(c, cantidad, 11.5f, TENUE, mono = true))
        }

    /** Barra de avance del partido. */
    private fun barra(c: Context, jugados: Int, duracion: Int, color: Int): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            val frac = (jugados.toFloat() / duracion).coerceIn(0f, 1f)
            layoutParams = LinearLayout.LayoutParams(dp(c, 46), dp(c, 4))
                .apply { marginEnd = dp(c, 9) }
            background = GradientDrawable().apply {
                cornerRadius = dp(c, 2).toFloat()
                setColor(0xFF232838.toInt())
            }
            addView(View(c).apply {
                background = GradientDrawable().apply {
                    cornerRadius = dp(c, 2).toFloat()
                    setColor(color)
                }
                layoutParams = LinearLayout.LayoutParams(0, dp(c, 4), frac.coerceAtLeast(0.03f))
            })
            addView(View(c).apply {
                layoutParams = LinearLayout.LayoutParams(0, dp(c, 4), (1f - frac))
            })
        }

    /** Fila de un partido que se está jugando. */
    fun filaEnCurso(c: Context, p: Partido, jugados: Int, duracion: Int, ficha: Ficha? = null): View {
        val reloj = relojDe(jugados)
        val color = when {
            reloj == "DESC" -> CIAN
            reloj == "90+" -> ROJO
            jugados > 60 -> AMBAR
            else -> VERDE
        }
        // Si el minuto viene del marcador en vivo, se usa ese en vez del estimado.
        // Sin dato real se marca con «~»: es el minuto calculado con la hora de inicio, no el de BetMines.
        val etiqueta = if (p.vivoMinuto != null && p.vivoEstado == "vivo") "${p.vivoMinuto}'"
        else if (p.vivoEstado == "descanso") "DESC" else "~$reloj"
        return fila(c).apply {
            addView(barra(c, jugados, duracion, color))
            addView(pastilla(c, etiqueta, color, 0xFF0B0D12.toInt()).apply {
                layoutParams = LinearLayout.LayoutParams(dp(c, 46), ViewGroup.LayoutParams.WRAP_CONTENT)
                    .apply { marginEnd = dp(c, 8) }
            })
            if (p.hayVivo) {
                // El marcador de verdad, mientras se juega.
                addView(pastilla(c, "${p.vivoGl}-${p.vivoGv}", 0xFF1C2230.toInt(), TEXTO).apply {
                    layoutParams = LinearLayout.LayoutParams(dp(c, 42), ViewGroup.LayoutParams.WRAP_CONTENT)
                        .apply { marginEnd = dp(c, 9) }
                })
            }
            addView(LinearLayout(c).apply {
                orientation = LinearLayout.VERTICAL
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                addView(texto(c, p.nombre, 13.5f, TEXTO))
                val pie = if (p.hayVivo)
                    "${p.hora}   ${if (p.total <= 2) "va Under 2.5" else "ya es Over 2.5"}   ${p.competicion}"
                else "${p.hora} · sin marcador real todavía   ${p.competicion}"
                addView(texto(c, pie, 11f, if (p.hayVivo && p.total > 2) ROJO else if (p.hayVivo) TENUE else AMBAR))
            })
            // Las rojas, a la vista sin abrir el partido.
            val rojas = (ficha?.rojas ?: 0) + (ficha?.rojasV ?: 0)
            if (rojas > 0) {
                addView(pastilla(c, "■ $rojas", 0xFF3A1D22.toInt(), ROJO).apply {
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT
                    ).apply { marginStart = dp(c, 6) }
                })
            }
        }
    }

    /** Fila de un partido que todavía no empieza. */
    fun filaPorJugar(c: Context, p: Partido, falta: Int): View {
        val pronto = falta <= 15
        return fila(c).apply {
            addView(pastilla(
                c, if (falta < 60) "$falta min" else faltaTexto(falta),
                if (pronto) AMBAR else 0xFF1C2230.toInt(),
                if (pronto) 0xFF0B0D12.toInt() else CIAN
            ).apply {
                layoutParams = LinearLayout.LayoutParams(dp(c, 74), ViewGroup.LayoutParams.WRAP_CONTENT)
                    .apply { marginEnd = dp(c, 10) }
            })
            addView(LinearLayout(c).apply {
                orientation = LinearLayout.VERTICAL
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                addView(texto(c, p.nombre, 13.5f, TEXTO))
                addView(texto(c, "${p.hora}   ${p.competicion}", 11f, TENUE))
            })
        }
    }

    /** Fila de un partido de mañana: la hora y cuánto falta, en horas. */
    fun filaManana(c: Context, p: Partido, falta: Int): View = fila(c).apply {
        addView(pastilla(c, p.hora, 0xFF241E33.toInt(), MAGENTA).apply {
            layoutParams = LinearLayout.LayoutParams(dp(c, 56), ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { marginEnd = dp(c, 10) }
        })
        addView(LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            addView(texto(c, p.nombre, 13.5f, TEXTO))
            addView(texto(c, "en ${faltaTexto(falta)}   ${p.competicion}", 11f, TENUE))
        })
    }

    /** Fila de un partido que ya terminó pero sigue sin resultado cargado. */
    fun filaEsperando(c: Context, p: Partido, duracion: Int, desde: Int): View = fila(c).apply {
        addView(pastilla(c, "?", 0xFF1C2230.toInt(), MAGENTA).apply {
            layoutParams = LinearLayout.LayoutParams(dp(c, 32), ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { marginEnd = dp(c, 10) }
        })
        addView(LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            addView(texto(c, p.nombre, 13.5f, TEXTO))
            addView(texto(c, "terminó ~${finTexto(p, duracion)} · hace ${faltaTexto(desde)}", 11f, TENUE))
        })
    }

    /** Fila de un partido con marcador. */
    fun filaFinal(c: Context, p: Partido): View = fila(c).apply {
        val under = p.esUnder
        addView(pastilla(c, "${p.marcadorGl}-${p.marcadorGv}", 0xFF1C2230.toInt(),
            if (under) VERDE else ROJO).apply {
            layoutParams = LinearLayout.LayoutParams(dp(c, 46), ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { marginEnd = dp(c, 8) }
        })
        addView(pastilla(
            c, if (under) "UNDER" else "over",
            if (under) VERDE else 0xFF3A1D22.toInt(),
            if (under) 0xFF06231A.toInt() else ROJO
        ).apply {
            layoutParams = LinearLayout.LayoutParams(dp(c, 58), ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { marginEnd = dp(c, 10) }
        })
        addView(LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            addView(texto(c, p.nombre, 13.5f, TEXTO))
            // "sin cargar" avisa que el marcador es del vivo y el Excel todavía no lo tiene.
            val pie = if (p.soloVivo) "${p.hora}   sin cargar en el Excel   ${p.competicion}"
            else "${p.hora}   ${p.competicion}"
            addView(texto(c, pie, 11f, if (p.soloVivo) AMBAR else TENUE))
        })
    }

    fun filaSuspendido(c: Context, p: Partido): View = fila(c).apply {
        addView(pastilla(c, "SR", 0xFF2A2030.toInt(), MAGENTA).apply {
            layoutParams = LinearLayout.LayoutParams(dp(c, 46), ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { marginEnd = dp(c, 10) }
        })
        addView(texto(c, p.nombre, 13.5f, SUAVE).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
    }

    /** Una línea de la ficha: valor del local, nombre del dato, valor del visitante. */
    private fun lineaDato(c: Context, nombre: String, local: String, visitante: String,
                          colorL: Int = TEXTO, colorV: Int = TEXTO): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(c, 4), 0, dp(c, 4))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            )
            if (visitante.isBlank()) {
                // Un solo valor (p. ej. «Apuesta sugerida  Menos de 3.5»): nombre a la izquierda, valor a la derecha.
                addView(texto(c, nombre, 11.5f, SUAVE).apply {
                    layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                })
                addView(texto(c, local, 12.5f, colorL, negrita = true, mono = true).apply {
                    gravity = Gravity.END
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT
                    ).apply { marginStart = dp(c, 8) }
                })
                return@apply
            }
            // Valores largos (la racha «G E P G G») necesitan más ancho que un número.
            val ancho = dp(c, if (maxOf(local.length, visitante.length) > 6) 88 else 52)
            addView(texto(c, local, 12.5f, colorL, negrita = true, mono = true).apply {
                gravity = Gravity.START
                layoutParams = LinearLayout.LayoutParams(ancho, ViewGroup.LayoutParams.WRAP_CONTENT)
            })
            addView(texto(c, nombre, 11.5f, SUAVE).apply {
                gravity = Gravity.CENTER
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
            addView(texto(c, visitante, 12.5f, colorV, negrita = true, mono = true).apply {
                gravity = Gravity.END
                layoutParams = LinearLayout.LayoutParams(ancho, ViewGroup.LayoutParams.WRAP_CONTENT)
            })
        }

    /** Una fila de la lista de eventos: lo del local | minuto | lo del visitante. */
    private fun lineaEvento(c: Context, minuto: String, local: String, visitante: String, color: Int): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(c, 3), 0, dp(c, 3))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            )
            addView(texto(c, local, 11.5f, color).apply {
                gravity = Gravity.START
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
            addView(texto(c, minuto, 11.5f, SUAVE, mono = true).apply {
                gravity = Gravity.CENTER
                layoutParams = LinearLayout.LayoutParams(dp(c, 52), ViewGroup.LayoutParams.WRAP_CONTENT)
            })
            addView(texto(c, visitante, 11.5f, color).apply {
                gravity = Gravity.END
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
        }

    /**
     * Encabezado del partido abierto, como en BetMines: el local a la izquierda,
     * el recuadro del centro con el marcador y el minuto, y el visitante a la
     * derecha. Así se sabe de quién es cada columna de las estadísticas.
     */
    fun cabeceraPartido(c: Context, p: Partido): View = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        background = GradientDrawable().apply {
            cornerRadius = dp(c, 9).toFloat()
            setColor(0xFF10141C.toInt())
        }
        setPadding(dp(c, 10), dp(c, 10), dp(c, 10), dp(c, 10))
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(c, 2); topMargin = -dp(c, 2) }

        val partes = p.nombre.split(" vs ", limit = 2)
        val local = partes.getOrElse(0) { p.nombre }.trim()
        val visita = partes.getOrElse(1) { "" }.trim()

        fun nombre(t: String, g: Int) = texto(c, t, 13f, TEXTO, negrita = true).apply {
            maxLines = 2
            gravity = g
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        addView(nombre(local, Gravity.START or Gravity.CENTER_VERTICAL))

        // El recuadro del centro: marcador grande y, debajo, minuto / descanso / final / hora.
        val gl = p.marcadorGl
        val gv = p.marcadorGv
        val marcador = if (gl != null && gv != null) "$gl - $gv" else "vs"
        val debajo = when {
            p.suspendido || p.vivoEstado == "suspendido" -> "SUSP."
            p.tieneResultado || p.vivoEstado == "fin" -> "FINAL"
            p.vivoEstado == "descanso" -> "DESCANSO"
            p.vivoEstado == "vivo" && p.vivoMinuto != null -> "${p.vivoMinuto}'"
            else -> p.hora
        }
        val colorMarcador = when {
            p.vivoEstado == "vivo" || p.vivoEstado == "descanso" -> ROJO
            p.tieneResultado || p.vivoEstado == "fin" -> if (p.esUnder) VERDE else ROJO
            else -> CIAN
        }
        addView(LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            background = GradientDrawable().apply {
                cornerRadius = dp(c, 8).toFloat()
                setColor(0xFF1C2230.toInt())
            }
            setPadding(dp(c, 12), dp(c, 6), dp(c, 12), dp(c, 6))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { marginStart = dp(c, 8); marginEnd = dp(c, 8) }
            addView(texto(c, marcador, 18f, colorMarcador, negrita = true, mono = true).apply {
                gravity = Gravity.CENTER
            })
            addView(texto(c, debajo, 10.5f, SUAVE, mono = true).apply { gravity = Gravity.CENTER })
        })
        addView(nombre(visita, Gravity.END or Gravity.CENTER_VERTICAL))
    }

    /**
     * El bloque de estadísticas que se abre al tocar un partido.
     * Las tarjetas van primero, y las rojas en rojo: son las que cambian el juego.
     */
    fun bloqueFicha(c: Context, f: Ficha, enJuego: Boolean = false, nota: String = ""): View = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        background = GradientDrawable().apply {
            cornerRadius = dp(c, 9).toFloat()
            setColor(0xFF10141C.toInt())
        }
        setPadding(dp(c, 12), dp(c, 10), dp(c, 12), dp(c, 10))
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(c, 8); topMargin = -dp(c, 2) }

        if (f.hayTarjetas && f.minuto != null && f.gl != null && f.gv != null) {
            addView(texto(c, "EN VIVO DE BETMINES · ${f.gl} - ${f.gv} · min ${f.minuto}", 11f, ROJO, negrita = true).apply {
                letterSpacing = 0.06f
                setPadding(0, 0, 0, dp(c, 4))
            })
        }
        if (f.hayTarjetas) {
            val rl = f.rojas ?: 0
            val rv = f.rojasV ?: 0
            addView(lineaDato(c, "rojas", "$rl", "$rv",
                if (rl > 0) ROJO else TENUE, if (rv > 0) ROJO else TENUE))
            if (f.rojasAnuladas > 0) {
                addView(lineaDato(c, "rojas anuladas por el VAR", "${f.rojasAnuladas}", "", SUAVE, SUAVE))
            }
            addView(lineaDato(c, "amarillas", "${f.amarillas ?: 0}", "${f.amarillasV ?: 0}",
                AMBAR, AMBAR))
            addView(lineaDato(c, "córners", "${f.corners ?: 0}", "${f.cornersV ?: 0}"))
            addView(View(c).apply {
                setBackgroundColor(0xFF232838.toInt())
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(c, 1)
                ).apply { topMargin = dp(c, 6); bottomMargin = dp(c, 6) }
            })
        }
        for (d in f.datos) addView(lineaDato(c, d.nombre, d.local, d.visitante))
        if (f.eventos.isNotEmpty()) {
            // La lista de eventos como en BetMines: lo del local a la izquierda, lo del visitante a la derecha.
            addView(View(c).apply {
                setBackgroundColor(0xFF232838.toInt())
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(c, 1)
                ).apply { topMargin = dp(c, 8); bottomMargin = dp(c, 4) }
            })
            addView(texto(c, "EVENTOS", 11f, CIAN, negrita = true).apply {
                letterSpacing = 0.09f
                setPadding(0, dp(c, 2), 0, dp(c, 4))
            })
            for (e in f.eventos) {
                val (marca, color) = when (e.tipo) {
                    "roja" -> "■ roja" to ROJO
                    "roja2" -> "■ 2ª amarilla" to ROJO
                    "amarilla" -> "■ amarilla" to AMBAR
                    "gol" -> "● gol" to VERDE
                    "autogol" -> "● autogol" to VERDE
                    "penal fallado" -> "○ penal fallado" to SUAVE
                    "cambio" -> "⇄ cambio" to SUAVE
                    "var" -> "VAR" to MAGENTA
                    else -> e.tipo to SUAVE
                }
                val txt = if (e.jugador.isNotBlank()) "$marca  ${e.jugador}" else marca
                addView(lineaEvento(c, e.minTxt, if (e.lado == "V") "" else txt, if (e.lado == "V") txt else "", color))
            }
        }
        if (!f.hayTarjetas && f.datos.isEmpty()) {
            val t = when {
                enJuego -> "Las estadísticas en vivo todavía no llegan de BetMines." +
                        (if (nota.isNotBlank()) "\nScarlet: $nota" else "\nMira el aviso de arriba.")
                f.previa.isEmpty() -> "Sin estadísticas todavía"
                else -> "Estadísticas en vivo: salen cuando el partido esté en juego"
            }
            addView(texto(c, t, 12f, if (enJuego) AMBAR else TENUE).apply { maxLines = 4 })
        }
        if (f.previa.isNotEmpty()) {
            // Lo de antes del partido, del Excel de omega: posiciones, cuotas, medias, H2H…
            addView(View(c).apply {
                setBackgroundColor(0xFF232838.toInt())
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(c, 1)
                ).apply { topMargin = dp(c, 8); bottomMargin = dp(c, 4) }
            })
            addView(texto(c, "PREVIA DEL PARTIDO", 11f, CIAN, negrita = true).apply {
                letterSpacing = 0.09f
                setPadding(0, dp(c, 2), 0, dp(c, 4))
            })
            for (d in f.previa) addView(lineaDato(c, d.nombre, d.local, d.visitante, SUAVE, SUAVE))
        }
    }

    /** Aviso de que ese partido aún no tiene ficha. */
    fun sinFicha(c: Context, t: String = "Todavía no he leído sus estadísticas"): View = texto(c, t, 11.5f, TENUE)
        .apply {
            maxLines = 3
            setPadding(dp(c, 12), dp(c, 2), dp(c, 12), dp(c, 10))
        }

    fun aviso(c: Context, t: String, color: Int = TENUE): TextView =
        texto(c, t, 12f, color).apply {
            maxLines = 4
            setPadding(dp(c, 4), dp(c, 6), dp(c, 4), dp(c, 10))
        }

    private fun finTexto(p: Partido, duracion: Int): String {
        val f = p.finMin(duracion)
        if (f < 0) return "--:--"
        val m = f % (24 * 60)
        return String.format("%02d:%02d", m / 60, m % 60)
    }
}
