package com.matrix.alertas

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Vuelve a encender la vigilancia cuando se reinicia el celular o se actualiza la app. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val accion = intent?.action ?: return
        if (accion == Intent.ACTION_BOOT_COMPLETED || accion == Intent.ACTION_MY_PACKAGE_REPLACED) {
            if (context.encendido && context.canal.isNotBlank()) {
                AlertaService.arrancar(context)
            }
        }
    }
}
