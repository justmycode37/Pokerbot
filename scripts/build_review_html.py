"""Build a local interactive review from the frozen qualitative JSON packet."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
packet = json.loads((ROOT / "reports/qualitative-ivey.json").read_text())
rows = json.dumps(packet["decisions"]).replace("<", "\\u003c")
page = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{font-family:var(--font-sans);color:var(--foreground)}
body{margin:0}*{box-sizing:border-box}select,button{font:inherit;color:var(--foreground);background:var(--secondary);border:1px solid var(--border);border-radius:var(--radius);padding:9px;max-width:100%}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}.muted{color:var(--muted-foreground);font-size:13px;line-height:1.5}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:12px}.label{font-size:12px;color:var(--muted-foreground);margin-bottom:6px}.action{font-size:23px;font-weight:650}.cards{font-family:var(--font-mono);font-size:18px;line-height:1.7}.facts{display:flex;gap:24px;flex-wrap:wrap;margin:12px 0}.barrow{display:grid;grid-template-columns:46px 1fr 42px;gap:8px;align-items:center;margin:9px 0;font-size:13px}.track{background:var(--secondary);height:8px;border-radius:var(--radius);overflow:hidden}.fill{height:8px;background:var(--chart-1)}.reading{line-height:1.55;font-size:14px}a{color:var(--primary)}details{margin-top:12px}pre{white-space:pre-wrap;font-size:12px;font-family:var(--font-mono)}@media(max-width:480px){.grid{grid-template-columns:1fr}.facts{gap:12px}}
</style></head><body>
<div class="toolbar"><select id="pick" aria-label="Choose a decision"></select><button id="reveal">Reveal Ivey's move</button></div>
<div class="muted" id="context"></div>
<div class="card"><div class="label">Information available at the decision</div><div class="cards" id="cards"></div><div class="facts" id="facts"></div><div class="muted" id="tier"></div></div>
<div class="grid"><div class="card"><div class="label">Bot decision</div><div class="action" id="bot"></div><p class="reading" id="reason"></p><div class="label">Bot's action mix for this position</div><div id="mix"></div></div><div class="card"><div class="label">Ivey's recorded decision</div><div class="action" id="ivey">Hidden for blind review</div><p class="reading" id="sizing"></p><div class="muted">A different action can be reasonable under a different opponent model. No result or opponent cards are supplied here.</div></div></div>
<div class="card reading"><div class="label">Review questions</div><p id="questions"></p><div class="muted" id="unknowns"></div><details><summary>Prior public actions</summary><pre id="history"></pre></details></div>
<div class="muted">Selected examples, with evidence tiers disclosed. This review does not establish Ivey's overall strategy or a population accuracy rate.</div>
<script>
const rows=ROWS;const $=id=>document.getElementById(id);let revealed=false;
const number=x=>Number(x).toLocaleString('en-US');
function action(a){return a.action.toUpperCase()+(a.action==='raise'?' to '+number(a.amount):'')}
function card(c){return c[0]+({c:'♣',d:'♦',h:'♥',s:'♠'}[c[1]]||c[1])}
rows.forEach((r,i)=>{let o=document.createElement('option');o.value=i;o.textContent=(i+1)+'. '+r.hand_id+' · '+r.visible_facts.street;$('pick').append(o)});
function draw(){let r=rows[Number($('pick').value)],f=r.visible_facts;
$('context').replaceChildren();let link=document.createElement('a');link.href=r.source;link.target='_blank';link.rel='noreferrer';link.textContent='Source at this decision';$('context').append(link,document.createTextNode(' · '+f.position+' · '+r.format));
$('cards').textContent='Hero '+f.hole_cards.map(card).join(' ')+'  |  Board '+(f.board.map(card).join(' ')||'not dealt');
$('facts').replaceChildren();for(let [label,v] of [['Pot',number(f.pot)],['To call',number(f.to_call)],['Price',(100*f.pot_odds).toFixed(1)+'%'],['Active players',f.players_active]]){let e=document.createElement('div'),l=document.createElement('div'),t=document.createElement('strong');l.className='label';l.textContent=label;t.textContent=v;e.append(l,t);$('facts').append(e)}
$('tier').textContent='Evidence: '+r.evidence_tier.replaceAll('_',' ');$('bot').textContent=action(r.bot);$('reason').textContent=r.bot.diagnostics?.reason||'No diagnostic supplied';$('mix').replaceChildren();
for(let a of ['fold','check','call','raise']){let p=r.bot.probabilities?.[a];if(p===undefined)continue;let e=document.createElement('div');e.className='barrow';let n=document.createElement('span');n.textContent=a;let t=document.createElement('div');t.className='track';let b=document.createElement('div');b.className='fill';b.style.width=(100*p)+'%';t.append(b);let v=document.createElement('span');v.textContent=(100*p).toFixed(0)+'%';e.append(n,t,v);$('mix').append(e)}
$('ivey').textContent=revealed?action(r.recorded_ivey_action):'Hidden for blind review';$('reveal').textContent=revealed?'Hide Ivey’s move':'Reveal Ivey’s move';
$('sizing').textContent=revealed&&r.ivey_sizing?'Street-total target; '+number(r.ivey_sizing.extra_chips)+' extra chips.':'';
$('questions').textContent=revealed?r.review_hypotheses_not_verdicts.join(' '):'Before revealing the recorded move, consider the plausible value and bluff ranges, the price, alternative sizes, and which opponent reads are missing.';
$('unknowns').textContent='Unknown: '+r.unknowns.join('; ')+(r.source_limitations?.length?'. Source limitations: '+r.source_limitations.join(' '):'');
$('history').textContent=f.prior_public_actions.map(x=>[x.street,x.player||x.position||'actor',x.action,x.amount!==undefined?number(x.amount):''].join(' ')).join('\\n');}
$('pick').onchange=()=>{revealed=false;draw()};$('reveal').onclick=()=>{revealed=!revealed;draw()};draw();
</script></body></html>'''.replace("ROWS", rows)
(ROOT / "reports/qualitative-ivey.html").write_text(page)
