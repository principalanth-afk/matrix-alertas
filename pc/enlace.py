# -*- coding: utf-8 -*-
"""
enlace.py — las direcciones por donde la app del celular llega a la PC.

  · wifi:  http://192.168.x.x:8782   (cuando el celular está en la misma red)
  · túnel: https://algo.trycloudflare.com   (desde cualquier lado, con datos)

El túnel es de Cloudflare, gratis y SIN cuenta: el programa cloudflared abre
una salida desde tu PC y Cloudflare le da una dirección pública al azar. La
dirección cambia cada vez que se reinicia, por eso el vigilante se la manda a
la app por ntfy (un solo mensaje cada vez que cambia).

Si cloudflared no está, se descarga solo (una vez, ~50 MB, desde la página
oficial de Cloudflare en GitHub) y se guarda al lado de este archivo.
Si Cloudflare falla varias veces seguidas, se prueba localhost.run, que usa el
programa ssh que ya trae Windows 10/11.

Nada de esto abre tu PC a internet entera: el túnel solo lleva al puerto 8782,
y ese servidor contesta únicamente si la dirección trae tu canal privado.
"""

import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
URL_CLOUDFLARED = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
                   "cloudflared-windows-amd64.exe")
RE_CLOUDFLARE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
RE_LHR = re.compile(r"https://[a-z0-9-]+\.(?:lhr\.life|localhost\.run)")

_lock = threading.Lock()
_estado = {"publico": "", "metodo": "", "proceso": None, "fallos": 0, "detalle": "", "hilo": None,
           "parar": False}
_registro = None


def _log(txt):
    if _registro:
        try:
            _registro(txt)
            return
        except Exception:
            pass
    print(txt, flush=True)


def ip_local():
    """La IP de esta PC en la red de la casa (sin mandar nada: el socket UDP no conecta de verdad)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = ""
    finally:
        s.close()
    if ip.startswith("127.") or not ip:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = ""
    return "" if ip.startswith("127.") else ip


def enlaces(puerto):
    """{'lan': 'http://192.168.1.20:8782', 'publico': 'https://….trycloudflare.com', 'metodo': …}"""
    ip = ip_local()
    with _lock:
        return {"lan": f"http://{ip}:{puerto}" if ip else "", "publico": _estado["publico"],
                "metodo": _estado["metodo"], "detalle": _estado["detalle"]}


# ------------------------------------------------------------------ cloudflared

def _buscar_cloudflared():
    for nombre in ("cloudflared.exe", "cloudflared"):
        local = os.path.join(AQUI, nombre)
        if os.path.exists(local):
            return local
    return shutil.which("cloudflared")


def _descargar_cloudflared():
    if os.name != "nt":
        return None
    destino = os.path.join(AQUI, "cloudflared.exe")
    tmp = destino + ".descargando"
    _log("Descargo cloudflared (el túnel gratis de Cloudflare para que la app llegue a la PC)…")
    try:
        req = urllib.request.Request(URL_CLOUDFLARED, headers={"User-Agent": "MATRIX-Alertas"})
        with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1024 * 256)
        if os.path.getsize(tmp) < 5_000_000:
            raise OSError("el archivo descargado está incompleto")
        os.replace(tmp, destino)
        _log("   listo: cloudflared.exe quedó en la carpeta pc.")
        return destino
    except Exception as e:
        _log(f"   no pude descargar cloudflared ({type(e).__name__}: {e}).")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None


def _sin_ventana():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _lanzar(cmd, regex, metodo, espera=45):
    """Arranca el túnel y espera a que diga su dirección. Devuelve el proceso o None."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=_sin_ventana(),
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError as e:
        _log(f"   no pude arrancar {metodo} ({e}).")
        return None
    encontrado = threading.Event()

    def leer():
        for linea in proc.stdout:
            m = regex.search(linea)
            if m:
                with _lock:
                    if _estado["publico"] != m.group(0):
                        _estado["publico"] = m.group(0)
                        _estado["metodo"] = metodo
                encontrado.set()
        # el proceso se cerró
        with _lock:
            if _estado["proceso"] is proc:
                _estado["publico"] = ""

    threading.Thread(target=leer, daemon=True).start()
    if encontrado.wait(espera):
        return proc
    try:
        proc.kill()
    except OSError:
        pass
    return None


def _cmd_cloudflared(puerto):
    exe = _buscar_cloudflared() or _descargar_cloudflared()
    if not exe:
        return None
    return [exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{puerto}"]


def _cmd_localhost_run(puerto):
    ssh = shutil.which("ssh")
    if not ssh:
        return None
    return [ssh, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=" + os.devnull,
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3", "-o", "ExitOnForwardFailure=yes",
            "-R", f"80:127.0.0.1:{puerto}", "nokey@localhost.run"]


def _mantener(puerto, preferido):
    """Hilo que mantiene el túnel arriba: si se cae, lo vuelve a levantar."""
    espera = 10
    while not _estado["parar"]:
        metodos = ["cloudflared", "localhost.run"] if preferido != "localhost.run" else ["localhost.run", "cloudflared"]
        if _estado["fallos"] >= 3:
            metodos.reverse()
        proc = None
        for metodo in metodos:
            cmd = _cmd_cloudflared(puerto) if metodo == "cloudflared" else _cmd_localhost_run(puerto)
            if not cmd:
                continue
            proc = _lanzar(cmd, RE_CLOUDFLARE if metodo == "cloudflared" else RE_LHR, metodo)
            if proc:
                with _lock:
                    _estado["proceso"] = proc
                    _estado["detalle"] = ""
                    _estado["fallos"] = 0
                _log(f"Enlace para el celular fuera de casa: {_estado['publico']} ({metodo})")
                break
            with _lock:
                _estado["fallos"] += 1
                _estado["detalle"] = f"{metodo} no dio dirección"
        if not proc:
            with _lock:
                _estado["publico"] = ""
                if not _estado["detalle"]:
                    _estado["detalle"] = "sin túnel (no hay cloudflared ni ssh)"
            time.sleep(min(600, espera))
            espera = min(600, espera * 2)
            continue
        espera = 10
        while not _estado["parar"] and proc.poll() is None:
            time.sleep(5)
        with _lock:
            _estado["publico"] = ""
            _estado["proceso"] = None
        if not _estado["parar"]:
            _log("El túnel se cerró; lo vuelvo a abrir.")
            time.sleep(5)


def iniciar(puerto, metodo="cloudflared", registro=None):
    """Arranca (una sola vez) el hilo que mantiene el túnel. metodo: cloudflared · localhost.run · ninguno."""
    global _registro
    if registro:
        _registro = registro
    if str(metodo).strip().lower() in ("ninguno", "no", "0", ""):
        with _lock:
            _estado["detalle"] = "apagado en config.ini (solo wifi)"
        return
    with _lock:
        if _estado["hilo"] is not None:
            return
        _estado["parar"] = False
        _estado["hilo"] = threading.Thread(target=_mantener, args=(int(puerto), metodo), daemon=True)
        _estado["hilo"].start()


def detener():
    with _lock:
        _estado["parar"] = True
        proc = _estado["proceso"]
    if proc is not None:
        try:
            proc.terminate()
        except OSError:
            pass
