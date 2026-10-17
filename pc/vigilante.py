# -*- coding: utf-8 -*-
"""
vigilante.py — manda al celular los avisos de los partidos del día.

Lee la pestaña CONSTRUCK del registro (columnas B, F, G, H, I) y manda:
  * 15 minutos antes de cada partido: el aviso previo.
  * Cuando aparece el resultado en GL/GV: el marcador y si quedó Under o Over 2.5.

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
import json
import os
import random
import re
import shutil
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


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


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
            filas = list(ws.iter_rows(min_row=1, max_col=10, values_only=True))
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
        })
    return partidos


# ------------------------------------------------------------------- el envío

def enviar(cfg, titulo, texto, prioridad=5, simular=False):
    """Manda un aviso al canal. Devuelve True si salió."""
    if simular:
        log(f"   [simulado] p{prioridad} · {titulo} · {texto.replace(chr(10), ' / ')}")
        return True
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
                    return True
                log(f"   el servidor respondió {r.status}")
        except (urllib.error.URLError, OSError) as e:
            log(f"   no se pudo enviar ({e}); reintento {intento + 1}/3")
            time.sleep(3)
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


def una_vuelta(cfg, estado, simular=False):
    """Una revisión completa. Devuelve cuántos avisos salieron."""
    try:
        partidos = leer_partidos(cfg["excel"])
    except FileNotFoundError:
        log(f"No encuentro el Excel: {cfg['excel']}")
        return 0
    except PermissionError:
        log("El Excel está bloqueado justo ahora; lo intento en la próxima vuelta.")
        return 0
    except Exception as e:
        log(f"No se pudo leer el Excel ({type(e).__name__}: {e})")
        return 0

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
                if enviar(cfg, f"⚽ {cuando}", texto, cfg["p_previo"], simular):
                    estado["previo"][p["clave"]] = ahora.isoformat(timespec="seconds")
                    enviados += 1
                    log(f"→ previo: {p['nombre']} ({p['hora_txt']})")

        # ---- resultado: de hoy y de los días anteriores, por si lo cargas tarde
        if cfg["avisar_resultado"] and p["fecha"] >= limite_atras:
            ya = p["clave"] in estado["resultado"]
            if p["suspendido"] and not ya:
                if enviar(cfg, "⏸ SUSPENDIDO", f"{p['nombre']}\nMarcado SR en el registro.",
                          3, simular):
                    estado["resultado"][p["clave"]] = ahora.isoformat(timespec="seconds")
                    enviados += 1
                    log(f"→ suspendido: {p['nombre']}")
            elif p["gl"] is not None and p["gv"] is not None and not ya:
                if enviar(cfg, "🏁 FINAL", texto_resultado(p), cfg["p_resultado"], simular):
                    estado["resultado"][p["clave"]] = ahora.isoformat(timespec="seconds")
                    enviados += 1
                    log(f"→ resultado: {p['nombre']} {p['gl']}-{p['gv']}")
            elif (not ya and p["inicio"] and p["fecha"] == hoy
                  and ahora - p["inicio"] > timedelta(hours=2, minutes=30)):
                pendientes_viejos.append(p)

    # ---- recordatorio único de los que ya terminaron y siguen sin resultado
    if cfg["recordar_horas"] > 0 and pendientes_viejos:
        desde = float(estado.get("ultimo_recordatorio") or 0)
        if time.time() - desde >= cfg["recordar_horas"] * 3600:
            lista = "\n".join(f"· {x['nombre']}" for x in pendientes_viejos[:12])
            extra = f"\n… y {len(pendientes_viejos) - 12} más" if len(pendientes_viejos) > 12 else ""
            if enviar(cfg, "📋 Faltan resultados",
                      f"{len(pendientes_viejos)} partido(s) ya terminaron y siguen sin "
                      f"cargar en el Excel:\n{lista}{extra}", 2, simular):
                estado["ultimo_recordatorio"] = time.time()
                enviados += 1

    if enviados:
        guardar_estado(estado)
    return enviados


# ------------------------------------------------------------------ comandos

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
    args = ap.parse_args()

    cfg = cargar_config()

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

    estado = cargar_estado()

    if args.simular:
        n = una_vuelta(cfg, estado, simular=True)
        print(f"\nAvisos que se mandarían ahora mismo: {n}\n")
        return 0

    log("Vigilando. Deja esta ventana abierta (puedes minimizarla). Ctrl+C para parar.")
    try:
        while True:
            una_vuelta(cfg, estado)
            time.sleep(cfg["cada"])
    except KeyboardInterrupt:
        log("Vigilancia detenida.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
