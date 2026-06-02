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


def _load_state() -> dict:
    """Review state, namespaced by annotator: {annotator: {variant: {verdict,comment,ts}}}.

    Multi-annotator-ready for future cloud crowdsourcing (each reviewer's verdicts are
    separate, so inter-annotator agreement can be computed later). Defensively migrates
    any legacy FLAT file ({variant: {verdict,...}}) under an 'anon' annotator.
    """
    if not STATE.exists():
        return {}
    s = json.loads(STATE.read_text() or "{}")
    is_flat = bool(s) and all(isinstance(v, dict) for v in s.values()) and any(
        ("verdict" in v or "comment" in v) for v in s.values())
    if is_flat:
        s = {"anon": s}
        STATE.write_text(json.dumps(s, indent=2))
    return s


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
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;align-items:center}
.chip{font-size:12px;padding:4px 10px;border:1px solid var(--line);border-radius:16px;cursor:pointer;background:var(--card);color:var(--fg)}
.chip.on{background:#10243e;border-color:var(--ac);color:var(--ac)}
.stat{font-size:12px;color:var(--mut);margin-left:auto}
.bt{font-size:11px;color:var(--mut)}
/* task card */
.task{background:var(--card);border:1px solid var(--line);border-radius:11px;margin-bottom:12px;overflow:hidden}
.th{display:flex;align-items:center;gap:11px;padding:13px 16px;cursor:pointer}
.th:hover{background:#171f2b}
.tid{font-weight:700;color:var(--ac);min-width:62px}
.ttl{flex:1;color:#cdd9e5;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cnt{font-size:11px;color:var(--mut);white-space:nowrap}
.tbody{display:none;padding:4px 16px 14px;border-top:1px solid var(--line)}
.tbody.open{display:block}
.sec{margin:13px 0}.sec h4{margin:0 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}
.q{color:#e6edf5;white-space:pre-wrap;font-size:13px;background:#0d1118;border-left:3px solid var(--ac);padding:9px 12px;border-radius:0 6px 6px 0}
.src{color:#cdd9e5;font-size:13px;background:#0d1118;border-left:3px solid #d2a8ff;padding:9px 12px;border-radius:0 6px 6px 0}.src a{text-decoration:none}
.rubric{white-space:pre-wrap;font-size:12px;color:#c2cdda;background:#0a0d13;border:1px solid var(--line);border-radius:6px;padding:10px 12px;max-height:340px;overflow:auto;margin-top:6px}
.toggle{font-size:11px;color:var(--ac);cursor:pointer;user-select:none}
/* variant row inside a task */
.v{background:#0e131c;border:1px solid var(--line);border-radius:8px;margin:7px 0;overflow:hidden}
.vh{display:flex;align-items:center;gap:9px;padding:9px 12px;cursor:pointer}
.vh:hover{background:#141b26}
.nm{font-weight:600;font-size:13px}
.tag{font-size:10px;padding:1px 7px;border-radius:4px;background:#1b2330;color:var(--ac)}
.tag.m-drop{background:#10243e;color:#6cb6ff}.tag.m-single{background:#241634;color:#d2a8ff}.tag.m-stat{background:#2a2410;color:#e3b341}
.st{margin-left:auto;display:flex;gap:7px;align-items:center}
.pill{font-size:10px;padding:2px 8px;border-radius:20px;border:1px solid var(--line)}
.ok{color:var(--ok);border-color:#1d4d28}.bad{color:var(--bad);border-color:#5d2020;background:#2a0f0f}
.pend{color:var(--mut);border-color:var(--line);background:#11161f}
.rev{font-size:11px;padding:3px 10px;border-radius:6px;border:1px solid var(--line);cursor:pointer;background:#0a0d13;color:var(--fg)}
.rev.approved{background:#0f2417;border-color:#1d4d28;color:var(--ok)}
.rev.flagged{background:#2a0f0f;border-color:#5d2020;color:var(--bad)}
.vbody{display:none;padding:0 12px 12px;border-top:1px solid var(--line)}
.vbody.open{display:block}
.v.cur{outline:2px solid var(--ac);outline-offset:-1px}
.kb{font-size:11px;color:var(--mut);margin-bottom:12px}
.kb kbd{background:#0a0d13;border:1px solid var(--line);border-radius:4px;padding:0 5px;color:var(--fg);font-size:10px}
.op{font-size:12px;padding:4px 8px;background:#0a0d13;border:1px solid var(--line);border-radius:5px;margin:3px 0}
.flagbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 12px;background:#2a0f0f;border-top:1px solid #5d2020}
.fr{background:#0a0d13;color:var(--fg);border:1px solid #5d2020;border-radius:5px;font:12px ui-monospace;padding:3px 6px}
.drp{font-size:11px;color:#f0b0a8}
.chk{font-size:12px;padding:3px 8px;border-radius:5px;margin:3px 0}
.chk.p{background:#0f2417;color:var(--ok)}.chk.f{background:#2a0f0f;color:var(--bad)}
.notes{color:var(--mut);font-size:12px;white-space:pre-wrap;background:#0a0d13;padding:8px;border-radius:5px;border:1px solid var(--line)}
textarea{width:100%;background:#0a0d13;color:var(--fg);border:1px solid var(--line);border-radius:5px;font:12px ui-monospace;padding:6px;margin-top:6px}
.cs{font-size:10px;color:var(--mut)}
</style></head><body><div class=wrap>
<h1>adversarial-variant review — by task</h1>
<div class=sub id=sub>loading…</div>
<div class=bar><span class=bt>reviewer:</span>
 <input id=who placeholder="your name" style="background:#0a0d13;color:var(--fg);border:1px solid var(--line);border-radius:6px;font:12px ui-monospace;padding:4px 8px">
 <span class=bt id=whohint></span></div>
<div class=bar id=modebar></div>
<div class=bar id=statusbar></div>
<div class=kb><kbd>j</kbd>/<kbd>k</kbd> next/prev · <kbd>o</kbd> or <kbd>Enter</kbd> expand · <kbd>a</kbd> approve · <kbd>f</kbd> flag · <kbd>u</kbd> next unreviewed · <kbd>c</kbd> comment · <kbd>r</kbd> rubric of current task</div>
<div id=list></div>
</div>
<script>
const $=s=>document.querySelector(s);
let DATA=null, STATE={}, fMode='all', fStatus='all', OPEN={};
const FR=['','still-answerable (signal survives elsewhere)','unfair / trivial','wrong expected behavior','biology off','other (see comment)'];
let me=localStorage.getItem('annotator')||'me';            // default so solo review just works
function mine(){return STATE[me]||{}}                       // current reviewer's verdicts
function others(name){let a=0,f=0;for(const k in STATE){if(k===me)continue;const v=STATE[k][name]?.verdict;if(v==='approved')a++;else if(v==='flagged')f++;}return{a,f};}
async function load(){
 DATA=await(await fetch('/api/bundle',{cache:'no-store'})).json();
 STATE=await(await fetch('/api/state',{cache:'no-store'})).json();
 const w=$('#who'); w.value=me;
 w.onchange=()=>{me=w.value.trim()||'me';w.value=me;localStorage.setItem('annotator',me);render();};
 $('#whohint').textContent=Object.keys(STATE).length>1?`· ${Object.keys(STATE).length} reviewers on record`:'';
 const s=DATA.summary;
 const extra=[]; if(s.rejected)extra.push(`${s.rejected} gate✗`); if(s.ungenerated)extra.push(`${s.ungenerated} not-generated`);
 $('#sub').textContent=`${s.base_tasks} tasks · ${s.emitted}/${s.total_specs} variants emitted${extra.length?' ('+extra.join(', ')+')':''} · dataset ${(s.dataset_revision||'?').slice(0,12)} · `+Object.entries(s.by_mode).map(([k,v])=>`${v} ${k}`).join(', ');
 const modes=['all',...Object.keys(s.by_mode)];
 $('#modebar').innerHTML='<span class=bt>mode:</span>'+modes.map(m=>`<span class="chip ${m===fMode?'on':''}" onclick="setMode('${m}')">${m}</span>`).join('');
 $('#statusbar').innerHTML='<span class=bt>status:</span>'+['all','emitted','rejected','not-generated','approved','flagged','unreviewed'].map(x=>`<span class="chip ${x===fStatus?'on':''}" onclick="setStatus('${x}')">${x}</span>`).join('')+`<span class=stat id=cnt></span>`;
 render();
}
function setMode(m){fMode=m;render();$('#modebar').querySelectorAll('.chip').forEach(c=>c.classList.toggle('on',c.textContent===fMode))}
function setStatus(x){fStatus=x;render();$('#statusbar').querySelectorAll('.chip').forEach(c=>c.classList.toggle('on',c.textContent===x))}
function mtag(m){return m.startsWith('drop')?'m-drop':m.startsWith('single')?'m-single':'m-stat'}
function vMatch(v){const r=mine()[v.name]?.verdict;
 if(fMode!=='all'&&v.mode!==fMode)return false;
 if(fStatus==='all')return true; if(fStatus==='emitted')return v.emitted===true; if(fStatus==='rejected')return v.emitted===false;
 if(fStatus==='not-generated')return v.emitted==null;
 if(fStatus==='approved')return r==='approved'; if(fStatus==='flagged')return r==='flagged'; if(fStatus==='unreviewed')return !r; return true;}
function render(){
 let allV=DATA.tasks.flatMap(t=>t.variants);
 const nrev=allV.filter(v=>mine()[v.name]?.verdict).length;
 const shownTasks=DATA.tasks.filter(t=>t.variants.some(vMatch));
 $('#cnt').textContent=`${shownTasks.length} tasks shown · ${nrev}/${allV.length} reviewed by ${me||'(set your name)'}`;
 $('#list').innerHTML=shownTasks.map(t=>{
  const vs=t.variants.filter(vMatch);
  const revd=t.variants.filter(v=>mine()[v.name]?.verdict).length;
  const gateSum=`<span class="pill ok">${t.n_emitted}✓</span>`+(t.n_rejected?`<span class="pill bad">${t.n_rejected}✗</span>`:'');
  const op=OPEN[t.base_task]?'open':'';
  return `<div class=task><div class=th onclick="togT('${t.base_task}')">
    <span class=tid>${t.base_task}</span><span class=ttl>${esc(t.title)}</span>
    <span class=cnt>${vs.length} variant${vs.length>1?'s':''} · ${revd}/${t.n_variants} reviewed</span>${gateSum}
   </div>
   <div class="tbody ${op}" id="t-${t.base_task}">
    ${srcLine(t.source)}
    <div class=sec><h4>original question <a class=toggle href="/file?path=data/biomnibench-da/${t.base_task}/instruction.md" target=_blank>↗ open instruction.md</a></h4><div class=q>${esc(t.question)}</div></div>
    <div class=sec><h4>rubric <span class=toggle onclick="togR('${t.base_task}')" id="rt-${t.base_task}">▸ show</span></h4>
      <div class=rubric id="r-${t.base_task}" style="display:none">${esc(t.rubric)}</div></div>
    <div class=sec><h4>variants derived from this task (${vs.length})</h4>
    ${vs.map(v=>varRow(v)).join('')}</div>
   </div></div>`;
 }).join('')||'<div class=sub>no tasks match the current filter</div>';
 FLAT=[...$('#list').querySelectorAll('.v')].map(e=>e.dataset.v);  // shown order
 if(cur>=FLAT.length)cur=FLAT.length-1; if(cur<0)cur=0;
 applyCursor(false);
}
// --- keyboard-driven review (stay on the keyboard; never reach for the mouse) ---
let FLAT=[], cur=0;
function curName(){return FLAT[cur]}
function applyCursor(scroll){
 $('#list').querySelectorAll('.v.cur').forEach(e=>e.classList.remove('cur'));
 const n=curName(); if(!n)return;
 const el=$('#list').querySelector(`.v[data-v="${CSS.escape(n)}"]`);
 if(el){el.classList.add('cur'); if(scroll)el.scrollIntoView({block:'center',behavior:'smooth'});}
}
function moveCur(d){ if(!FLAT.length)return; cur=Math.max(0,Math.min(FLAT.length-1,cur+d));
 const n=curName(), el=$('#list').querySelector(`.v[data-v="${CSS.escape(n)}"]`);
 if(el){const t=el.dataset.task; if(!OPEN[t]){OPEN[t]=true; $('#t-'+CSS.escape(t)).classList.add('open');}}
 applyCursor(true);}
function nextUnreviewed(){ if(!FLAT.length)return;
 for(let i=1;i<=FLAT.length;i++){const j=(cur+i)%FLAT.length; if(!mine()[FLAT[j]]?.verdict){cur=j;break;}}
 const n=curName(), el=$('#list').querySelector(`.v[data-v="${CSS.escape(n)}"]`);
 if(el){const t=el.dataset.task; if(!OPEN[t]){OPEN[t]=true; $('#t-'+CSS.escape(t)).classList.add('open');}}
 applyCursor(true);}
document.addEventListener('keydown',e=>{
 if(e.target.tagName==='TEXTAREA'){ if(e.key==='Escape')e.target.blur(); return; }
 const n=curName();
 if(e.key==='j'||e.key==='ArrowDown'){e.preventDefault();moveCur(1);}
 else if(e.key==='k'||e.key==='ArrowUp'){e.preventDefault();moveCur(-1);}
 else if(e.key==='o'||e.key==='Enter'){e.preventDefault(); if(n)togV(n);}
 else if(e.key==='a'){e.preventDefault(); if(n)verdict(n,'approved');}
 else if(e.key==='f'){e.preventDefault(); if(n)verdict(n,'flagged');}
 else if(e.key==='u'){e.preventDefault();nextUnreviewed();}
 else if(e.key==='r'){e.preventDefault(); const el=n&&$('#list').querySelector(`.v[data-v="${CSS.escape(n)}"]`); if(el)togR(el.dataset.task);}
 else if(e.key==='c'){e.preventDefault(); if(n){const b=$('#b-'+CSS.escape(n)); if(!b.classList.contains('open'))togV(n); const ta=b.querySelector('textarea'); if(ta)ta.focus();}}
});
function srcLine(s){
 if(!s||!s.title)return '';
 const jy=[s.journal,s.year].filter(Boolean).join(' · ');
 const doi=s.doi?` · <a href="https://doi.org/${s.doi}" target=_blank style="color:var(--ac)">${s.doi}</a>`:(s.note?` · ${esc(s.note)}`:'');
 const acc=s.accession?` · <span class=bt>${esc(s.accession)}</span>`:'';
 return `<div class=sec><h4>source publication</h4><div class=src>${esc(s.title)}<div class=bt style="margin-top:3px">${esc(jy)}${doi}${acc}</div></div></div>`;
}
function varRow(v){
 const r=mine()[v.name]||{};
 const gate = v.emitted===true ? '<span class="pill ok">gate ✓</span>'
            : v.emitted===false ? '<span class="pill bad">gate ✗</span>'
            : '<span class="pill pend" title="in a spec but not in MANIFEST.json — re-run generate_variants">not generated</span>';
 const av=r.verdict==='approved'?'approved':'', fv=r.verdict==='flagged'?'flagged':'';
 const o=others(v.name); const oh=(o.a||o.f)?`<span class=bt title="other reviewers">others ${o.a?o.a+'✓':''}${o.f?' '+o.f+'✗':''}</span>`:'';
 const dropped=(v.dropped||[]);
 const flagbar = r.verdict==='flagged' ? `<div class=flagbar>
     <span class=bt>flag reason:</span>
     <select class=fr onclick="event.stopPropagation()" onchange="event.stopPropagation();flagReason('${v.name}',this.value)">
       ${FR.map(o=>`<option value="${o}"${(r.flag_reason||'')===o?' selected':''}>${o||'— pick a reason —'}</option>`).join('')}</select>
     <span class=drp title="exact perturbation">dropped: ${esc(dropped.join(' ; ')||'(none)')}</span>
   </div>` : '';
 return `<div class=v data-v="${v.name}" data-task="${v.base_task}"><div class=vh onclick="togV('${v.name}')">
   <span class=nm>${v.name.replace(v.base_task+'_','')}</span>
   <span class="tag ${mtag(v.mode)}">${v.mode}</span>
   <span class=st>${oh}${gate}
     <span class="rev ${av}" onclick="event.stopPropagation();verdict('${v.name}','approved')">approve</span>
     <span class="rev ${fv}" onclick="event.stopPropagation();verdict('${v.name}','flagged')">flag</span>
   </span></div>
   ${flagbar}
   <div class=vbody id="b-${v.name}">
     <div class=sec><h4>perturbation · expects: ${v.expected_behavior}</h4>${dropped.map(d=>`<div class=op>✂ ${esc(d)}</div>`).join('')||'<div class=bt>(validate_existing / none)</div>'}</div>
     <div class=sec><h4>gate proof (signal provably gone)</h4>${(v.gate_checks.length?v.gate_checks:v.checks).map(c=>`<div class="chk ${c.passed===false?'f':'p'}">${c.passed===false?'✗':'✓'} ${esc(JSON.stringify(c))}</div>`).join('')}${v.gate_error?`<div class="chk f">${esc(v.gate_error)}</div>`:''}</div>
     <div class=sec><h4>why unanswerable (author notes)</h4><div class=notes>${esc(v.notes||'—')}</div></div>
     <div class=sec><span class=cs>checksum ${v.checksum||'—'} · <a href="/file?path=${encodeURIComponent(v.spec_path)}" target=_blank style="color:var(--ac)">${v.spec_path}</a></span>
       <textarea placeholder="review comment…" onchange="comment('${v.name}',this.value)">${esc(r.comment||'')}</textarea></div>
   </div></div>`;
}
function togT(t){OPEN[t]=!OPEN[t];$('#t-'+CSS.escape(t)).classList.toggle('open')}
function togV(n){$('#b-'+CSS.escape(n)).classList.toggle('open')}
function togR(t){const e=$('#r-'+CSS.escape(t)),b=$('#rt-'+CSS.escape(t));const sh=e.style.display==='none';e.style.display=sh?'block':'none';b.textContent=sh?'▾ hide':'▸ show'}
function esc(s){return(s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function verdict(n,v){ const cur=mine()[n]?.verdict; const nv=cur===v?null:v;
 (STATE[me]=STATE[me]||{})[n]={...(mine()[n]||{}),verdict:nv};
 try{await fetch('/api/state',{method:'POST',body:JSON.stringify({annotator:me,name:n,verdict:nv})});}catch(e){console.error('save failed',e);}
 render();}
async function comment(n,c){ (STATE[me]=STATE[me]||{})[n]={...(mine()[n]||{}),comment:c};
 try{await fetch('/api/state',{method:'POST',body:JSON.stringify({annotator:me,name:n,comment:c})});}catch(e){console.error('save failed',e);}}
async function flagReason(n,reason){ (STATE[me]=STATE[me]||{})[n]={...(mine()[n]||{}),flag_reason:reason};
 try{await fetch('/api/state',{method:'POST',body:JSON.stringify({annotator:me,name:n,flag_reason:reason})});}catch(e){console.error('save failed',e);}}
load();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(200); self.send_header("Content-Type", ctype)
        # Never let the browser cache the page/JS — otherwise a normal reload re-runs
        # STALE rendering logic after the server is updated (the "perturbation is gone"
        # / "buttons dead" class of bug), and only a hard-reload fixes it.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache"); self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/bundle"):
            rebuild_bundle()
            self._send(BUNDLE.read_text() if BUNDLE.exists() else '{"summary":{},"variants":[]}')
        elif self.path.startswith("/api/state"):
            self._send(json.dumps(_load_state()))
        elif self.path.startswith("/file"):
            # Serve a repo file as plain text so the review page can hyperlink to it
            # (browsers block file:// from an http page). Path-traversal guarded.
            from urllib.parse import urlparse, parse_qs, unquote
            rel = unquote(parse_qs(urlparse(self.path).query).get("path", [""])[0])
            target = (ROOT / rel).resolve()
            if ROOT in target.parents and target.is_file():
                self._send(target.read_text(errors="replace"), "text/plain; charset=utf-8")
            else:
                self.send_response(404); self.end_headers()
        else:
            self._send(PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        upd = json.loads(self.rfile.read(n) or "{}")
        state = _load_state()
        who = (upd.get("annotator") or "anon").strip() or "anon"
        per = state.setdefault(who, {})
        rec = per.get(upd["name"], {})
        if "verdict" in upd: rec["verdict"] = upd["verdict"]
        if "comment" in upd: rec["comment"] = upd["comment"]
        if "flag_reason" in upd: rec["flag_reason"] = upd["flag_reason"]
        from datetime import datetime, timezone
        rec["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        per[upd["name"]] = rec
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
