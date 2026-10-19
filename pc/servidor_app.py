# -*- coding: utf-8 -*-
"""
servidor_app.py — la conexión DIRECTA entre la PC y la app del celular.

Por qué existe: ntfy.sh gratis deja mandar unos 250 mensajes al día. Si el
resumen del día y las estadísticas viajan por ntfy cada minuto, a media tarde
se acaba el cupo y ya no sale ni una alarma (ni gol, ni roja, ni el aviso de
los 15 minutos). Por aquí no hay límite: la app viene a buscar los datos.

    celular  ──GET /m/<canal>/datos──►  PC (este servidor, puerto 8782)

  · En casa la app entra por el wifi (http://192.168.x.x:8782).
  · Fuera de casa entra por el túnel que arma enlace.py (https://….trycloudflare.com).

Qué ofrece:
  /m/<canal>/datos?ack=N   todos los partidos del día con marcador, minuto y
                           estadísticas, más las alarmas pendientes (eventos).
  /m/<canal>/ack?n=N       la app confirma que ya mostró los eventos hasta N.
  /m/<canal>/ping          para probar que la conexión funciona.

EL BUZÓN DE ALARMAS. Cada aviso (gol, roja, inicio, final…) entra aquí con un
número. Si la app lo recoge y lo confirma, ntfy no se usa. Si en 45 segundos
nadie lo confirmó (el celular está sin datos, la PC sin túnel…), se manda por
ntfy como siempre. Así la alarma llega igual, y el cupo de ntfy casi no se toca.

Seguridad: el canal es la llave. Sin el canal en la dirección, todo da 404.
Aquí NO se escribe en el Excel.
"""

import json
import secrets
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUERTO = 8782
ESPERA_ACK_SEG = 45          # si la app no confirma en este rato, va por ntfy
GUARDAR_EVENTOS_SEG = 3 * 3600

_lock = threading.Lock()
_srv = None
_hilo_buzon = None
_estado = {
    "canal": "",
    "id": secrets.token_hex(4),   # cambia si se borra estado_avisos.json: la app reinicia su cuenta
    "datos": None,           # dict con los partidos (lo arma el vigilante)
    "datos_txt": b"",
    "eventos": [],           # [{n, t, titulo, texto, prioridad, tipo, clave, ntfy, ack}]
    "serie": 0,
    "ack": 0,                # el último evento que la app confirmó
    "ultimo_telefono": 0.0,  # la última vez que la app vino a buscar datos
    "telefono_ip": "",
    "via": "",               # «wifi» o «túnel»
}
_respaldo = None             # función(evento) que lo manda por ntfy; la pone el vigilante
_registro = None


def _log(txt):
    if _registro:
        try:
            _registro(txt)
            return
        except Exception:
            pass
    print(txt, flush=True)


def _cargar_estado(guardado):
    """Recupera la serie y el último ack para que reiniciar no repita alarmas."""
    if not isinstance(guardado, dict):
        return
    with _lock:
        _estado["serie"] = max(_estado["serie"], int(guardado.get("serie") or 0))
        _estado["ack"] = max(_estado["ack"], int(guardado.get("ack") or 0))
        if guardado.get("id"):
            _estado["id"] = str(guardado["id"])


def para_guardar():
    with _lock:
        return {"serie": _estado["serie"], "ack": _estado["ack"], "id": _estado["id"]}


# ------------------------------------------------------------------ servidor

