#!/usr/bin/env python3
"""Build a static statistics page from gallery metadata.json / metadata.json.gz."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a static Stats Explorer HTML from metadata.json[.gz]"
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        required=True,
        help="Path to metadata.json or metadata.json.gz",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("stats.html"),
        help="Output HTML file (default: stats.html)",
    )
    parser.add_argument(
        "--favicon-svg",
        type=Path,
        default=None,
        help="Path to an SVG file to embed as the page favicon",
    )
    parser.add_argument(
        "--include-plausible",
        action="store_true",
        help="Include the Plausible analytics snippet in the generated HTML",
    )
    parser.add_argument(
        "--no-local-links",
        action="store_true",
        help="Hide the R (local) link button in ad listings, showing only the G (Drive) button",
    )
    return parser.parse_args()



def render_html(metadata_gz_url: str, favicon_svg: str | None = None, include_plausible: bool = False, no_local_links: bool = False) -> str:
    metadata_gz_path = json.dumps(metadata_gz_url)
    if favicon_svg:
        favicon_b64 = base64.b64encode(favicon_svg.encode("utf-8")).decode("ascii")
        favicon_snippet = f'  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{favicon_b64}" />'
    else:
        favicon_snippet = ""

    plausible_snippet = """  <!-- Privacy-friendly analytics by Plausible -->
  <script async src="https://plausible.io/js/pa-rQ77GcOf_OMaqzLW3wWXn.js"></script>
  <script>
    window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},plausible.init=plausible.init||function(i){plausible.o=i||{}};
    plausible.init()
  </script>""" if include_plausible else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Stats Explorer</title>
{favicon_snippet}
{plausible_snippet}
  <script src="wordcloud2.js"></script>
  <style>
    :root {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      color: #0a0a0a;
      background: #f5f5f7;
    }}
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 1.5rem;
      min-height: 100vh;
    }}
    h1 {{
      margin: 0 0 0.25rem;
      font-size: 1.4rem;
      font-weight: 700;
    }}
    .subtitle {{
      font-size: 0.9rem;
      color: #666;
      margin: 0 0 1.25rem;
    }}
    .stat-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }}
    .stat-pill {{
      background: #fff;
      border: 1px solid #ddd;
      border-radius: 999px;
      padding: 0.3rem 0.9rem;
      font-size: 0.85rem;
      font-weight: 600;
      color: #333;
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }}
    .stat-pill span {{
      color: #0a84ff;
    }}
    /* Card */
    .card {{
      background: #fff;
      border: 1px solid #e0e0e0;
      border-radius: 1rem;
      box-shadow: 0 2px 12px rgba(0,0,0,0.07);
      overflow: hidden;
    }}
    .card-header {{
      padding: 0.9rem 1.25rem;
      border-bottom: 1px solid #eee;
      display: flex;
      align-items: center;
      gap: 0.6rem;
      flex-wrap: wrap;
      min-height: 3rem;
    }}
    .card-title {{
      font-size: 1rem;
      font-weight: 700;
      margin: 0;
      color: #111;
    }}
    .card-subtitle {{
      font-size: 0.82rem;
      color: #777;
      margin: 0;
    }}
    .back-btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      border: 1px solid #bbb;
      background: #fff;
      color: #444;
      border-radius: 999px;
      padding: 0.2rem 0.6rem;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      line-height: 1.4;
      transition: background 100ms;
    }}
    .back-btn:hover {{ background: #f0f0f0; }}
    .back-btn svg {{ flex-shrink: 0; }}
    .sort-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: 1px solid #bbb;
      border-radius: 999px;
      width: 1.8rem;
      height: 1.8rem;
      font-size: 0.8rem;
      font-weight: 700;
      cursor: pointer;
      line-height: 1;
      transition: background 100ms, border-color 100ms, color 100ms;
      margin-left: auto;
      flex-shrink: 0;
    }}
    .sort-btn[data-sort="alpha"]  {{ background: #fff;                        color: #444; border-color: #bbb; }}
    .sort-btn[data-sort="ads"]    {{ background: rgba(10,132,255,0.12);        color: #0a60cc; border-color: #0a84ff; }}
    .sort-btn[data-sort="subs"]   {{ background: rgba(88,175,88,0.15);         color: #2a7a2a; border-color: #4caf50; }}
    .sort-btn[data-sort="count"]  {{ background: #fff;                        color: #444; border-color: #bbb; }}
    .sort-btn[data-sort="az"]     {{ background: rgba(10,132,255,0.12);        color: #0a60cc; border-color: #0a84ff; }}
    .sort-btn:hover {{ filter: brightness(0.93); }}
    /* Layout */
    .card-body {{
      display: grid;
      grid-template-columns: 240px 190px 1fr;
      height: 560px;
    }}
    /* List pane */
    .list-pane {{
      border-right: 1px solid #eee;
      overflow-y: auto;
      padding: 0.5rem 0;
      height: 100%;
    }}
    /* Sub-brand legend pane */
    .sub-list-pane {{
      border-right: 1px solid #eee;
      overflow-y: auto;
      padding: 0.5rem 0;
      height: 100%;
    }}
    .sub-list-pane:empty {{
      border-right-color: transparent;
    }}
    .sub-list-header {{
      padding: 0.42rem 0.9rem 0.3rem;
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #999;
      user-select: none;
    }}
    .sub-list-item {{
      display: flex;
      align-items: center;
      padding: 0.38rem 0.9rem;
      font-size: 0.82rem;
      gap: 0.55rem;
      user-select: none;
      color: #333;
    }}
    .sub-list-swatch {{
      width: 10px;
      height: 10px;
      border-radius: 2px;
      flex-shrink: 0;
    }}
    .sub-list-name {{
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .sub-list-count {{
      font-size: 0.75rem;
      color: #999;
      flex-shrink: 0;
    }}
    .list-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.42rem 1rem;
      cursor: pointer;
      font-size: 0.875rem;
      gap: 0.5rem;
      border-radius: 0;
      transition: background 80ms;
      user-select: none;
    }}
    .list-item:hover {{ background: #f2f6ff; }}
    .list-item.active {{
      background: rgba(10,132,255,0.1);
      color: #0a60cc;
      font-weight: 600;
    }}
    .list-item-name {{
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .list-item-count {{
      font-size: 0.75rem;
      color: #999;
      flex-shrink: 0;
    }}
    .list-item.active .list-item-count {{ color: #0a84ff; }}
    /* Chart pane */
    .chart-pane {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 0;
      overflow: hidden;
      min-height: 0;
    }}
    .chart-pane svg {{
      display: block;
      width: calc(100% - 5rem);
      height: calc(100% - 5rem);
      max-width: calc(100% - 5rem);
      max-height: calc(100% - 5rem);
      overflow: visible;
    }}
    /* Tooltip */
    .tooltip {{
      position: fixed;
      pointer-events: none;
      background: rgba(15,15,20,0.88);
      color: #fff;
      padding: 0.35rem 0.65rem;
      border-radius: 0.4rem;
      font-size: 0.8rem;
      white-space: nowrap;
      z-index: 999;
      opacity: 0;
      transition: opacity 80ms;
      box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    }}
    .tooltip.visible {{ opacity: 1; }}
    .merge-note {{
      position: absolute;
      bottom: 0.5rem;
      right: 0.75rem;
      font-size: 0.7rem;
      color: #aaa;
      font-style: italic;
      pointer-events: none;
    }}
    .card {{
      position: relative;
    }}
    .loading-overlay {{
      position: fixed;
      inset: 0;
      background: rgba(245,245,247,0.9);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1200;
      transition: opacity 180ms ease;
    }}
    .loading-overlay.hidden {{
      opacity: 0;
      pointer-events: none;
    }}
    .loading-card {{
      background: white;
      border-radius: 1rem;
      padding: 1.5rem 2rem;
      box-shadow: 0 12px 40px rgba(0,0,0,0.12);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.75rem;
      max-width: 320px;
      text-align: center;
    }}
    .spinner {{
      width: 32px;
      height: 32px;
      border-radius: 50%;
      border: 3px solid rgba(10,132,255,0.2);
      border-top-color: #0a84ff;
      animation: spin 1s linear infinite;
    }}
    .loading-text {{ font-size: 0.95rem; color: #333; }}
    .loading-overlay.loading-error .spinner {{ display: none; }}
    .loading-overlay.loading-error .loading-text {{ color: #c0392b; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    /* Entry modal */
    .obj-modal-backdrop {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.45);
      z-index: 1100;
      align-items: center;
      justify-content: center;
      padding: 1rem;
    }}
    .obj-modal-backdrop.open {{
      display: flex;
    }}
    .obj-modal {{
      background: #fff;
      border-radius: 1rem;
      box-shadow: 0 12px 40px rgba(0,0,0,0.2);
      max-width: 760px;
      width: 100%;
      max-height: 80vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .obj-modal-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.85rem 1.25rem;
      border-bottom: 1px solid #eee;
      flex-shrink: 0;
    }}
    .obj-modal-title {{
      font-size: 0.95rem;
      font-weight: 700;
      color: #111;
    }}
    .obj-modal-close {{
      background: none;
      border: none;
      font-size: 1rem;
      cursor: pointer;
      color: #888;
      line-height: 1;
      padding: 0.2rem 0.4rem;
      border-radius: 4px;
    }}
    .obj-modal-close:hover {{ background: #f0f0f0; color: #333; }}
    .obj-modal-body {{
      overflow-y: auto;
      flex: 1;
    }}
    .obj-modal-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }}
    .obj-modal-table th {{
      position: sticky;
      top: 0;
      background: #f7f7f7;
      padding: 0.5rem 0.75rem;
      text-align: left;
      font-weight: 600;
      color: #555;
      border-bottom: 1px solid #e0e0e0;
      white-space: nowrap;
    }}
    .obj-modal-table td {{
      padding: 0.4rem 0.75rem;
      border-bottom: 1px solid #f0f0f0;
      vertical-align: middle;
    }}
    .obj-modal-table tr:last-child td {{ border-bottom: none; }}
    .obj-modal-table tr:hover td {{ background: #f9f9ff; }}
    .obj-link-btn {{
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 700;
      text-decoration: none;
      margin-right: 0.3rem;
      border: 1px solid;
    }}
    .obj-link-btn.r-btn {{ color: #c0392b; border-color: #c0392b; background: rgba(192,57,43,0.07); }}
    .obj-link-btn.r-btn:hover {{ background: rgba(192,57,43,0.15); }}
    .obj-link-btn.g-btn {{ color: #27ae60; border-color: #27ae60; background: rgba(39,174,96,0.07); }}
    .obj-link-btn.g-btn:hover {{ background: rgba(39,174,96,0.15); }}
    /* Objects dataset buttons */
    .obj-dataset-btns {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      flex: 1;
    }}
    .obj-ds-btn {{
      border: 1px solid #ddd;
      border-radius: 999px;
      background: #fff;
      color: #555;
      font-size: 0.8rem;
      font-weight: 600;
      padding: 0.2rem 0.75rem;
      cursor: pointer;
      transition: background 100ms, border-color 100ms, color 100ms;
      white-space: nowrap;
    }}
    .obj-ds-btn:hover {{ background: #f0f0f0; }}
    .obj-ds-btn.active {{
      background: rgba(10,132,255,0.12);
      border-color: #0a84ff;
      color: #0a60cc;
    }}
    /* Word cloud canvas */
    #obj-wordcloud {{
      display: block;
      width: 100%;
      height: 100%;
    }}
    /* Summary card */
    .summary-grid {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.55rem 1.1rem;
      padding: 1rem 1.25rem;
    }}
    .summary-item {{
      font-size: 0.85rem;
      color: #333;
      white-space: nowrap;
    }}
    .summary-item .s-label {{
      color: #777;
      font-weight: 400;
    }}
    .summary-item .s-value {{
      font-weight: 700;
      color: #111;
    }}
    .summary-item .s-detail {{
      font-size: 0.78rem;
      color: #999;
      margin-left: 0.25rem;
    }}
    .summary-divider {{
      width: 100%;
      height: 0;
      border-top: 1px solid #eee;
      margin: 0.15rem 0;
    }}
    @media (max-width: 640px) {{
      .card-body {{
        grid-template-columns: 1fr !important;
        height: auto !important;
      }}
      .list-pane {{
        border-right: none;
        height: 280px;
      }}
      .sub-list-pane, .chart-pane, #obj-chart-pane {{
        display: none !important;
      }}
      .merge-note {{
        display: none !important;
      }}
      #obj-sort-btn {{
        display: none !important;
      }}
    }}
  </style>
</head>
<body>
  <div id="back-bar" style="display:none;margin-bottom:0.75rem;">
    <a id="back-link" href="#" style="display:inline-flex;align-items:center;gap:0.4rem;font-size:0.9rem;font-weight:600;color:#0a60cc;text-decoration:none;">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9,2 4,7 9,12"/></svg>
      Back
    </a>
  </div>
  <div class="card" id="summary-card">
    <div class="card-header">
      <h2 class="card-title">Summary</h2>
    </div>
    <div class="summary-grid" id="summary-grid">
      <div class="summary-item"><span class="s-label">Loading…</span></div>
    </div>
  </div>

  <div class="card" style="margin-top:1.25rem;">
    <div class="card-header" id="card-header">
      <h2 class="card-title" id="card-title">Brands</h2>
      <p class="card-subtitle" id="card-subtitle">by number of advertisements</p>
      <div class="stat-pills">
        <div class="stat-pill">Brands: <span id="stat-brands">…</span></div>
        <div class="stat-pill">Sub-brands: <span id="stat-subbrands">…</span></div>
      </div>
      <button class="sort-btn" id="sort-btn" data-sort="alpha" title="Sorted alphabetically — click to change">S</button>
    </div>
    <div class="card-body" id="card-body">
      <div class="list-pane" id="list-pane"></div>
      <div class="sub-list-pane" id="sub-list-pane"></div>
      <div class="chart-pane" id="chart-pane">
        <svg id="pie-svg" viewBox="-150 -150 300 300" preserveAspectRatio="xMidYMid meet"></svg>
      </div>
    </div>
    <div class="merge-note" id="merge-note" hidden></div>
  </div>

  <div class="card" style="margin-top:1.25rem;">
    <div class="card-header">
      <h2 class="card-title">Ad language</h2>
      <p class="card-subtitle">by number of advertisements</p>
      <div class="stat-pills">
        <div class="stat-pill">Languages: <span id="stat-languages">…</span></div>
      </div>
      <button class="sort-btn" id="lang-sort-btn" data-sort="ads" title="Sorted by number of ads — click to change">S</button>
    </div>
    <div class="card-body" style="grid-template-columns: 240px 1fr; height: 360px;">
      <div class="list-pane" id="lang-list-pane"></div>
      <div class="chart-pane">
        <svg id="lang-pie-svg" viewBox="-140 -140 280 280" preserveAspectRatio="xMidYMid meet"></svg>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top:1.25rem;">
    <div class="card-header">
      <h2 class="card-title">Year breakdown</h2>
      <p class="card-subtitle" id="year-subtitle">all years</p>
      <div class="stat-pills">
        <div class="stat-pill">Years: <span id="stat-years">…</span></div>
      </div>
      <button class="sort-btn" id="year-sort-btn" data-sort="all" title="Showing all years — click to show only certain years">S</button>
    </div>
    <div class="card-body" style="grid-template-columns: 240px 1fr; height: 420px;">
      <div class="list-pane" id="year-list-pane"></div>
      <div class="chart-pane">
        <svg id="year-pie-svg" viewBox="-140 -140 280 280" preserveAspectRatio="xMidYMid meet"></svg>
      </div>
    </div>
    <div class="merge-note" id="year-fn-note" hidden></div>
  </div>

  <div class="card" style="margin-top:1.25rem;">
    <div class="card-header">
      <h2 class="card-title">Objects</h2>
      <p class="card-subtitle" id="obj-subtitle">word cloud</p>
      <div class="obj-dataset-btns">
        <button class="obj-ds-btn" data-ds="categories">Categories: <span id="stat-categories">…</span></button>
        <button class="obj-ds-btn" data-ds="casematerials">Case materials: <span id="stat-casematerials">…</span></button>
        <button class="obj-ds-btn" data-ds="caseshapes">Case shapes: <span id="stat-caseshapes">…</span></button>
        <button class="obj-ds-btn" data-ds="colors">Colors: <span id="stat-colors">…</span></button>
        <button class="obj-ds-btn" data-ds="complications">Complications: <span id="stat-complications">…</span></button>
        <button class="obj-ds-btn" data-ds="currencies">Currencies: <span id="stat-currencies">…</span></button>
        <button class="obj-ds-btn" data-ds="dialcolors">Dial colors: <span id="stat-dialcolors">…</span></button>
        <button class="obj-ds-btn active" data-ds="objects">Objects: <span id="stat-objects">…</span></button>
        <button class="obj-ds-btn" data-ds="strapstyles">Strap styles: <span id="stat-strapstyles">…</span></button>
      </div>
      <div style="display:flex;gap:0.3rem;flex-shrink:0;">
        <button class="sort-btn" id="obj-alpha-btn" data-sort="count" title="List sorted by frequency — click to sort alphabetically">S</button>
        <button class="sort-btn" id="obj-sort-btn" data-sort="alpha" title="Showing word cloud — click to show pie chart"></button>
      </div>
    </div>
    <div class="card-body" style="grid-template-columns: 240px 1fr; height: 420px;">
      <div class="list-pane" id="obj-list-pane"></div>
      <div class="chart-pane" id="obj-chart-pane">
        <canvas id="obj-wordcloud"></canvas>
        <svg id="obj-pie-svg" viewBox="-150 -150 300 300" preserveAspectRatio="xMidYMid meet" style="display:none;"></svg>
      </div>
    </div>
  </div>

  <div class="obj-modal-backdrop" id="obj-modal-backdrop">
    <div class="obj-modal" id="obj-modal">
      <div class="obj-modal-header">
        <span class="obj-modal-title" id="obj-modal-title"></span>
        <button class="obj-modal-close" id="obj-modal-close">✕</button>
      </div>
      <div class="obj-modal-body">
        <table class="obj-modal-table" id="obj-modal-table">
          <thead><tr><th>Brand</th><th>Year</th><th>Sub-brand</th><th></th></tr></thead>
          <tbody id="obj-modal-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="loading-overlay" id="loading-overlay">
    <div class="loading-card">
      <div class="spinner"></div>
      <div id="loading-text" class="loading-text">Loading metadata…</div>
    </div>
  </div>

  <div class="tooltip" id="tooltip"></div>

  <script>
    const METADATA_GZ_URL = {metadata_gz_path};
    const NO_LOCAL_LINKS = {'true' if no_local_links else 'false'};
    const ISO_NAMES = {{
      'af':'Afrikaans','sq':'Albanian','am':'Amharic','ar':'Arabic','hy':'Armenian',
      'az':'Azerbaijani','eu':'Basque','be':'Belarusian','bn':'Bengali','bs':'Bosnian',
      'bg':'Bulgarian','ca':'Catalan','zh':'Chinese','zh-Hant':'Chinese (Traditional)',
      'hr':'Croatian','cs':'Czech','da':'Danish','nl':'Dutch','en':'English',
      'eo':'Esperanto','et':'Estonian','fi':'Finnish','fr':'French','gl':'Galician',
      'ka':'Georgian','de':'German','el':'Greek','gu':'Gujarati','ht':'Haitian Creole',
      'ha':'Hausa','he':'Hebrew','hi':'Hindi','hu':'Hungarian','is':'Icelandic',
      'id':'Indonesian','ga':'Irish','it':'Italian','ja':'Japanese','kn':'Kannada',
      'kk':'Kazakh','km':'Khmer','ko':'Korean','ku':'Kurdish','ky':'Kyrgyz',
      'lo':'Lao','la':'Latin','lv':'Latvian','lt':'Lithuanian','lb':'Luxembourgish',
      'mk':'Macedonian','mg':'Malagasy','ms':'Malay','ml':'Malayalam','mt':'Maltese',
      'mi':'Maori','mr':'Marathi','mn':'Mongolian','my':'Myanmar','ne':'Nepali',
      'nb':'Norwegian','or':'Odia','ps':'Pashto','fa':'Persian','pl':'Polish',
      'pt':'Portuguese','pa':'Punjabi','ro':'Romanian','ru':'Russian','sm':'Samoan',
      'sr':'Serbian','sk':'Slovak','sl':'Slovenian','so':'Somali','es':'Spanish',
      'sw':'Swahili','sv':'Swedish','tl':'Tagalog','tg':'Tajik','ta':'Tamil',
      'tt':'Tatar','te':'Telugu','th':'Thai','tr':'Turkish','tk':'Turkmen',
      'uk':'Ukrainian','ur':'Urdu','ug':'Uyghur','uz':'Uzbek','vi':'Vietnamese',
      'cy':'Welsh','xh':'Xhosa','yi':'Yiddish','yo':'Yoruba','zu':'Zulu',
      'unknown':'Unknown',
    }};

    const PIE_MAX = 50;
    const ACCENT_MAP = {{'è':'e','È':'E'}};

    function normalizeBrand(s) {{
      return s.trim().replace(/[èÈ]/g, c => ACCENT_MAP[c] || c).toLowerCase();
    }}
    function displayBrand(s) {{
      const t = s.trim().replace(/[èÈ]/g, c => ACCENT_MAP[c] || c);
      return t ? t[0].toUpperCase() + t.slice(1) : t;
    }}

    // Safe helpers for untrusted JSON data
    const MAX_STR = 200; // max length for any string from metadata
    function safeStr(v) {{
      if (typeof v !== 'string') return '';
      return v.trim().slice(0, MAX_STR);
    }}
    function safeArr(v) {{
      return Array.isArray(v) ? v : [];
    }}
    function safePrimary(meta) {{
      if (Array.isArray(meta)) {{
        const p = meta[0];
        return (p !== null && typeof p === 'object' && !Array.isArray(p)) ? p : {{}};
      }}
      return (meta !== null && typeof meta === 'object' && !Array.isArray(meta)) ? meta : {{}};
    }}
    function safeObj(v) {{
      return (v !== null && typeof v === 'object' && !Array.isArray(v)) ? v : {{}};
    }}
    function safeCount(v) {{
      const n = Number(v);
      return (Number.isFinite(n) && n >= 0) ? Math.floor(n) : 0;
    }}
    // Validate CSS colour — only allow palette hex values
    const HEX_COLOR = /^#[0-9a-fA-F]{{6}}$/;
    function safeColor(c) {{
      return (typeof c === 'string' && HEX_COLOR.test(c)) ? c : '#bab0ac';
    }}

    function computeStats(entries) {{
      // Brands — use Object.create(null) to avoid prototype pollution
      const rawCounts    = Object.create(null);
      const rawSub       = Object.create(null);
      const rawSpellings = Object.create(null);
      const canonical    = Object.create(null);
      const rawBrandRows = Object.create(null); // norm → array of row objects

      for (const entry of entries) {{
        const e0      = safeObj(entry);
        const primary = safePrimary(e0.metadata);
        const bp    = safeObj(primary['brands-products']);
        const brands = safeArr(bp.brand);
        const subs   = safeArr(bp.sub_brands);
        const am0    = safeObj(primary.ad_metadata);
        const ya0    = safeObj(am0.year_ad);
        const ry0    = ya0.year;
        const bRow   = {{
          brand:      '', // filled per brand below
          year:       (typeof ry0 === 'number' && Number.isFinite(ry0) && ry0 >= 1700 && ry0 <= 2100) ? Math.floor(ry0) : '',
          subBrands:  subs.map(s => safeStr(s)).filter(Boolean).join(', '),
          viewUrl:    safeStr(e0.viewUrl),
          originalUrl: safeStr(e0.originalUrl),
        }};
        for (const b of brands) {{
          const bs = safeStr(b);
          if (!bs) continue;
          const norm = normalizeBrand(bs);
          if (!norm) continue;
          rawCounts[norm] = (rawCounts[norm] || 0) + 1;
          if (!rawSpellings[norm]) rawSpellings[norm] = new Set();
          rawSpellings[norm].add(bs);
          if (!canonical[norm]) canonical[norm] = displayBrand(bs);
          if (!rawBrandRows[norm]) rawBrandRows[norm] = [];
          rawBrandRows[norm].push(Object.assign({{}}, bRow, {{ brand: displayBrand(bs) }}));
        }}
        for (const sb of subs) {{
          const sbs = safeStr(sb);
          if (!sbs) continue;
          for (const b of brands) {{
            const bs = safeStr(b);
            if (!bs) continue;
            const norm = normalizeBrand(bs);
            if (!norm) continue;
            if (!rawSub[norm]) rawSub[norm] = Object.create(null);
            rawSub[norm][sbs] = (rawSub[norm][sbs] || 0) + 1;
          }}
        }}
      }}

      const brandCounts      = Object.create(null);
      const subBrandsByBrand = Object.create(null);
      const brandMergeCounts = Object.create(null);
      const brandIndex       = Object.create(null); // display name → array of row objects
      for (const norm of Object.keys(rawCounts)) {{
        const disp = canonical[norm];
        brandCounts[disp]      = rawCounts[norm];
        subBrandsByBrand[disp] = rawSub[norm] || Object.create(null);
        brandMergeCounts[disp] = rawSpellings[norm].size;
        brandIndex[disp]       = rawBrandRows[norm] || [];
      }}

      // Languages
      const langCounts = Object.create(null);
      const langIndex  = Object.create(null);
      for (const entry of entries) {{
        const e1      = safeObj(entry);
        const primary = safePrimary(e1.metadata);
        const bp1     = safeObj(primary['brands-products']);
        const ocr     = safeObj(primary.text_ocr);
        const lang    = safeStr(ocr.original_language);
        const key     = lang || 'unknown';
        langCounts[key] = (langCounts[key] || 0) + 1;
        const lRow = {{
          brand:      safeArr(bp1.brand).map(b => safeStr(b)).filter(Boolean).join(', ') || '—',
          year:       (() => {{ const am = safeObj(primary.ad_metadata); const ya = safeObj(am.year_ad); const y = ya.year; return (typeof y === 'number' && Number.isFinite(y) && y >= 1700 && y <= 2100) ? Math.floor(y) : ''; }})(),
          subBrands:  safeArr(bp1.sub_brands).map(b => safeStr(b)).filter(Boolean).join(', '),
          viewUrl:    safeStr(e1.viewUrl),
          originalUrl: safeStr(e1.originalUrl),
        }};
        if (!langIndex[key]) langIndex[key] = [];
        langIndex[key].push(lRow);
      }}
      const languageCounts = Object.fromEntries(
        Object.entries(langCounts).sort((a, b) => b[1] - a[1])
      );

      // Years
      const FN_PATTERN = new RegExp('^[^-]+-([0-9]{{4}})-[^-]+-[^-]+-[0-9]{{2}}\\.[^.]+$');
      const yearEntries = [];
      let yearFilenameOverrides = 0;
      const yearIndex = Object.create(null); // year key → array of row objects
      for (const entry of entries) {{
        const e2       = safeObj(entry);
        const primary  = safePrimary(e2.metadata);
        const am       = safeObj(primary.ad_metadata);
        const yearAd   = safeObj(am.year_ad);
        const bp2      = safeObj(primary['brands-products']);
        const rawYear  = yearAd.year;
        let year       = (typeof rawYear === 'number' && Number.isFinite(rawYear)) ? Math.floor(rawYear) : 0;
        let estimate   = yearAd.estimate !== false;

        // filename override (already validated by regex + range check)
        const fnMatch = FN_PATTERN.exec(safeStr(e2.filename || '') || '');
        if (fnMatch) {{
          const fnYear = parseInt(fnMatch[1], 10);
          if (fnYear >= 1700 && fnYear <= 2100) {{
            year = fnYear;
            estimate = false;
            yearFilenameOverrides++;
          }}
        }}

        const yKey = (year >= 1700 && year <= 2100) ? year : 'unknown';
        if (year >= 1700 && year <= 2100) {{
          yearEntries.push({{ year, estimate }});
        }} else {{
          yearEntries.push({{ year: 'unknown', estimate: true }});
        }}

        const yRow = {{
          brand:     safeArr(bp2.brand).map(b => safeStr(b)).filter(Boolean).join(', ') || '—',
          year:      yKey === 'unknown' ? '' : yKey,
          subBrands: safeArr(bp2.sub_brands).map(b => safeStr(b)).filter(Boolean).join(', '),
          viewUrl:   safeStr(e2.viewUrl),
          originalUrl: safeStr(e2.originalUrl),
        }};
        if (!yearIndex[yKey]) yearIndex[yKey] = [];
        yearIndex[yKey].push(yRow);
      }}

      const yearCountsAll     = Object.create(null);
      const yearCountsCertain = Object.create(null);
      for (const {{ year, estimate }} of yearEntries) {{
        yearCountsAll[year]     = (yearCountsAll[year] || 0) + 1;
        if (!estimate) yearCountsCertain[year] = (yearCountsCertain[year] || 0) + 1;
      }}

      // Summary stats + entry index (key → [{{brand, year, subBrands, viewUrl, originalUrl}}])
      const objectCounts        = Object.create(null);
      const caseShapeCounts     = Object.create(null);
      const caseMaterialCounts  = Object.create(null);
      const strapStyleCounts    = Object.create(null);
      const dominantColorCounts = Object.create(null);
      const dialColorCounts     = Object.create(null);
      const currencyCounts      = Object.create(null);
      const complicationCounts  = Object.create(null);
      const watchCatCounts      = Object.create(null);
      // entryIndex: ds name → Object.create(null) of key → array of row objects
      const entryIndex = {{
        objects: Object.create(null),
        caseshapes: Object.create(null),
        casematerials: Object.create(null),
        strapstyles: Object.create(null),
        colors: Object.create(null),
        dialcolors: Object.create(null),
        currencies: Object.create(null),
        complications: Object.create(null),
        categories: Object.create(null),
      }};
      function indexEntry(ds, key, row) {{
        if (!entryIndex[ds][key]) entryIndex[ds][key] = [];
        entryIndex[ds][key].push(row);
      }}
      let pricingCount    = 0;
      const currencySet   = new Set();
      const complicationSet = new Set();
      const watchCatSet   = new Set();
      const watchRefSet   = new Set();
      let colorAdCount    = 0;
      let nonColorAdCount = 0;
      const dominantColorSet = new Set();
      const dialColorSet  = new Set();
      const objectSet     = new Set();
      const caseShapeSet  = new Set();
      const caseMaterialSet = new Set();
      const strapStyleSet = new Set();
      let mensCount  = 0;
      let womensCount = 0;

      function addToCount(map, rawVal) {{
        const k = safeStr(rawVal).toLowerCase();
        if (!k) return;
        map[k] = (map[k] || 0) + 1;
      }}

      for (const entry of entries) {{
        const e       = safeObj(entry);
        const primary = safePrimary(e.metadata);
        const am = safeObj(primary.ad_metadata);
        const pi = safeObj(am.price_info);
        const bp = safeObj(primary['brands-products']);

        // Build a compact row for the entry index
        const yearAd    = safeObj(am.year_ad);
        const rawYear   = yearAd.year;
        const entryYear = (typeof rawYear === 'number' && Number.isFinite(rawYear) && rawYear >= 1700 && rawYear <= 2100)
          ? Math.floor(rawYear) : '';
        const entryBrand    = safeArr(bp.brand).map(b => safeStr(b)).filter(Boolean).join(', ') || '—';
        const entrySubBrands = safeArr(bp.sub_brands).map(b => safeStr(b)).filter(Boolean).join(', ');
        const entryViewUrl  = safeStr(e.viewUrl);
        const entryOrigUrl  = safeStr(e.originalUrl);
        const row = {{ brand: entryBrand, year: entryYear, subBrands: entrySubBrands, viewUrl: entryViewUrl, originalUrl: entryOrigUrl }};

        function idx(ds, rawVal) {{
          const k = safeStr(rawVal).toLowerCase();
          if (k) indexEntry(ds, k, row);
        }}

        // Pricing — validate array, string type, length
        const currencies = safeArr(pi.currency);
        if (currencies.length > 0) {{
          pricingCount++;
          for (const c of currencies) {{
            const cs = safeStr(c);
            if (!cs) continue;
            const n = cs.toUpperCase().slice(0, 10);
            if (n === 'N/A') continue;
            const k = n === '$' ? 'USD' : n;
            currencySet.add(k);
            currencyCounts[k] = (currencyCounts[k] || 0) + 1;
            indexEntry('currencies', k, row);
          }}
        }}

        // Complications (ignore 'none')
        for (const c of safeArr(bp.complications)) {{
          const cs = safeStr(c);
          if (!cs || cs === 'none') continue;
          complicationSet.add(cs);
          addToCount(complicationCounts, cs);
          idx('complications', cs);
        }}

        // Watch categories
        for (const c of safeArr(bp.watch_categories)) {{
          const cs = safeStr(c);
          if (!cs) continue;
          watchCatSet.add(cs);
          addToCount(watchCatCounts, cs);
          idx('categories', cs);
        }}

        // Watch references
        for (const r of safeArr(bp.watch_references)) {{
          const rs = safeStr(r);
          if (rs) watchRefSet.add(rs);
        }}

        // Color
        if (primary.color_ad === true) colorAdCount++;
        else if (primary.color_ad === false) nonColorAdCount++;

        // Dominant colors
        for (const c of safeArr(primary.colors_dominant)) {{
          const cs = safeStr(c);
          if (!cs) continue;
          dominantColorSet.add(cs);
          addToCount(dominantColorCounts, cs);
          idx('colors', cs);
        }}

        // Dial colors
        for (const c of safeArr(primary.dial_colors)) {{
          const cs = safeStr(c);
          if (!cs) continue;
          dialColorSet.add(cs);
          addToCount(dialColorCounts, cs);
          idx('dialcolors', cs);
        }}

        // Objects
        for (const o of safeArr(primary.objects)) {{
          const os = safeStr(o);
          if (!os) continue;
          objectSet.add(os);
          addToCount(objectCounts, os);
          idx('objects', os);
        }}

        // Case shapes
        for (const s of safeArr(primary.case_shapes)) {{
          const ss = safeStr(s);
          if (!ss) continue;
          caseShapeSet.add(ss);
          addToCount(caseShapeCounts, ss);
          idx('caseshapes', ss);
        }}

        // Case materials
        for (const m of safeArr(primary.case_materials)) {{
          const ms = safeStr(m);
          if (!ms) continue;
          caseMaterialSet.add(ms);
          addToCount(caseMaterialCounts, ms);
          idx('casematerials', ms);
        }}

        // Strap styles
        for (const s of safeArr(primary.strap_styles)) {{
          const ss = safeStr(s);
          if (!ss) continue;
          strapStyleSet.add(ss);
          addToCount(strapStyleCounts, ss);
          idx('strapstyles', ss);
        }}

        // Genders
        const wg = safeObj(primary.watch_genders);
        if (safeCount(wg.mens) > 0)   mensCount++;
        if (safeCount(wg.womens) > 0) womensCount++;
      }}

      let totalWatches = 0;
      for (const entry of entries) {{
        const primary = safePrimary(safeObj(entry).metadata);
        totalWatches += safeCount(primary.count_watches);
      }}

      const summaryStats = {{
        totalAds: entries.length,
        totalWatches,
        objectCounts,
        caseShapeCounts,
        caseMaterialCounts,
        strapStyleCounts,
        dominantColorCounts,
        dialColorCounts,
        currencyCounts,
        complicationCounts,
        watchCatCounts,
        pricingCount,
        currencies: [...currencySet],
        complicationCount: complicationSet.size,
        watchCatCount: watchCatSet.size,
        watchRefCount: watchRefSet.size,
        colorAdCount,
        nonColorAdCount,
        dominantColorCount: dominantColorSet.size,
        dialColorCount: dialColorSet.size,
        objectCount: objectSet.size,
        caseShapeCount: caseShapeSet.size,
        caseMaterialCount: caseMaterialSet.size,
        strapStyleCount: strapStyleSet.size,
        mensCount,
        womensCount,
        entryIndex,
      }};

      return {{ brandCounts, subBrandsByBrand, brandMergeCounts, brandIndex, languageCounts, langIndex, yearCountsAll, yearCountsCertain, yearFilenameOverrides, yearIndex, summaryStats }};
    }}

    const loadingOverlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');

    async function fetchMetadata() {{
      const resp = await fetch(METADATA_GZ_URL);
      if (!resp.ok) throw new Error(`HTTP ${{resp.status}}`);
      const ds = new DecompressionStream('gzip');
      const src = resp.body ? resp.body : new Blob([await resp.arrayBuffer()]).stream();
      const text = await new Response(src.pipeThrough(ds)).text();
      return JSON.parse(text);
    }}

    let BRANDS = {{}};
    let SUB_BRANDS_BY_BRAND = {{}};
    let BRAND_MERGE_COUNTS = {{}};
    let LANGUAGE_COUNTS = {{}};
    let YEAR_COUNTS_ALL = {{}};
    let YEAR_COUNTS_CERTAIN = {{}};
    let YEAR_FILENAME_OVERRIDES = 0;
    let SUMMARY_STATS = {{}};
    let OBJECT_COUNTS = {{}};
    let CASE_SHAPE_COUNTS = {{}};
    let CASE_MATERIAL_COUNTS = {{}};
    let STRAP_STYLE_COUNTS = {{}};
    let DOMINANT_COLOR_COUNTS = {{}};
    let DIAL_COLOR_COUNTS = {{}};
    let CURRENCY_COUNTS = {{}};
    let COMPLICATION_COUNTS = {{}};
    let WATCH_CAT_COUNTS = {{}};
    let ENTRY_INDEX = {{}};
    let YEAR_INDEX  = {{}};
    let LANG_INDEX  = {{}};
    let BRAND_INDEX = {{}};

    async function bootstrap() {{
      loadingOverlay.classList.remove('hidden');
      try {{
        const meta = await fetchMetadata();
        const MAX_ENTRIES = 25000;
        const allEntries = Array.isArray(meta.entries) ? meta.entries : [];
        const entries = allEntries.slice(0, MAX_ENTRIES);
        if (allEntries.length > MAX_ENTRIES) {{
          alert(`Warning: metadata contains ${{allEntries.length.toLocaleString()}} ads. Only the first ${{MAX_ENTRIES.toLocaleString()}} will be shown.`);
        }}
        const stats = computeStats(entries);
        BRANDS = stats.brandCounts;
        SUB_BRANDS_BY_BRAND = stats.subBrandsByBrand;
        BRAND_MERGE_COUNTS = stats.brandMergeCounts;
        LANGUAGE_COUNTS = stats.languageCounts;
        YEAR_COUNTS_ALL = stats.yearCountsAll;
        YEAR_COUNTS_CERTAIN = stats.yearCountsCertain;
        YEAR_FILENAME_OVERRIDES = stats.yearFilenameOverrides;
        SUMMARY_STATS = stats.summaryStats;
        OBJECT_COUNTS        = stats.summaryStats.objectCounts;
        CASE_SHAPE_COUNTS    = stats.summaryStats.caseShapeCounts;
        CASE_MATERIAL_COUNTS = stats.summaryStats.caseMaterialCounts;
        STRAP_STYLE_COUNTS   = stats.summaryStats.strapStyleCounts;
        DOMINANT_COLOR_COUNTS = stats.summaryStats.dominantColorCounts;
        DIAL_COLOR_COUNTS    = stats.summaryStats.dialColorCounts;
        CURRENCY_COUNTS      = stats.summaryStats.currencyCounts;
        COMPLICATION_COUNTS  = stats.summaryStats.complicationCounts;
        WATCH_CAT_COUNTS     = stats.summaryStats.watchCatCounts;
        ENTRY_INDEX          = stats.summaryStats.entryIndex;
        YEAR_INDEX           = stats.yearIndex;
        LANG_INDEX           = stats.langIndex;
        BRAND_INDEX          = stats.brandIndex;

        const allSubBrands = new Set(Object.values(SUB_BRANDS_BY_BRAND).flatMap(Object.keys));
        document.getElementById('stat-brands').textContent = Object.keys(BRANDS).length.toLocaleString();
        document.getElementById('stat-subbrands').textContent = allSubBrands.size.toLocaleString();
        document.getElementById('stat-languages').textContent = Object.keys(LANGUAGE_COUNTS).length.toLocaleString();
        const uniqueYears = Object.keys(YEAR_COUNTS_ALL).filter(y => y !== 'unknown').length;
        const certainYears = Object.keys(YEAR_COUNTS_CERTAIN).filter(y => y !== 'unknown').length;
        document.getElementById('stat-years').textContent = uniqueYears.toLocaleString();

        buildSummaryCard(allSubBrands.size, Object.keys(BRANDS).length, uniqueYears, certainYears);
        updateSortBtn();
        showBrandsView();
        buildLangCard();
        buildYearCard();
        buildObjectsCard();
        loadingOverlay.classList.add('hidden');
      }} catch(err) {{
        console.error(err);
        loadingOverlay.classList.add('loading-error');
        loadingText.textContent = `Failed to load metadata: ${{err.message || err}}`;
      }}
    }}

    // Palette — 50 distinguishable colours
    const PALETTE = [
      '#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f',
      '#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ac',
      '#a0cbe8','#ffbe7d','#8cd17d','#b6992d','#f1ce63',
      '#499894','#86bcb6','#e49444','#d37295','#fabfd2',
      '#79706e','#d4a6c8','#d7b5a6','#b8d0eb','#3d6b9b',
      '#c94040','#5fa85c','#d4a017','#8e5fa3','#ff7f7f',
      '#2e8b57','#cd853f','#4682b4','#da70d6','#32cd32',
      '#ff8c00','#6495ed','#dc143c','#20b2aa','#9370db',
      '#ff6347','#4169e1','#2e8b57','#b22222','#5f9ea0',
      '#d2691e','#6b8e23','#8b4513','#708090','#2f4f4f',
    ];

    const tooltip = document.getElementById('tooltip');
    const listPane = document.getElementById('list-pane');
    const subListPane = document.getElementById('sub-list-pane');
    const pieSvg = document.getElementById('pie-svg');
    const cardTitle = document.getElementById('card-title');
    const cardSubtitle = document.getElementById('card-subtitle');
    const cardHeader = document.getElementById('card-header');
    const sortBtn = document.getElementById('sort-btn');
    const mergeNote = document.getElementById('merge-note');
    const statPills = document.querySelector('.stat-pills');

    let activeBrand = null;
    // Sort states: 'alpha' | 'ads' | 'subs'
    const SORT_STATES = ['alpha', 'ads', 'subs'];
    const SORT_LABELS = {{
      alpha: 'Sorted alphabetically — click to change',
      ads:   'Sorted by number of ads — click to change',
      subs:  'Sorted by number of sub-brands — click to change',
    }};
    const SORT_SUBTITLES = {{
      alpha: 'sorted alphabetically',
      ads:   'by number of advertisements',
      subs:  'by number of sub-brands',
    }};
    let currentSort = 'ads';

    function applySort(entries) {{
      if (currentSort === 'alpha') {{
        return [...entries].sort((a, b) => a[0].localeCompare(b[0]));
      }} else if (currentSort === 'ads') {{
        return [...entries].sort((a, b) => b[1] - a[1]);
      }} else {{ // subs
        return [...entries].sort((a, b) => {{
          const sa = Object.keys(SUB_BRANDS_BY_BRAND[a[0]] || {{}}).length;
          const sb = Object.keys(SUB_BRANDS_BY_BRAND[b[0]] || {{}}).length;
          return sb - sa || b[1] - a[1];
        }});
      }}
    }}

    function updateSortBtn() {{
      sortBtn.setAttribute('data-sort', currentSort);
      sortBtn.title = SORT_LABELS[currentSort];
      if (!activeBrand) {{
        cardSubtitle.textContent = SORT_SUBTITLES[currentSort];
      }}
    }}

    sortBtn.addEventListener('click', () => {{
      const idx = SORT_STATES.indexOf(currentSort);
      currentSort = SORT_STATES[(idx + 1) % SORT_STATES.length];
      updateSortBtn();
      if (!activeBrand) {{
        const entries = applySort(Object.entries(BRANDS));
        buildList(entries, null);
        buildPie(Object.entries(BRANDS).sort((a, b) => b[1] - a[1]));
      }}
    }});

    function sortedEntries(obj) {{
      return Object.entries(obj).sort((a, b) => b[1] - a[1]);
    }}

    function showTooltip(text, e) {{
      tooltip.textContent = text;
      tooltip.classList.add('visible');
      moveTooltip(e);
    }}
    function moveTooltip(e) {{
      let x = e.clientX + 14;
      let y = e.clientY - 28;
      if (x + 180 > window.innerWidth) x = e.clientX - 180;
      if (y < 4) y = e.clientY + 14;
      tooltip.style.left = x + 'px';
      tooltip.style.top = y + 'px';
    }}
    function hideTooltip() {{
      tooltip.classList.remove('visible');
    }}

    function buildPie(data) {{
      // data: [[name, count], ...]  — already sorted descending
      // returns Map(name -> color) for all rendered slices
      pieSvg.innerHTML = '';

      const colorMap = new Map();
      const total = data.reduce((s, d) => s + d[1], 0);
      if (!total) return colorMap;

      // Bucket into top-PIE_MAX + "Other"
      let slices = data.slice(0, PIE_MAX);
      const rest = data.slice(PIE_MAX).reduce((s, d) => s + d[1], 0);
      if (rest > 0) slices = [...slices, ['Other', rest]];

      const sliceTotal = slices.reduce((s, d) => s + d[1], 0);

      let angle = -Math.PI / 2;
      slices.forEach((slice, i) => {{
        const [name, count] = slice;
        const pct = count / sliceTotal;
        const sweep = pct * 2 * Math.PI;
        const x1 = Math.cos(angle) * 130;
        const y1 = Math.sin(angle) * 130;
        angle += sweep;
        const x2 = Math.cos(angle) * 130;
        const y2 = Math.sin(angle) * 130;
        const large = sweep > Math.PI ? 1 : 0;
        const color = PALETTE[i % PALETTE.length];
        colorMap.set(name, color);

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const d = `M 0 0 L ${{x1.toFixed(2)}} ${{y1.toFixed(2)}} A 130 130 0 ${{large}} 1 ${{x2.toFixed(2)}} ${{y2.toFixed(2)}} Z`;
        path.setAttribute('d', d);
        path.setAttribute('fill', color);
        path.setAttribute('stroke', '#fff');
        path.setAttribute('stroke-width', '1.5');
        path.style.cursor = 'default';
        path.style.transition = 'opacity 80ms';
        const label = `${{name}}: ${{count.toLocaleString()}} (${{(pct * 100).toFixed(1)}}%)`;
        path.addEventListener('mousemove', (e) => showTooltip(label, e));
        path.addEventListener('mouseleave', hideTooltip);
        path.addEventListener('mouseenter', () => {{
          pieSvg.querySelectorAll('path').forEach(p => p.style.opacity = '0.45');
          path.style.opacity = '1';
        }});
        path.addEventListener('mouseleave', () => {{
          pieSvg.querySelectorAll('path').forEach(p => p.style.opacity = '1');
        }});
        pieSvg.appendChild(path);
      }});

      return colorMap;
    }}

    function buildList(entries, activeItem) {{
      listPane.innerHTML = '';
      entries.forEach(([name, count]) => {{
        const item = document.createElement('div');
        item.className = 'list-item' + (name === activeItem ? ' active' : '');
        const nameEl = document.createElement('span');
        nameEl.className = 'list-item-name';
        nameEl.textContent = name;
        nameEl.title = name;
        const countEl = document.createElement('span');
        countEl.className = 'list-item-count';
        const displayCount = currentSort === 'subs'
          ? Object.keys(SUB_BRANDS_BY_BRAND[name] || {{}}).length
          : count;
        countEl.textContent = displayCount.toLocaleString();
        item.append(nameEl, countEl);
        item.addEventListener('click', () => onBrandClick(name));
        listPane.appendChild(item);
      }});
    }}

    function showBrandsView() {{
      activeBrand = null;
      const existing = cardHeader.querySelector('.back-btn');
      if (existing) existing.remove();
      sortBtn.style.display = '';
      mergeNote.hidden = true;
      statPills.style.display = '';
      subListPane.innerHTML = '';

      cardTitle.textContent = 'Brands';
      cardSubtitle.textContent = SORT_SUBTITLES[currentSort];

      const allEntries = Object.entries(BRANDS);
      // Always rebuild brands list (restores it on mobile after sub-brand view)
      buildList(applySort(allEntries), null);
      if (!isMobile()) buildPie(allEntries.sort((a, b) => b[1] - a[1]));
    }}

    function isMobile() {{ return window.innerWidth <= 640; }}

    function onBrandClick(brand) {{
      activeBrand = brand;
      // Scroll the clicked item into view & mark active (desktop only — on mobile we replace the list)
      if (!isMobile()) {{
        Array.from(listPane.querySelectorAll('.list-item')).forEach(el => {{
          const isActive = el.querySelector('.list-item-name').textContent === brand;
          el.classList.toggle('active', isActive);
          if (isActive) el.scrollIntoView({{ block: 'nearest' }});
        }});
      }}

      const subs = SUB_BRANDS_BY_BRAND[brand] || {{}};
      const subEntries = sortedEntries(subs);
      const totalSubCount = subEntries.reduce((s, e) => s + e[1], 0);
      const subCount = subEntries.length;

      // Update header
      cardTitle.textContent = brand;
      cardSubtitle.textContent = subCount > 0
        ? `${{subCount.toLocaleString()}} sub-brands`
        : 'No sub-brands recorded';

      sortBtn.style.display = 'none';
      statPills.style.display = 'none';
      const mergedCount = (BRAND_MERGE_COUNTS[brand] || 1) - 1;
      if (mergedCount > 0) {{
        mergeNote.textContent = `brand names normalized and merged: ${{mergedCount}}`;
        mergeNote.hidden = false;
      }} else {{
        mergeNote.hidden = true;
      }}
      // Add back button if not already there
      if (!cardHeader.querySelector('.back-btn')) {{
        const btn = document.createElement('button');
        btn.className = 'back-btn';
        btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="8,2 4,6 8,10"/></svg> Back`;
        btn.title = 'Back to all brands';
        btn.addEventListener('click', (e) => {{ e.stopPropagation(); showBrandsView(); }});
        cardHeader.insertBefore(btn, cardHeader.querySelector('.card-subtitle'));
      }}

      // Rebuild pie + sub-list for sub-brands (or empty state)
      subListPane.innerHTML = '';
      const brandRows = BRAND_INDEX[brand] || [];
      const brandClickable = brandRows.length > 0 && brandRows.length < OBJ_MODAL_MAX;
      if (subEntries.length > 0) {{
        const colorMap = buildPie(subEntries);

        // On mobile: replace list-pane with sub-brands
        if (isMobile()) {{
          listPane.innerHTML = '';
          subEntries.forEach(([name, count], i) => {{
            const color = colorMap.get(name) || PALETTE[i % PALETTE.length];
            const item = document.createElement('div');
            item.className = 'list-item';
            item.style.cursor = brandClickable ? 'pointer' : 'default';
            if (brandClickable) {{
              item.addEventListener('click', () => openEntryModal(`${{brand}} — ${{brandRows.length.toLocaleString()}} ads`, brandRows));
            }}
            const swatch = document.createElement('span');
            swatch.style.width = '10px'; swatch.style.height = '10px'; swatch.style.borderRadius = '2px'; swatch.style.backgroundColor = safeColor(color); swatch.style.flexShrink = '0'; swatch.style.display = 'inline-block';
            const nameEl = document.createElement('span');
            nameEl.className = 'list-item-name';
            nameEl.textContent = name;
            const countEl = document.createElement('span');
            countEl.className = 'list-item-count';
            countEl.textContent = count.toLocaleString();
            item.append(swatch, nameEl, countEl);
            listPane.appendChild(item);
          }});
        }}

        const header = document.createElement('div');
        header.className = 'sub-list-header';
        header.textContent = `Sub-brands (${{subEntries.length}})`;
        subListPane.appendChild(header);
        subEntries.forEach(([name, count], i) => {{
          const color = colorMap.get(name) || PALETTE[i % PALETTE.length];
          const item = document.createElement('div');
          item.className = 'sub-list-item';
          item.style.cursor = brandClickable ? 'pointer' : 'default';
          if (brandClickable) {{
            item.addEventListener('click', () => openEntryModal(`${{brand}} — ${{brandRows.length.toLocaleString()}} ads`, brandRows));
          }}
          const swatch = document.createElement('span');
          swatch.className = 'sub-list-swatch';
          swatch.style.backgroundColor = safeColor(color);
          const nameEl = document.createElement('span');
          nameEl.className = 'sub-list-name';
          nameEl.textContent = name;
          nameEl.title = name;
          const countEl = document.createElement('span');
          countEl.className = 'sub-list-count';
          countEl.textContent = count.toLocaleString();
          item.append(swatch, nameEl, countEl);
          subListPane.appendChild(item);
        }});
      }} else {{
        if (isMobile()) {{
          listPane.innerHTML = '';
          const msg = document.createElement('div');
          msg.style.cssText = 'padding:1rem;color:#aaa;font-size:0.875rem;';
          msg.textContent = 'No sub-brand data';
          listPane.appendChild(msg);
        }}
        pieSvg.innerHTML = '';
        const msg = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        msg.setAttribute('text-anchor', 'middle');
        msg.setAttribute('dominant-baseline', 'middle');
        msg.setAttribute('fill', '#aaa');
        msg.setAttribute('font-size', '14');
        msg.textContent = 'No sub-brand data';
        pieSvg.appendChild(msg);
      }}
    }}

    const langSortBtn = document.getElementById('lang-sort-btn');
    const LANG_SORT_STATES = ['ads', 'alpha'];
    const LANG_SORT_LABELS = {{
      ads:   'Sorted by number of ads — click to change',
      alpha: 'Sorted alphabetically — click to change',
    }};
    let langCurrentSort = 'ads';
    let langColorMap = new Map();

    function buildLangList() {{
      const langListPane = document.getElementById('lang-list-pane');
      langListPane.innerHTML = '';
      const entries = Object.entries(LANGUAGE_COUNTS);
      const sorted = langCurrentSort === 'alpha'
        ? [...entries].sort((a, b) => {{
            const na = ISO_NAMES[a[0]] || a[0];
            const nb = ISO_NAMES[b[0]] || b[0];
            return na.localeCompare(nb);
          }})
        : entries; // already sorted by count from computeStats

      sorted.forEach(([code, count]) => {{
        const color = langColorMap.get(code);
        const name  = ISO_NAMES[code];
        const label = name ? `${{name}} (${{code}})` : code;
        const rows  = LANG_INDEX[code] || [];
        const clickable = rows.length > 0 && rows.length < OBJ_MODAL_MAX;

        const item = document.createElement('div');
        item.className = 'list-item';
        item.style.cursor = clickable ? 'pointer' : 'default';
        if (clickable) item.addEventListener('click', () => openEntryModal(`${{label}} — ${{count.toLocaleString()}} ads`, rows));

        if (color) {{
          const swatch = document.createElement('span');
          swatch.style.width = '10px'; swatch.style.height = '10px'; swatch.style.borderRadius = '2px';
          swatch.style.backgroundColor = safeColor(color); swatch.style.flexShrink = '0'; swatch.style.display = 'inline-block';
          item.appendChild(swatch);
        }}
        const nameEl = document.createElement('span');
        nameEl.className = 'list-item-name';
        nameEl.textContent = label;
        nameEl.title = label;
        const countEl = document.createElement('span');
        countEl.className = 'list-item-count';
        countEl.textContent = count.toLocaleString();
        item.append(nameEl, countEl);
        langListPane.appendChild(item);
      }});
    }}

    langSortBtn.addEventListener('click', () => {{
      const idx = LANG_SORT_STATES.indexOf(langCurrentSort);
      langCurrentSort = LANG_SORT_STATES[(idx + 1) % LANG_SORT_STATES.length];
      langSortBtn.setAttribute('data-sort', langCurrentSort);
      langSortBtn.title = LANG_SORT_LABELS[langCurrentSort];
      buildLangList();
    }});

    function buildLangCard() {{
      const langPieSvg = document.getElementById('lang-pie-svg');
      const entries = Object.entries(LANGUAGE_COUNTS); // sorted by count

      // Pie (built once, colours fixed by ad-count order)
      let slices = entries.slice(0, PIE_MAX);
      const rest = entries.slice(PIE_MAX).reduce((s, e) => s + e[1], 0);
      if (rest > 0) slices = [...slices, ['other', rest]];
      const sliceTotal = slices.reduce((s, e) => s + e[1], 0);
      langColorMap = new Map();

      let angle = -Math.PI / 2;
      slices.forEach((slice, i) => {{
        const [code, count] = slice;
        const pct = count / sliceTotal;
        const sweep = pct * 2 * Math.PI;
        const x1 = Math.cos(angle) * 125;
        const y1 = Math.sin(angle) * 125;
        angle += sweep;
        const x2 = Math.cos(angle) * 125;
        const y2 = Math.sin(angle) * 125;
        const large = sweep > Math.PI ? 1 : 0;
        const color = PALETTE[i % PALETTE.length];
        langColorMap.set(code, color);
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const d = `M 0 0 L ${{x1.toFixed(2)}} ${{y1.toFixed(2)}} A 125 125 0 ${{large}} 1 ${{x2.toFixed(2)}} ${{y2.toFixed(2)}} Z`;
        path.setAttribute('d', d);
        path.setAttribute('fill', color);
        path.setAttribute('stroke', '#fff');
        path.setAttribute('stroke-width', '1.5');
        path.style.transition = 'opacity 80ms';
        const name = ISO_NAMES[code] || code;
        const label = `${{name}} (${{code}}): ${{count.toLocaleString()}} (${{(pct * 100).toFixed(1)}}%)`;
        path.addEventListener('mousemove', (e) => showTooltip(label, e));
        path.addEventListener('mouseleave', hideTooltip);
        path.addEventListener('mouseenter', () => {{
          langPieSvg.querySelectorAll('path').forEach(p => p.style.opacity = '0.45');
          path.style.opacity = '1';
        }});
        path.addEventListener('mouseleave', () => {{
          langPieSvg.querySelectorAll('path').forEach(p => p.style.opacity = '1');
        }});
        langPieSvg.appendChild(path);
      }});

      langSortBtn.setAttribute('data-sort', langCurrentSort);
      langSortBtn.title = LANG_SORT_LABELS[langCurrentSort];
      buildLangList();
    }}

    const yearSortBtn = document.getElementById('year-sort-btn');
    const YEAR_SORT_STATES = ['all', 'certain'];
    const YEAR_SORT_LABELS = {{
      all:     'Showing all years — click to show only certain years',
      certain: 'Showing only certain years — click to show all',
    }};
    const YEAR_SORT_SUBTITLES = {{
      all:     'all years',
      certain: 'certain years only',
    }};
    let yearCurrentSort = 'all';
    let yearColorMap = new Map();

    function yearSortedEntries(counts) {{
      // Sort numerically (unknown at end), smallest to largest
      return Object.entries(counts).sort((a, b) => {{
        if (a[0] === 'unknown') return 1;
        if (b[0] === 'unknown') return -1;
        return Number(a[0]) - Number(b[0]);
      }});
    }}

    function buildYearList() {{
      const yearListPane = document.getElementById('year-list-pane');
      yearListPane.innerHTML = '';
      const counts = yearCurrentSort === 'certain' ? YEAR_COUNTS_CERTAIN : YEAR_COUNTS_ALL;
      const entries = yearSortedEntries(counts).filter(([y]) => yearCurrentSort !== 'certain' || y !== 'unknown');
      entries.forEach(([year, count]) => {{
        const color = yearColorMap.get(year);
        const rows = YEAR_INDEX[year] || [];
        const clickable = rows.length > 0 && rows.length < OBJ_MODAL_MAX;
        const label = year === 'unknown' ? 'Unknown' : String(year);

        const item = document.createElement('div');
        item.className = 'list-item';
        item.style.cursor = clickable ? 'pointer' : 'default';
        if (clickable) item.addEventListener('click', () => openEntryModal(`${{label}} — ${{count.toLocaleString()}} ads`, rows));

        if (color) {{
          const swatch = document.createElement('span');
          swatch.style.width = '10px'; swatch.style.height = '10px'; swatch.style.borderRadius = '2px';
          swatch.style.backgroundColor = safeColor(color); swatch.style.flexShrink = '0'; swatch.style.display = 'inline-block';
          item.appendChild(swatch);
        }}
        const nameEl = document.createElement('span');
        nameEl.className = 'list-item-name';
        nameEl.textContent = label;
        const countEl = document.createElement('span');
        countEl.className = 'list-item-count';
        countEl.textContent = count.toLocaleString();
        item.append(nameEl, countEl);
        yearListPane.appendChild(item);
      }});
    }}

    yearSortBtn.addEventListener('click', () => {{
      const idx = YEAR_SORT_STATES.indexOf(yearCurrentSort);
      yearCurrentSort = YEAR_SORT_STATES[(idx + 1) % YEAR_SORT_STATES.length];
      yearSortBtn.setAttribute('data-sort', yearCurrentSort === 'all' ? 'ads' : 'alpha');
      yearSortBtn.title = YEAR_SORT_LABELS[yearCurrentSort];
      document.getElementById('year-subtitle').textContent = YEAR_SORT_SUBTITLES[yearCurrentSort];
      const counts = yearCurrentSort === 'certain' ? YEAR_COUNTS_CERTAIN : YEAR_COUNTS_ALL;
      const uniqueYears = Object.keys(counts).filter(y => y !== 'unknown').length;
      document.getElementById('stat-years').textContent = uniqueYears.toLocaleString();
      buildYearPie(counts);
      buildYearList();
    }});

    function buildYearPie(counts) {{
      const yearPieSvg = document.getElementById('year-pie-svg');
      yearPieSvg.innerHTML = '';
      yearColorMap = new Map();

      const isCertain = yearCurrentSort === 'certain';
      // Sort known entries by count desc for colour assignment (top years get distinct colours)
      const byCount = Object.entries(counts).filter(([y]) => y !== 'unknown').sort((a, b) => b[1] - a[1]);
      const knownEntries = byCount; // used for overflow colour mapping below
      const unknownCount = isCertain ? 0
        : (counts['unknown'] || 0) + byCount.slice(PIE_MAX).reduce((s, e) => s + e[1], 0);
      // Assign colours by count rank so top years get distinct palette entries
      const colorByYear = new Map();
      byCount.slice(0, PIE_MAX).forEach(([y], i) => colorByYear.set(y, PALETTE[i % PALETTE.length]));
      if (unknownCount > 0) colorByYear.set('unknown', PALETTE[byCount.slice(0, PIE_MAX).length % PALETTE.length]);
      // Build slices sorted smallest→largest year, unknown last
      const knownSlices = byCount.slice(0, PIE_MAX).sort((a, b) => Number(a[0]) - Number(b[0]));
      let slices = knownSlices;
      if (unknownCount > 0) slices = [...knownSlices, ['unknown', unknownCount]];
      const sliceTotal = slices.reduce((s, e) => s + e[1], 0);
      if (!sliceTotal) return;

      // Build yearColorMap from colour-by-count assignment
      yearColorMap = colorByYear;

      let angle = -Math.PI / 2;
      slices.forEach((slice) => {{
        const [year, count] = slice;
        const pct = count / sliceTotal;
        const sweep = pct * 2 * Math.PI;
        const x1 = Math.cos(angle) * 125;
        const y1 = Math.sin(angle) * 125;
        angle += sweep;
        const x2 = Math.cos(angle) * 125;
        const y2 = Math.sin(angle) * 125;
        const large = sweep > Math.PI ? 1 : 0;
        const color = colorByYear.get(year) || '#bab0ac';
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const d = `M 0 0 L ${{x1.toFixed(2)}} ${{y1.toFixed(2)}} A 125 125 0 ${{large}} 1 ${{x2.toFixed(2)}} ${{y2.toFixed(2)}} Z`;
        path.setAttribute('d', d);
        path.setAttribute('fill', color);
        path.setAttribute('stroke', '#fff');
        path.setAttribute('stroke-width', '1.5');
        path.style.transition = 'opacity 80ms';
        const label = `${{year === 'unknown' ? 'Unknown' : year}}: ${{count.toLocaleString()}} (${{(pct * 100).toFixed(1)}}%)`;
        path.addEventListener('mousemove', (e) => showTooltip(label, e));
        path.addEventListener('mouseleave', hideTooltip);
        path.addEventListener('mouseenter', () => {{
          yearPieSvg.querySelectorAll('path').forEach(p => p.style.opacity = '0.45');
          path.style.opacity = '1';
        }});
        path.addEventListener('mouseleave', () => {{
          yearPieSvg.querySelectorAll('path').forEach(p => p.style.opacity = '1');
        }});
        yearPieSvg.appendChild(path);
      }});

      // Map overflow entries (beyond PIE_MAX) to a fallback colour so list items always have a swatch
      const overflowColor = yearColorMap.get('unknown') || '#bab0ac';
      knownEntries.slice(PIE_MAX).forEach(([y]) => yearColorMap.set(y, overflowColor));
    }}

    function buildYearCard() {{
      buildYearPie(YEAR_COUNTS_ALL);
      yearSortBtn.setAttribute('data-sort', 'ads');
      yearSortBtn.title = YEAR_SORT_LABELS[yearCurrentSort];
      const fnNote = document.getElementById('year-fn-note');
      fnNote.textContent = `Year info from filename: ${{YEAR_FILENAME_OVERRIDES}}`;
      fnNote.hidden = false;
      buildYearList();
    }}

    // ── Objects card ─────────────────────────────────────────────────────────
    const OBJ_LIST_MAX = 3000;
    const OBJ_PIE_MAX  = 100;
    const OBJ_WC_MAX   = 3000;

    const objSortBtn = document.getElementById('obj-sort-btn');
    const objAlphaBtn = document.getElementById('obj-alpha-btn');
    let objCurrentDataset = 'objects';
    let objListSort = 'count'; // 'count' | 'az'
    const OBJ_SORT_BTN_PIE_SVG = `<svg width="16" height="16" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path d="M429.9 186.7v406.4h407.5c-4 34.1-12.8 67.3-26.2 99.1-18.4 43.6-44.8 82.7-78.5 116.3-33.6 33.6-72.8 60-116.4 78.4-45.1 19.1-93 28.7-142.5 28.7-49.4 0-97.4-9.7-142.5-28.7-43.6-18.4-82.7-44.8-116.4-78.4-33.6-33.6-60-72.7-78.4-116.3-19.1-45.1-28.7-93-28.7-142.4s9.7-97.3 28.7-142.4c18.4-43.6 44.8-82.7 78.4-116.3 33.6-33.6 72.8-60 116.4-78.4 31.7-13.2 64.7-21.9 98.6-26m44-46.6c-226.4 0-410 183.5-410 409.8s183.6 409.8 410 409.8 410-183.5 410-409.8v-0.8h-410v-409z" fill="currentColor"/><path d="M566.1 80.5c43.7 1.7 86.4 10.6 127 26.4 44 17.1 84.2 41.8 119.6 73.5 71.7 64.1 117.4 151.7 128.7 246.7 1.2 9.9 2 20 2.4 30.2H566.1V80.5m-16-16.3v409h410c0-16.3-1-32.3-2.9-48.1C933.1 221.9 760 64.2 550.1 64.2zM264.7 770.4c-23.1-23.1-42.3-49.1-57.3-77.7l-14.7 6.5c35.7 68.2 94 122.7 165 153.5l4.3-15.6c-36.3-16-69.1-38.4-97.3-66.7z" fill="currentColor"/></svg>`;
    function updateObjSortBtn() {{
      objSortBtn.innerHTML = objCurrentView === 'wordcloud' ? OBJ_SORT_BTN_PIE_SVG : 'W';
    }}
    function objActiveCounts() {{
      switch (objCurrentDataset) {{
        case 'caseshapes':    return CASE_SHAPE_COUNTS;
        case 'casematerials': return CASE_MATERIAL_COUNTS;
        case 'strapstyles':   return STRAP_STYLE_COUNTS;
        case 'colors':        return DOMINANT_COLOR_COUNTS;
        case 'dialcolors':    return DIAL_COLOR_COUNTS;
        case 'currencies':    return CURRENCY_COUNTS;
        case 'complications': return COMPLICATION_COUNTS;
        case 'categories':    return WATCH_CAT_COUNTS;
        default:              return OBJECT_COUNTS;
      }}
    }}

    document.querySelectorAll('.obj-ds-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        objCurrentDataset = btn.dataset.ds;
        document.querySelectorAll('.obj-ds-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (objCurrentView === 'wordcloud') buildObjWordCloud();
        else buildObjPie();
        buildObjList();
      }});
    }});

    const OBJ_VIEWS   = ['wordcloud', 'pie'];
    const OBJ_LABELS  = {{
      wordcloud: 'Showing word cloud — click to show pie chart',
      pie:       'Showing pie chart — click to show word cloud',
    }};
    const OBJ_SUBTITLES = {{
      wordcloud: 'word cloud',
      pie:       'pie chart',
    }};
    let objCurrentView = 'wordcloud';
    let objColorMap = new Map();

    // Prepare sorted entries: top N by count, overflow → 'other'
    function objSortedEntries(max) {{
      const byCount = Object.entries(objActiveCounts()).sort((a, b) => b[1] - a[1]);
      const top = byCount.length <= max ? byCount : byCount.slice(0, max);
      if (byCount.length > max) {{
        const otherCount = byCount.slice(max).reduce((s, e) => s + e[1], 0);
        if (otherCount > 0) top.push(['other', otherCount]);
      }}
      if (objListSort === 'az') {{
        top.sort((a, b) => a[0].localeCompare(b[0]));
      }}
      return top;
    }}

    const OBJ_MODAL_MAX = 2000;

    function openEntryModal(title, rows) {{

      const backdrop  = document.getElementById('obj-modal-backdrop');
      const titleEl   = document.getElementById('obj-modal-title');
      const tbody     = document.getElementById('obj-modal-tbody');

      titleEl.textContent = title;
      tbody.innerHTML   = '';

      [...rows].sort((a, b) => a.brand.toLowerCase().localeCompare(b.brand.toLowerCase())).forEach(row => {{
        const tr = document.createElement('tr');

        const tdBrand = document.createElement('td');
        tdBrand.textContent = row.brand;

        const tdYear = document.createElement('td');
        tdYear.textContent = row.year || '—';

        const tdSub = document.createElement('td');
        tdSub.textContent = row.subBrands || '—';

        const tdLinks = document.createElement('td');
        tdLinks.style.whiteSpace = 'nowrap';

        const viewUrl = row.viewUrl;
        const origUrl = row.originalUrl;
        const sameUrl = viewUrl && origUrl && viewUrl === origUrl;

        if (sameUrl || NO_LOCAL_LINKS) {{
          // Only G button
          if (origUrl) {{
            const g = document.createElement('a');
            g.className = 'obj-link-btn g-btn';
            g.textContent = 'G';
            g.href = origUrl;
            g.target = '_blank';
            g.rel = 'noopener noreferrer';
            tdLinks.appendChild(g);
          }}
        }} else {{
          if (viewUrl) {{
            const r = document.createElement('a');
            r.className = 'obj-link-btn r-btn';
            r.textContent = 'R';
            r.href = viewUrl;
            r.target = '_blank';
            r.rel = 'noopener noreferrer';
            tdLinks.appendChild(r);
          }}
          if (origUrl) {{
            const g = document.createElement('a');
            g.className = 'obj-link-btn g-btn';
            g.textContent = 'G';
            g.href = origUrl;
            g.target = '_blank';
            g.rel = 'noopener noreferrer';
            tdLinks.appendChild(g);
          }}
        }}

        tr.append(tdBrand, tdYear, tdSub, tdLinks);
        tbody.appendChild(tr);
      }});

      backdrop.classList.add('open');
    }}

    document.getElementById('obj-modal-close').addEventListener('click', () => {{
      document.getElementById('obj-modal-backdrop').classList.remove('open');
    }});
    document.getElementById('obj-modal-backdrop').addEventListener('click', (e) => {{
      if (e.target === e.currentTarget) e.currentTarget.classList.remove('open');
    }});
    document.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') document.getElementById('obj-modal-backdrop').classList.remove('open');
    }});

    function buildObjList() {{
      const pane = document.getElementById('obj-list-pane');
      pane.innerHTML = '';
      const entries = objSortedEntries(OBJ_LIST_MAX);
      entries.forEach(([name, count]) => {{
        const color = objColorMap.get(name);
        const dsIndex = ENTRY_INDEX[objCurrentDataset] || {{}};
        const rows    = dsIndex[name.toLowerCase()] || [];
        const clickable = rows.length > 0 && rows.length < OBJ_MODAL_MAX;

        const item = document.createElement('div');
        item.className = 'list-item';
        item.style.cursor = clickable ? 'pointer' : 'default';
        if (clickable) item.addEventListener('click', () => openEntryModal(`${{name}} — ${{count.toLocaleString()}} ads`, rows));

        const swatch = document.createElement('span');
        swatch.style.width = '10px'; swatch.style.height = '10px'; swatch.style.borderRadius = '2px';
        swatch.style.flexShrink = '0'; swatch.style.display = 'inline-block';
        if (color) {{
          swatch.style.backgroundColor = safeColor(color);
        }} else {{
          swatch.style.backgroundColor = '#fff';
          swatch.style.border = '1px solid #999';
        }}
        item.appendChild(swatch);
        const nameEl = document.createElement('span');
        nameEl.className = 'list-item-name';
        nameEl.textContent = name;
        const countEl = document.createElement('span');
        countEl.className = 'list-item-count';
        countEl.textContent = count.toLocaleString();
        item.append(nameEl, countEl);
        pane.appendChild(item);
      }});
    }}

    function buildObjPie() {{
      const svg = document.getElementById('obj-pie-svg');
      svg.innerHTML = '';
      objColorMap = new Map();

      const all = Object.entries(objActiveCounts()).sort((a, b) => b[1] - a[1]);
      const top = all.slice(0, OBJ_PIE_MAX);
      const otherCount = all.slice(OBJ_PIE_MAX).reduce((s, e) => s + e[1], 0);
      let slices = [...top];
      if (otherCount > 0) slices.push(['other', otherCount]);

      // Assign colours by count rank (top → distinct palette), then draw largest→smallest from 12 o'clock
      top.forEach(([name], i) => objColorMap.set(name, PALETTE[i % PALETTE.length]));
      if (otherCount > 0) objColorMap.set('other', '#bab0ac');
      // Overflow list entries get fallback colour
      all.slice(OBJ_PIE_MAX).forEach(([name]) => objColorMap.set(name, '#bab0ac'));

      // Draw largest first from 12 o'clock clockwise
      slices.sort((a, b) => b[1] - a[1]);
      const total = slices.reduce((s, e) => s + e[1], 0);
      if (!total) return;

      let angle = -Math.PI / 2;
      slices.forEach(([name, count]) => {{
        const pct = count / total;
        const sweep = pct * 2 * Math.PI;
        const r = 145;
        const x1 = Math.cos(angle) * r, y1 = Math.sin(angle) * r;
        angle += sweep;
        const x2 = Math.cos(angle) * r, y2 = Math.sin(angle) * r;
        const large = sweep > Math.PI ? 1 : 0;
        const color = objColorMap.get(name) || '#bab0ac';
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const d = `M 0 0 L ${{x1.toFixed(2)}} ${{y1.toFixed(2)}} A ${{r}} ${{r}} 0 ${{large}} 1 ${{x2.toFixed(2)}} ${{y2.toFixed(2)}} Z`;
        path.setAttribute('d', d);
        path.setAttribute('fill', color);
        path.setAttribute('stroke', '#fff');
        path.setAttribute('stroke-width', '1');
        path.style.transition = 'opacity 80ms';
        const label = `${{name}}: ${{count.toLocaleString()}} (${{(pct * 100).toFixed(1)}}%)`;
        path.addEventListener('mousemove', (e) => showTooltip(label, e));
        path.addEventListener('mouseleave', hideTooltip);
        path.addEventListener('mouseenter', () => {{
          svg.querySelectorAll('path').forEach(p => p.style.opacity = '0.45');
          path.style.opacity = '1';
        }});
        path.addEventListener('mouseleave', () => {{
          svg.querySelectorAll('path').forEach(p => p.style.opacity = '1');
        }});
        svg.appendChild(path);
      }});
    }}

    function buildObjWordCloud() {{
      const canvas = document.getElementById('obj-wordcloud');
      const pane   = document.getElementById('obj-chart-pane');
      objColorMap  = new Map();

      // Size canvas to fill the chart pane
      const cw = pane.offsetWidth  || 600;
      const ch = pane.offsetHeight || 400;
      canvas.width  = cw;
      canvas.height = ch;

      const all = Object.entries(objActiveCounts()).sort((a, b) => b[1] - a[1]);
      // Drop singletons only for large datasets where they'd never fit; keep all if < 100 unique words
      const filtered = all.length >= 100 ? all.filter(([, c]) => c > 1) : all;
      const top = filtered.slice(0, Math.min(OBJ_WC_MAX, 1000));
      if (!top.length) return;

      top.forEach(([name], i) => objColorMap.set(name, PALETTE[i % PALETTE.length]));

      const maxCount = top[0][1];
      const minCount = top[top.length - 1][1];
      const MIN_W = 12, MAX_W = 60;
      function wordWeight(count) {{
        if (maxCount === minCount) return (MIN_W + MAX_W) / 2;
        return MIN_W + (MAX_W - MIN_W) * Math.sqrt((count - minCount) / (maxCount - minCount));
      }}

      const list = top.map(([name, count]) => [String(name).slice(0, MAX_STR), wordWeight(count)]);

      // Build a lookup for tooltip: word → count
      const countByWord = new Map(top.map(([name, count]) => [name, count]));

      canvas.addEventListener('mouseleave', hideTooltip);
      WordCloud(canvas, {{
        list,
        gridSize: Math.round(3 * cw / 600),
        weightFactor: 1,
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        color: (word) => objColorMap.get(word) || '#bab0ac',
        rotateRatio: 0,
        backgroundColor: '#ffffff',
        shrinkToFit: true,
        drawOutOfBound: false,
        hover: (item, dimension, event) => {{
          if (item && typeof item[0] === 'string') {{
            const count = safeCount(countByWord.get(item[0]));
            showTooltip(`${{item[0]}}: ${{count.toLocaleString()}}`, event);
          }} else {{
            hideTooltip();
          }}
        }},
      }});
    }}

    function buildObjectsCard() {{
      document.getElementById('stat-objects').textContent       = Object.keys(OBJECT_COUNTS).length.toLocaleString();
      document.getElementById('stat-caseshapes').textContent    = Object.keys(CASE_SHAPE_COUNTS).length.toLocaleString();
      document.getElementById('stat-casematerials').textContent = Object.keys(CASE_MATERIAL_COUNTS).length.toLocaleString();
      document.getElementById('stat-strapstyles').textContent   = Object.keys(STRAP_STYLE_COUNTS).length.toLocaleString();
      document.getElementById('stat-colors').textContent        = Object.keys(DOMINANT_COLOR_COUNTS).length.toLocaleString();
      document.getElementById('stat-dialcolors').textContent    = Object.keys(DIAL_COLOR_COUNTS).length.toLocaleString();
      document.getElementById('stat-currencies').textContent    = Object.keys(CURRENCY_COUNTS).length.toLocaleString();
      document.getElementById('stat-complications').textContent = Object.keys(COMPLICATION_COUNTS).length.toLocaleString();
      document.getElementById('stat-categories').textContent    = Object.keys(WATCH_CAT_COUNTS).length.toLocaleString();
      objSortBtn.setAttribute('data-sort', 'alpha');
      objSortBtn.title = OBJ_LABELS[objCurrentView];
      document.getElementById('obj-subtitle').textContent = OBJ_SUBTITLES[objCurrentView];
      updateObjSortBtn();
      buildObjWordCloud();
      buildObjList();
    }}

    objSortBtn.addEventListener('click', () => {{
      const idx = OBJ_VIEWS.indexOf(objCurrentView);
      objCurrentView = OBJ_VIEWS[(idx + 1) % OBJ_VIEWS.length];
      objSortBtn.setAttribute('data-sort', objCurrentView === 'wordcloud' ? 'alpha' : 'ads');
      objSortBtn.title = OBJ_LABELS[objCurrentView];
      document.getElementById('obj-subtitle').textContent = OBJ_SUBTITLES[objCurrentView];
      updateObjSortBtn();

      const wc  = document.getElementById('obj-wordcloud');
      const pie = document.getElementById('obj-pie-svg');
      if (objCurrentView === 'wordcloud') {{
        pie.style.display = 'none';
        wc.style.display  = 'block';
        buildObjWordCloud();
      }} else {{
        wc.style.display  = 'none';
        pie.style.display = 'block';
        buildObjPie();
      }}
      buildObjList();
    }});

    objAlphaBtn.addEventListener('click', () => {{
      objListSort = objListSort === 'count' ? 'az' : 'count';
      objAlphaBtn.setAttribute('data-sort', objListSort === 'az' ? 'az' : 'count');
      objAlphaBtn.title = objListSort === 'az'
        ? 'List sorted alphabetically — click to sort by frequency'
        : 'List sorted by frequency — click to sort alphabetically';
      buildObjList();
    }});

    function buildSummaryCard(subBrandCount, brandCount, allYears, certainYears) {{
      const s = SUMMARY_STATS;
      const grid = document.getElementById('summary-grid');

      // Build rows of items
      function item(label, value, detail) {{
        const d = document.createElement('div');
        d.className = 'summary-item';
        const lbl = document.createElement('span');
        lbl.className = 's-label';
        lbl.textContent = label + ':';
        const val = document.createElement('span');
        val.className = 's-value';
        val.textContent = ' ' + value;
        d.appendChild(lbl);
        d.appendChild(val);
        if (detail) {{
          const det = document.createElement('span');
          det.className = 's-detail';
          det.textContent = ' ' + detail;
          d.appendChild(det);
        }}
        return d;
      }}
      function divider() {{
        const d = document.createElement('div');
        d.className = 'summary-divider';
        return d;
      }}

      grid.innerHTML = '';

      // Row 1 — core counts
      grid.appendChild(item('Total ads', s.totalAds.toLocaleString()));
      grid.appendChild(item('Brands', brandCount.toLocaleString()));
      grid.appendChild(item('Sub-brands', subBrandCount.toLocaleString()));
      grid.appendChild(item('Total watches', s.totalWatches.toLocaleString()));
      grid.appendChild(item('Years', `${{allYears.toLocaleString()}} / ${{certainYears.toLocaleString()}}`, '(all / certain)'));
      grid.appendChild(item('Languages', Object.keys(LANGUAGE_COUNTS).length.toLocaleString()));
      grid.appendChild(divider());

      // Row 2 — pricing
      grid.appendChild(item('Pricing info', s.pricingCount.toLocaleString()));
      if (s.currencies.length > 0) {{
        grid.appendChild(item('Currencies', s.currencies.length.toLocaleString()));
      }}
      grid.appendChild(divider());

      // Row 3 — product details
      grid.appendChild(item('Complications', s.complicationCount.toLocaleString()));
      grid.appendChild(item('Watch categories', s.watchCatCount.toLocaleString()));
      grid.appendChild(item('Watch references', s.watchRefCount.toLocaleString()));
      grid.appendChild(divider());

      // Row 4 — visual
      grid.appendChild(item('Color ads', s.colorAdCount.toLocaleString()));
      grid.appendChild(item('Non-color ads', s.nonColorAdCount.toLocaleString()));
      grid.appendChild(item('Dominant colors', s.dominantColorCount.toLocaleString()));
      grid.appendChild(item('Dial colors', s.dialColorCount.toLocaleString()));
      grid.appendChild(divider());

      // Row 5 — physical attributes
      grid.appendChild(item('Objects', s.objectCount.toLocaleString()));
      grid.appendChild(item('Case shapes', s.caseShapeCount.toLocaleString()));
      grid.appendChild(item('Case materials', s.caseMaterialCount.toLocaleString()));
      grid.appendChild(item('Strap styles', s.strapStyleCount.toLocaleString()));
      grid.appendChild(divider());

      // Row 6 — gender
      grid.appendChild(item('Watch gender — Men/unisex', s.mensCount.toLocaleString()));
      grid.appendChild(item('Women', s.womensCount.toLocaleString()));
    }}

    // Back link from ?back= query param
    (function () {{
      const params = new URLSearchParams(window.location.search);
      const back = params.get('back') || '';
      // Reject anything containing a protocol (e.g. http://, https://, javascript://)
      if (back && !new RegExp('[a-zA-Z][a-zA-Z0-9+.-]*://').test(back)) {{
        const link = document.getElementById('back-link');
        link.href = back;
        document.getElementById('back-bar').style.display = '';
      }}
    }})();

    // Init
    bootstrap();

    // Global mousemove for tooltip positioning
    document.addEventListener('mousemove', (e) => {{
      if (tooltip.classList.contains('visible')) moveTooltip(e);
    }});
  </script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()

    metadata_path = args.metadata
    # Derive .gz path relative to the output file
    if metadata_path.suffix == ".gz":
        gz_path = metadata_path
    else:
        gz_path = metadata_path.with_suffix(metadata_path.suffix + ".gz")

    metadata_gz_url = Path(os.path.relpath(gz_path, args.output.parent)).as_posix()

    favicon_svg = None
    if args.favicon_svg:
        try:
            favicon_svg = args.favicon_svg.read_text()
        except FileNotFoundError:
            print(f"! favicon SVG not found: {args.favicon_svg}", file=sys.stderr)
            return 1
    html = render_html(metadata_gz_url=metadata_gz_url, favicon_svg=favicon_svg, include_plausible=args.include_plausible, no_local_links=args.no_local_links)

    args.output.write_text(html, encoding="utf-8")
    log(f"Wrote {args.output} ({args.output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"! {exc}", file=sys.stderr)
        sys.exit(1)
