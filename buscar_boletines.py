#!/usr/bin/env python3
"""Busca disposiciones sobre un municipio en boletines oficiales.

Cubre el BOJA (Andalucia) y el BOP de Granada, que se comportan de forma muy
distinta y por eso se atacan de forma distinta:

  BOJA  Tiene buscador propio accesible por URL, sin captcha. Se consulta en
        directo y devuelve titulo, organismo, boletin, fecha y enlace.
  BOP   Su buscador de anuncios esta protegido con reCAPTCHA y no es
        automatizable. La via que queda es bajar los boletines del rango de
        fechas que interese y buscar dentro de los PDF en local.

Tres subcomandos:

  scan   Recorre una carpeta de PDF, extrae el texto y busca el municipio y las
         palabras clave. Informa de la pagina y el contexto de cada acierto, y
         distingue el acierto real del falso positivo por raiz compartida
         (Padul / Padules) mediante limites de palabra.

  boja   Consulta el buscador historico del BOJA y lista las disposiciones que
         mencionan el termino. Cubre desde 1979.

  fetch  Descarga boletines del BOP de Granada por rango de fechas, para poder
         escanearlos despues. El PDF no tiene URL construible (lleva UUID y sello
         de tiempo), asi que abre la pagina del dia y extrae de ella el enlace.
         Solo cubre los boletines del portal actual; para anos anteriores hay que
         bajarlos a mano desde la seccion 'Boletines anteriores'.

Uso:
    python3 buscar_boletines.py boja "Padul" --desde 2022-01-01
    python3 buscar_boletines.py boja "Padul depuracion"
    python3 buscar_boletines.py scan ~/Downloads/BOP --municipio Padul
    python3 buscar_boletines.py fetch --desde 2026-08-01 --hasta 2026-08-23

Requiere `pdftotext` (viene con poppler: brew install poppler).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

# El PDF del BOP de Granada no tiene URL construible: lleva un UUID y un sello de
# tiempo. Hay que abrir la pagina del dia y extraer de ella el enlace real.
BOP_DIA = "https://bop.dipgra.es/publica/consulta-de-bops/buscador/BOP-{dd}-{mm}-{yyyy}/"
BOP_BASE = "https://bop.dipgra.es"
RE_PDF = re.compile(r'href="(/export/sites/bop/[^"]*Documentos-BOPs-en-PDF[^"]*\.pdf)"', re.I)

UA = {"User-Agent": "Mozilla/5.0 (uso personal, consulta puntual)"}

CLAVES_DEFECTO = [
    "solar", "solares", "vallado", "desbroce", "desbrozar", "maleza",
    "limpieza de solares", "conservacion", "orden de ejecucion",
    "seguridad, salubridad", "ornato",
]


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def texto_pdf(pdf: Path) -> list[str]:
    """Texto del PDF, una entrada por pagina. Lista vacia si no se puede leer."""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf), "-"],
            capture_output=True, text=True, timeout=180, check=True,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  aviso: no se pudo extraer texto de {pdf.name}: {e}", file=sys.stderr)
        return []
    return out.split("\f")


def buscar(paginas: list[str], termino: str) -> list[tuple[int, str]]:
    """Aciertos de `termino` como palabra completa. Devuelve (pagina, linea de contexto)."""
    patron = re.compile(rf"\b{re.escape(sin_tildes(termino).lower())}\b")
    hits = []
    for n, pag in enumerate(paginas, start=1):
        for linea in pag.splitlines():
            if patron.search(sin_tildes(linea).lower()):
                hits.append((n, " ".join(linea.split())[:160]))
    return hits


def cmd_scan(args) -> int:
    carpeta = Path(args.carpeta).expanduser()
    pdfs = sorted(carpeta.glob("*.pdf"))
    if not pdfs:
        print(f"No hay PDF en {carpeta}")
        return 1

    claves = args.claves or CLAVES_DEFECTO
    print(f"Carpeta   : {carpeta}")
    print(f"Boletines : {len(pdfs)}")
    print(f"Municipio : {args.municipio}")
    print(f"Claves    : {', '.join(claves)}\n")

    con_municipio = []
    for pdf in pdfs:
        paginas = texto_pdf(pdf)
        if not paginas:
            continue
        hits_m = buscar(paginas, args.municipio)
        hits_c = {c: buscar(paginas, c) for c in claves}
        hits_c = {k: v for k, v in hits_c.items() if v}

        marca = "SI" if hits_m else "no"
        print(f"[{marca}] {pdf.name}  ({len(paginas)} pag.)")
        if hits_m:
            con_municipio.append(pdf.name)
            for pag, ctx in hits_m[:6]:
                print(f"      p.{pag}: {ctx}")
        if hits_m and hits_c:
            print(f"      claves presentes en el boletin: {', '.join(hits_c)}")
        elif hits_c and args.verbose:
            print(f"      (claves sin municipio: {', '.join(hits_c)})")

    print()
    if con_municipio:
        print(f"Boletines con '{args.municipio}': {', '.join(con_municipio)}")
    else:
        print(f"Ningun boletin de la carpeta menciona a '{args.municipio}'.")
    return 0


def cmd_fetch(args) -> int:
    import requests

    destino = Path(args.destino).expanduser()
    destino.mkdir(parents=True, exist_ok=True)
    d0 = date.fromisoformat(args.desde)
    d1 = date.fromisoformat(args.hasta)
    if d1 < d0:
        print("El rango de fechas esta invertido.")
        return 1

    bajados = fallidos = 0
    d = d0
    while d <= d1:
        if d.weekday() < 5:  # el BOP no publica en fin de semana
            out = destino / f"{d.isoformat().replace('-', '')}.pdf"
            if out.exists():
                d += timedelta(days=1)
                continue
            pagina = BOP_DIA.format(yyyy=d.year, mm=f"{d.month:02d}", dd=f"{d.day:02d}")
            try:
                p = requests.get(pagina, timeout=60, headers=UA)
                if not p.ok:
                    print(f"  --   {d}: sin pagina de boletin ({p.status_code})")
                    fallidos += 1
                    d += timedelta(days=1)
                    continue
                m = RE_PDF.search(p.text)
                if not m:
                    print(f"  --   {d}: la pagina no enlaza ningun PDF")
                    fallidos += 1
                    d += timedelta(days=1)
                    continue
                r = requests.get(BOP_BASE + m.group(1), timeout=180, headers=UA)
                r.raise_for_status()
                out.write_bytes(r.content)
                print(f"  ok   {d} -> {out.name} ({len(r.content) // 1024} KB)")
                bajados += 1
            except requests.RequestException as e:
                print(f"  err  {d}: {e}")
                fallidos += 1
        d += timedelta(days=1)

    print(f"\nDescargados {bajados}, sin resultado {fallidos}. Destino: {destino}")
    if fallidos and not bajados:
        print("Aviso: el buscador por dia solo cubre los boletines recientes. Para anos\n"
              "anteriores hay que usar la seccion 'Boletines anteriores' del BOP.")
    return 0



BOJA_URL = "https://www.juntadeandalucia.es/eboja/buscador/search.do"
RE_RESULTADO = re.compile(
    r'<a href="(?P<url>[^"]+)">(?P<titulo>[^<]+)</a>\s*</p>\s*'
    r'<p class="d-block">(?P<meta>.*?)</p>',
    re.S,
)


def cmd_boja(args) -> int:
    """El buscador del BOJA acepta GET y no lleva captcha. Las fechas van en dd/mm/aaaa:
    con el formato ISO el servidor las ignora en silencio y devuelve todo el historico."""
    import html
    import requests

    def a_ddmmaaaa(iso: str) -> str:
        a, m, d = iso.split("-")
        return f"{d}/{m}/{a}"

    params = {"q": args.termino}
    if args.desde:
        params["startDate"] = a_ddmmaaaa(args.desde)
    if args.hasta:
        params["endDate"] = a_ddmmaaaa(args.hasta)

    r = requests.get(BOJA_URL, params=params, timeout=90, headers=UA)
    r.raise_for_status()
    cuerpo = re.sub(r"<script.*?</script>", "", r.text, flags=re.S)

    if "No se han encontrado resultados" in cuerpo:
        print(f"BOJA: sin resultados para '{args.termino}'"
              + (f" entre {args.desde} y {args.hasta}" if args.desde else ""))
        return 0

    total = re.search(r"<strong>(\d+)</strong>\s*recursos disponibles", cuerpo)
    print(f"BOJA: '{args.termino}'"
          + (f", {args.desde} a {args.hasta}" if args.desde else "")
          + (f" -> {total.group(1)} disposiciones" if total else ""))
    print()

    n = 0
    for m in RE_RESULTADO.finditer(cuerpo):
        n += 1
        if n > args.limite:
            break
        titulo = " ".join(html.unescape(m.group("titulo")).split())
        meta = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group("meta"))).split())
        fecha = re.search(r"(\d\d/\d\d/\d{4})", meta)
        print(f"[{n}] {fecha.group(1) if fecha else '?'}  {titulo[:150]}")
        print(f"     {meta[:120]}")
        print(f"     {m.group('url')}")
        print()

    if total and int(total.group(1)) > n:
        print(f"({int(total.group(1)) - n} resultados mas; sube --limite o acota las fechas)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="buscar en una carpeta de PDF")
    s.add_argument("carpeta")
    s.add_argument("--municipio", required=True)
    s.add_argument("--claves", nargs="*", default=None)
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=cmd_scan)

    b = sub.add_parser("boja", help="buscar en el BOJA (Andalucia)")
    b.add_argument("termino")
    b.add_argument("--desde", metavar="AAAA-MM-DD")
    b.add_argument("--hasta", metavar="AAAA-MM-DD", default=None)
    b.add_argument("--limite", type=int, default=25)
    b.set_defaults(func=cmd_boja)

    f = sub.add_parser("fetch", help="descargar boletines del BOP de Granada")
    f.add_argument("--desde", required=True, metavar="AAAA-MM-DD")
    f.add_argument("--hasta", required=True, metavar="AAAA-MM-DD")
    f.add_argument("--destino", default="~/Downloads/BOP")
    f.set_defaults(func=cmd_fetch)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
