# -*- coding: utf-8 -*-
"""
vigilante.py — manda al celular los avisos de los partidos del día.

Lee la pestaña CONSTRUCK del registro (columnas B, F, G, H, I) y manda:
  * 15 minutos antes de cada partido: el aviso previo.
  * Cuando aparece el resultado en GL/GV: el marcador y si quedó Under o Over 2.5.
  * En vivo (con la extensión Scarlet): goles, rojas, y si el VAR los anula.

Cómo llega todo al celular (v2, 19/10/2026):
  * La app viene a buscar los datos directo a esta PC (servidor_app.py), por el
    wifi de la casa o por un túnel gratis de Cloudflare (enlace.py). Ahí van la
    lista del día, los marcadores, las estadísticas y las alarmas. Sin límite.
  * ntfy.sh queda de RESPALDO: si la app no recoge una alarma en 45 segundos,
    sale por ntfy. ntfy gratis deja ~250 mensajes al día; por eso el resumen ya
    no viaja por ahí cada minuto (antes se agotaba el cupo a media tarde y
    dejaban de salir las alarmas).

No toca el Excel: trabaja sobre una copia temporal, así que puedes tenerlo
abierto mientras esto corre. Tampoco guarda nada dentro del registro.

Uso:
    python vigilante.py                 arranca la vigilancia
    python vigilante.py --probar        manda un aviso de prueba al celular
    python vigilante.py --hoy           lista los partidos de hoy y sale
    python vigilante.py --simular       enseña qué avisos mandaría, sin mandarlos

Solo necesita openpyxl (el mismo que ya usa omega). Nada más.
"""

import argparse
import configparser
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import string
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta

try:
    from openpyxl import load_workbook
except ImportError:
    sys.exit("Falta openpyxl. Instálalo con:  pip install openpyxl")

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "config.ini")
ESTADO = os.path.join(AQUI, "estado_avisos.json")

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


# ----------------------------------------------------------------- utilidades

def sin_tildes(s):
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


ULTIMOS = []          # últimas líneas, para mostrarlas dentro del panel


def log(msg):
    linea = f"[{datetime.now():%H:%M:%S}] {msg}"
    ULTIMOS.append(linea)
    del ULTIMOS[:-8]
    print(linea, flush=True)


