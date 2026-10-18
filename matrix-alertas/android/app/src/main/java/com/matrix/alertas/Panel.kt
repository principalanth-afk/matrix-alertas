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
    fun filaEnCurso(c: Context, p: Partido, jugados: Int, duracion: Int): View {
        val reloj = relojDe(jugados)
        val color = when {
            reloj == "DESC" -> CIAN
            reloj == "90+" -> ROJO
            jugados > 60 -> AMBAR
            else -> VERDE
        }
        return fila(c).apply {
            addView(barra(c, jugados, duracion, color))
            addView(pastilla(c, reloj, color, 0xFF0B0D12.toInt()).apply {
                layoutParams = LinearLayout.LayoutParams(dp(c, 46), ViewGroup.LayoutParams.WRAP_CONTENT)
                    .apply { marginEnd = dp(c, 9) }
            })
            addView(LinearLayout(c).apply {
                orientation = LinearLayout.VERTICAL
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                addView(texto(c, p.nombre, 13.5f, TEXTO))
                addView(texto(c, "${p.hora} → ${finTexto(p, duracion)}   ${p.competicion}", 11f, TENUE))
            })
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
        addView(pastilla(c, "${p.gl}-${p.gv}", 0xFF1C2230.toInt(), if (under) VERDE else ROJO).apply {
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
            addView(texto(c, "${p.hora}   ${p.competicion}", 11f, TENUE))
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

    fun aviso(c: Context, t: String, color: Int = TENUE): View =
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
