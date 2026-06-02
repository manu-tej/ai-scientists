#!/usr/bin/env python3
"""Interactive review page for the adversarial-variant set.

Serves a self-contained page over runs/review/variants_review.json: filter by
mode / base-task / gate-status, drill into each variant (the question, what the
perturbation does, the validator proof, the author's notes), and FLAG/APPROVE
each one — flags persist to runs/review/review_state.json so a review survives
reloads and you can come back to it.

Run:  uv run python scripts/review_server.py [--port 8788]
Open: http://localhost:8788   (rebuilds the bundle on each load)
"""
import argparse, json, subprocess, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "runs/review/variants_review.json"
STATE = ROOT / "runs/review/review_state.json"


def rebuild_bundle():
    try:
        subprocess.run([sys.executable, str(ROOT / "scripts/build_review_bundle.py")],
                       cwd=ROOT, capture_output=True, timeout=120)
    except Exception:
        pass


PAGE = r"""<!doctype html><html><head><meta charset=utf-8><title>variant review</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b0e14;--card:#141a24;--line:#222c3a;--fg:#d7e0ea;--mut:#7d8aa0;--ok:#3fb950;--bad:#f85149;--warn:#f0883e;--ac:#6cb6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 ui-monospace,Menlo,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:20px}
h1{font-size:18px;margin:0 0 4px}.sub{color:var(--mut);font-size:12px;margin-bottom:14px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
.chip{font-size:12px;padding:4px 10px;border:1px solid var(--line);border-radius:16px;cursor:pointer;background:var(--card);color:var(--fg)}
.chip.on{background:#10243e;border-color:var(--ac);color:var(--ac)}
.stat{font-size:12px;color:var(--mut);margin-left:auto}
.v{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:10px;overflow:hidden}
.vh{display:flex;align-items:center;gap:10px;padding:11px 14px;cursor:pointer}
.vh:hover{background:#171f2b}
.nm{font-weight:700}.bt{font-size:11px;color:var(--mut)}
.tag{font-size:11px;padding:1px 8px;border-radius:4px;background:#1b2330;color:var(--ac)}
.tag.m-drop{background:#10243e;color:#6cb6ff}.tag.m-single{background:#241634;color:#d2a8ff}.tag.m-stat{background:#2a2410;color:#e3b341}
.st{margin-left:auto;display:flex;gap:8px;align-items:center}
.pill{font-size:11px;padding:2px 9px;border-radius:20px;border:1px solid var(--line)}
.ok{color:var(--ok);border-color:#1d4d28}.bad{color:var(--bad);border-color:#5d2020;background:#2a0f0f}
.pend{color:var(--mut);border-color:var(--line);background:#11161f}
.rev{font-size:11px;padding:3px 10px;border-radius:6px;border:1px solid var(--line);cursor:pointer;background:#0a0d13;color:var(--fg)}
.rev.approved{background:#0f2417;border-color:#1d4d28;color:var(--ok)}
.rev.flagged{background:#2a0f0f;border-color:#5d2020;color:var(--bad)}
.body{display:none;padding:0 14px 14px;border-top:1px solid var(--line)}
.body.open{display:block}
.sec{margin:12px 0}.sec h4{margin:0 0 5px;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}
.q{color:#cdd9e5;white-space:pre-wrap;font-size:13px}
.op{font-size:12px;padding:4px 8px;background:#0a0d13;border:1px solid var(--line);border-radius:5px;margin:3px 0}
.chk{font-size:12px;padding:3px 8px;border-radius:5px;margin:3px 0}
.chk.p{background:#0f2417;color:var(--ok)}.chk.f{background:#2a0f0f;color:var(--bad)}
.notes{color:var(--mut);font-size:12px;white-space:pre-wrap;background:#0a0d13;padding:8px;border-radius:5px;border:1px solid var(--line)}
textarea{width:100%;background:#0a0d13;color:var(--fg);border:1px solid var(--line);border-radius:5px;font:12px ui-monospace;padding:6px;margin-top:6px}
.cs{font-size:10px;color:var(--mut)}
</style></head><body><div class=wrap>
<h1>adversarial-variant review</h1>
<div class=sub id=sub>loading…</div>
<div class=bar id=modebar></div>
<div class=bar id=statusbar></div>
<div id=list></div>
</div>
<script>
const $=s=>document.querySelector(s);
let DATA=null, STATE={}, fMode='all', fStatus='all';
async function load(){
 DATA=await(await fetch('/api/bundle',{cache:'no-store'})).json();
 STATE=await(await fetch('/api/state',{cache:'no-store'})).json();
 const s=DATA.summary;
 const extra=[]; if(s.rejected)extra.push(`${s.rejected} gate✗`); if(s.ungenerated)extra.push(`${s.ungenerated} not-generated`);
 $('#sub').textContent=`${s.emitted} emitted / ${s.total_specs} specs${extra.length?' ('+extra.join(', ')+')':''} · ${s.base_tasks} tasks · dataset ${(s.dataset_revision||'?').slice(0,12)} · modes: `+Object.entries(s.by_mode).map(([k,v])=>`${v} ${k}`).join(', ');
 const modes=['all',...Object.keys(s.by_mode)];
 $('#modebar').innerHTML='<span class=bt>mode:</span>'+modes.map(m=>`<span class="chip ${m===fMode?'on':''}" onclick="setMode('${m}')">${m}</span>`).join('');
 $('#statusbar').innerHTML='<span class=bt>status:</span>'+['all','emitted','rejected','not-generated','approved','flagged','unreviewed'].map(x=>`<span class="chip ${x===fStatus?'on':''}" onclick="setStatus('${x}')">${x}</span>`).join('')+`<span class=stat id=cnt></span>`;
 render();
}
function setMode(m){fMode=m;load()} function setStatus(x){fStatus=x;render();$('#statusbar').querySelectorAll('.chip').forEach(c=>c.classList.toggle('on',c.textContent===x))}
function mtag(m){return m.startsWith('drop')?'m-drop':m.startsWith('single')?'m-single':'m-stat'}
function render(){
 let vs=DATA.variants.filter(v=>fMode==='all'||v.mode===fMode);
 vs=vs.filter(v=>{const r=STATE[v.name]?.verdict;
   if(fStatus==='all')return true; if(fStatus==='emitted')return v.emitted===true; if(fStatus==='rejected')return v.emitted===false;
   if(fStatus==='not-generated')return v.emitted==null;
   if(fStatus==='approved')return r==='approved'; if(fStatus==='flagged')return r==='flagged'; if(fStatus==='unreviewed')return !r;});
 const nrev=DATA.variants.filter(v=>STATE[v.name]?.verdict).length;
 $('#cnt').textContent=`${vs.length} shown · ${nrev}/${DATA.variants.length} reviewed`;
 $('#list').innerHTML=vs.map(v=>{
  const r=STATE[v.name]||{};
  const gate = v.emitted===true ? '<span class="pill ok">gate ✓</span>'
             : v.emitted===false ? '<span class="pill bad">gate ✗</span>'
             : '<span class="pill pend" title="in a spec file but not in MANIFEST.json — re-run generate_variants">not generated</span>';
  const av=r.verdict==='approved'?'approved':'', fv=r.verdict==='flagged'?'flagged':'';
  return `<div class=v><div class=vh onclick="tog('${v.name}')">
    <span class=nm>${v.name}</span><span class=bt>${v.base_task}</span>
    <span class="tag ${mtag(v.mode)}">${v.mode}</span>
    <span class=st>${gate}
      <span class="rev ${av}" onclick="event.stopPropagation();verdict('${v.name}','approved')">approve</span>
      <span class="rev ${fv}" onclick="event.stopPropagation();verdict('${v.name}','flagged')">flag</span>
    </span></div>
    <div class=body id="b-${v.name}">
      <div class=sec><h4>question (base ${v.base_task})</h4><div class=q>${esc(v.question)}</div></div>
      <div class=sec><h4>perturbation · ${v.expected_behavior}</h4>${v.ops.map(o=>`<div class=op>${esc(JSON.stringify(o))}</div>`).join('')||'<div class=bt>(validate_existing / none)</div>'}</div>
      <div class=sec><h4>gate proof (validator checks)</h4>${(v.gate_checks.length?v.gate_checks:v.checks).map(c=>`<div class="chk ${c.passed===false?'f':'p'}">${c.passed===false?'✗':'✓'} ${esc(JSON.stringify(c))}</div>`).join('')}${v.gate_error?`<div class="chk f">${esc(v.gate_error)}</div>`:''}</div>
      <div class=sec><h4>author notes</h4><div class=notes>${esc(v.notes||'—')}</div></div>
      <div class=sec><span class=cs>checksum ${v.checksum||'—'} · ${v.spec_path}</span>
        <textarea placeholder="review comment…" id="c-${v.name}" onchange="comment('${v.name}',this.value)">${esc(r.comment||'')}</textarea></div>
    </div></div>`}).join('')||'<div class=sub>none match</div>';
}
function tog(n){$('#b-'+CSS.escape(n)).classList.toggle('open')}
function esc(s){return(s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function verdict(n,v){const cur=STATE[n]?.verdict; const nv=cur===v?null:v;
 STATE[n]={...(STATE[n]||{}),verdict:nv};
 await fetch('/api/state',{method:'POST',body:JSON.stringify({name:n,verdict:nv})}); render();}
async function comment(n,c){STATE[n]={...(STATE[n]||{}),comment:c};
 await fetch('/api/state',{method:'POST',body:JSON.stringify({name:n,comment:c})});}
load();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/bundle"):
            rebuild_bundle()
            self._send(BUNDLE.read_text() if BUNDLE.exists() else '{"summary":{},"variants":[]}')
        elif self.path.startswith("/api/state"):
            self._send(STATE.read_text() if STATE.exists() else "{}")
        else:
            self._send(PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        upd = json.loads(self.rfile.read(n) or "{}")
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        rec = state.get(upd["name"], {})
        if "verdict" in upd: rec["verdict"] = upd["verdict"]
        if "comment" in upd: rec["comment"] = upd["comment"]
        state[upd["name"]] = rec
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2))
        self._send('{"ok":true}')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8788)
    a = ap.parse_args()
    rebuild_bundle()
    print(f"variant review → http://localhost:{a.port}")
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
