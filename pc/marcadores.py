# -*- coding: utf-8 -*-
"""
marcadores.py — marcador en vivo de los partidos del día.

El Excel solo tiene lo que tú cargas a mano, así que para ver el marcador
mientras el partido se juega hace falta una fuente de afuera. Se usa SofaScore,
que es la misma que ya usa omega y que sí cubre ligas chicas (Primera B
Nacional, Torneo Federal, Liga Pro, Iraq, Etiopía...).

Dos reglas que no se rompen:

  1. NUNCA se escribe en el Excel. El marcador en vivo es solo para mirar;
     tu registro sigue siendo lo que tú cargas en GL/GV.
  2. Ante la duda, no se inventa. Si no se puede emparejar un partido con
     seguridad, se queda sin marcador en vivo y no pasa nada.

Si SofaScore no responde o bloquea, el módulo devuelve vacío y el resto del
programa funciona igual que antes.
"""

import difflib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date

URL_DIA = "https://api.sofascore.com/api/v1/sport/football/scheduled-events/{fecha}"

CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}

# Qué tan parecidos deben ser los nombres para dar por bueno un emparejamiento.
# Alto a propósito: mostrar el marcador de OTRO partido es peor que no mostrar nada.
MIN_PARECIDO = 0.82
MIN_PARECIDO_FLOJO = 0.70      # se acepta solo si el otro equipo calza casi exacto

_cache = {"cuando": 0.0, "fecha": None, "eventos": []}


# ----------------------------------------------------------------- nombres

_RUIDO = re.compile(
    r"\b(fc|cf|afc|sc|ac|cd|ca|cs|ad|club|deportivo|deportiva|atletico|atlético|"
    r"sporting|sportivo|social|cultural|asociacion|asociación|de|del|la|el|los|las|"
    r"futbol|fútbol|football|reserves?|res|sub\s?\d+|u\d+|ii)\b", re.I)


