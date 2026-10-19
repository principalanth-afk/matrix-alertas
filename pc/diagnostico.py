# -*- coding: utf-8 -*-
"""
diagnostico.py — averigua por que marcadores.py devolvio 0 partidos.

Prueba varias formas de pedirle los partidos a SofaScore (y una fuente
alterna) e imprime el resultado exacto de cada una. No escribe nada y no
toca el Excel: solo mira.

    python diagnostico.py
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import date

HOY = date.today().isoformat()          # 2026-10-18
HOY_JUNTO = HOY.replace("-", "")        # 20261018

RUTA = "/api/v1/sport/football/scheduled-events/" + HOY
SITIOS = [
    ("api.sofascore.com", "https://api.sofascore.com" + RUTA),
    ("www.sofascore.com", "https://www.sofascore.com" + RUTA),
]

# Las cabeceras que usa hoy marcadores.py.
CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
}
SOLO_REFERER = {"Referer": "https://www.sofascore.com/"}

ESPN = ("https://site.web.api.espn.com/apis/v2/scoreboard/header"
        "?sport=soccer&league=all&region=us&lang=en&dates=" + HOY_JUNTO)

exitos = []


def p(txt=""):
    print(txt, flush=True)


def cuenta_sofa(datos):
    if isinstance(datos, dict) and isinstance(datos.get("events"), list):
        return len(datos["events"])
    return -1


def resumen(crudo):
    return crudo[:130].replace("\n", " ").replace("\r", " ")


# --------------------------------------------------------------- urllib

def probar_urllib(nombre, url):
    p("")
    p("[urllib] " + nombre)
    try:
        pet = urllib.request.Request(url, headers=CABECERAS)
        with urllib.request.urlopen(pet, timeout=15) as r:
            crudo = r.read().decode("utf-8", "replace")
        p("   http " + str(r.status) + "  " + str(len(crudo)) + " bytes")
        try:
            n = cuenta_sofa(json.loads(crudo))
        except ValueError:
            p("   no es JSON: " + resumen(crudo))
            return
        p("   partidos: " + str(n))
        if n > 0:
            exitos.append("urllib + " + nombre)
    except urllib.error.HTTPError as e:
        p("   BLOQUEADO http " + str(e.code) + " " + str(e.reason))
    except Exception as e:
        p("   FALLO " + type(e).__name__ + ": " + str(e)[:150])


# ------------------------------------------------------------- curl_cffi

def probar_curl(nombre, url, etiqueta, perfil, cabeceras):
    p("")
    p("[curl_cffi] " + perfil + " / " + etiqueta + "  ->  " + nombre)
    try:
        from curl_cffi import requests as creq
    except Exception as e:
        p("   curl_cffi no carga: " + type(e).__name__ + ": " + str(e)[:120])
        return
    try:
        if cabeceras:
            r = creq.get(url, headers=cabeceras, timeout=15, impersonate=perfil)
        else:
            r = creq.get(url, timeout=15, impersonate=perfil)
        p("   http " + str(r.status_code) + "  " + str(len(r.content)) + " bytes")
        if r.status_code != 200:
            p("   " + resumen(r.text))
            return
        try:
            n = cuenta_sofa(r.json())
        except Exception:
            p("   no es JSON: " + resumen(r.text))
            return
        p("   partidos: " + str(n))
        if n > 0:
            exitos.append("curl_cffi " + perfil + " / " + etiqueta + " + " + nombre)
    except Exception as e:
        p("   FALLO " + type(e).__name__ + ": " + str(e)[:150])


# ------------------------------------------------------------------ ESPN

def probar_espn():
    p("")
    p("[ESPN] fuente alterna")
    try:
        pet = urllib.request.Request(
            ESPN, headers={"User-Agent": CABECERAS["User-Agent"]})
        with urllib.request.urlopen(pet, timeout=15) as r:
            crudo = r.read().decode("utf-8", "replace")
        datos = json.loads(crudo)
        n = 0
        for deporte in datos.get("sports") or []:
            for liga in deporte.get("leagues") or []:
                n += len(liga.get("events") or [])
        p("   http 200  " + str(len(crudo)) + " bytes  partidos: " + str(n))
        if n > 0:
            exitos.append("ESPN")
        else:
            p("   claves que trajo: " + ", ".join(list(datos.keys())[:10]))
    except urllib.error.HTTPError as e:
        p("   BLOQUEADO http " + str(e.code) + " " + str(e.reason))
    except Exception as e:
        p("   FALLO " + type(e).__name__ + ": " + str(e)[:150])


# ------------------------------------------------------------------ main

def main():
    p("=" * 60)
    p("DIAGNOSTICO DE MARCADORES   fecha " + HOY)
    p("Python " + sys.version.split()[0])
    try:
        import curl_cffi
        p("curl_cffi " + str(getattr(curl_cffi, "__version__", "?")))
        try:
            from curl_cffi.requests import BrowserType
            nombres = [x.value for x in BrowserType][:40]
            p("perfiles disponibles: " + ", ".join(nombres))
        except Exception:
            pass
    except Exception:
        p("curl_cffi NO instalado")
    p("=" * 60)

    # 1. tal como lo hace hoy marcadores.py
    for nombre, url in SITIOS:
        probar_urllib(nombre, url)

    # 2. curl_cffi: lo importante es si molestan las cabeceras propias
    variantes = [
        ("sin cabeceras propias", None),
        ("solo Referer", SOLO_REFERER),
        ("cabeceras completas", CABECERAS),
    ]
    for nombre, url in SITIOS:
        for etiqueta, cab in variantes:
            probar_curl(nombre, url, etiqueta, "chrome", cab)

    # 3. otros perfiles, por si el de Chrome esta quemado
    for perfil in ("chrome124", "chrome110", "safari17_0", "edge101"):
        probar_curl(SITIOS[0][0], SITIOS[0][1], "sin cabeceras", perfil, None)

    probar_espn()

    p("")
    p("=" * 60)
    if exitos:
        p("FUNCIONAN:")
        for e in exitos:
            p("   " + e)
    else:
        p("NINGUNO funciono. Copiame todo lo de arriba.")
    p("=" * 60)


if __name__ == "__main__":
    main()
