package com.matrix.alertas

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Vuelve a encender la vigilancia:
 *  - al reiniciar el celular o actualizar la app,
 *  - y cada vez que el "vigía" comprueba que el servicio debería estar vivo
 *    (por si Android lo mató al deslizar la app fuera de recientes, o por
 *    ahorro de batería).
 */
class BootReceiver : BroadcastReceiver() {

    companion object {
        const val ACCION_REVIVIR = "com.matrix.alertas.REVIVIR"
    }

    override fun onReceive(context: Context, intent: Intent?) {
        val accion = intent?.action ?: return
        val toca = accion == Intent.ACTION_BOOT_COMPLETED ||
                accion == Intent.ACTION_MY_PACKAGE_REPLACED ||
                accion == ACCION_REVIVIR
        if (!toca) return
        if (context.encendido && context.canal.isNotBlank()) {
            // Puede fallar si el sistema no deja arrancar servicios en segundo
            // plano en ese momento; el vigía lo vuelve a intentar más tarde.
            runCatching { AlertaService.arrancar(context) }
        }
    }
}
