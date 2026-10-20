# -*- coding: utf-8 -*-
"""
vivo.py — marcador en vivo leído por el navegador, no por una API.

Por qué así: SofaScore, ESPN y compañía bloquean las consultas directas desde
Python (403). Tu navegador, en cambio, entra a BetMines sin problema porque es
un navegador de verdad y tú tienes la sesión abierta. La extensión Scarlet ya
sabe leer esa página: lleva semanas haciéndolo para cargar los resultados.

Entonces el reparto queda así:

    Scarlet            -> escribe en el Excel SOLO partidos terminados (FT/SR)
    extensión en vivo  -> lee la lista del día y manda marcador y minuto aquí
    vigilante          -> lo pasa al celular

Este archivo es el que recibe. Levanta un servidor chiquito en 127.0.0.1:8781
al que solo le habla la extensión, y le ofrece al vigilante:

    marcadores(cfg, partidos)  ->  {clave: {gl, gv, estado, minuto}}
    fichas()                   ->  {clave: {estadísticas, tarjetas...}}
    pausar(True/False)         ->  mientras Scarlet hace su vuelta

REGLA QUE NO SE ROMPE: aquí NO se escribe en el Excel. Ni una celda. El
marcador en vivo es para mirarlo en el celular; tu registro sigue siendo lo
que carga Scarlet (o tú a mano) cuando el partido terminó de verdad.
"""

import json
import os
import subprocess
import threading
import urllib.parse
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUERTO = 8781

# Cuánto antes de la hora de inicio y cuánto después del final se sigue
# mirando un partido. Generoso por los retrasos y el descuento.
ANTES_MIN = 10
DESPUES_MIN = 175

# Si la extensión deja de dar señales, el marcador se da por viejo y se deja
# de enseñar: mejor sin marcador que con uno congelado de hace media hora.
VENCE_SEG = 210

# Cuando no hay nada que mirar durante este rato, se le dice a la extensión
# que cierre sus pestañas.
APAGAR_TRAS_SEG = 300

_lock = threading.Lock()
_srv = None
_estado = {
    "partidos": [],        # lo que la extensión tiene que buscar
    "marcadores": {},      # clave -> {gl, gv, estado, minuto, visto}
    "fichas": {},          # clave -> ficha con estadísticas
    "pausa": False,
    "fichas_si": True,
    "recargar_cada": 1,   # cada cuántas vueltas se recarga la lista
    "segundos": 30,
    "max_pestanas": 8,     # partidos en juego seguidos a la vez (una pestaña cada uno)
    "ultimo_aviso": 0.0,   # última vez que la extensión habló
    "ultimo_util": 0.0,    # última vez que hubo partidos que mirar
    "filas": 0,
    "progreso": [],
    "navegador_abierto": 0.0,
    "dueno": "",           # qué navegador (su extensión) está siguiendo los partidos
    "dueno_t": 0.0,
    "dueno_nav": "",       # «Chrome» o «Edge», lo dice la extensión
    "version_ext": "",
    "notas": {},           # clave -> (hora, lo último que dijo la extensión de ese partido)
}

# Si Scarlet está en Chrome Y en Edge, los dos querrían seguir los partidos y
# abrirían pestañas dobles. Sigue el primero que pide; el otro espera. Si el
# primero se calla este rato, el otro toma el relevo.
DUENO_SEG = 90

_registro = None           # función para escribir en la consola del vigilante


def _log(txt):
    if _registro:
        try:
            _registro(txt)
            return
        except Exception:
            pass
    print(txt, flush=True)


# ------------------------------------------------------------------ servidor

PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>MATRIX · marcador en vivo</title>
<style>
 body{background:#0b0d12;color:#e6e8ef;font:15px/1.5 system-ui,Segoe UI,sans-serif;
      margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
 .c{max-width:520px;padding:28px 32px;background:#141821;border-radius:14px}
 h1{font-size:17px;margin:0 0 10px;color:#22d3ee;letter-spacing:.06em}
 p{margin:8px 0;color:#9aa2b8;font-size:13.5px}
 b{color:#e6e8ef}
</style></head><body><div class="c">
<h1>MARCADOR EN VIVO</h1>
<p>Esta pestaña es la que usa la extensión Scarlet (3.6) para seguir los partidos
de hoy en BetMines y mandarle el marcador y las estadísticas a tu celular.</p>
<p><b>Déjala abierta</b> y minimizada. Si la cierras, el marcador en vivo deja
de actualizarse (las alarmas de inicio y de resultado final siguen igual).</p>
<p>Las pestañas de los partidos en juego se abren en una <b>ventana aparte,
minimizada</b>: una por partido, solo mientras se juega. Si la ves, no la cierres.</p>
<p>Desde la 3.5 la extensión arranca sola aunque esta pestaña no esté: basta con
tener abierto el navegador donde está Scarlet.</p>
<p>Al Excel no se escribe nada desde aquí.</p>
</div></body></html>"""


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _resp(self, cuerpo, tipo="application/json; charset=utf-8", codigo=200):
        b = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
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
        params = {}
        for par in consulta.split("&"):
            k, _, v = par.partition("=")
            if k:
                params[k] = urllib.parse.unquote_plus(v)
        if ruta in ("/vivo", "/vivo/", "/"):
            return self._resp(PAGINA, "text/html; charset=utf-8")
        if ruta == "/vivo/latido":
            # La extensión llama cada 15 s para que el navegador no la duerma.
            with _lock:
                _estado["ultimo_aviso"] = time.time()
            return self._resp('{"ok":true}')
        if ruta == "/vivo/partidos":
            quien = str(params.get("quien") or "")[:40]
            with _lock:
                ahora = time.time()
                if quien and _estado["dueno"] and quien != _estado["dueno"] \
                        and ahora - _estado["dueno_t"] < DUENO_SEG:
                    # otro navegador ya los está siguiendo: este espera
                    return self._resp(json.dumps({"otro": True, "segundos": 60, "partidos": [],
                                                  "dueno": _estado["dueno_nav"]}))
                if quien:
                    if quien != _estado["dueno"]:
                        _estado["dueno"] = quien
                    _estado["dueno_t"] = ahora
                    _estado["dueno_nav"] = str(params.get("nav") or "")[:20]
                    _estado["version_ext"] = str(params.get("v") or "")[:40]
                _estado["ultimo_aviso"] = time.time()
                hay = bool(_estado["partidos"])
                if hay:
                    _estado["ultimo_util"] = time.time()
                fin = (not hay) and (time.time() - _estado["ultimo_util"] > APAGAR_TRAS_SEG)
                plan = {
                    "segundos": _estado["segundos"],
                    "pausa": bool(_estado["pausa"]),
                    "fichas": bool(_estado["fichas_si"]),
                    "recargar_cada": int(_estado["recargar_cada"]),
                    "fin": bool(fin),
                    "max_pestanas": int(_estado["max_pestanas"]),
                    "abrir_antes_min": 0,          # la pestaña se abre a la hora del partido, no antes
                    "ventana_propia": True,        # en una ventana aparte y minimizada
                    "partidos": list(_estado["partidos"]),
                }
            return self._resp(json.dumps(plan, ensure_ascii=False))
        return self._resp('{"error":"no existe"}', codigo=404)

    def do_POST(self):
        ruta = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        try:
            datos = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            return self._resp('{"ok":false}', codigo=400)

        ahora = time.time()
        if ruta == "/vivo/marcadores":
            with _lock:
                _estado["ultimo_aviso"] = ahora
                _estado["filas"] = int(datos.get("filas") or 0)
                for m in datos.get("marcadores") or []:
                    clave = m.get("clave")
                    if not clave:
                        continue
                    _estado["marcadores"][clave] = {
                        "gl": m.get("gl"), "gv": m.get("gv"),
                        "estado": str(m.get("estado") or ""),
                        "minuto": m.get("minuto"),
                        "href": m.get("href") or "",
                        "visto": ahora,
                    }
            return self._resp('{"ok":true}')

        if ruta == "/vivo/ficha":
            clave = datos.get("clave")
            if clave:
                with _lock:
                    _estado["ultimo_aviso"] = ahora
                    datos["visto"] = ahora
                    _estado["fichas"][clave] = datos
            return self._resp('{"ok":true}')

        if ruta == "/vivo/progreso":
            txt = str(datos.get("texto") or "")[:200]
            if txt:
                with _lock:
                    _estado["ultimo_aviso"] = ahora
                    _estado["progreso"].append(f"{datetime.now():%H:%M:%S} {txt}")
                    del _estado["progreso"][:-40]
                    # «Local vs Visitante: …» se guarda como la nota de ese partido (la app la enseña)
                    for p in _estado["partidos"]:
                        pre = f"{p['local']} vs {p['visitante']}: "
                        if txt.startswith(pre):
                            _estado["notas"][p["clave"]] = (ahora, txt[len(pre):])
                            break
                _anotar(txt)
            return self._resp('{"ok":true}')

        if ruta == "/vivo/diagnostico":
            try:
                ruta_d = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "diagnostico_vivo.txt")
                if os.path.exists(ruta_d) and os.path.getsize(ruta_d) > 600_000:
                    os.replace(ruta_d, ruta_d + ".anterior")
                with open(ruta_d, "a", encoding="utf-8") as f:
                    f.write(f"\n\n######## {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                    f.write(f"=== {datos.get('nombre') or ''}\n")
                    f.write(str(datos.get("texto") or "")[:20000])
                _log("   (guardé diagnostico_vivo.txt: una página que no supe leer)")
            except OSError:
                pass
            return self._resp('{"ok":true}')

        return self._resp('{"error":"no existe"}', codigo=404)


REGISTRO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vivo_registro.txt")


def _anotar(txt):
    """Todo lo que cuenta la extensión queda en vivo_registro.txt (para revisar qué pasó con un partido)."""
    try:
        if os.path.exists(REGISTRO) and os.path.getsize(REGISTRO) > 1_500_000:
            os.replace(REGISTRO, REGISTRO + ".anterior")
        with open(REGISTRO, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {txt}\n")
    except OSError:
        pass


def iniciar(registro=None, puerto=PUERTO):
    """Levanta el servidor. Devuelve True si quedó escuchando."""
    global _srv, _registro
    if registro:
        _registro = registro
    if _srv is not None:
        return True
    try:
        _srv = ThreadingHTTPServer(("127.0.0.1", int(puerto)), _H)
    except OSError as e:
        _log(f"No pude abrir el puerto {puerto} para el marcador en vivo ({e}).")
        return False
    threading.Thread(target=_srv.serve_forever, daemon=True).start()
    # Al arrancar se le da margen antes de decirle a la extensión que ya no hay
    # nada que mirar: si no, al abrir el programa antes del primer partido la
    # extensión se apagaría de entrada.
    with _lock:
        _estado["ultimo_util"] = time.time()
    return True


def detener():
    global _srv
    if _srv is not None:
        try:
            _srv.shutdown()
        except Exception:
            pass
        _srv = None


# ------------------------------------------------------------------ navegador

NAVEGADORES = {"auto": "tu navegador predeterminado", "edge": "Microsoft Edge", "chrome": "Google Chrome",
               "firefox": "Firefox"}


def _comandos(nav, url):
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    if nav == "firefox":
        rutas = [pf + r"\Mozilla Firefox\firefox.exe", pf86 + r"\Mozilla Firefox\firefox.exe"]
        if local:
            rutas.append(local + r"\Mozilla Firefox\firefox.exe")
        return [[r, url] for r in rutas] + [["cmd", "/c", "start", "", "firefox", url]]
    if nav == "chrome":
        rutas = [pf + r"\Google\Chrome\Application\chrome.exe",
                 pf86 + r"\Google\Chrome\Application\chrome.exe"]
        if local:
            rutas.append(local + r"\Google\Chrome\Application\chrome.exe")
        return [[r, url] for r in rutas] + [["cmd", "/c", "start", "", "chrome", url]]
    return [["cmd", "/c", "start", "", "msedge", url]]


def abrir_navegador(nav="edge"):
    """Abre la pestaña del modo en vivo en el navegador que tiene la extensión."""
    url = f"http://127.0.0.1:{PUERTO}/vivo"
    nav = str(nav or "auto").strip().lower()
    if nav not in NAVEGADORES:
        nav = "auto"
    if os.name != "nt":
        try:
            subprocess.Popen(["xdg-open", url])
        except OSError:
            pass
        return
    if nav == "auto":
        try:
            os.startfile(url)            # el navegador predeterminado de Windows
            return
        except OSError:
            nav = "edge"
    if nav == "edge":
        try:
            os.startfile("microsoft-edge:" + url)
            return
        except OSError:
            pass
    for cmd in _comandos(nav, url):
        if cmd[0] != "cmd" and not os.path.exists(cmd[0]):
            continue
        try:
            subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                             if cmd[0] == "cmd" else 0)
            return
        except OSError:
            continue
    _log(f"✖ no pude abrir {NAVEGADORES[nav]} para el marcador en vivo.")


# ------------------------------------------------------- lo que usa el vigilante

def _minutos_de(p):
    """
    Minutos desde medianoche a los que empieza el partido.

    El vigilante los trae en `inicio` (una fecha y hora completa); se aceptan
    también `hora` y `hora_txt` en formato «15:30» por si el partido viene de
    otro sitio. None si no se sabe la hora.
    """
    ini = p.get("inicio")
    if isinstance(ini, datetime):
        return ini.hour * 60 + ini.minute
    for campo in ("hora", "hora_txt"):
        txt = p.get(campo)
        if not txt:
            continue
        try:
            h, m = str(txt).strip().split(":")[:2]
            h, m = int(h), int(m)
        except (ValueError, TypeError):
            continue
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    return None


def _hhmm(minutos):
    return "" if minutos is None else f"{minutos // 60:02d}:{minutos % 60:02d}"


def _en_ventana(ini, ahora_min):
    """¿Este partido está en el rato en que vale la pena mirarlo?"""
    if ini is None:
        return False
    return ini - ANTES_MIN <= ahora_min <= ini + DESPUES_MIN


def fijar_partidos(partidos, hoy=None, segundos=30, fichas=True, max_pestanas=8):
    """
    Le dice a la extensión qué partidos mirar: los de hoy que están dentro de
    su ventana de juego y a los que el Excel todavía no les puso resultado.
    """
    hoy = hoy or datetime.now().date()
    ahora = datetime.now()
    ahora_min = ahora.hour * 60 + ahora.minute
    lista = []
    for p in partidos:
        if p.get("fecha") != hoy:
            continue
        if p.get("gl") is not None and p.get("gv") is not None:
            continue                                   # ya tiene resultado cargado
        if p.get("suspendido"):
            continue
        ini = _minutos_de(p)
        if not _en_ventana(ini, ahora_min):
            continue
        nombre = str(p.get("nombre") or "")
        if " vs " not in nombre:
            continue
        local, visitante = nombre.split(" vs ", 1)
        lista.append({
            "clave": p["clave"],
            "local": local.strip(),
            "visitante": visitante.strip(),
            "fecha": hoy.isoformat(),
            "hora": _hhmm(ini),
        })
    with _lock:
        _estado["partidos"] = lista
        _estado["segundos"] = max(10, int(segundos))
        _estado["fichas_si"] = bool(fichas)
        _estado["max_pestanas"] = max(1, int(max_pestanas or 8))
        if lista:
            _estado["ultimo_util"] = time.time()
    return lista


def pausar(si):
    with _lock:
        _estado["pausa"] = bool(si)


def hay_extension(margen=VENCE_SEG):
    """¿La extensión dio señales hace poco?"""
    with _lock:
        return time.time() - _estado["ultimo_aviso"] < margen


def marcadores(cfg, partidos):
    """
    {clave: {gl, gv, estado, minuto}} — la misma forma que devolvía la versión
    por API, para que el resto del vigilante no cambie.

    Lo que ya venció no se devuelve: antes un marcador congelado que uno viejo
    haciéndose pasar por bueno.
    """
    if not cfg.get("vivo"):
        return {}
    ahora = time.time()
    salida = {}
    with _lock:
        for clave, m in _estado["marcadores"].items():
            if ahora - m["visto"] > VENCE_SEG:
                continue
            if not m["estado"]:
                continue
            salida[clave] = {"gl": m["gl"], "gv": m["gv"],
                             "estado": m["estado"], "minuto": m["minuto"]}
    return salida


def fichas(vence=600):
    """{clave: ficha} con las estadísticas leídas de la página del partido."""
    ahora = time.time()
    with _lock:
        return {k: v for k, v in _estado["fichas"].items()
                if ahora - float(v.get("visto") or 0) < vence}


def progreso(n=6):
    with _lock:
        return list(_estado["progreso"][-n:])


def nota(clave, vence=900, con_hora=False):
    """Lo último que la extensión dijo de ese partido («encontré su página», «leí 1-0 min 23»…)."""
    with _lock:
        n = _estado["notas"].get(clave)
    if not n or time.time() - n[0] > vence:
        return ""
    return f"{datetime.fromtimestamp(n[0]):%H:%M:%S}: {n[1]}" if con_hora else n[1]


def extension():
    """Cómo está la extensión: si habla, hace cuánto, en qué navegador y lo último que dijo."""
    with _lock:
        t = _estado["ultimo_aviso"]
        ultima = _estado["progreso"][-1] if _estado["progreso"] else ""
        return {"ok": bool(t) and time.time() - t < VENCE_SEG,
                "hace": int(time.time() - t) if t else None,
                "navegador": _estado["dueno_nav"], "version": _estado["version_ext"],
                "ultima": ultima[9:] if len(ultima) > 9 else ultima,
                "siguiendo": len(_estado["partidos"])}


def resumen():
    with _lock:
        return {
            "partidos": len(_estado["partidos"]),
            "marcadores": len(_estado["marcadores"]),
            "filas": _estado["filas"],
            "extension": time.time() - _estado["ultimo_aviso"] < VENCE_SEG,
            "pausa": _estado["pausa"],
        }


def asegurar_navegador(cfg, cada_seg=600):
    """
    Abre la pestaña del modo en vivo si hace falta: cuando hay partidos que
    mirar y la extensión lleva rato sin dar señales. No la abre a cada rato.
    """
    with _lock:
        hay = bool(_estado["partidos"])
        callada = time.time() - _estado["ultimo_aviso"] > VENCE_SEG
        hace_poco = time.time() - _estado["navegador_abierto"] < cada_seg
        if not hay or not callada or hace_poco or _estado["pausa"]:
            return False
        _estado["navegador_abierto"] = time.time()
    _log("Abro la pestaña del marcador en vivo en el navegador.")
    abrir_navegador(cfg.get("navegador") or "auto")
    return True


if __name__ == "__main__":
    # ----------------------------------------------------------- prueba suelta
    # Levanta el servidor con UN partido de mentira para que la extensión tenga
    # algo que buscar, abre el navegador y enseña paso a paso lo que va pasando.
    # No toca el Excel ni manda nada al celular.
    import sys

    iniciar()
    ahora = datetime.now()
    hora = f"{(ahora.hour - 1) % 24:02d}:{ahora.minute:02d}"
    fijar_partidos([{
        "clave": "prueba",
        "nombre": "Belgrano vs River Plate",      # da igual si hoy no juegan:
        "fecha": ahora.date(),                     # lo que se comprueba es que
        "hora": hora,                              # la extensión lea la lista
        "gl": None, "gv": None, "suspendido": False,
    }], segundos=20)

    nav = (sys.argv[1] if len(sys.argv) > 1 else "edge").lower()
    print("=" * 62)
    print("PRUEBA DEL MARCADOR EN VIVO")
    print("=" * 62)
    print(f"Servidor en http://127.0.0.1:{PUERTO}/vivo")
    print(f"Abriendo {NAVEGADORES.get(nav, nav)}…  (si no se abre solo, pega esa")
    print("dirección a mano en el navegador que tiene la extensión Scarlet 3.3)")
    print("\nQué tiene que pasar, en orden:")
    print("   1. «extensión: sí»           -> la extensión contestó")
    print("   2. «Modo en vivo listo»      -> arrancó el modo")
    print("   3. «filas vistas» mayor que 0 -> leyó la lista de BetMines")
    print("\nCtrl+C para salir.\n")
    abrir_navegador(nav)

    try:
        vueltas = 0
        while True:
            time.sleep(5)
            vueltas += 1
            r = resumen()
            print(f"  extensión: {'sí' if r['extension'] else 'no'} · "
                  f"partidos a mirar: {r['partidos']} · "
                  f"filas vistas: {r['filas']} · marcadores: {r['marcadores']}")
            for linea in progreso(3):
                print("     " + linea)
            if vueltas == 12 and not r["extension"]:
                print("\n  La extensión no ha contestado en un minuto. Revisa:")
                print("   · que la pestaña http://127.0.0.1:8781/vivo esté abierta")
                print("   · que en edge://extensions Scarlet diga 3.3 y esté encendida")
                print("   · pulsa «Volver a cargar» en Scarlet y recarga esa pestaña (F5)\n")
    except KeyboardInterrupt:
        detener()
        print("\nlisto.")