class _H(BaseHTTPRequestHandler):
    server_version = "MATRIX"

    def log_message(self, *a):
        pass

    def _resp(self, cuerpo, tipo="application/json; charset=utf-8", codigo=200):
        b = cuerpo if isinstance(cuerpo, bytes) else str(cuerpo).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        try:
            self.wfile.write(b)
        except OSError:
            pass

    def do_GET(self):
        ruta, _, consulta = self.path.partition("?")
        partes = [p for p in ruta.split("/") if p]
        params = {}
        for par in consulta.split("&"):
            k, _, v = par.partition("=")
            if k:
                params[k] = v
        with _lock:
            canal = _estado["canal"]
        if len(partes) != 3 or partes[0] != "m" or not canal or partes[1] != canal:
            return self._resp('{"error":"no existe"}', codigo=404)

        que = partes[2]
        ahora = time.time()
        via = "túnel" if self.headers.get("Cf-Ray") or self.headers.get("X-Forwarded-For") else "wifi"
        if que == "ping":
            return self._resp(json.dumps({"ok": True, "hora": datetime.now().strftime("%H:%M:%S")}))

        if que == "ack":
            _ack(params.get("n"), ahora, via, params.get("id"))
            return self._resp('{"ok":true}')

        if que == "datos":
            _ack(params.get("ack"), ahora, via, params.get("id"))
            with _lock:
                _estado["ultimo_telefono"] = ahora
                _estado["via"] = via
                cuerpo = _estado["datos_txt"]
                limite = ahora - GUARDAR_EVENTOS_SEG
                eventos = [e for e in _estado["eventos"] if e["t"] >= limite]
                serie = _estado["serie"]
            if not cuerpo:
                cuerpo = b'{"partidos":[]}'
            # Los eventos se pegan al final del JSON del día sin volver a serializar todo.
            extra = json.dumps({"eventos": [_publico(e) for e in eventos], "serie": serie, "id": _estado["id"],
                                "servido": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")},
                               ensure_ascii=False)
            cuerpo = cuerpo.rstrip()
            if cuerpo.endswith(b"}") and len(cuerpo) > 2:
                cuerpo = cuerpo[:-1] + b"," + extra.encode("utf-8")[1:]
            return self._resp(cuerpo)

        return self._resp('{"error":"no existe"}', codigo=404)


def _publico(e):
    return {k: e[k] for k in ("n", "titulo", "texto", "prioridad", "tipo", "clave", "ntfy", "hora")}


def _ack(valor, ahora, via, ident=None):
    with _lock:
        _estado["ultimo_telefono"] = ahora
        _estado["via"] = via
        if ident is not None and ident != _estado["id"]:
            return                 # la app viene de otra «vida» de la PC: su cuenta no vale aquí
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return
    with _lock:
        if n > _estado["ack"]:
            _estado["ack"] = min(n, _estado["serie"])
        for e in _estado["eventos"]:
            if e["n"] <= _estado["ack"]:
                e["ack"] = True


def iniciar(canal, registro=None, respaldo=None, puerto=PUERTO, guardado=None):
    """
    Levanta el servidor en TODAS las interfaces de la PC (para que el celular
    entre por el wifi) y el revisor del buzón. Devuelve True si quedó escuchando.
    """
    global _srv, _registro, _respaldo, _hilo_buzon
    if registro:
        _registro = registro
    if respaldo:
        _respaldo = respaldo
    with _lock:
        _estado["canal"] = str(canal or "").strip()
    _cargar_estado(guardado)
    if _srv is not None:
        return True
    try:
        _srv = ThreadingHTTPServer(("0.0.0.0", int(puerto)), _H)
    except OSError as e:
        _log(f"No pude abrir el puerto {puerto} para la app ({e}). La app seguirá recibiendo por ntfy.")
        return False
    _srv.daemon_threads = True
    threading.Thread(target=_srv.serve_forever, daemon=True).start()
    _hilo_buzon = threading.Thread(target=_vigilar_buzon, daemon=True)
    _hilo_buzon.start()
    return True


def activo():
    return _srv is not None


def detener():
    global _srv
    if _srv is not None:
        try:
            _srv.shutdown()
        except Exception:
            pass
        _srv = None


# ------------------------------------------------------------------- datos

def publicar(datos):
    """El vigilante deja aquí, en cada vuelta, todo lo que la app tiene que pintar."""
    txt = json.dumps(datos, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    with _lock:
        _estado["datos"] = datos
        _estado["datos_txt"] = txt


def telefono_reciente(seg=120):
    """¿La app vino a buscar datos hace poco? (entonces el resumen por ntfy sobra)."""
    with _lock:
        return time.time() - _estado["ultimo_telefono"] < seg


def resumen():
    with _lock:
        hace = time.time() - _estado["ultimo_telefono"] if _estado["ultimo_telefono"] else None
        return {"hace": hace, "via": _estado["via"], "pendientes":
                sum(1 for e in _estado["eventos"] if not e["ack"] and not e["ntfy"])}


# ------------------------------------------------------------------- buzón

def evento(titulo, texto, prioridad, tipo="", clave=""):
    """
    Deja una alarma en el buzón. La app la recoge en su próxima consulta
    (cada ~15 s). Si nadie la confirma en ESPERA_ACK_SEG, sale por ntfy.
    Devuelve el número de evento.
    """
    with _lock:
        _estado["serie"] += 1
        n = _estado["serie"]
        _estado["eventos"].append({
            "n": n, "t": time.time(), "hora": datetime.now().strftime("%H:%M"),
            "titulo": str(titulo), "texto": str(texto), "prioridad": int(prioridad),
            "tipo": tipo, "clave": clave, "ntfy": False, "ack": False,
        })
        limite = time.time() - GUARDAR_EVENTOS_SEG
        _estado["eventos"] = [e for e in _estado["eventos"] if e["t"] >= limite][-200:]
    return n


def _vigilar_buzon():
    """Cada 5 s: lo que nadie confirmó a tiempo se manda por ntfy (una sola vez)."""
    while _srv is not None:
        time.sleep(5)
        ahora = time.time()
        with _lock:
            vencidos = [e for e in _estado["eventos"]
                        if not e["ack"] and not e["ntfy"] and ahora - e["t"] >= ESPERA_ACK_SEG]
            for e in vencidos:
                e["ntfy"] = True          # se marca antes: si la app lo ve después, ya sabe que llegó por ntfy
        for e in vencidos:
            ok = False
            if _respaldo:
                try:
                    ok = bool(_respaldo(e))
                except Exception as ex:
                    _log(f"   no salió por ntfy ({type(ex).__name__}: {ex})")
            if not ok:
                with _lock:
                    e["ntfy"] = False     # se vuelve a intentar en la próxima revisión
                    e["t"] = time.time() - ESPERA_ACK_SEG + 60   # …dentro de un minuto
