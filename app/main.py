#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kurage 通報先ナビ (kecnavi / Kurage Emergency Contact Navigator)

困りごとから「どこに言えばいいか」を一発で答える。名古屋市が初期対象。

なぜ作るか（2026-09-06〜07 実測）:
  - 「不法投棄 通報」1,300/月、「◯◯区 土木事務所」各50〜260/月。人は
    「通報アプリ」ではなく「どこに言えばいいか」を検索している。
  - 名古屋市には公式LINE通報があるが、窓口は道路(土木事務所)・ごみ(環境事業所)・
    不法投棄(専用FAX)・国道(#9910)・警察(#9110)に分散し、市自身も
    「どこに言えばいいか分からなければおしえてダイヤルへ」と案内している。

設計の芯（khazard から引き継ぐ）:
  1. 電話番号・受付時間・URLは公式一次情報から取り、出典を必ず添える。
  2. 名古屋市サイトの文章は転載しない（同サイトの再利用規約は改変不可・引用のみ）。
     事実(番号・住所・時間)とリンクだけを使い、説明文はすべて自前で書く。
  3. 断定しない。緊急時は110/119を最初に出し、当ナビは案内であって通報の代行ではない。
  4. 議員事務所・政党支部が「自らの情報発信ページ」として運用できる形にする
     （特定の人への供与ではなく、誰でも見られる一般的な案内）。

出典:
  土木事務所: 名古屋市 緑政土木局 連絡先一覧
  環境事業所: 名古屋市 各区の環境事業所
  区役所の所在地・座標: 名古屋市オープンデータ「施設カルテ」(CC BY 4.0)
"""
import json
import math
import os
import re
import time
from collections import defaultdict

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
GSI = "https://msearch.gsi.go.jp/address-search/AddressSearch"
PUBLIC = "https://kurage.exbridge.jp/kecnavi.php"
GA4 = "G-BP0650KDFR"

with open(os.path.join(DATA, "wards.json"), encoding="utf-8") as f:
    WARDS_DOC = json.load(f)
with open(os.path.join(DATA, "contacts.json"), encoding="utf-8") as f:
    CONTACTS_DOC = json.load(f)
WARDS = WARDS_DOC["wards"]
WARD_BY_SLUG = {w["slug"]: w for w in WARDS}
WARD_BY_SHORT = {w["short"]: w for w in WARDS}
CATS = CONTACTS_DOC["categories"]
CAT_BY_SLUG = {c["slug"]: c for c in CATS}
ASOF = WARDS_DOC["asof"]

app = FastAPI(title="Kurage 通報先ナビ")
_hits = defaultdict(list)


def limited(ip, per_min=30):
    now = time.time()
    _hits[ip] = [t for t in _hits[ip] if now - t < 60]
    if len(_hits[ip]) >= per_min:
        return True
    _hits[ip].append(now)
    return False


def geocode(q):
    r = requests.get(GSI, params={"q": q}, timeout=10,
                     headers={"User-Agent": "kecnavi/1.0 (kurage.exbridge.jp)"})
    r.raise_for_status()
    items = r.json()
    if not items:
        return None

    def score(it):
        t = it.get("properties", {}).get("title", "")
        return (q in t, t.startswith(q), -len(t))
    it = max(items, key=score)
    lon, lat = it["geometry"]["coordinates"]
    return {"lat": lat, "lon": lon, "label": it.get("properties", {}).get("title", q)}


def haversine(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def ward_of(label, lat, lon):
    """住所ラベルの「名古屋市◯◯区」を最優先。無ければ名古屋市内に限り最寄りの区役所で補う。"""
    m = re.search(r"名古屋市(.+?)区", label or "")
    if m and m.group(1) in WARD_BY_SHORT:
        return WARD_BY_SHORT[m.group(1)], "label"
    if "名古屋市" not in (label or ""):
        return None, None
    best = min(WARDS, key=lambda w: haversine(lat, lon, w["kuyakusho"]["lat"], w["kuyakusho"]["lon"]))
    return best, "nearest"


def prefix(request: Request):
    """heteml のプロキシ越し(/kecnavi.php/...)か、ローカル直(/)かで内部リンクの接頭辞を変える。"""
    return "/kecnavi.php" if request.headers.get("x-forwarded-host") else ""


# ---------- API ----------
@app.get("/api/resolve")
def resolve(request: Request, q: str):
    ip = request.client.host if request.client else "?"
    if limited(ip):
        raise HTTPException(429, "しばらく待ってからお試しください")
    q = (q or "").strip()
    if not q:
        raise HTTPException(400, "住所を入力してください")
    try:
        g = geocode(q)
    except Exception:
        raise HTTPException(502, "住所検索に接続できませんでした")
    if not g:
        raise HTTPException(404, "住所が見つかりませんでした")
    w, how = ward_of(g["label"], g["lat"], g["lon"])
    if not w:
        return JSONResponse({"query": q, "resolved": g["label"], "ward": None,
                             "note": "名古屋市外の住所です。現在の収録は名古屋市16区のみです。"
                                     "全国共通の窓口（110・119・#9110・#9910）は困りごと別のページをご覧ください。"})
    return JSONResponse({
        "query": q, "resolved": g["label"], "how": how,
        "ward": {"slug": w["slug"], "name": w["name"]},
        "offices": {
            "doboku": w["doboku"], "kankyo": w["kankyo"], "kuyakusho": w["kuyakusho"],
        },
        "asof": ASOF,
        "note": ("住所から区を判定しました。番地単位の境界では隣の区になることがあります。"
                 if how == "nearest" else None),
    })


@app.get("/healthz")
def healthz():
    return {"status": "ok", "wards": len(WARDS), "categories": len(CATS), "asof": ASOF}


# ---------- HTML ----------
STYLE = """<style>
*{box-sizing:border-box}
body{margin:0;background:#fff;color:#12202f;line-height:1.75;
 font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:22px 16px 60px}
.crumb{font-size:12px;color:#7d8a97;margin:0 0 10px}.crumb a{color:#0a726b;text-decoration:none}
h1{font-size:25px;margin:0 0 10px;line-height:1.4}h1 a{color:inherit;text-decoration:none}
h2{font-size:18px;margin:28px 0 8px;border-left:4px solid #0a9a8f;padding-left:10px}
.lead{font-size:15px;color:#37485a;margin:0 0 18px}
.card{border:1px solid #e5ebf1;border-radius:14px;padding:18px;background:#fff;margin:0 0 14px}
form{display:flex;gap:8px;flex-wrap:wrap}
input{flex:1 1 240px;min-width:0;padding:12px 13px;font-size:16px;border:1px solid #cdd8e3;border-radius:10px}
button{padding:12px 22px;font-size:15.5px;font-weight:800;color:#fff;background:#0a9a8f;border:0;border-radius:10px;cursor:pointer}
button:disabled{opacity:.5}
.res{margin-top:14px;font-size:15px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.tile{display:block;border:1.5px solid #e5ebf1;border-radius:14px;padding:14px 15px;text-decoration:none;color:#12202f;background:#fff}
.tile:hover{border-color:#0a9a8f}
.tile b{display:block;font-size:15.5px;color:#0a726b}.tile span{font-size:12.5px;color:#55697a}
.tile.em b{color:#b3261e}
.office{display:grid;grid-template-columns:1fr auto;gap:6px 14px;align-items:center;padding:10px 0;border-top:1px solid #eef2f6}
.office:first-child{border-top:0}
.office .n{font-weight:800}.office .d{font-size:12.5px;color:#55697a}
.tel{font-size:19px;font-weight:900;color:#0a726b;text-decoration:none;white-space:nowrap}
.step{display:flex;gap:12px;margin:0 0 12px}
.step .no{flex:none;width:30px;height:30px;border-radius:50%;background:#0a9a8f;color:#fff;font-weight:900;display:flex;align-items:center;justify-content:center}
.step .em .no{background:#b3261e}
.step p{margin:0;font-size:14.5px}.step small{color:#55697a;font-size:12.5px;display:block}
.warn{background:#fdecec;border:1px solid #f4c9c6;border-radius:12px;padding:12px 14px;font-size:14px;margin:0 0 16px}
.warn b{color:#b3261e}
.note{background:#f3f8f8;border-radius:12px;padding:12px 14px;font-size:13px;color:#37485a;margin:18px 0}
.src{font-size:12px;color:#7d8a97;margin-top:24px;line-height:1.7}
.wards a{display:inline-block;margin:0 8px 6px 0;font-size:14px;color:#0a726b}
@media(max-width:560px){.office{grid-template-columns:1fr}.tel{font-size:18px}}
</style>"""

SCRIPT = """<script>
(function(){
var f=document.getElementById('f');if(!f)return;
var q=document.getElementById('q'),b=document.getElementById('b'),r=document.getElementById('r');
var API=(f.getAttribute('data-api')||'')+'/api/resolve';
function esc(s){return String(s||'').replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function office(o,label){if(!o)return '';var tel=o.tel?'<a class="tel" href="tel:'+esc(o.tel.replace(/-/g,''))+'">'+esc(o.tel)+'</a>':'';
 return '<div class="office"><div><div class="n">'+esc(o.name)+'<span style="font-weight:400;color:#7d8a97;font-size:12.5px"> — '+label+'</span></div><div class="d">'+esc(o.addr||'')+(o.hours?' ／ '+esc(o.hours):'')+'</div></div>'+tel+'</div>'}
f.addEventListener('submit',async function(e){e.preventDefault();var v=q.value.trim();if(!v)return;b.disabled=true;r.innerHTML='<div class="d">調べています…</div>';
 try{var res=await fetch(API+'?q='+encodeURIComponent(v));var d=await res.json();
  if(!res.ok){r.innerHTML='<div class="warn">'+esc(d.detail||'エラー')+'</div>';return}
  if(!d.ward){r.innerHTML='<div class="note">'+esc(d.note)+'</div>';return}
  var h='<div class="card"><div style="font-size:13px;color:#55697a">'+esc(d.resolved)+' → <b>'+esc(d.ward.name)+'</b>'+(d.note?'<br>'+esc(d.note):'')+'</div>';
  h+=office(d.offices.doboku,'道路・公園・街路灯・街路樹');h+=office(d.offices.kankyo,'ごみ・不法投棄');h+=office(d.offices.kuyakusho,'区役所');
  h+='<div class="d" style="margin-top:8px;font-size:12.5px;color:#7d8a97">電話番号・受付時間の時点: '+esc(d.asof)+'。かける前に公式ページで最新をご確認ください。</div></div>';
  r.innerHTML=h;}catch(err){r.innerHTML='<div class="warn">通信に失敗しました</div>'}finally{b.disabled=false}});
var p=new URLSearchParams(location.search).get('q');if(p){q.value=p;f.dispatchEvent(new Event('submit'))}
})();
</script>"""


def shell(title, desc, path, body, ld_list, og_title=None):
    url = PUBLIC + path
    ld = "".join('<script type="application/ld+json">' + json.dumps(x, ensure_ascii=False) + "</script>" for x in ld_list)
    ga = ('<script async src="https://www.googletagmanager.com/gtag/js?id=' + GA4 + '"></script>'
          '<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}'
          "gtag('js',new Date());gtag('config','" + GA4 + "');</script>")
    st = ("<script>(function(){var s=document.createElement('script');"
          "s.src='https://kurage.exbridge.jp/simpletrack.php?url='+encodeURIComponent(location.href)+'&ref='+encodeURIComponent(document.referrer);"
          "s.async=true;document.head.appendChild(s)})();</script>")
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>" + title + "</title>"
            '<meta name="description" content="' + desc + '">'
            '<link rel="canonical" href="' + url + '">'
            '<meta property="og:type" content="website">'
            '<meta property="og:title" content="' + (og_title or title) + '">'
            '<meta property="og:description" content="' + desc + '">'
            '<meta property="og:url" content="' + url + '">'
            '<meta property="og:image" content="https://kurage.exbridge.jp/images/kecnavi-ogp.png">'
            '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
            '<meta name="twitter:card" content="summary_large_image">'
            '<link rel="icon" href="https://kurage.exbridge.jp/images/bittensorman-96.webp">'
            + ld + ga + STYLE + '</head><body><div class="wrap">' + body
            + SCRIPT + st + "</div></body></html>")


def crumb(pre, items):
    parts = ['<a href="' + pre + '/">Kurage 通報先ナビ</a>']
    for name, href in items:
        parts.append('<a href="' + pre + href + '">' + name + "</a>" if href else name)
    return '<nav class="crumb" aria-label="パンくず">' + " ／ ".join(parts) + "</nav>"


def bc_ld(items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": PUBLIC + p} for i, (n, p) in enumerate(items)]}


def faq_ld(pairs):
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in pairs]}


def cat_tiles(pre):
    out = []
    for c in CATS:
        cls = "tile em" if c.get("emergency") else "tile"
        out.append('<a class="' + cls + '" href="' + pre + "/c/" + c["slug"] + '"><b>' + c["title"] + "</b><span>" + c["short"] + "</span></a>")
    return '<div class="grid">' + "".join(out) + "</div>"


def ward_links(pre):
    return '<p class="wards">' + "".join('<a href="' + pre + "/ku/" + w["slug"] + '">' + w["name"] + "</a>" for w in WARDS) + "</p>"


def giin_note():
    return ('<div class="note">議員事務所・政党支部の方へ: このページは「困りごとの通報先案内」という一般的な情報発信として、'
            '事務所の名前で運用できます（特定の方への供与ではありません）。買い切り・ホワイトラベルの詳細は '
            '<a href="https://kurage.exbridge.jp/bousai-giin.html">議員・政党事務所むけ 地域防災情報サービス</a> をご覧ください。</div>')


def src_block(extra=""):
    return ('<p class="src">出典: 土木事務所の電話番号=名古屋市 緑政土木局「連絡先一覧」／環境事業所の電話番号・住所=名古屋市「各区の環境事業所」／'
            "区役所の所在地・座標=名古屋市オープンデータ「施設カルテ」(CC BY 4.0)／"
            "住所検索=国土地理院 地名検索API。" + extra +
            " 本ナビは案内であり、通報や相談を代行するものではありません。番号・受付時間は変わることがあります（時点 " + ASOF + "）。</p>")


def steps_html(cat, pre):
    out = []
    for i, s in enumerate(cat["steps"], 1):
        em = ' class="em"' if s.get("emergency") else ""
        tel = ('<a class="tel" href="tel:' + s["tel"].replace("-", "").replace("#", "%23") + '">' + s["tel"] + "</a> ") if s.get("tel") else ""
        link = (' <a href="' + s["url"] + '" target="_blank" rel="noopener">' + s.get("url_label", "公式ページ") + "</a>") if s.get("url") else ""
        ward = ' <a href="#f">住所を入れると区の電話番号が出ます</a>' if s.get("ward_office") else ""
        out.append('<div class="step"><div' + em + '><div class="no">' + str(i) + "</div></div><div><p><b>" + s["label"] + "</b> " + tel + s["text"] + link + ward + "</p>"
                   + ('<small>' + s["hours"] + "</small>" if s.get("hours") else "") + "</div></div>")
    return "".join(out)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    pre = prefix(request)
    body = (
        '<h1><a href="' + pre + '/">名古屋市の通報先ナビ</a></h1>'
        '<p class="lead">道路の穴、不法投棄、街路灯の故障、公園の遊具——「これ、どこに言えばいいの？」に一発で答えます。'
        "<strong>困りごとから選ぶ</strong>か、<strong>住所を入れる</strong>と、あなたの区の土木事務所・環境事業所の電話番号が出ます。"
        "電話番号と受付時間はすべて名古屋市の公式ページから取り、出典を添えています。</p>"
        '<div class="warn"><b>命に関わる緊急時は 110（警察）／119（消防・救急）</b>。このナビは平時の「どこに連絡するか」の案内です。</div>'
        "<h2>困りごとから選ぶ</h2>" + cat_tiles(pre) +
        '<h2 id="f-h">住所から、あなたの区の窓口を出す</h2>'
        '<div class="card"><form id="f" data-api="' + pre + '">'
        '<input id="q" placeholder="例: 名古屋市天白区島田二丁目" autocomplete="off"><button id="b">窓口を調べる</button></form>'
        '<div class="res" id="r"></div></div>'
        "<h2>区から選ぶ</h2>" + ward_links(pre) +
        "<h2>なぜこのページがあるのか</h2>"
        "<p>名古屋市の通報窓口は、道路は土木事務所、ごみと不法投棄は環境事業所、国道は国の道路緊急ダイヤル、危険は警察と、"
        "内容ごとに分かれています。市の公式LINEでも道路・公園の損傷は通報できますが、写真と位置情報のみで文章は送れず、"
        "不法投棄は対象外です。このナビは、その分かれている窓口を一つの入口にまとめたものです。</p>"
        + giin_note() + src_block())
    title = "名古屋市の通報先ナビ｜道路の穴・不法投棄・街路灯・公園の遊具はどこに連絡する？ | Kurage"
    desc = ("名古屋市で道路の損傷・不法投棄・街路灯・公園遊具などを見つけたとき、どこに通報するかを一発で案内。"
            "住所を入れると区の土木事務所・環境事業所の電話番号が出ます。市公式の番号と受付時間、出典つき。無料。")
    faqs = [("道路の穴や街路灯の故障はどこに連絡すればいいですか？", "名古屋市では区の土木事務所が窓口です。名古屋市公式LINEの「道路・公園損傷通報」でも写真と位置情報で通報できます。国道・県道は国土交通省の道路緊急ダイヤル#9910です。"),
            ("不法投棄はどこに通報しますか？", "名古屋市の不法投棄通報専用ファクス（0120-245318、24時間）または各区の環境事業所です。資源ステーションでの不法投棄・持ち去りは「さんあ～る」アプリから通報できます。"),
            ("どこに言えばいいか分からないときは？", "名古屋おしえてダイヤル 052-953-7584（8時〜21時・年中無休）が市政全般の案内窓口です。")]
    return HTMLResponse(shell(title, desc, "/", body, [bc_ld([("Kurage 通報先ナビ", "/")]), faq_ld(faqs)],
                              "名古屋市の通報先ナビ｜どこに連絡する？を一発で"))


@app.get("/c/{slug}", response_class=HTMLResponse)
def category(request: Request, slug: str):
    c = CAT_BY_SLUG.get(slug)
    if not c:
        raise HTTPException(404, "該当する困りごとが見つかりません")
    pre = prefix(request)
    body = (
        crumb(pre, [(c["title"], None)])
        + '<h1><a href="' + pre + "/c/" + slug + '">' + c["h1"] + "</a></h1>"
        '<p class="lead">' + c["lead"] + "</p>"
        + ('<div class="warn"><b>' + c["warn"] + "</b></div>" if c.get("warn") else "")
        + "<h2>連絡する順番</h2>" + steps_html(c, pre)
        + ('<h2 id="f-h">住所から、あなたの区の窓口を出す</h2>'
           '<div class="card"><form id="f" data-api="' + pre + '">'
           '<input id="q" placeholder="例: 名古屋市天白区島田二丁目" autocomplete="off"><button id="b">窓口を調べる</button></form>'
           '<div class="res" id="r"></div></div>' if c.get("needs_ward") else "")
        + "<h2>他の困りごと</h2>" + cat_tiles(pre)
        + giin_note() + src_block(c.get("src_note", "")))
    title = c["title_seo"] + " | Kurage 通報先ナビ"
    lds = [bc_ld([("Kurage 通報先ナビ", "/"), (c["title"], "/c/" + slug)])]
    if c.get("faq"):
        lds.append(faq_ld([(q, a) for q, a in c["faq"]]))
    return HTMLResponse(shell(title, c["desc"], "/c/" + slug, body, lds, c["h1"] + "｜名古屋市の通報先ナビ"))


@app.get("/ku/{slug}", response_class=HTMLResponse)
def ward(request: Request, slug: str):
    w = WARD_BY_SLUG.get(slug)
    if not w:
        raise HTTPException(404, "区が見つかりません")
    pre = prefix(request)

    def office(o, label):
        tel = ('<a class="tel" href="tel:' + o["tel"].replace("-", "") + '">' + o["tel"] + "</a>") if o.get("tel") else ""
        mp = (' <a href="https://maps.gsi.go.jp/#16/' + str(o["lat"]) + "/" + str(o["lon"]) + '" target="_blank" rel="noopener">地図</a>') if o.get("lat") else ""
        return ('<div class="office"><div><div class="n">' + o["name"] + '<span style="font-weight:400;color:#7d8a97;font-size:12.5px"> — ' + label + "</span></div>"
                '<div class="d">' + (o.get("addr") or "") + (" ／ " + o["hours"] if o.get("hours") else "") + mp + "</div></div>" + tel + "</div>")
    body = (
        crumb(pre, [(w["name"], None)])
        + '<h1><a href="' + pre + "/ku/" + slug + '">' + w["name"] + "の通報先・連絡先</a></h1>"
        '<p class="lead">' + w["name"] + "で道路の損傷・街路灯・公園・ごみ・不法投棄を見つけたときの連絡先です。"
        "電話番号は名古屋市の公式ページから取っています（時点 " + ASOF + "）。</p>"
        '<div class="warn"><b>緊急時は 110／119</b>。ここに載せているのは平時の窓口です。</div>'
        "<h2>" + w["name"] + "の窓口</h2><div class=\"card\">"
        + office(w["doboku"], "道路の穴・段差・ガードレール・街路灯・街路樹・公園の遊具")
        + office(w["kankyo"], "家庭ごみ・粗大ごみ・不法投棄")
        + office(w["kuyakusho"], "区役所（各種手続き）")
        + "</div>"
        "<h2>困りごと別の連絡先（全市共通）</h2>" + cat_tiles(pre)
        + "<h2>他の区</h2>" + ward_links(pre)
        + giin_note() + src_block())
    title = w["name"] + "の通報先｜土木事務所・環境事業所・区役所の電話番号（名古屋市） | Kurage 通報先ナビ"
    desc = (w["name"] + "の土木事務所（道路・街路灯・公園）と環境事業所（ごみ・不法投棄）の電話番号・受付時間、区役所の所在地。"
            "道路の穴や不法投棄をどこに連絡するかを一発で。名古屋市公式の番号・出典つき。")
    faqs = [(w["name"] + "で道路の穴を見つけたらどこに連絡しますか？", w["doboku"]["name"] + "（" + w["doboku"]["tel"] + "）です。名古屋市公式LINEの道路・公園損傷通報も使えます。国道・県道は#9910です。"),
            (w["name"] + "の不法投棄はどこに通報しますか？", "不法投棄通報専用ファクス 0120-245318（24時間）または" + w["kankyo"]["name"] + "（" + w["kankyo"]["tel"] + "）です。")]
    return HTMLResponse(shell(title, desc, "/ku/" + slug, body,
                              [bc_ld([("Kurage 通報先ナビ", "/"), (w["name"], "/ku/" + slug)]), faq_ld(faqs)],
                              w["name"] + "の通報先・連絡先｜名古屋市の通報先ナビ"))


@app.get("/sitemap.xml")
def sitemap():
    urls = [PUBLIC + "/"] + [PUBLIC + "/c/" + c["slug"] for c in CATS] + [PUBLIC + "/ku/" + w["slug"] for w in WARDS]
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + \
          "".join("<url><loc>" + u + "</loc><changefreq>monthly</changefreq></url>" for u in urls) + "</urlset>"
    return Response(content=xml, media_type="application/xml")
