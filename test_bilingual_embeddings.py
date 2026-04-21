#!/usr/bin/env python3
"""
Bilingual Embedding Quality Test
=================================

Validates that nomic-embed-text embeddings yield equivalent retrieval
quality for English and Spanish queries against the existing LanceDB
email and document tables.

Tests three statistical hypotheses:
  H1: EN and ES queries for the same concept retrieve equally relevant results
      (measured by cosine distance distributions)
  H2: Cross-language retrieval works (EN query finds ES content and vice versa)
  H3: No systematic language bias in top-K results

With --verbose, outputs the actual top-N content for every pair, suitable
for agentic relevance assessment by the Claude Code CLI session.

Requirements:
  - Ollama running with nomic-embed-text model
  - LanceDB at ~/mylab/paco/data/lancedb/ with emails and documents tables

Usage:
    python test_bilingual_embeddings.py                    # Full test
    python test_bilingual_embeddings.py --quick            # Quick (8 pairs)
    python test_bilingual_embeddings.py --verbose          # Include result content
    python test_bilingual_embeddings.py --json results.json
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, stdev

import lancedb
import ollama

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LANCEDB_PATH = Path.home() / "mylab" / "paco" / "data" / "lancedb"
EMBEDDING_MODEL = "nomic-embed-text"
TOP_K = 20
VERBOSE_TOP_N = 5  # how many results to show content for in --verbose
VERBOSE_CONTENT_CHARS = 300

# Parallel query pairs: (English, Spanish) expressing the same concept.
QUERY_PAIRS = [
    # Infrastructure & transport
    ("road maintenance financing mechanisms", "mecanismos de financiacion del mantenimiento de carreteras"),
    ("public private partnership risk allocation", "asignacion de riesgos en asociaciones publico privadas"),
    ("bridge inspection and structural assessment", "inspeccion de puentes y evaluacion estructural"),
    ("highway toll revenue forecast", "prevision de ingresos por peaje en autopistas"),
    ("railway infrastructure investment strategy", "estrategia de inversion en infraestructura ferroviaria"),
    # Project finance
    ("project finance due diligence process", "proceso de due diligence en financiacion de proyectos"),
    ("value for money analysis methodology", "metodologia de analisis de valor por dinero"),
    ("government fiscal commitment guarantees", "garantias de compromiso fiscal del gobierno"),
    ("infrastructure fund institutional investors", "inversores institucionales en fondos de infraestructura"),
    ("concession contract termination clauses", "clausulas de terminacion de contratos de concesion"),
    # Asset management
    ("pavement condition monitoring systems", "sistemas de monitoreo del estado del pavimento"),
    ("whole life cost asset management", "coste del ciclo de vida en gestion de activos"),
    ("predictive maintenance decision support", "soporte a la decision en mantenimiento predictivo"),
    ("road asset inventory data collection", "recopilacion de datos de inventario de activos viales"),
    # Governance & policy
    ("road fund governance transparency audit", "auditoria de transparencia en la gobernanza de fondos viales"),
    ("procurement reform public sector", "reforma de la contratacion publica en el sector publico"),
    ("institutional capacity building transport", "fortalecimiento de capacidad institucional en transporte"),
    ("climate resilience infrastructure adaptation", "adaptacion de infraestructura a la resiliencia climatica"),
    # Technical / engineering
    ("geotechnical investigation soil analysis", "investigacion geotecnica y analisis de suelos"),
    ("traffic demand model calibration", "calibracion de modelos de demanda de trafico"),
    ("environmental impact assessment mitigation", "evaluacion de impacto ambiental y medidas de mitigacion"),
    ("construction supervision quality control", "supervision de obra y control de calidad"),
    # Africa-specific (common in RRAM project)
    ("rural road connectivity economic development", "conectividad de caminos rurales y desarrollo economico"),
    ("road fund second generation reform Africa", "reforma de segunda generacion de fondos viales en Africa"),
]

QUICK_PAIRS = QUERY_PAIRS[:8]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    query: str
    lang: str
    distances: list[float] = field(default_factory=list)
    result_count: int = 0
    lang_distribution: dict = field(default_factory=dict)
    top5_avg_distance: float = 0.0
    embed_time_ms: float = 0.0
    search_time_ms: float = 0.0
    top_contents: list[dict] = field(default_factory=list)


@dataclass
class PairResult:
    concept_index: int
    en: QueryResult = None
    es: QueryResult = None
    distance_diff: float = 0.0
    cross_lang_en: int = 0
    cross_lang_es: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_embedding(text: str) -> list[float]:
    response = ollama.embed(model=EMBEDDING_MODEL, input=text)
    return response["embeddings"][0]


def detect_language_heuristic(text: str) -> str:
    if not text:
        return "unknown"
    text_lower = text.lower()
    es_markers = [
        " de ", " del ", " los ", " las ", " una ", " por ", " para ",
        " con ", " que ", " este ", " esta ", " como ", " entre ",
        " sobre ", " desde ", " proyecto ", " contrato ",
    ]
    en_markers = [
        " the ", " and ", " for ", " with ", " from ", " this ",
        " that ", " which ", " have ", " been ", " project ",
        " contract ", " shall ", " will ",
    ]
    es_count = sum(1 for m in es_markers if m in text_lower)
    en_count = sum(1 for m in en_markers if m in text_lower)

    if es_count > en_count + 1:
        return "es"
    elif en_count > es_count + 1:
        return "en"
    else:
        return "mixed"


def run_query(table, query: str, lang: str, verbose: bool = False) -> QueryResult:
    t0 = time.perf_counter()
    embedding = get_embedding(query)
    embed_time = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    results = table.search(embedding).limit(TOP_K).to_pandas()
    search_time = (time.perf_counter() - t1) * 1000

    distances = results["_distance"].tolist() if len(results) > 0 else []
    top5_avg = mean(distances[:5]) if len(distances) >= 5 else (mean(distances) if distances else 999.0)

    lang_counts = {"en": 0, "es": 0, "mixed": 0, "unknown": 0}
    top_contents = []
    for idx, (_, row) in enumerate(results.iterrows()):
        content = row.get("content", "")
        detected = detect_language_heuristic(content)
        lang_counts[detected] += 1
        if verbose and idx < VERBOSE_TOP_N:
            truncated = content[:VERBOSE_CONTENT_CHARS]
            if len(content) > VERBOSE_CONTENT_CHARS:
                truncated += "..."
            top_contents.append({
                "rank": idx + 1,
                "distance": round(distances[idx], 4) if idx < len(distances) else None,
                "lang": detected,
                "content": truncated,
            })

    return QueryResult(
        query=query,
        lang=lang,
        distances=distances,
        result_count=len(results),
        lang_distribution=lang_counts,
        top5_avg_distance=top5_avg,
        embed_time_ms=embed_time,
        search_time_ms=search_time,
        top_contents=top_contents,
    )


def format_pct(n, total):
    return f"{n}/{total} ({100*n/total:.0f}%)" if total > 0 else "0/0"


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests(table_name: str, table, pairs: list, verbose: bool) -> dict:

    print(f"\n{'='*72}")
    print(f"  TABLE: {table_name}")
    print(f"  Rows: {table.count_rows():,}")
    print(f"  Query pairs: {len(pairs)}")
    print(f"{'='*72}")

    pair_results: list[PairResult] = []

    for i, (en_query, es_query) in enumerate(pairs):
        en_result = run_query(table, en_query, "en", verbose=verbose)
        es_result = run_query(table, es_query, "es", verbose=verbose)

        pr = PairResult(
            concept_index=i,
            en=en_result,
            es=es_result,
            distance_diff=abs(en_result.top5_avg_distance - es_result.top5_avg_distance),
            cross_lang_en=en_result.lang_distribution.get("es", 0),
            cross_lang_es=es_result.lang_distribution.get("en", 0),
        )
        pair_results.append(pr)

        if verbose:
            print(f"\n  --- Pair [{i+1:02d}] ---")
            print(f"  EN: \"{en_query}\"  (top5 dist={en_result.top5_avg_distance:.4f})")
            print(f"  ES: \"{es_query}\"  (top5 dist={es_result.top5_avg_distance:.4f})")
            print(f"  dist_diff={pr.distance_diff:.4f}  "
                  f"cross: EN->ES={pr.cross_lang_en}  ES->EN={pr.cross_lang_es}")

            print(f"  EN results:")
            for r in en_result.top_contents:
                print(f"    [{r['rank']}] dist={r['distance']}  lang={r['lang']}")
                for line in r["content"].split("\n")[:4]:
                    if line.strip():
                        print(f"        {line.strip()[:120]}")

            print(f"  ES results:")
            for r in es_result.top_contents:
                print(f"    [{r['rank']}] dist={r['distance']}  lang={r['lang']}")
                for line in r["content"].split("\n")[:4]:
                    if line.strip():
                        print(f"        {line.strip()[:120]}")
        else:
            sys.stdout.write(f"  [{i+1:02d}/{len(pairs)}] {en_query[:50]}..."
                             f" dist_diff={pr.distance_diff:.4f}\n")
            sys.stdout.flush()

    # -----------------------------------------------------------------------
    # Aggregate statistics
    # -----------------------------------------------------------------------

    en_top5_dists = [p.en.top5_avg_distance for p in pair_results]
    es_top5_dists = [p.es.top5_avg_distance for p in pair_results]
    distance_diffs = [p.distance_diff for p in pair_results]

    total_en_results = sum(p.en.result_count for p in pair_results)
    total_es_results = sum(p.es.result_count for p in pair_results)

    total_cross_en_to_es = sum(p.cross_lang_en for p in pair_results)
    total_cross_es_to_en = sum(p.cross_lang_es for p in pair_results)

    en_query_lang_totals = {"en": 0, "es": 0, "mixed": 0, "unknown": 0}
    es_query_lang_totals = {"en": 0, "es": 0, "mixed": 0, "unknown": 0}
    for p in pair_results:
        for lang_key in en_query_lang_totals:
            en_query_lang_totals[lang_key] += p.en.lang_distribution.get(lang_key, 0)
            es_query_lang_totals[lang_key] += p.es.lang_distribution.get(lang_key, 0)

    en_embed_times = [p.en.embed_time_ms for p in pair_results]
    es_embed_times = [p.es.embed_time_ms for p in pair_results]

    degraded_pairs = []
    for p in pair_results:
        if p.en.top5_avg_distance > 0:
            ratio = p.es.top5_avg_distance / p.en.top5_avg_distance
            if ratio > 1.20:
                degraded_pairs.append((p.concept_index, ratio))

    # Also check EN degraded vs ES
    en_degraded_pairs = []
    for p in pair_results:
        if p.es.top5_avg_distance > 0:
            ratio = p.en.top5_avg_distance / p.es.top5_avg_distance
            if ratio > 1.20:
                en_degraded_pairs.append((p.concept_index, ratio))

    # -----------------------------------------------------------------------
    # H1
    # -----------------------------------------------------------------------

    print(f"\n  {'─'*68}")
    print(f"  H1: DISTANCE PARITY")
    print(f"  {'─'*68}")
    print(f"  EN queries  - top5 avg dist: mean={mean(en_top5_dists):.4f}  "
          f"median={median(en_top5_dists):.4f}  stdev={stdev(en_top5_dists):.4f}")
    print(f"  ES queries  - top5 avg dist: mean={mean(es_top5_dists):.4f}  "
          f"median={median(es_top5_dists):.4f}  stdev={stdev(es_top5_dists):.4f}")
    print(f"  Pair diffs  - mean={mean(distance_diffs):.4f}  "
          f"median={median(distance_diffs):.4f}  max={max(distance_diffs):.4f}")

    parity_pass = mean(distance_diffs) < 0.15
    print(f"  VERDICT: {'PASS' if parity_pass else 'FAIL'} "
          f"(mean pair diff {'<' if parity_pass else '>='} 0.15 threshold)")

    # -----------------------------------------------------------------------
    # H2
    # -----------------------------------------------------------------------

    print(f"\n  {'─'*68}")
    print(f"  H2: CROSS-LANGUAGE RETRIEVAL")
    print(f"  {'─'*68}")
    print(f"  EN queries -> ES results: {format_pct(total_cross_en_to_es, total_en_results)}")
    print(f"  ES queries -> EN results: {format_pct(total_cross_es_to_en, total_es_results)}")

    cross_lang_rate = (total_cross_en_to_es + total_cross_es_to_en) / max(total_en_results + total_es_results, 1)
    cross_pass = cross_lang_rate > 0.05
    print(f"  Combined cross-language rate: {cross_lang_rate:.1%}")
    print(f"  VERDICT: {'PASS' if cross_pass else 'FAIL'} "
          f"(cross-language rate {'>' if cross_pass else '<='} 5% threshold)")

    # -----------------------------------------------------------------------
    # H3
    # -----------------------------------------------------------------------

    print(f"\n  {'─'*68}")
    print(f"  H3: LANGUAGE BIAS")
    print(f"  {'─'*68}")
    print(f"  EN queries retrieved: en={en_query_lang_totals['en']}  "
          f"es={en_query_lang_totals['es']}  "
          f"mixed={en_query_lang_totals['mixed']}  "
          f"unk={en_query_lang_totals['unknown']}")
    print(f"  ES queries retrieved: en={es_query_lang_totals['en']}  "
          f"es={es_query_lang_totals['es']}  "
          f"mixed={es_query_lang_totals['mixed']}  "
          f"unk={es_query_lang_totals['unknown']}")

    en_same_pct = en_query_lang_totals["en"] / max(total_en_results, 1)
    es_same_pct = es_query_lang_totals["es"] / max(total_es_results, 1)
    bias_diff = abs(en_same_pct - es_same_pct)
    print(f"  EN query -> EN result rate: {en_same_pct:.1%}")
    print(f"  ES query -> ES result rate: {es_same_pct:.1%}")
    print(f"  Bias differential: {bias_diff:.1%}")

    bias_pass = bias_diff < 0.30
    print(f"  VERDICT: {'PASS' if bias_pass else 'FAIL'} "
          f"(bias differential {'<' if bias_pass else '>='} 30% threshold)")

    # -----------------------------------------------------------------------
    # Degraded pairs
    # -----------------------------------------------------------------------

    if degraded_pairs:
        print(f"\n  ES degraded (distance >20% worse than EN):")
        for idx, ratio in degraded_pairs:
            en_q, _ = pairs[idx]
            print(f"    [{idx+1:02d}] ratio={ratio:.2f}x  \"{en_q[:60]}\"")

    if en_degraded_pairs:
        print(f"\n  EN degraded (distance >20% worse than ES):")
        for idx, ratio in en_degraded_pairs:
            en_q, _ = pairs[idx]
            print(f"    [{idx+1:02d}] ratio={ratio:.2f}x  \"{en_q[:60]}\"")

    if not degraded_pairs and not en_degraded_pairs:
        print(f"\n  No degraded pairs in either direction.")

    # -----------------------------------------------------------------------
    # Timing
    # -----------------------------------------------------------------------

    print(f"\n  {'─'*68}")
    print(f"  TIMING")
    print(f"  {'─'*68}")
    print(f"  EN embed: mean={mean(en_embed_times):.0f}ms  median={median(en_embed_times):.0f}ms")
    print(f"  ES embed: mean={mean(es_embed_times):.0f}ms  median={median(es_embed_times):.0f}ms")

    return {
        "table": table_name,
        "row_count": table.count_rows(),
        "query_pairs": len(pairs),
        "h1_distance_parity": {
            "en_mean": round(mean(en_top5_dists), 4),
            "es_mean": round(mean(es_top5_dists), 4),
            "mean_pair_diff": round(mean(distance_diffs), 4),
            "max_pair_diff": round(max(distance_diffs), 4),
            "pass": parity_pass,
        },
        "h2_cross_language": {
            "en_to_es": total_cross_en_to_es,
            "es_to_en": total_cross_es_to_en,
            "rate": round(cross_lang_rate, 4),
            "pass": cross_pass,
        },
        "h3_language_bias": {
            "en_same_lang_rate": round(en_same_pct, 4),
            "es_same_lang_rate": round(es_same_pct, 4),
            "bias_diff": round(bias_diff, 4),
            "pass": bias_pass,
        },
        "degraded_es": len(degraded_pairs),
        "degraded_en": len(en_degraded_pairs),
        "timing": {
            "en_embed_mean_ms": round(mean(en_embed_times)),
            "es_embed_mean_ms": round(mean(es_embed_times)),
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Test nomic-embed-text bilingual retrieval quality against LanceDB"
    )
    parser.add_argument("--quick", action="store_true", help="Run subset of queries (8 pairs)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show top-N result content for every pair (for LLM assessment)")
    parser.add_argument("--json", type=str, help="Write results to JSON file")
    parser.add_argument("--table", choices=["emails", "documents", "both"], default="both",
                        help="Which table(s) to test (default: both)")
    args = parser.parse_args()

    pairs = QUICK_PAIRS if args.quick else QUERY_PAIRS

    print(f"Bilingual Embedding Quality Test")
    print(f"Model: {EMBEDDING_MODEL}")
    print(f"Query pairs: {len(pairs)}")
    print(f"Top-K: {TOP_K}")
    print(f"LanceDB: {LANCEDB_PATH}")

    # Verify Ollama
    try:
        get_embedding("test")
    except Exception as e:
        print(f"\nERROR: Cannot connect to Ollama: {e}")
        print("Start Ollama first: ollama serve")
        sys.exit(1)

    db = lancedb.connect(str(LANCEDB_PATH))

    all_results = []
    overall_pass = True

    tables_to_test = []
    if args.table in ("emails", "both"):
        tables_to_test.append(("emails", db.open_table("emails")))
    if args.table in ("documents", "both"):
        tables_to_test.append(("documents", db.open_table("documents")))

    for table_name, table in tables_to_test:
        result = run_tests(table_name, table, pairs, args.verbose)
        all_results.append(result)

        if not (result["h1_distance_parity"]["pass"]
                and result["h2_cross_language"]["pass"]
                and result["h3_language_bias"]["pass"]):
            overall_pass = False

    # Final verdict
    print(f"\n{'='*72}")
    print(f"  OVERALL VERDICT: {'PASS' if overall_pass else 'FAIL'}")
    print(f"{'='*72}")

    for r in all_results:
        h1 = "PASS" if r["h1_distance_parity"]["pass"] else "FAIL"
        h2 = "PASS" if r["h2_cross_language"]["pass"] else "FAIL"
        h3 = "PASS" if r["h3_language_bias"]["pass"] else "FAIL"
        print(f"  {r['table']:12s}  H1={h1}  H2={h2}  H3={h3}  "
              f"degraded_es={r['degraded_es']}  degraded_en={r['degraded_en']}")

    print()

    if args.json:
        output = {
            "model": EMBEDDING_MODEL,
            "top_k": TOP_K,
            "query_pairs": len(pairs),
            "tables": all_results,
            "overall_pass": overall_pass,
        }
        with open(args.json, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Results written to {args.json}")

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