def normalizar(nombre):
    """'CA Talleres de Córdoba Res.' -> 'tallerescordoba' (para comparar)."""
    s = unicodedata.normalize("NFKD", str(nombre or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = _RUIDO.sub(" ", s)
    return re.sub(r"\s+", "", s)


def es_reserva(nombre):
    s = unicodedata.normalize("NFKD", str(nombre or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return bool(re.search(r"\bres\b|\breserves?\b|\bsub\s?\d+\b|\bu\d{2}\b|\bii\b", s))


def parecido(a, b):
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # uno contenido en el otro ('talleres' dentro de 'tallerescordoba')
    if len(na) >= 5 and len(nb) >= 5 and (na in nb or nb in na):
        return 0.95
    return difflib.SequenceMatcher(None, na, nb).ratio()


# ------------------------------------------------------------------ fuente

def _bajar(url, tiempo=12):
    """Devuelve el JSON, o None si no se pudo. Prueba curl_cffi si está instalado."""
    try:
        pet = urllib.request.Request(url, headers=CABECERAS)
        with urllib.request.urlopen(pet, timeout=tiempo) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        pass
    # Segundo intento: algunos días SofaScore bloquea a urllib pero no a curl_cffi,
    # que imita a un navegador de verdad. Es opcional: si no está, se deja ahí.
    try:
        from curl_cffi import requests as creq
        r = creq.get(url, headers=CABECERAS, timeout=tiempo, impersonate="chrome")
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _estado_de(ev):
    """Traduce el estado de SofaScore a: vivo, descanso, fin, programado, suspendido."""
    tipo = ((ev.get("status") or {}).get("type") or "").lower()
    desc = ((ev.get("status") or {}).get("description") or "").lower()
    if tipo == "finished":
        return "fin"
    if tipo in ("canceled", "postponed", "interrupted", "suspended"):
        return "suspendido"
    if tipo == "inprogress":
        if "halftime" in desc or "half time" in desc or "descanso" in desc:
            return "descanso"
        return "vivo"
    return "programado"


def _minuto_de(ev, ahora_ts):
    """Minuto aproximado del partido según SofaScore. None si no se puede."""
    t = ev.get("time") or {}
    ini = t.get("currentPeriodStartTimestamp")
    if not ini:
        return None
    corridos = int((ahora_ts - ini) // 60)
    if corridos < 0:
        return None
    desc = ((ev.get("status") or {}).get("description") or "").lower()
    base = 45 if ("2nd" in desc or "segundo" in desc) else 0
    return min(base + corridos, 130)


def eventos_del_dia(dia=None, refrescar_cada=60):
    """Todos los partidos de fútbol del día según SofaScore. Lista vacía si falla."""
    dia = dia or date.today()
    clave = dia.isoformat()
    ahora = time.time()
    if _cache["fecha"] == clave and ahora - _cache["cuando"] < refrescar_cada:
        return _cache["eventos"]

    datos = _bajar(URL_DIA.format(fecha=clave))
    if not isinstance(datos, dict):
        # Se conserva lo último que sí se pudo bajar: mejor un marcador de hace
        # un minuto que ninguno.
        return _cache["eventos"] if _cache["fecha"] == clave else []

    eventos = []
    for ev in datos.get("events") or []:
        try:
            eventos.append({
                "local": ((ev.get("homeTeam") or {}).get("name") or ""),
                "visitante": ((ev.get("awayTeam") or {}).get("name") or ""),
                "gl": (ev.get("homeScore") or {}).get("current"),
                "gv": (ev.get("awayScore") or {}).get("current"),
                "estado": _estado_de(ev),
                "minuto": _minuto_de(ev, ahora),
                "torneo": (((ev.get("tournament") or {}).get("name")) or ""),
            })
        except Exception:
            continue
    _cache.update(cuando=ahora, fecha=clave, eventos=eventos)
    return eventos


# -------------------------------------------------------------- emparejar

def buscar(local, visitante, eventos):
    """
    Busca el partido entre los eventos del día. Devuelve el evento o None.
    Exige que calcen los DOS equipos y que coincida si es de reserva o no.
    """
    if not local or not visitante or not eventos:
        return None
    reserva = es_reserva(local) or es_reserva(visitante)
    mejor, mejor_puntaje = None, 0.0
    for ev in eventos:
        if (es_reserva(ev["local"]) or es_reserva(ev["visitante"])) != reserva:
            continue
        pl = parecido(local, ev["local"])
        pv = parecido(visitante, ev["visitante"])
        if min(pl, pv) < MIN_PARECIDO_FLOJO:
            continue
        # o los dos bastante parecidos, o uno casi exacto y el otro razonable
        if not (min(pl, pv) >= MIN_PARECIDO or (max(pl, pv) >= 0.95 and min(pl, pv) >= MIN_PARECIDO_FLOJO)):
            continue
        puntaje = pl + pv
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = ev, puntaje
    return mejor


def marcador_de(local, visitante, eventos=None):
    """
    (gl, gv, estado, minuto) del partido en vivo, o (None, None, "", None).
    estado: 'vivo' | 'descanso' | 'fin' | 'suspendido' | '' (no se encontró)
    """
    ev = buscar(local, visitante, eventos if eventos is not None else eventos_del_dia())
    if not ev or ev["estado"] == "programado":
        return None, None, "", None
    return ev["gl"], ev["gv"], ev["estado"], ev["minuto"]


if __name__ == "__main__":
    import sys
    evs = eventos_del_dia()
    print(f"SofaScore devolvió {len(evs)} partidos para hoy.")
    if not evs:
        print("No se pudo consultar. Puede ser que no haya internet, que SofaScore")
        print("esté bloqueando, o que haga falta:  pip install curl_cffi")
        sys.exit(1)
    vivos = [e for e in evs if e["estado"] in ("vivo", "descanso")]
    print(f"En juego ahora mismo: {len(vivos)}")
    for e in vivos[:15]:
        m = f"{e['minuto']}'" if e["minuto"] else e["estado"]
        print(f"  {e['gl']}-{e['gv']}  {m:>6}  {e['local']} vs {e['visitante']}  ({e['torneo']})")
    if len(sys.argv) >= 3:
        gl, gv, est, mi = marcador_de(sys.argv[1], sys.argv[2], evs)
        print(f"\nBuscando «{sys.argv[1]} vs {sys.argv[2]}» -> {gl}-{gv} {est} {mi}")
