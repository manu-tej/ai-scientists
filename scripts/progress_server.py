#!/usr/bin/env python3
"""Live benchbench progress dashboard.

Background thread refreshes status every REFRESH_S by running the host-local
collector on the Mac AND over SSH on serene, then merges them. The HTTP server
serves a self-contained HTML page that polls /api/status. Stdlib only.

Run:  python3 scripts/progress_server.py [--port 8787]
Open: http://localhost:8787
"""
import argparse, json, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERENE = "manu@10.0.0.113"
MAC_ROOT = "/Users/manuarrojwala/2026/ai-scientists/runs/harbor_base_matrix"
SERENE_ROOT = "~/benchbench/runs/harbor_base_matrix"
COLLECTOR_MAC = "/Users/manuarrojwala/2026/ai-scientists/scripts/collect_status.py"
COLLECTOR_SERENE = "~/benchbench/scripts/collect_status.py"
REFRESH_S = 25
TOTAL = 50

_state = {"updated": 0, "hosts": {}, "merged": {}, "error": None}
_lock = threading.Lock()


def _collect_mac():
    out = subprocess.run(["python3", COLLECTOR_MAC, "--root", MAC_ROOT, "--host", "mac"],
                         capture_output=True, text=True, timeout=30).stdout
    return json.loads(out)


def _collect_serene():
    cmd = ["ssh", "-o", "ConnectTimeout=8", SERENE,
           f"cd ~/benchbench && python3 {COLLECTOR_SERENE} --root {SERENE_ROOT} --host serene"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=35).stdout
    return json.loads(out)


def _merge(mac, serene):
    """Union scored tasks across hosts (cc runs on both); codex serene-only."""
    agents = {}
    for ag in ("codex", "claude-code"):
        tasks = set()
        for h in (mac, serene):
            if h:
                tasks |= set(h.get("agents", {}).get(ag, {}).get("tasks", []))
        agents[ag] = {"scored": len(tasks), "total": TOTAL, "tasks": sorted(tasks)}
    live, recent, billed, examples = [], [], 0, []
    arms = {"serene_codex": False, "serene_cc": False, "mac_cc": False}
    for label, h in (("serene", serene), ("mac", mac)):
        if not h:
            continue
        for c in h.get("live", []):
            live.append({**c, "host": label})
        for r in h.get("recent_scores", []):
            recent.append({**r, "host": label})
        billed += h.get("billing", {}).get("billed_cells", 0)
        examples += h.get("billing", {}).get("examples", [])
    if serene:
        arms["serene_codex"] = any(c["agent"] == "codex" for c in serene.get("live", [])) or serene.get("arms", {}).get("until_complete", False)
        arms["serene_cc"] = any(c["agent"] == "claude-code" for c in serene.get("live", [])) or serene.get("arms", {}).get("until_complete", False)
    if mac:
        arms["mac_cc"] = mac.get("arms", {}).get("mac_cc", False) or any(c["agent"] == "claude-code" for c in mac.get("live", []))
    if serene:
        arms["variant_paired"] = serene.get("arms", {}).get("variant_paired", False) or bool(serene.get("variant_live"))
    recent.sort(key=lambda r: r.get("mtime", 0), reverse=True)
    # variants run only on serene
    variants = (serene or {}).get("variants", {"present": False})
    variant_live = (serene or {}).get("variant_live", [])
    return {
        "agents": agents,
        "live": live,
        "recent_scores": recent[:14],
        "billing": {"billed_cells": billed, "examples": examples[:3],
                    "status": "clean" if billed == 0 else "BILLING"},
        "arms": arms,
        "variants": variants,
        "variant_live": variant_live,
    }


def refresher():
    while True:
        mac = serene = None
        err = []
        try:
            mac = _collect_mac()
        except Exception as e:
            err.append(f"mac: {e}")
        try:
            serene = _collect_serene()
        except Exception as e:
            err.append(f"serene: {e}")
        with _lock:
            _state["hosts"] = {"mac": mac, "serene": serene}
            _state["merged"] = _merge(mac, serene)
            _state["updated"] = time.time()
            _state["error"] = "; ".join(err) if err else None
        time.sleep(REFRESH_S)


PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<title>benchbench · live</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b0e14;--card:#141a24;--line:#222c3a;--fg:#d7e0ea;--mut:#7d8aa0;--ok:#3fb950;--warn:#f0883e;--bad:#f85149;--cx:#6cb6ff;--cc:#d2a8ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
.wrap{max-width:1100px;margin:0 auto;padding:22px}
h1{font-size:19px;margin:0 0 2px}.sub{color:var(--mut);font-size:12px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:760px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:0 0 12px}
.bar{height:26px;background:#0a0d13;border:1px solid var(--line);border-radius:6px;overflow:hidden;position:relative}
.bar>span{display:block;height:100%;transition:width .6s}
.bar.codex>span{background:linear-gradient(90deg,#1f6feb,#6cb6ff)}.bar.cc>span{background:linear-gradient(90deg,#8957e5,#d2a8ff)}
.bar b{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;color:#fff;text-shadow:0 1px 2px #000}
.row{display:flex;justify-content:space-between;align-items:center;margin:6px 0}
.pill{font-size:11px;padding:2px 9px;border-radius:20px;border:1px solid var(--line)}
.ok{color:var(--ok);border-color:#1d4d28}.bad{color:var(--bad);border-color:#5d2020;background:#2a0f0f}.warn{color:var(--warn);border-color:#5a3a1a}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:5px 6px;border-bottom:1px solid var(--line)}th{color:var(--mut);font-weight:400;font-size:11px;text-transform:uppercase}
.tag{font-size:11px;padding:1px 6px;border-radius:4px}.tcx{background:#10243e;color:var(--cx)}.tcc{background:#241634;color:var(--cc)}
.host{font-size:11px;color:var(--mut)}
.score{font-weight:700}.s100{color:var(--ok)}.smid{color:var(--warn)}.slow{color:var(--bad)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}.live{background:var(--ok);box-shadow:0 0 8px var(--ok);animation:p 1.4s infinite}.dead{background:var(--mut)}
@keyframes p{50%{opacity:.35}}
.big{font-size:30px;font-weight:700}.muted{color:var(--mut)}
.banner{padding:10px 14px;border-radius:8px;margin-bottom:16px;font-weight:600}
.bgreen{background:#0f2417;border:1px solid #1d4d28;color:var(--ok)}.bred{background:#2a0f0f;border:1px solid #5d2020;color:var(--bad)}
</style></head><body><div class=wrap>
<h1>benchbench · capability baseline</h1>
<div class=sub id=sub>connecting…</div>
<div id=guard class="banner bgreen">⏳ loading…</div>
<div class=grid>
  <div class=card><h2>codex (gpt-5.5 · ChatGPT sub)</h2>
    <div class="bar codex"><span id=cxbar style=width:0%></span><b id=cxlbl>—</b></div>
    <div class=row><span class=muted>scored</span><span class=big id=cxn>0</span></div></div>
  <div class=card><h2>claude-code (opus-4-7 · Max sub)</h2>
    <div class="bar cc"><span id=ccbar style=width:0%></span><b id=cclbl>—</b></div>
    <div class=row><span class=muted>scored</span><span class=big id=ccn>0</span></div></div>
</div>
<div class=card style=margin-top:14px><h2>live cells</h2><table id=live><thead><tr><th>host<th>agent<th>task<th>log</th><th>last write</th></tr></thead><tbody></tbody></table></div>
<div class=card style=margin-top:14px id=variantcard><h2>refusal variants · K=3 paired (9 variants × 3 reps)</h2>
  <div class=row><span class=muted>codex</span><span id=vcxn class=muted>—</span></div>
  <div class="bar codex"><span id=vcxbar style=width:0%></span><b id=vcxlbl>—</b></div>
  <div class=row style=margin-top:8px><span class=muted>claude-code</span><span id=vccn class=muted>—</span></div>
  <div class="bar cc"><span id=vccbar style=width:0%></span><b id=vcclbl>—</b></div>
  <div id=vgrid style=margin-top:12px></div>
</div>
<div class=card style=margin-top:14px><h2>recent scores</h2><table id=recent><thead><tr><th>host<th>agent<th>task<th>score</tr></thead><tbody></tbody></table></div>
<div class=sub id=foot></div>
</div>
<script>
const $=s=>document.querySelector(s);
function ago(s){if(s==null)return'—';if(s<60)return s.toFixed(0)+'s';if(s<3600)return(s/60).toFixed(1)+'m';return(s/3600).toFixed(1)+'h'}
function sc(n){return n==null?'slow':n>=85?'s100':n>=50?'smid':'slow'}
function kb(b){return b?(b/1024).toFixed(0)+'KB':'—'}
async function tick(){
 let d;try{d=await(await fetch('/api/status',{cache:'no-store'})).json()}catch(e){$('#sub').textContent='server unreachable';return}
 const m=d.merged||{},a=m.agents||{};
 const cx=a.codex||{scored:0,total:50},cc=a['claude-code']||{scored:0,total:50};
 $('#cxn').textContent=cx.scored+' / '+cx.total;$('#ccn').textContent=cc.scored+' / '+cc.total;
 $('#cxbar').style.width=(100*cx.scored/cx.total)+'%';$('#ccbar').style.width=(100*cc.scored/cc.total)+'%';
 $('#cxlbl').textContent=(100*cx.scored/cx.total).toFixed(0)+'%';$('#cclbl').textContent=(100*cc.scored/cc.total).toFixed(0)+'%';
 const b=m.billing||{billed_cells:0,status:'clean'},g=$('#guard');
 if(b.status==='clean'){g.className='banner bgreen';g.textContent='✓ $0 — subscription auth on all arms · 0 cells billed (auth-guards live)';}
 else{g.className='banner bred';g.textContent='⚠ BILLING DETECTED — '+b.billed_cells+' cell(s) used ANTHROPIC_API_KEY · '+(b.examples||[]).join(', ');}
 const lb=$('#live tbody');lb.innerHTML='';
 (m.live||[]).forEach(c=>{const t=document.createElement('tr');
  const tag=c.agent==='codex'?'tcx':'tcc';const fresh=c.log_age_s!=null&&c.log_age_s<120;
  t.innerHTML=`<td><span class="dot ${fresh?'live':'dead'}"></span><span class=host>${c.host}</span></td>`+
   `<td><span class="tag ${tag}">${c.agent}</span></td><td>${c.task}</td><td>${kb(c.log_bytes)}</td><td class=muted>${ago(c.log_age_s)} ago</td>`;
  lb.appendChild(t)});
 if(!(m.live||[]).length)lb.innerHTML='<tr><td colspan=5 class=muted>no live cells</td></tr>';
 const rb=$('#recent tbody');rb.innerHTML='';
 (m.recent_scores||[]).forEach(r=>{const t=document.createElement('tr');const tag=r.agent==='codex'?'tcx':'tcc';
  t.innerHTML=`<td class=host>${r.host}</td><td><span class="tag ${tag}">${r.agent}</span></td><td>${r.task}</td><td class="score ${sc(r.score)}">${r.score==null?'—':r.score}</td>`;
  rb.appendChild(t)});
 // --- refusal variants panel ---
 const V=m.variants||{present:false}, vlive=(m.variant_live||[]);
 const vcard=$('#variantcard');
 if(!V.present){vcard.style.display='none';}
 else{vcard.style.display='';
  const livevar=ag=>vlive.find(c=>c.agent===ag);
  ['codex','cc'].forEach(short=>{const ag=short==='cc'?'claude-code':'codex';
    const o=V[ag]||{done:0,total:27,per_variant:{}};
    const pct=o.total?100*o.done/o.total:0;
    $('#v'+short+'n').textContent=o.done+' / '+o.total+' reps'+(livevar(ag)?' · running '+livevar(ag).variant:'');
    $('#v'+short+'bar').style.width=pct+'%';$('#v'+short+'lbl').textContent=pct.toFixed(0)+'%';
  });
  // per-variant rep dots (rows = variants, 2 agents each)
  const ag0=V['codex']||{per_variant:{}}, ag1=V['claude-code']||{per_variant:{}};
  const vars=Object.keys(ag0.per_variant||{}).length?Object.keys(ag0.per_variant):Object.keys(ag1.per_variant||{});
  const dots=(n)=>Array.from({length:3},(_, i)=>`<span class="dot ${i<n?'live':'dead'}" style="animation:none"></span>`).join('');
  $('#vgrid').innerHTML='<table style=width:100%><thead><tr><th>variant</th><th>codex</th><th>cc</th></tr></thead><tbody>'+
    vars.map(v=>`<tr><td style=font-size:12px>${v}</td><td>${dots((ag0.per_variant||{})[v]||0)}</td><td>${dots((ag1.per_variant||{})[v]||0)}</td></tr>`).join('')+'</tbody></table>';
 }
 const arms=(m.arms||{});const A=k=>arms[k]?'<span class="pill ok">● up</span>':'<span class="pill warn">○ idle</span>';
 $('#sub').innerHTML=`serene-codex ${A('serene_codex')}  serene-cc ${A('serene_cc')}  mac-cc ${A('mac_cc')}  variants ${A('variant_paired')}`;
 const age=((Date.now()/1000)-(d.updated||0));
 $('#foot').textContent='updated '+ago(age)+' ago'+(d.error?(' · warn: '+d.error):'')+' · refreshes ~25s';
}
tick();setInterval(tick,5000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/status"):
            with _lock:
                body = json.dumps({"updated": _state["updated"], "merged": _state["merged"],
                                   "error": _state["error"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    threading.Thread(target=refresher, daemon=True).start()
    print(f"benchbench dashboard → http://localhost:{a.port}")
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