def parsear_fecha(valor):
    """'17 de octubre de 2026' -> date. También acepta lo que Excel guarde como fecha."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if hasattr(valor, "year") and hasattr(valor, "day") and not hasattr(valor, "hour"):
        return valor
    t = sin_tildes(valor)
    m = re.search(r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})", t)
    if m:
        mes = MESES.get(m.group(2))
        if mes:
            try:
                return datetime(int(m.group(3)), mes, int(m.group(1))).date()
            except ValueError:
                return None
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", t)
    if m:
        d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a < 100:
            a += 2000
        try:
            return datetime(a, mes, d).date()
        except ValueError:
            return None
    return None


def parsear_hora(valor):
    """'15:30' -> (15, 30). Acepta también la hora como objeto de Excel."""
    if valor is None:
        return None
    if hasattr(valor, "hour") and hasattr(valor, "minute"):
        return valor.hour, valor.minute
    m = re.search(r"(\d{1,2})\s*[:.]\s*(\d{2})", str(valor))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h, mi
    return None


def goles(valor):
    """Devuelve (numero, suspendido). 0 es un resultado válido, vacío no."""
    if valor is None:
        return None, False
    if isinstance(valor, str):
        t = valor.strip()
        if not t:
            return None, False
        if sin_tildes(t) in ("sr", "s/r", "susp", "suspendido", "aplazado"):
            return None, True
        try:
            return int(float(t.replace(",", "."))), False
        except ValueError:
            return None, False
    try:
        return int(valor), False
    except (TypeError, ValueError):
        return None, False


def nombre_bonito(partido, local, visitante):
    """'Kedus Giorgis_vs_Ethiopia Bunna_17 de octubre de 2026' -> 'Kedus Giorgis vs Ethiopia Bunna'."""
    if local and visitante:
        return f"{local} vs {visitante}"
    t = str(partido or "").strip()
    partes = t.split("_vs_")
    if len(partes) == 2:
        # El visitante trae pegada la fecha: 'Ethiopia Bunna_17 de octubre de 2026'
        visita = re.sub(r"_\d{1,2}\s+de\s+\w+\s+de\s+\d{4}\s*$", "", partes[1], flags=re.I)
        return f"{partes[0].strip()} vs {visita.strip()}"
    return t


# ------------------------------------------------------------------ el Excel

def leer_partidos(ruta):
    """
    Lee CONSTRUCK sobre una copia, para no estorbar si el Excel está abierto.
    Devuelve una lista de dicts con lo que hace falta para avisar.
    """
    copia = None
    try:
        fd, copia = tempfile.mkstemp(prefix="vigilante_", suffix=".xlsx")
        os.close(fd)
        shutil.copy2(ruta, copia)
        wb = load_workbook(copia, read_only=True, data_only=True)
        try:
            if "CONSTRUCK" not in wb.sheetnames:
                raise RuntimeError(
                    f"El archivo no tiene la pestaña CONSTRUCK (tiene: {', '.join(wb.sheetnames)})"
                )
            ws = wb["CONSTRUCK"]
            filas = list(ws.iter_rows(min_row=1, max_col=93, values_only=True))
        finally:
            wb.close()
    finally:
        if copia and os.path.exists(copia):
            try:
                os.remove(copia)
            except OSError:
                pass

    # La cabecera no siempre está en la misma fila: se busca la que dice PARTIDO.
    inicio = None
    for i, fila in enumerate(filas[:15]):
        celdas = [sin_tildes(c) for c in fila if c is not None]
        if "partido" in celdas:
            inicio = i + 1
            break
    if inicio is None:
        inicio = 3   # como está hoy: cabecera en la fila 3, datos desde la 4
    # Las columnas de la previa se buscan por su NOMBRE en la cabecera (no por posición):
    # si omega agrega o mueve columnas, esto sigue funcionando.
    cabecera = [str(x).strip() if x is not None else "" for x in filas[inicio - 1]] if inicio - 1 < len(filas) else []
    col = {nombre: i for i, nombre in enumerate(cabecera) if nombre}

    partidos = []
    for fila in filas[inicio:]:
        if len(fila) < 9 or not fila[1]:
            continue
        fecha = parsear_fecha(fila[5])
        hora = parsear_hora(fila[6])
        if fecha is None:
            continue
        gl, susp_l = goles(fila[7])
        gv, susp_v = goles(fila[8])
        inicio_dt = None
        if hora is not None:
            inicio_dt = datetime(fecha.year, fecha.month, fecha.day, hora[0], hora[1])
        partidos.append({
            "clave": sin_tildes(fila[1]),
            "nombre": nombre_bonito(fila[1], fila[2], fila[3]),
            "competicion": str(fila[4] or "").strip(),
            "fecha": fecha,
            "inicio": inicio_dt,
            "hora_txt": str(fila[6] or "sin hora").strip(),
            "gl": gl,
            "gv": gv,
            "suspendido": susp_l or susp_v,
            "previa": previa_de(fila, col),
        })
    return partidos


# Lo que se muestra en el celular como «previa» de cada partido: sale de las
# columnas que llena omega en CONSTRUCK. (nombre en la app, columna local, columna visitante)
PREVIA = [
    ("Posición en la tabla", "posicion_local", "posicion_visitante"),
    ("Cuota gana (1 / 2)", "1", "2"),
    ("Cuota empate (X)", "x", None),
    ("Cuota Under / Over 2.5", "und", "ovr"),
    ("Ambos marcan: Sí / No", "cuota_gg_si", "cuota_ng_no"),
    ("Goles a favor (media)", "media_gf_local", "media_gf_visitante"),
    ("Goles en contra (media)", "media_gc_local", "media_gc_visitante"),
    ("xG a favor", "xG_L", "xG_V"),
    ("xG en contra", "xGA_L", "xGA_V"),
    ("Posesión media", "posesion_media_local", "posesion_media_visitante", "pct"),
    ("Últimos 5", "ultimos_5_local", "ultimos_5_visitante", "forma"),
    ("H2H Under / Over 2.5", "h2h_under_2_5", "h2h_over_2_5", "pct"),
    ("Partidos H2H", "n_h2h", None),
    ("Goles esperados (λ)", "lambda_L", "lambda_V"),
    ("λ total", "lambda_total", None),
    ("Apuesta sugerida BetMines", "apuesta_sugerida_betmines", None),
    ("Prob. / cuota sugerida", "probabilidad_apuesta_sugerida", "cuota_apuesta_sugerida", "pct1"),
    ("Confianza", "nivel_confianza", None),
    ("Estado en omega", "status", None),
]


def _valor(v, fmt=""):
    if v is None:
        return ""
    if fmt == "pct" and isinstance(v, (int, float)) and 0 <= v <= 1:
        return f"{round(v * 100)} %"
    if fmt == "forma" and isinstance(v, str):
        # W/D/L de FootyStats -> G/E/P como los pinta BetMines
        return " ".join({"W": "G", "D": "E", "L": "P"}.get(x.strip().upper(), x.strip())
                        for x in v.split(",") if x.strip())
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.0f}"
    return str(v).strip()[:22]


def previa_de(fila, col):
    """[{nombre, local, visitante}] con los datos previos que tenga la fila (los vacíos se saltan)."""
    salida = []
    for item in PREVIA:
        nombre, cl, cv = item[:3]
        fmt = item[3] if len(item) > 3 else ""
        il = col.get(cl)
        iv = col.get(cv) if cv else None
        a = _valor(fila[il], "pct" if fmt in ("pct", "pct1") else fmt) if il is not None and il < len(fila) else ""
        b = _valor(fila[iv], "pct" if fmt == "pct" else fmt if fmt != "pct1" else "") \
            if iv is not None and iv < len(fila) else ""
        if not a and not b:
            continue
        salida.append({"nombre": nombre, "local": a, "visitante": b})
    return salida


# ------------------------------------------------------------------- el envío

# Lo que se lleva gastado del cupo diario de ntfy. Se guarda en estado_avisos.json.
CUPO = {"fecha": "", "n": 0, "pausa_hasta": 0.0, "avisado": ""}


def _cupo_hoy():
    hoy = datetime.now().strftime("%Y-%m-%d")
    if CUPO.get("fecha") != hoy:
        CUPO.update({"fecha": hoy, "n": 0, "avisado": ""})
    return CUPO


def enviar(cfg, titulo, texto, prioridad=5, simular=False, esencial=False):
    """
    Manda un mensaje por ntfy. Devuelve True si salió.

    ntfy.sh gratis permite ~250 mensajes al día por conexión. Los que NO son
    alarmas (el resumen, las estadísticas, el enlace) dejan de mandarse al
    llegar a `limite_ntfy_dia`; las alarmas (esencial=True) siguen hasta el tope.
    Si ntfy contesta 429 (cupo agotado) se espera 10 min antes de volver a probar.
    """
    if simular:
        log(f"   [simulado] p{prioridad} · {titulo} · {texto.replace(chr(10), ' / ')}")
        return True
    cupo = _cupo_hoy()
    if time.time() < float(cupo.get("pausa_hasta") or 0):
        return False
    limite = cfg.get("limite_ntfy", 230)
    if cupo["n"] >= (245 if esencial else limite):
        if cupo.get("avisado") != ("e" if esencial else "n"):
            cupo["avisado"] = "e" if esencial else "n"
            log(f"Cupo de ntfy de hoy casi agotado ({cupo['n']} mensajes): "
                + ("ya no salen ni las alarmas por ntfy (la app las sigue recibiendo directo)." if esencial
                   else "el resumen ya no va por ntfy; las alarmas sí."))
        return False
    datos = json.dumps({
        "topic": cfg["canal"],
        "title": titulo,
        "message": texto,
        "priority": int(prioridad),
    }).encode("utf-8")
    pet = urllib.request.Request(
        cfg["servidor"], data=datos,
        headers={"Content-Type": "application/json"},
    )
    for intento in range(3):
        try:
            with urllib.request.urlopen(pet, timeout=20) as r:
                if 200 <= r.status < 300:
                    cupo["n"] += 1
                    return True
                log(f"   el servidor respondió {r.status}")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                cupo["pausa_hasta"] = time.time() + 600
                cupo["n"] = max(cupo["n"], 250)
                log("ntfy dice que se agotó el cupo de hoy (429). Pruebo de nuevo en 10 min; "
                    "la app sigue recibiendo todo directo.")
                return False
            log(f"   ntfy respondió {e.code}; reintento {intento + 1}/3")
            time.sleep(3)
        except (urllib.error.URLError, OSError) as e:
            log(f"   no se pudo enviar ({e}); reintento {intento + 1}/3")
            time.sleep(3)
    return False


# ------------------------------------------------- avisos: buzón de la app + ntfy

_APP = {"activo": False}


def avisar(cfg, titulo, texto, prioridad, simular=False, tipo="", clave=""):
    """
    Una alarma o aviso para el celular. Si el servidor de la app está arriba, va
    al buzón: la app la recoge en segundos, y si no la recoge en 45 s, sale por
    ntfy solita (respaldo). Si no hay servidor, va por ntfy directo como antes.
    """
    if simular:
        log(f"   [simulado] p{prioridad} · {titulo} · {texto.replace(chr(10), ' / ')}")
        return True
    if _APP["activo"]:
        try:
            import servidor_app
            servidor_app.evento(titulo, texto, prioridad, tipo, clave)
            return True
        except Exception as e:
            log(f"   el buzón de la app falló ({type(e).__name__}: {e}); va por ntfy")
    return enviar(cfg, titulo, texto, prioridad, esencial=True)


def _respaldo_ntfy(cfg):
    def mandar(e):
        if time.time() - e["t"] > 20 * 60:       # una alarma de hace 20 min ya no sirve: se suelta
            return True
        ok = enviar(cfg, e["titulo"], e["texto"], e["prioridad"], esencial=True)
        if ok:
            log(f"   (por ntfy: la app no recogió «{e['titulo']}» a tiempo)")
        return ok
    return mandar


def iniciar_app(cfg, estado):
    """Levanta el servidor para la app y el túnel. Devuelve True si quedó arriba."""
    if not cfg.get("enlace_directo"):
        return False
    try:
        import servidor_app
    except ImportError:
        log("Falta servidor_app.py; la app sigue recibiendo solo por ntfy.")
        return False
    ok = servidor_app.iniciar(cfg["canal"], registro=log, respaldo=_respaldo_ntfy(cfg),
                              puerto=cfg["puerto_app"], guardado=estado.get("buzon"))
    _APP["activo"] = bool(ok)
    if ok:
        try:
            import enlace
            enlace.iniciar(cfg["puerto_app"], cfg.get("tunel", "cloudflared"), registro=log)
        except ImportError:
            log("Falta enlace.py: la app solo podrá conectarse por el wifi de la casa.")
    return _APP["activo"]


def anunciar_enlace(cfg, estado, simular=False):
    """
    Le dice a la app por dónde entrar (wifi y túnel). Va por ntfy, pero solo
    cuando la dirección cambia o cada 6 horas: unos pocos mensajes al día.
    """
    if not _APP["activo"]:
        return False
    try:
        import enlace
        e = enlace.enlaces(cfg["puerto_app"])
    except ImportError:
        e = {"lan": "", "publico": ""}
    datos = {"lan": e.get("lan", ""), "publico": e.get("publico", ""), "v": 2}
    if not datos["lan"] and not datos["publico"]:
        return False
    cuerpo = "MATRIXE|" + json.dumps(datos, separators=(",", ":"))
    firma = hashlib.md5(cuerpo.encode("utf-8")).hexdigest()
    pasado = time.time() - float(estado.get("enlace_enviado_en") or 0)
    if firma == estado.get("enlace_firma") and pasado < 6 * 3600:
        return False
    # Al arrancar, el túnel tarda unos segundos en dar su dirección: se espera
    # un poco para no mandar dos mensajes seguidos (uno sin túnel y otro con él).
    if not datos["publico"] and pasado < 6 * 3600 and time.time() - _APP.get("desde", time.time()) < 90:
        return False
    if enviar(cfg, TITULO_ENLACE, cuerpo, 1, simular, esencial=True):
        estado["enlace_firma"] = firma
        estado["enlace_enviado_en"] = time.time()
        log(f"Le mandé a la app la dirección: {datos['publico'] or datos['lan']}")
        return True
    return False


# ------------------------------------------------------------- configuración

def canal_nuevo():
    azar = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(14))
    return f"matrix-{azar}"


def cargar_config():
    cp = configparser.ConfigParser()
    if os.path.exists(CONFIG):
        cp.read(CONFIG, encoding="utf-8")
    if not cp.has_section("alertas"):
        cp.add_section("alertas")
    s = cp["alertas"]

    creado = False
    if not s.get("canal", "").strip():
        s["canal"] = canal_nuevo()
        creado = True

    s.setdefault("excel", r"C:\top secret\SELECTOR 3F\omega\outputs\registro_partidos.xlsx")
    s.setdefault("servidor", "https://ntfy.sh")
    s.setdefault("minutos_antes", "15")
    s.setdefault("revisar_cada_segundos", "30")
    s.setdefault("prioridad_previo", "5")
    s.setdefault("prioridad_resultado", "4")
    s.setdefault("avisar_resultado", "si")
    s.setdefault("dias_atras_resultados", "3")
    s.setdefault("solo_competiciones", "")
    s.setdefault("recordar_pendientes_cada_horas", "0")
    s.setdefault("minutos_partido", "115")
    s.setdefault("panel_en_vivo", "si")
    s.setdefault("colores", "si")
    s.setdefault("mandar_estado_cada_minutos", "3")
    s.setdefault("marcador_en_vivo", "si")
    s.setdefault("scarlet_carpeta", "")
    s.setdefault("scarlet_cada_minutos", "12")
    s.setdefault("segundos_refresco_vivo", "45")
    s.setdefault("fuente_vivo", "navegador")
    s.setdefault("navegador", "edge")
    s.setdefault("fichas_vivo", "si")
    s.setdefault("mandar_manana", "no")
    s.setdefault("avisar_goles", "si")
    s.setdefault("prioridad_gol", "4")
    s.setdefault("prioridad_under_perdido", "4")
    s.setdefault("avisar_rojas", "si")
    s.setdefault("prioridad_roja", "4")
    s.setdefault("avisar_anulados", "si")
    s.setdefault("enlace_directo", "si")
    s.setdefault("puerto_app", "8782")
    s.setdefault("tunel", "cloudflared")
    s.setdefault("limite_ntfy_dia", "230")
    s.setdefault("max_pestanas", "8")

    # v2 (19/10/2026): el gol y la roja pasan a ser ALARMA (pedido de Anthony) y el
    # resumen por ntfy deja de salir cada 3 min (se agotaba el cupo diario de ntfy).
    if int(s.get("version_config", "1") or 1) < 2:
        s["prioridad_gol"] = "4"
        s["prioridad_roja"] = "4"
        s["mandar_estado_cada_minutos"] = "15"
        s["version_config"] = "2"

    with open(CONFIG, "w", encoding="utf-8") as f:
        cp.write(f)

    cfg = {
        "canal": s["canal"].strip(),
        "excel": s["excel"].strip().strip('"'),
        "servidor": s["servidor"].strip().rstrip("/"),
        "minutos_antes": int(s["minutos_antes"]),
        "cada": max(10, int(s["revisar_cada_segundos"])),
        "p_previo": int(s["prioridad_previo"]),
        "p_resultado": int(s["prioridad_resultado"]),
        "avisar_resultado": sin_tildes(s["avisar_resultado"]) in ("si", "s", "yes", "true", "1"),
        "dias_atras": int(s["dias_atras_resultados"]),
        "competiciones": [sin_tildes(x) for x in s["solo_competiciones"].split(",") if x.strip()],
        "recordar_horas": float(s["recordar_pendientes_cada_horas"] or 0),
        "minutos_partido": max(60, int(s["minutos_partido"])),
        "panel": sin_tildes(s["panel_en_vivo"]) in ("si", "s", "yes", "true", "1"),
        "colores": sin_tildes(s["colores"]) in ("si", "s", "yes", "true", "1"),
        "estado_cada": float(s["mandar_estado_cada_minutos"] or 0),
        "vivo": sin_tildes(s["marcador_en_vivo"]) in ("si", "s", "yes", "true", "1"),
        "scarlet": s["scarlet_carpeta"].strip().strip('"'),
        "scarlet_cada": float(s["scarlet_cada_minutos"] or 0),
        "refresco_vivo": max(20, int(s["segundos_refresco_vivo"] or 45)),
        "fuente_vivo": "api" if sin_tildes(s["fuente_vivo"]) == "api" else "navegador",
        "navegador": sin_tildes(s["navegador"]) or "edge",
        "fichas_vivo": sin_tildes(s["fichas_vivo"]) in ("si", "s", "yes", "true", "1"),
        "mandar_manana": sin_tildes(s["mandar_manana"]) in ("si", "s", "yes", "true", "1"),
        "avisar_goles": sin_tildes(s["avisar_goles"]) in ("si", "s", "yes", "true", "1"),
        "p_gol": int(s["prioridad_gol"]),
        "p_under_perdido": int(s["prioridad_under_perdido"]),
        "avisar_rojas": sin_tildes(s["avisar_rojas"]) in ("si", "s", "yes", "true", "1"),
        "p_roja": int(s["prioridad_roja"]),
        "avisar_anulados": sin_tildes(s["avisar_anulados"]) in ("si", "s", "yes", "true", "1"),
        "enlace_directo": sin_tildes(s["enlace_directo"]) in ("si", "s", "yes", "true", "1"),
        "puerto_app": int(s["puerto_app"] or 8782),
        "tunel": sin_tildes(s["tunel"]) or "cloudflared",
        "limite_ntfy": max(20, min(245, int(s["limite_ntfy_dia"] or 230))),
        "max_pestanas": max(1, min(20, int(s["max_pestanas"] or 8))),
        "canal_recien_creado": creado,
    }
    return cfg


def cargar_estado():
    if os.path.exists(ESTADO):
        try:
            with open(ESTADO, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            log("El archivo de estado estaba dañado; se empieza de cero.")
    return {"previo": {}, "resultado": {}, "sembrado": False, "ultimo_recordatorio": 0}


def guardar_estado(e):
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ESTADO)


# --------------------------------------------------------------- la vigilancia

def interesa(cfg, p):
    if not cfg["competiciones"]:
        return True
    comp = sin_tildes(p["competicion"])
    return any(c in comp for c in cfg["competiciones"])


def texto_resultado(p):
    total = p["gl"] + p["gv"]
    veredicto = "UNDER 2.5 ✅" if total <= 2 else "OVER 2.5 ❌"
    return (f"{p['nombre']}\n"
            f"{p['gl']} - {p['gv']}  (total {total})\n"
            f"{veredicto}"
            + (f"\n{p['competicion']}" if p["competicion"] else ""))


# ------------------------------------- cargar los resultados con Scarlet

_SCARLET = {"ultimo": 0.0, "proceso": None}


def lanzar_scarlet(cfg, pendientes):
    """
    Le pide a tu Scarlet Resultados que busque YA los partidos de hoy que ya
    terminaron y siguen sin GL/GV. Solo se llama cuando de verdad hay alguno
    esperando, para que el navegador no se abra porque sí.

    Scarlet escribe en el Excel únicamente los partidos terminados (FT) o los
    aplazados (SR); los que siguen en juego NO los toca. Por eso es seguro
    llamarlo durante el día: tu registro no se llena de marcadores a medias.

    Corre aparte, sin frenar la vigilancia: una vuelta suya tarda de 1 a 5 min.
    """
    if not cfg["scarlet"] or cfg["scarlet_cada"] <= 0 or not pendientes:
        return False
    guion = os.path.join(cfg["scarlet"], "scarlet_resultados.py")
    if not os.path.exists(guion):
        return False

    # ¿sigue trabajando la vuelta anterior, nuestra o la suya?
    proc = _SCARLET["proceso"]
    if proc is not None and proc.poll() is None:
        return False
    candado = os.path.join(cfg["scarlet"], "vuelta_en_curso.lock")
    try:
        if os.path.exists(candado) and time.time() - os.path.getmtime(candado) < 120:
            return False
    except OSError:
        pass
    if time.time() - _SCARLET["ultimo"] < cfg["scarlet_cada"] * 60:
        return False

    try:
        _SCARLET["proceso"] = subprocess.Popen(
            [sys.executable, "scarlet_resultados.py", "--hoy"],
            cwd=cfg["scarlet"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _SCARLET["ultimo"] = time.time()
        log(f"Scarlet: buscando el resultado de {len(pendientes)} partido(s) que ya terminaron.")
        return True
    except Exception as e:
        log(f"No se pudo lanzar Scarlet ({type(e).__name__}: {e}). Revisa scarlet_carpeta en config.ini.")
        _SCARLET["ultimo"] = time.time()      # para no reintentar en bucle
        return False


# --------------------------------------------- marcadores en vivo (opcional)

_AVISO_VIVO = {"dado": False}


def marcadores_vivos(cfg, partidos):
    """
    {clave_partido: {gl, gv, estado, minuto}} con el marcador en vivo de hoy.

    De dónde sale, según `fuente_vivo` en config.ini:

      navegador (por defecto) — lo lee la extensión Scarlet 3.3 en BetMines,
          con tu navegador abierto, y lo manda al servidor de vivo.py. Es el
          que funciona: las APIs devuelven 403 desde Python.
      api — el método viejo (marcadores.py, SofaScore). Se deja por si algún
          día vuelve a responder.

    Es opcional de punta a punta: si falla, devuelve {} y todo lo demás sigue
    igual, solo que sin marcador. Nunca escribe nada en el Excel.
    """
    if not cfg.get("vivo"):
        return {}

    if cfg.get("fuente_vivo", "navegador") == "navegador":
        try:
            import vivo
        except ImportError:
            if not _AVISO_VIVO["dado"]:
                log("Falta vivo.py; sigo sin marcador en vivo.")
                _AVISO_VIVO["dado"] = True
            return {}
        if not vivo.iniciar(registro=log):
            return {}
        vivo.fijar_partidos(partidos, segundos=cfg.get("refresco_vivo", 30),
                            fichas=cfg.get("fichas_vivo", True),
                            max_pestanas=cfg.get("max_pestanas", 8))
        vivo.asegurar_navegador(cfg)
        return vivo.marcadores(cfg, partidos)

    try:
        import marcadores
    except ImportError:
        return {}
    try:
        eventos = marcadores.eventos_del_dia(refrescar_cada=cfg["refresco_vivo"])
    except Exception as e:
        if not _AVISO_VIVO["dado"]:
            log(f"Marcador en vivo no disponible ({type(e).__name__}); sigo sin él.")
            _AVISO_VIVO["dado"] = True
        return {}
    if not eventos:
        if not _AVISO_VIVO["dado"]:
            log("Marcador en vivo: la fuente no devolvió partidos; sigo sin él.")
            _AVISO_VIVO["dado"] = True
        return {}

    hoy = datetime.now().date()
    salida = {}
    for p in partidos:
        if p["fecha"] != hoy:
            continue
        nombre = str(p["nombre"])
        if " vs " not in nombre:
            continue
        local, visitante = nombre.split(" vs ", 1)
        try:
            gl, gv, est, minuto = marcadores.marcador_de(local, visitante, eventos)
        except Exception:
            continue
        if est:
            salida[p["clave"]] = {"gl": gl, "gv": gv, "estado": est, "minuto": minuto}
    return salida


def avisar_cambios_marcador(cfg, estado, partidos, vivos, simular=False):
    """
    Avisa al celular cada vez que cambia el marcador de un partido en juego.

      · GOL (prioridad_gol, alarma por defecto).
      · SE CAYÓ EL UNDER: cuando el total llega a 3 (prioridad_under_perdido).
      · GOL ANULADO: si el marcador BAJA y se mantiene así en la vuelta
        siguiente (el VAR lo anuló). Una sola lectura rara no basta: así una
        página que se dibujó a medias no inventa anulaciones.

    Lo último visto se guarda en estado_avisos.json, así reiniciar no reenvía
    avisos viejos.
    """
    if not cfg["avisar_goles"] or not vivos:
        return 0
    previos = estado.setdefault("marcador_visto", {})
    bajas = estado.setdefault("marcador_baja", {})
    por_clave = {p["clave"]: p for p in partidos}
    enviados = 0

    for clave, v in vivos.items():
        if v["estado"] not in ("vivo", "descanso", "fin"):
            continue
        if v["gl"] is None or v["gv"] is None:
            continue
        ahora_txt = f"{v['gl']}-{v['gv']}"
        antes_txt = previos.get(clave)
        if antes_txt == ahora_txt:
            bajas.pop(clave, None)
            continue

        # La primera vez que se ve un partido no se avisa: no es un gol nuevo,
        # es que recién empezamos a mirarlo.
        if antes_txt is None:
            previos[clave] = ahora_txt
            continue

        p = por_clave.get(clave)
        try:
            agl, agv = (int(x) for x in antes_txt.split("-"))
        except ValueError:
            agl, agv = 0, 0
        antes_total = agl + agv
        total = v["gl"] + v["gv"]
        minuto = f"min {v['minuto']}" if v.get("minuto") else v["estado"]

        if v["gl"] < agl or v["gv"] < agv:
            # Bajó: se confirma en la vuelta siguiente antes de creerlo.
            if bajas.get(clave) != ahora_txt:
                bajas[clave] = ahora_txt
                continue
            bajas.pop(clave, None)
            previos[clave] = ahora_txt
            if p is not None and cfg.get("avisar_anulados", True):
                restante = "vuelve a ser Under 2.5" if total <= 2 < antes_total else (
                    "sigue Under 2.5" if total <= 2 else "sigue Over 2.5")
                if avisar(cfg, "↩️ GOL ANULADO",
                          f"{p['nombre']}\nQueda {v['gl']} - {v['gv']} (antes {antes_txt})\n{minuto}\n{restante}",
                          3, simular, "anulado", clave):
                    enviados += 1
                    log(f"→ gol anulado: {p['nombre']} {antes_txt} → {ahora_txt}")
            continue

        bajas.pop(clave, None)
        previos[clave] = ahora_txt
        if p is None or total <= antes_total:
            continue

        quien = ""
        if " vs " in str(p["nombre"]):
            loc, vis = str(p["nombre"]).split(" vs ", 1)
            quien = loc if v["gl"] > agl else vis
        pie = (f"{p['nombre']}\n{v['gl']} - {v['gv']}  ({total} gol{'es' if total != 1 else ''})"
               f"\n{minuto}" + (f" · marca {quien}" if quien else ""))
        if antes_total <= 2 <= total - 1:
            # acaba de entrar el tercero: el Under 2.5 se perdió
            if avisar(cfg, "❌ SE CAYÓ EL UNDER", pie + "\nYa es Over 2.5",
                      cfg["p_under_perdido"], simular, "under", clave):
                enviados += 1
                log(f"→ under perdido: {p['nombre']} {ahora_txt}")
        else:
            restante = "sigue Under 2.5" if total <= 2 else "ya es Over 2.5"
            if avisar(cfg, "⚽ GOL", pie + f"\n{restante}", cfg["p_gol"], simular, "gol", clave):
                enviados += 1
                log(f"→ gol: {p['nombre']} {ahora_txt}")

    # No dejar crecer el archivo para siempre.
    if len(previos) > 300:
        for k in list(previos)[:-150]:
            previos.pop(k, None)
    for k in list(bajas):
        if k not in previos:
            bajas.pop(k, None)
    return enviados


def rojas_netas(f):
    """
    Las rojas que de verdad cuentan: las del icono menos las que el VAR anuló.

    BetMines deja el icono de la roja en 1 aunque el VAR la anule (Belgrano–River
    del 18/10: roja a Lisandro López al 28', «Red card overturned» al 29', y el
    icono siguió en 1). La extensión cuenta aparte las anulaciones; aquí se
    restan. No se sabe de qué equipo es cada anulación, así que se quita del
    lado que tiene rojas (si los dos tienen, del que tiene más).
    """
    rl, rv = f.get("rojas"), f.get("rojasV")
    if rl is None and rv is None:
        return None, None
    rl, rv = int(rl or 0), int(rv or 0)
    k = int(f.get("rojasAnuladas") or 0)
    while k > 0 and (rl > 0 or rv > 0):
        if rl > 0 and rl >= rv:
            rl -= 1
        else:
            rv -= 1
        k -= 1
    return rl, rv


def avisar_tarjetas_rojas(cfg, estado, partidos, simular=False):
    """
    Avisa cuando sale una tarjeta roja en un partido que estás mirando.

    Una expulsión cambia el partido más que casi cualquier otra cosa, y para
    Under 2.5 suele ser buena noticia: con diez hombres el equipo se repliega.
    Por eso va aparte del gol y con su propia prioridad.

    Las rojas salen de la ficha que lee la extensión en la página del partido.
    Solo se avisa cuando el número SUBE: si BetMines corrige hacia abajo (pasó
    de 1 a 0 porque era un error), no se avisa nada.
    """
    if not cfg.get("avisar_rojas"):
        return 0
    try:
        import vivo
    except ImportError:
        return 0

    fichas = vivo.fichas()
    if not fichas:
        return 0
    previos = estado.setdefault("rojas_vistas", {})
    por_clave = {p["clave"]: p for p in partidos}
    enviados = 0

    for clave, f in fichas.items():
        rl, rv = rojas_netas(f)
        if rl is None:
            continue
        antes = previos.get(clave)
        previos[clave] = [rl, rv]
        if antes is None:                 # primera vez que se ve: no es nueva
            continue
        try:
            arl, arv = int(antes[0]), int(antes[1])
        except (TypeError, ValueError, IndexError):
            continue
        p = por_clave.get(clave)
        if p is None:
            continue
        if rl < arl or rv < arv:
            # El VAR la anuló (o BetMines la corrigió): se avisa para que no quede la duda.
            if cfg.get("avisar_anulados", True) and rl <= arl and rv <= arv:
                quien = ""
                if " vs " in str(p["nombre"]):
                    loc, vis = str(p["nombre"]).split(" vs ", 1)
                    quien = loc if rl < arl else vis
                minuto = f"\nmin {f['minuto']}" if f.get("minuto") else ""
                if avisar(cfg, "↩️ ROJA ANULADA", f"{p['nombre']}{minuto}\nEl VAR le quitó la roja a {quien}"
                          f"\nVuelven a ser 11 contra 11" if rl == 0 and rv == 0 else
                          f"{p['nombre']}{minuto}\nAnularon una roja de {quien}",
                          3, simular, "anulado", clave):
                    enviados += 1
                    log(f"→ roja anulada: {p['nombre']} ({quien})")
            continue
        if rl <= arl and rv <= arv:       # igual
            continue
        nombre = str(p["nombre"])
        local, visitante = (nombre.split(" vs ", 1) + [""])[:2] if " vs " in nombre else (nombre, "")
        quien = local if rl > arl else visitante
        cuantas = (rl - arl) + (rv - arv)

        marcador = ""
        if f.get("gl") is not None and f.get("gv") is not None:
            marcador = f"\n{f['gl']} - {f['gv']}"
        minuto = f"\nmin {f['minuto']}" if f.get("minuto") else ""
        texto = (f"{nombre}{marcador}{minuto}\nExpulsado: {quien}"
                 f"\nQuedan {11 - (rl if rl > arl else rv)} contra 11")
        titulo = "🟥 ROJA" if cuantas == 1 else "🟥 ROJAS"
        if avisar(cfg, titulo, texto, cfg["p_roja"], simular, "roja", clave):
            enviados += 1
            log(f"→ roja: {nombre} ({quien})")

    if len(previos) > 300:
        for k in list(previos)[:-150]:
            previos.pop(k, None)
    return enviados


# ------------------------------------------------ el estado para el celular

TITULO_ENLACE = "__ENLACE__"
MARCA_ESTADO = "MATRIX2"
MARCA_ESTADO_MANANA = "MATRIX3"     # el mismo formato, más los de mañana
TITULO_ESTADO = "__ESTADO__"
MAX_PARTIDOS_ESTADO = 40
MAX_PARTIDOS_MANANA = 20
LIMITE_ESTADO = 3600


def texto_estado(cfg, partidos, ahora=None, vivos=None):
    """
    Arma el resumen del día que la app del celular pinta en pantalla.
    Una línea por partido, compacto, para que entre en un solo mensaje:

        MATRIX2|<enviado HH:MM>|<dd/mm/aaaa>
        HH:MM|GL|GV|susp|nombre|competición|vGL|vGV|vEstado|vMinuto

    GL y GV son los del Excel (los que tú cargas). Los que empiezan por v son
    el marcador en vivo, si se consiguió: vEstado vale vivo, descanso, fin o
    suspendido, y va vacío cuando no hay dato. La app calcula sola el minuto
    con la hora de inicio, así el reloj avanza entre un envío y el siguiente.
    """
    ahora = ahora or datetime.now()
    hoy = ahora.date()
    manana = hoy + timedelta(days=1)
    vivos = vivos or {}
    con_manana = bool(cfg.get("mandar_manana"))

    def fila(p, nd):
        hora = f"{p['inicio']:%H:%M}" if p["inicio"] else ""
        gl = "" if p["gl"] is None else str(p["gl"])
        gv = "" if p["gv"] is None else str(p["gv"])
        nombre = str(p["nombre"]).replace("|", " ")[:34]
        comp = str(p["competicion"]).replace("|", " ")[:14]
        v = vivos.get(p["clave"]) or {}
        vgl = "" if v.get("gl") is None else str(v["gl"])
        vgv = "" if v.get("gv") is None else str(v["gv"])
        vest = v.get("estado") or ""
        vmin = "" if v.get("minuto") is None else str(v["minuto"])
        return (f"{hora}|{gl}|{gv}|{1 if p['suspendido'] else 0}|{nombre}|{comp}"
                f"|{vgl}|{vgv}|{vest}|{vmin}|{nd}")

    dia = [p for p in partidos if p["fecha"] == hoy and interesa(cfg, p)]
    dia.sort(key=lambda p: p["inicio"] or datetime.max)

    marca = MARCA_ESTADO_MANANA if con_manana else MARCA_ESTADO
    cabecera = f"{marca}|{ahora:%H:%M}|{hoy:%d/%m/%Y}"
    filas_hoy = [fila(p, 0) for p in dia[:MAX_PARTIDOS_ESTADO]]

    # Los de mañana solo si la app sabe leerlos (config: mandar_manana).
    # Una app vieja no entendería el día y los pintaría como de hoy.
    filas_manana = []
    if con_manana:
        otro = [p for p in partidos if p["fecha"] == manana and interesa(cfg, p)]
        otro.sort(key=lambda p: p["inicio"] or datetime.max)
        filas_manana = [fila(p, 1) for p in otro[:MAX_PARTIDOS_MANANA]]

    # El mensaje tiene un tope de tamaño. Si se pasa, se van quitando primero
    # los de mañana (los menos urgentes) y después los últimos de hoy. Es
    # preferible una lista incompleta a un mensaje que el celular rechace
    # entero y deje la pantalla en blanco.
    while True:
        cuerpo = "\n".join([cabecera] + filas_hoy + filas_manana)
        if len(cuerpo.encode("utf-8")) <= LIMITE_ESTADO:
            return cuerpo
        if filas_manana:
            filas_manana.pop()
        elif len(filas_hoy) > 1:
            filas_hoy.pop()
        else:
            return cuerpo


# ------------------------------------------- las estadísticas para el celular

MARCA_FICHAS = "MATRIXF"
TITULO_FICHAS = "__FICHAS__"
MAX_FICHAS = 8
MAX_STATS = 8


def texto_fichas(partidos, fichas, ahora=None):
    """
    Las estadísticas de los partidos en juego, para desplegarlas en el celular
    al tocar un partido:

        MATRIXF|<enviado HH:MM>
        nombre|gl|gv|minuto|córners,cambios,amarillas,rojas (local)|(visitante)|datos

    Los datos van como  Nombre~local~visitante  separados por punto y coma.
    El nombre del partido es la llave: es el mismo que va en el resumen.
    """
    ahora = ahora or datetime.now()
    por_clave = {p["clave"]: p for p in partidos}
    lineas = [f"{MARCA_FICHAS}|{ahora:%H:%M}"]

    for clave, f in list(fichas.items())[:MAX_FICHAS]:
        p = por_clave.get(clave)
        if p is None:
            continue
        nombre = str(p["nombre"]).replace("|", " ")[:34]
        gl = "" if f.get("gl") is None else str(f["gl"])
        gv = "" if f.get("gv") is None else str(f["gv"])
        minuto = "" if f.get("minuto") is None else str(f["minuto"])

        def cuatro(a, b, c, d):
            return ",".join("" if x is None else str(int(x))
                            for x in (f.get(a), f.get(b), f.get(c), f.get(d)))

        local = cuatro("corners", "cambios", "amarillas", "rojas")
        visita = cuatro("cornersV", "cambiosV", "amarillasV", "rojasV")
        datos = ";".join(
            f"{str(s.get('nombre', ''))[:24]}~{str(s.get('local', ''))[:9]}"
            f"~{str(s.get('visitante', ''))[:9]}".replace("|", " ")
            for s in (f.get("stats") or [])[:MAX_STATS])
        lineas.append(f"{nombre}|{gl}|{gv}|{minuto}|{local}|{visita}|{datos}")

    return "\n".join(lineas) if len(lineas) > 1 else ""


def _app_al_dia():
    """¿La app está leyendo directo de la PC? Entonces el resumen por ntfy sobra."""
    if not _APP["activo"]:
        return False
    try:
        import servidor_app
        return servidor_app.telefono_reciente(180)
    except ImportError:
        return False


def mandar_fichas(cfg, estado, partidos, simular=False):
    """
    RESPALDO: las estadísticas por ntfy solo si la app no está leyendo directo,
    como mucho cada `mandar_estado_cada_minutos` y por debajo de los 4 KB que
    acepta ntfy (más grande, ntfy lo convierte en archivo y la app no lo lee).
    """
    if not cfg.get("vivo") or not cfg.get("fichas_vivo") or _app_al_dia():
        return False
    if time.time() - float(estado.get("fichas_enviado_en") or 0) < max(10, cfg["estado_cada"]) * 60:
        return False
    try:
        import vivo
    except ImportError:
        return False
    cuerpo = texto_fichas(partidos, vivo.fichas())
    while len(cuerpo.encode("utf-8")) > 3900 and cuerpo.count("\n") > 1:
        cuerpo = cuerpo.rsplit("\n", 1)[0]
    if not cuerpo:
        return False
    firma = hashlib.md5(cuerpo.encode("utf-8")).hexdigest()
    if firma == estado.get("fichas_firma"):
        return False
    if enviar(cfg, TITULO_FICHAS, cuerpo, 1, simular):
        estado["fichas_firma"] = firma
        estado["fichas_enviado_en"] = time.time()
        return True
    return False


def mandar_estado(cfg, estado, partidos, vivos=None, simular=False, forzar=False):
    """
    RESPALDO: el resumen del día por ntfy. Si la app está leyendo directo de la
    PC no se manda (ya tiene todo, y al segundo). Si no, va cada
    `mandar_estado_cada_minutos` (15 por defecto) y solo si algo cambió.

    Antes salía cada vez que cambiaba algo, y como el resumen lleva la hora,
    eso era cada minuto: el cupo diario de ntfy se acababa en pocas horas.
    """
    if cfg["estado_cada"] <= 0:
        return False
    if not forzar and _app_al_dia():
        return False
    cuerpo = texto_estado(cfg, partidos, vivos=vivos or {})
    # La firma no lleva la cabecera (que trae la hora): solo cuenta si cambiaron los partidos.
    firma = hashlib.md5(cuerpo.split("\n", 1)[-1].encode("utf-8")).hexdigest()
    pasado = time.time() - float(estado.get("estado_enviado_en") or 0)
    cambio = firma != estado.get("estado_firma")
    if not forzar and (pasado < max(5, cfg["estado_cada"]) * 60 or (not cambio and pasado < 3600)):
        return False
    # Prioridad 1 y un título reservado: la app lo guarda para la pantalla y
    # NO lo muestra como aviso. Si llegara a un teléfono sin la app nueva,
    # entra como una notificación silenciosa y no molesta.
    if enviar(cfg, TITULO_ESTADO, cuerpo, 1, simular):
        estado["estado_firma"] = firma
        estado["estado_enviado_en"] = time.time()
        return True
    return False


# ------------------------------------------- lo que la app lee directo de la PC

def guardar_fichas_dia(estado, partidos):
    """
    Las estadísticas de cada partido de hoy quedan guardadas todo el día (y
    sobreviven a reiniciar): así un partido terminado sigue mostrando las suyas.
    """
    try:
        import vivo
        nuevas = vivo.fichas()
    except ImportError:
        nuevas = {}
    hoy = datetime.now().strftime("%Y-%m-%d")
    dia = estado.setdefault("fichas_dia", {})
    for f in list(dia):
        if f != hoy:
            dia.pop(f, None)
    guardadas = dia.setdefault(hoy, {})
    claves_hoy = {p["clave"] for p in partidos if p["fecha"] == datetime.now().date()}
    cambio = False
    for clave, f in nuevas.items():
        if clave not in claves_hoy:
            continue
        limpia = {k: v for k, v in f.items() if k not in ("visto", "clave")}
        if guardadas.get(clave) != limpia:
            guardadas[clave] = limpia
            cambio = True
    return guardadas, cambio


def situacion(p, v, ahora, minutos_partido):
    """Lo mismo que estado_partido, pero el marcador en vivo manda sobre el reloj estimado."""
    if p["suspendido"] or (v or {}).get("estado") == "suspendido":
        return "suspendido"
    if p["gl"] is not None and p["gv"] is not None:
        return "listo"
    est = (v or {}).get("estado")
    if est == "fin":
        return "listo"
    if est in ("vivo", "descanso"):
        return "en_curso"
    return estado_partido(p, ahora, minutos_partido)[0]


def datos_app(cfg, partidos, vivos, fichas_dia, ahora=None):
    """Todo lo que la app pinta: los partidos de hoy (y mañana) con marcador, minuto y estadísticas."""
    ahora = ahora or datetime.now()
    hoy = ahora.date()
    manana = hoy + timedelta(days=1)
    lista = []
    for p in sorted(partidos, key=lambda x: x["inicio"] or datetime.max):
        if p["fecha"] not in (hoy, manana) or not interesa(cfg, p):
            continue
        if p["fecha"] == manana and not cfg.get("mandar_manana"):
            continue
        v = vivos.get(p["clave"]) if p["fecha"] == hoy else None
        f = fichas_dia.get(p["clave"]) if p["fecha"] == hoy else None
        local, visitante = (str(p["nombre"]).split(" vs ", 1) + [""])[:2] if " vs " in str(p["nombre"]) \
            else (str(p["nombre"]), "")
        ficha = None
        if f:
            rl, rv = rojas_netas(f)
            ficha = {
                "gl": f.get("gl"), "gv": f.get("gv"), "minuto": f.get("minuto"),
                "corners": f.get("corners"), "cambios": f.get("cambios"),
                "amarillas": f.get("amarillas"), "rojas": rl,
                "cornersV": f.get("cornersV"), "cambiosV": f.get("cambiosV"),
                "amarillasV": f.get("amarillasV"), "rojasV": rv,
                "rojasAnuladas": int(f.get("rojasAnuladas") or 0),
                "stats": [{"nombre": str(x.get("nombre", "")), "local": str(x.get("local", "")),
                           "visitante": str(x.get("visitante", ""))} for x in (f.get("stats") or [])][:16],
            }
        lista.append({
            "clave": p["clave"],
            "nombre": str(p["nombre"]),
            "local": local.strip(), "visitante": visitante.strip(),
            "competicion": p["competicion"],
            "hora": f"{p['inicio']:%H:%M}" if p["inicio"] else "",
            "dia": 0 if p["fecha"] == hoy else 1,
            "gl": p["gl"], "gv": p["gv"], "susp": bool(p["suspendido"]),
            "vivo": ({"gl": v.get("gl"), "gv": v.get("gv"), "estado": v.get("estado") or "",
                      "minuto": v.get("minuto")} if v else None),
            "situacion": situacion(p, v, ahora, cfg["minutos_partido"]) if p["fecha"] == hoy else "por_jugar",
            "ficha": ficha,
            "previa": p.get("previa") or [],
        })
    try:
        import enlace
        e = enlace.enlaces(cfg["puerto_app"])
        enlaces = {"lan": e.get("lan", ""), "publico": e.get("publico", "")}
    except ImportError:
        enlaces = {}
    return {"v": 2, "enlaces": enlaces, "hoy": f"{hoy:%d/%m/%Y}", "hora": f"{ahora:%H:%M}",
            "generado": ahora.strftime("%Y-%m-%dT%H:%M:%S"), "duracion": cfg["minutos_partido"],
            "partidos": lista}


def publicar_app(cfg, estado, partidos, vivos):
    if not _APP["activo"]:
        return
    fichas_dia, _ = guardar_fichas_dia(estado, partidos)
    try:
        import servidor_app
        servidor_app.publicar(datos_app(cfg, partidos, vivos or {}, fichas_dia))
        estado["buzon"] = servidor_app.para_guardar()
    except Exception as e:
        log(f"No pude preparar los datos para la app ({type(e).__name__}: {e})")


def una_vuelta(cfg, estado, simular=False):
    """Una revisión completa. Devuelve (avisos_enviados, partidos_leídos)."""
    try:
        partidos = leer_partidos(cfg["excel"])
    except FileNotFoundError:
        log(f"No encuentro el Excel: {cfg['excel']}")
        return 0, []
    except PermissionError:
        log("El Excel está bloqueado justo ahora; lo intento en la próxima vuelta.")
        return 0, []
    except Exception as e:
        log(f"No se pudo leer el Excel ({type(e).__name__}: {e})")
        return 0, []

    ahora = datetime.now()
    hoy = ahora.date()
    limite_atras = hoy - timedelta(days=cfg["dias_atras"])
    enviados = 0

    # La primera vez se marcan como vistos todos los resultados que YA están
    # cargados. Si no, al arrancar saldrían cientos de avisos de golpe.
    if not estado.get("sembrado"):
        for p in partidos:
            if p["suspendido"] or (p["gl"] is not None and p["gv"] is not None):
                estado["resultado"][p["clave"]] = "sembrado"
        estado["sembrado"] = True
        guardar_estado(estado)
        log(f"Primera vez: {len(estado['resultado'])} resultados ya cargados quedan marcados "
            f"como vistos (no se avisan).")

    pendientes_viejos = []

    for p in partidos:
        if not interesa(cfg, p):
            continue

        # ---- aviso previo: solo partidos de hoy que todavía no empezaron
        if p["inicio"] and p["fecha"] == hoy and p["clave"] not in estado["previo"]:
            falta = (p["inicio"] - ahora).total_seconds() / 60.0
            # Se avisa dentro de la ventana [15 min antes, 10 min después del inicio].
            # El margen de atrás cubre un corte de luz o que la PC estuviera dormida;
            # más allá de eso el aviso ya no sirve de nada y se deja pasar.
            if -10 <= falta <= cfg["minutos_antes"]:
                cuando = "EMPEZANDO" if falta <= 0 else f"EN {int(round(falta))} MIN"
                texto = (f"{p['nombre']}\n"
                         f"{p['hora_txt']}"
                         + (f"\n{p['competicion']}" if p["competicion"] else ""))
                if avisar(cfg, f"⚽ {cuando}", texto, cfg["p_previo"], simular, "previo", p["clave"]):
                    estado["previo"][p["clave"]] = ahora.isoformat(timespec="seconds")
                    enviados += 1
                    log(f"→ previo: {p['nombre']} ({p['hora_txt']})")

        # ---- resultado: de hoy y de los días anteriores, por si lo cargas tarde
        if cfg["avisar_resultado"] and p["fecha"] >= limite_atras:
            ya = p["clave"] in estado["resultado"]
            if p["suspendido"] and not ya:
                if avisar(cfg, "⏸ SUSPENDIDO", f"{p['nombre']}\nMarcado SR en el registro.",
                          3, simular, "suspendido", p["clave"]):
                    estado["resultado"][p["clave"]] = ahora.isoformat(timespec="seconds")
                    enviados += 1
                    log(f"→ suspendido: {p['nombre']}")
            elif p["gl"] is not None and p["gv"] is not None and not ya:
                if avisar(cfg, "🏁 FINAL", texto_resultado(p), cfg["p_resultado"], simular, "final", p["clave"]):
                    estado["resultado"][p["clave"]] = ahora.isoformat(timespec="seconds")
                    enviados += 1
                    log(f"→ resultado: {p['nombre']} {p['gl']}-{p['gv']}")
            elif (not ya and p["inicio"] and p["fecha"] == hoy
                  and ahora - p["inicio"] > timedelta(hours=2, minutes=30)):
                pendientes_viejos.append(p)

    # ---- que Scarlet busque los que ya terminaron y siguen sin cargar
    if not simular:
        lanzar_scarlet(cfg, pendientes_viejos)

    # ---- recordatorio único de los que ya terminaron y siguen sin resultado
    if cfg["recordar_horas"] > 0 and pendientes_viejos:
        desde = float(estado.get("ultimo_recordatorio") or 0)
        if time.time() - desde >= cfg["recordar_horas"] * 3600:
            lista = "\n".join(f"· {x['nombre']}" for x in pendientes_viejos[:12])
            extra = f"\n… y {len(pendientes_viejos) - 12} más" if len(pendientes_viejos) > 12 else ""
            if avisar(cfg, "📋 Faltan resultados",
                      f"{len(pendientes_viejos)} partido(s) ya terminaron y siguen sin "
                      f"cargar en el Excel:\n{lista}{extra}", 2, simular):
                estado["ultimo_recordatorio"] = time.time()
                enviados += 1

    # Una sola consulta de marcadores por vuelta: sirve para avisar los goles
    # y para el resumen que ve el celular.
    vivos = marcadores_vivos(cfg, partidos)
    if avisar_cambios_marcador(cfg, estado, partidos, vivos, simular):
        guardar_estado(estado)
    if avisar_tarjetas_rojas(cfg, estado, partidos, simular):
        guardar_estado(estado)
    if not simular:
        publicar_app(cfg, estado, partidos, vivos)
        anunciar_enlace(cfg, estado)
    if mandar_estado(cfg, estado, partidos, vivos, simular):
        guardar_estado(estado)
    if mandar_fichas(cfg, estado, partidos, simular):
        guardar_estado(estado)
    estado["cupo_ntfy"] = dict(CUPO)
    guardar_estado(estado)
    return enviados, partidos


# ------------------------------------------------------------------ comandos

# ------------------------------------------------------------------ color

# Paleta, la misma del extractor para que todo se vea de la misma familia.
PAL = {
    "cian":    (34, 211, 238),
    "verde":   (62, 207, 142),
    "ambar":   (255, 184, 77),
    "rojo":    (255, 107, 107),
    "magenta": (192, 132, 252),
    "azul":    (91, 140, 255),
    "suave":   (122, 132, 158),
    "texto":   (230, 232, 239),
    "tenue":   (74, 82, 104),
}
COLOR_ON = True


def activar_color():
    """En Windows hay que pedirle a la consola que entienda los colores."""
    global COLOR_ON
    if not sys.stdout.isatty():
        COLOR_ON = False
        return
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            # 7 = salida procesada + salto de línea + secuencias de color
            if not k.SetConsoleMode(k.GetStdHandle(-11), 7):
                COLOR_ON = False
        except Exception:
            COLOR_ON = False


def c(texto, color=None, negrita=False, fondo=None):
    if not COLOR_ON:
        return texto
    partes = []
    if negrita:
        partes.append("1")
    if color and color in PAL:
        r, g, b = PAL[color]
        partes.append(f"38;2;{r};{g};{b}")
    if fondo and fondo in PAL:
        r, g, b = PAL[fondo]
        partes.append(f"48;2;{r};{g};{b}")
    if not partes:
        return texto
    return "\033[" + ";".join(partes) + "m" + texto + "\033[0m"


def _visible(s):
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _rellenar(s, ancho):
    return s + " " * max(0, ancho - _visible(s))


def _regla(titulo, cantidad, color, ancho=78, icono="·"):
    """'  ● EN VIVO ───────────────────── 9 partidos'"""
    izq = f"  {icono} {titulo} "
    der = f" {cantidad} "
    guiones = max(3, ancho - len(izq) - len(der) - 2)
    return (c(f"  {icono} ", color, True) + c(titulo, color, True) + " "
            + c("─" * guiones, "tenue") + " " + c(der.strip(), color))


def _barra(minutos, total=115, n=8):
    """Barra del avance del partido, que va cambiando de color."""
    llenos = max(0, min(n, int(round(minutos / total * n))))
    if minutos <= 45:
        col = "verde"
    elif minutos <= 60:
        col = "cian"
    elif minutos <= 95:
        col = "ambar"
    else:
        col = "rojo"
    return c("━" * llenos, col) + c("─" * (n - llenos), "tenue")


# --------------------------------------------------------------- el panel

def estado_partido(p, ahora, minutos_partido):
    """
    En qué anda cada partido. Ojo: el minuto es ESTIMADO a partir de la hora de
    inicio del Excel. Esto no se conecta a ningún marcador en vivo; no sabe de
    retrasos ni de descuentos.
      por_jugar · en_curso · esperando (ya debió terminar, falta cargar el
      resultado) · listo · suspendido
    """
    if p["suspendido"]:
        return "suspendido", None
    if p["gl"] is not None and p["gv"] is not None:
        return "listo", None
    if p["inicio"] is None:
        return "por_jugar", None
    minutos = (ahora - p["inicio"]).total_seconds() / 60.0
    if minutos < 0:
        return "por_jugar", -minutos          # cuántos minutos faltan
    if minutos <= minutos_partido:
        return "en_curso", minutos            # minuto aproximado de juego
    return "esperando", minutos


def _falta(minutos):
    """68 -> '1 h 08 min'."""
    m = int(round(minutos))
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60:02d} min"


def _reloj(minutos):
    """Minuto de juego aproximado, descontando los 15 del entretiempo."""
    m = int(minutos)
    if m <= 45:
        return f"min ~{m}"
    if m <= 60:
        return "descanso"
    if m - 15 >= 90:
        return "terminando"       # ya pasó el 90, está por acabar
    return f"min ~{m - 15}"


def panel(cfg, partidos, estado, ahora=None):
    """Dibuja la pantalla: lo que está en juego ahora y lo que viene después."""
    ahora = ahora or datetime.now()
    hoy = ahora.date()
    A = 78
    hoy_lista = [p for p in partidos if p["fecha"] == hoy and interesa(cfg, p)]

    grupos = {"en_curso": [], "por_jugar": [], "esperando": [], "listo": [], "suspendido": []}
    for p in hoy_lista:
        est, dato = estado_partido(p, ahora, cfg["minutos_partido"])
        grupos[est].append((p, dato))
    grupos["en_curso"].sort(key=lambda t: -(t[1] or 0))
    grupos["por_jugar"].sort(key=lambda t: t[1] or 0)
    grupos["esperando"].sort(key=lambda t: -(t[1] or 0))
    grupos["listo"].sort(key=lambda t: t[0]["inicio"] or datetime.max)

    DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
    L = []

    # ---- cabecera
    L.append(c("╔" + "═" * (A - 2) + "╗", "cian"))
    marca = c("▌▌ ", "magenta", True) + c("M A T R I X", "cian", True) + c("  ·  ", "tenue") \
        + c("vigilante de partidos", "texto")
    reloj = c(f"{DIAS[ahora.weekday()]} {ahora:%d/%m}", "suave") + "  " \
        + c(f"{ahora:%H:%M}", "cian", True)
    hueco = max(1, A - 4 - _visible(marca) - _visible(reloj))
    L.append(c("║", "cian") + " " + marca + " " * hueco + reloj + " " + c("║", "cian"))
    L.append(c("╚" + "═" * (A - 2) + "╝", "cian"))

    # ---- en curso
    n = len(grupos["en_curso"])
    L.append("")
    L.append(_regla("EN VIVO", f"{n} partido{'s' if n != 1 else ''}" if n else "ninguno ahora",
                    "rojo" if n else "tenue", A, "●"))
    for p, mins in grupos["en_curso"]:
        texto_reloj = _reloj(mins)
        if texto_reloj == "descanso":
            etiqueta = c(_rellenar("descanso", 11), "cian", True)
        elif texto_reloj == "terminando":
            etiqueta = c(_rellenar("terminando", 11), "rojo", True)
        else:
            etiqueta = c(_rellenar(texto_reloj.replace("min ~", "min ") + "'", 11), "ambar", True)
        fin = p["inicio"] + timedelta(minutes=cfg["minutos_partido"])
        L.append("     " + _barra(mins, cfg["minutos_partido"]) + "  " + etiqueta
                 + c(_rellenar(p["nombre"][:38], 38), "texto")
                 + c(f" {p['hora_txt']:>5}", "suave")
                 + c(" → ", "tenue") + c(f"{fin:%H:%M}", "suave"))
    if not n:
        L.append(c("       nada en juego en este momento", "tenue"))

    # ---- los que vienen
    n = len(grupos["por_jugar"])
    L.append("")
    L.append(_regla("VIENEN HOY", f"{n} partido{'s' if n != 1 else ''}" if n else "no queda ninguno",
                    "cian" if n else "tenue", A, "●"))
    for p, falta in grupos["por_jugar"][:10]:
        avisado = p["clave"] in estado.get("previo", {})
        pronto = falta <= cfg["minutos_antes"]
        col = "ambar" if pronto else "cian"
        L.append("     " + c("▶", col) + "  " + c(_rellenar(_falta(falta), 11), col, pronto)
                 + c(_rellenar(p["nombre"][:38], 38), "texto")
                 + c(f" {p['hora_txt']:>5}", "suave")
                 + (c("  avisado", "verde") if avisado else ""))
    if n > 10:
        L.append(c(f"        … y {n - 10} más", "tenue"))
    if not n:
        L.append(c("       ya salieron todos los de hoy", "tenue"))

    # ---- esperando resultado
    if grupos["esperando"]:
        L.append("")
        L.append(_regla("ESPERANDO RESULTADO", str(len(grupos["esperando"])), "magenta", A, "●"))
        for p, mins in grupos["esperando"][:6]:
            fin = p["inicio"] + timedelta(minutes=cfg["minutos_partido"])
            L.append("     " + c("▸  ", "magenta")
                     + c(_rellenar(p["nombre"][:30], 30), "texto")
                     + c(f" {p['hora_txt']:>5}", "tenue")
                     + c(f"  terminó ~{fin:%H:%M}", "suave")
                     + c(f"  hace {_falta(mins - cfg['minutos_partido'])}", "tenue"))

    # ---- terminados
    if grupos["listo"] or grupos["suspendido"]:
        extra = f"  ·  {len(grupos['suspendido'])} susp." if grupos["suspendido"] else ""
        L.append("")
        L.append(_regla("FINALIZADOS", f"{len(grupos['listo'])}{extra}", "verde", A, "●"))
        unders = sum(1 for p, _ in grupos["listo"] if p["gl"] + p["gv"] <= 2)
        for p, _ in grupos["listo"][-6:]:
            total = p["gl"] + p["gv"]
            es_under = total <= 2
            marcador = c(f" {p['gl']}-{p['gv']} ", "verde" if es_under else "rojo", True)
            sello = c(" UNDER 2.5 ", "texto", True, "verde") if es_under \
                else c(" over 2.5  ", "texto", False, "rojo")
            L.append("     " + marcador + " " + sello + "  "
                     + c(_rellenar(p["nombre"][:36], 36), "texto")
                     + c(f" {p['hora_txt']:>5}", "tenue"))
        if grupos["listo"]:
            L.append("     " + c(f"{unders} de {len(grupos['listo'])} terminaron Under 2.5 "
                                 f"({unders/len(grupos['listo']):.0%})", "suave"))

    # ---- últimos avisos
    L.append("")
    L.append(c("  " + "─" * (A - 4), "tenue"))
    for linea in ULTIMOS[-5:]:
        hora, _, resto = linea.partition("] ")
        L.append("   " + c(hora[1:], "tenue") + "  " + c(resto[:A - 16], "suave"))
    if not ULTIMOS:
        L.append("   " + c("todavía no ha salido ningún aviso", "tenue"))
    L.append(c("  " + "─" * (A - 4), "tenue"))
    L.append("   " + c("canal ", "tenue") + c(cfg["canal"], "magenta")
             + c("   ·   ", "tenue") + c(f"refresca cada {cfg['cada']} s", "tenue")
             + c("   ·   ", "tenue") + c("Ctrl+C", "ambar") + c(" para parar", "tenue"))
    L.append("   " + c(linea_app(cfg), "tenue"))
    return "\n".join(L)


def linea_app(cfg):
    """Una línea para el panel: si la app está leyendo directo, por dónde, y el cupo de ntfy."""
    cupo = _cupo_hoy()
    partes = []
    if _APP["activo"]:
        try:
            import servidor_app
            r = servidor_app.resumen()
            if r["hace"] is None:
                partes.append("app: todavía no se conecta")
            elif r["hace"] < 90:
                partes.append(f"app: conectada por {r['via']} (hace {int(r['hace'])} s)")
            else:
                partes.append(f"app: sin conectarse hace {int(r['hace'] // 60)} min (va todo por ntfy)")
        except ImportError:
            pass
        try:
            import enlace
            e = enlace.enlaces(cfg["puerto_app"])
            if e["lan"]:
                partes.append("dirección para el celular: " + e["lan"].replace("http://", "").replace(":8782", ""))
            partes.append("túnel: " + (e["publico"].replace("https://", "") if e["publico"]
                                       else (e.get("detalle") or "abriendo…")))
        except ImportError:
            pass
    else:
        partes.append("app: solo por ntfy")
    partes.append(f"ntfy hoy: {cupo['n']}/250")
    return "   ·   ".join(partes)


def pintar(cfg, partidos, estado):
    global COLOR_ON
    if not cfg.get("colores", True):
        COLOR_ON = False
    if cfg["panel"]:
        os.system("cls" if os.name == "nt" else "clear")
    print(panel(cfg, partidos, estado), flush=True)


def mostrar_hoy(cfg):
    partidos = [p for p in leer_partidos(cfg["excel"]) if p["fecha"] == datetime.now().date()]
    partidos.sort(key=lambda x: x["inicio"] or datetime.max)
    print(f"\nPartidos de hoy ({datetime.now():%d/%m/%Y}): {len(partidos)}\n")
    for p in partidos:
        if p["gl"] is not None and p["gv"] is not None:
            res = f"{p['gl']}-{p['gv']}  {'UNDER' if p['gl'] + p['gv'] <= 2 else 'OVER'}"
        elif p["suspendido"]:
            res = "SR"
        else:
            res = "—"
        print(f"  {p['hora_txt']:>6}  {p['nombre'][:46]:46.46s}  {res}")
    print()
    if cfg["competiciones"]:
        print(f"(filtro activo: solo {', '.join(cfg['competiciones'])})\n")
    avisos = len([p for p in partidos if interesa(cfg, p)])
    print(f"Con la configuración de ahora: hasta {avisos} avisos previos "
          f"y {avisos if cfg['avisar_resultado'] else 0} de resultado.\n")


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--probar", action="store_true", help="manda un aviso de prueba al celular")
    ap.add_argument("--hoy", action="store_true", help="lista los partidos de hoy y sale")
    ap.add_argument("--simular", action="store_true", help="enseña los avisos sin mandarlos")
    ap.add_argument("--curso", action="store_true",
                    help="enseña el panel de en curso / los que vienen, y sale")
    args = ap.parse_args()

    global COLOR_ON
    activar_color()
    cfg = cargar_config()
    if not cfg["colores"]:
        COLOR_ON = False
    estado_inicial = cargar_estado()

    if args.curso:
        try:
            print(panel(cfg, leer_partidos(cfg["excel"]), estado_inicial))
        except FileNotFoundError:
            print(f"No encuentro el Excel: {cfg['excel']}")
            return 1
        except Exception as e:
            print(f"No se pudo leer el Excel ({type(e).__name__}: {e})")
            return 1
        return 0

    print("=" * 62)
    print("  MATRIX — vigilante de partidos")
    print("=" * 62)
    print(f"  Excel   : {cfg['excel']}")
    print(f"  Canal   : {cfg['canal']}")
    print(f"  Servidor: {cfg['servidor']}")
    print("=" * 62)
    if cfg["canal_recien_creado"]:
        print()
        print("  ESTE ES TU CANAL PRIVADO. Pégalo en la app del celular:")
        print()
        print(f"      {cfg['canal']}")
        print()
        print("  Quien lo conozca puede ver tus avisos, así que no lo publiques.")
        print("  Queda guardado en config.ini; no hace falta que lo anotes.")
        print("=" * 62)
    print()

    if args.hoy:
        mostrar_hoy(cfg)
        return 0

    if args.probar:
        ok = enviar(cfg, "PRUEBA",
                    "Si ves esto en el celular con sonido, las alertas ya funcionan.",
                    5)
        print("Aviso enviado." if ok else "No se pudo enviar. Revisa internet y el canal.")
        return 0 if ok else 1

    estado = estado_inicial
    if isinstance(estado.get("cupo_ntfy"), dict):
        CUPO.update(estado["cupo_ntfy"])
    _cupo_hoy()

    if args.simular:
        n, _ = una_vuelta(cfg, estado, simular=True)
        print(f"\nAvisos que se mandarían ahora mismo: {n}\n")
        return 0

    _APP["desde"] = time.time()
    if iniciar_app(cfg, estado):
        try:
            import enlace
            lan = enlace.enlaces(cfg["puerto_app"])["lan"]
        except ImportError:
            lan = ""
        log(f"La app puede leer directo de esta PC{(' en ' + lan) if lan else ''} (y por túnel fuera de casa).")
    log("Vigilando. Deja esta ventana abierta (puedes minimizarla). Ctrl+C para parar.")
    primera = True
    try:
        while True:
            _, partidos = una_vuelta(cfg, estado)
            # Con el panel encendido se redibuja la pantalla en cada vuelta; los
            # avisos que fueron saliendo quedan en el recuadro de abajo.
            if partidos and (cfg["panel"] or primera):
                pintar(cfg, partidos, estado)
                primera = False
            time.sleep(cfg["cada"])
    except KeyboardInterrupt:
        log("Vigilancia detenida.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
