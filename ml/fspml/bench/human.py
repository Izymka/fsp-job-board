"""Экспертная разметка: выгрузка слепой выборки пар в автономную HTML-страницу и импорт результатов.

Все эксперты размечают одну и ту же выборку (фиксированный seed) — так считается согласие
экспертов между собой, а затем согласие LLM-асессора с экспертами. Выборка стратифицирована по
метке LLM (если она уже есть), чтобы в ней были и сильные, и слабые пары; контрольные пары
(другая специализация, ответ 0) проверяют внимательность. Какая система нашла пару, эксперт не видит.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .build import BENCH_DIR, DATA, load_jsonl
from .judge import aggregate
from .rubric import LABELS, RUBRIC, RUBRIC_VERSION

LABEL_DIR = BENCH_DIR / "label"


def sample_pairs(n: int = 160, n_control: int = 10, seed: int = 7, data: Path = DATA) -> list[dict]:
    pairs = load_jsonl(data / "pairs.jsonl")
    rng = random.Random(seed)
    llm = aggregate(load_jsonl(data / "judgments_llm.jsonl"), ["claude-opus-5-5"])
    main = [p for p in pairs if p["kind"] != "control"]
    controls = [p for p in pairs if p["kind"] == "control"]
    chosen: list[dict] = []
    if llm:
        strata: dict[int, list[dict]] = {}
        for p in main:
            if p["pair_id"] in llm:
                strata.setdefault(llm[p["pair_id"]], []).append(p)
        per = (n - n_control) // max(1, len(strata))
        for _, items in sorted(strata.items()):
            chosen += rng.sample(items, min(per, len(items)))
        rest = [p for p in main if p not in chosen]
        chosen += rng.sample(rest, max(0, n - n_control - len(chosen)))
    else:
        chosen = rng.sample(main, min(n - n_control, len(main)))
    chosen += rng.sample(controls, min(n_control, len(controls)))
    # группируем по вакансии: эксперт читает вакансию один раз и оценивает несколько кандидатов
    rng.shuffle(chosen)
    order = {nid: i for i, nid in enumerate(dict.fromkeys(p["need_id"] for p in chosen))}
    chosen.sort(key=lambda p: order[p["need_id"]])
    return chosen


def export_html(n: int = 160, out: Path | None = None, data: Path = DATA) -> Path:
    needs = {r["need_id"]: r for r in load_jsonl(data / "needs.jsonl")}
    cands = {r["cand_id"]: r for r in load_jsonl(data / "candidates.jsonl")}
    # Набор фиксируется при первой выгрузке: все эксперты (в том числе приглашённые позже)
    # размечают одни и те же пары, иначе нельзя посчитать их согласие.
    frozen = LABEL_DIR / "sample.json"
    by_id = {p["pair_id"]: p for p in load_jsonl(data / "pairs.jsonl")}
    if frozen.exists():
        sample = [by_id[pid] for pid in json.loads(frozen.read_text(encoding="utf-8"))]
    else:
        sample = sample_pairs(n, data=data)
        frozen.parent.mkdir(parents=True, exist_ok=True)
        frozen.write_text(json.dumps([p["pair_id"] for p in sample]), encoding="utf-8")
    items = [
        {
            "pair_id": p["pair_id"],
            "need_title": needs[p["need_id"]]["title"],
            "need": needs[p["need_id"]]["text"],
            "cand": cands[p["cand_id"]]["text"],
        }
        for p in sample
    ]
    payload = {
        "set_id": f"{RUBRIC_VERSION}-{len(items)}",
        "rubric": RUBRIC,
        "labels": {str(k): v for k, v in LABELS.items()},
        "items": items,
    }
    out = out or LABEL_DIR / "label.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out.write_text(HTML.replace("__DATA__", data_json), encoding="utf-8")
    return out


def import_results(files: list[Path], data: Path = DATA) -> dict:
    """Импорт JSON, скачанных со страницы разметки → judgments_human.jsonl (без дублей)."""
    out_path = data / "judgments_human.jsonl"
    existing = {(r["pair_id"], r["annotator"]) for r in load_jsonl(out_path)}
    added = 0
    with out_path.open("a", encoding="utf-8") as fh:
        for f in files:
            obj = json.loads(Path(f).read_text(encoding="utf-8"))
            who = obj["annotator"].strip()
            for pid, rec in obj["labels"].items():
                if (pid, who) in existing or rec.get("label") is None:
                    continue
                fh.write(
                    json.dumps(
                        {
                            "pair_id": pid,
                            "annotator": who,
                            "label": int(rec["label"]),
                            "comment": rec.get("comment", ""),
                            "set_id": obj.get("set_id"),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                existing.add((pid, who))
                added += 1
    return {"added": added, "total": len(existing)}


HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Разметка пар</title>
<style>
:root{--bg:#f6f6f8;--card:#fff;--ink:#1b1c21;--muted:#6b6d76;--line:#e3e3e8;--primary:#402fff;--primary-soft:#ecebff;--danger:#ec1d35}
@media (prefers-color-scheme: dark){:root{--bg:#141519;--card:#1d1e24;--ink:#ececf1;--muted:#9a9ca6;--line:#2c2d35;--primary:#8d84ff;--primary-soft:#26244a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header b{font-size:16px}.bar{flex:1;min-width:120px;height:6px;background:var(--line);border-radius:3px;overflow:hidden}.bar i{display:block;height:100%;background:var(--primary)}
input,textarea,button{font:inherit;color:inherit}input[type=text]{border:1px solid var(--line);background:var(--bg);border-radius:8px;padding:6px 10px}
button{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:8px 12px;cursor:pointer}button:hover{border-color:var(--primary)}
button.primary{background:var(--primary);border-color:var(--primary);color:#fff}
main{max-width:1200px;margin:0 auto;padding:16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:820px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;white-space:pre-wrap;overflow-wrap:anywhere}
.card h3{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.labels{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:16px 0}@media (max-width:620px){.labels{grid-template-columns:1fr 1fr}}
.labels button{text-align:left;padding:10px}.labels button.on{background:var(--primary-soft);border-color:var(--primary)}
.labels button kbd{font-weight:700;color:var(--primary);margin-right:6px}
textarea{width:100%;min-height:44px;border:1px solid var(--line);background:var(--bg);border-radius:8px;padding:8px}
details{margin-top:16px}details pre{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.nav{display:flex;gap:8px;justify-content:space-between;margin-top:12px}.muted{color:var(--muted);font-size:13px}
</style>
</head>
<body>
<header>
  <b>Разметка «вакансия — кандидат»</b>
  <label class="muted">Эксперт: <input id="who" type="text" placeholder="имя или инициалы" size="14"></label>
  <span id="count" class="muted"></span><div class="bar"><i id="prog"></i></div>
  <button id="dl" class="primary">Скачать результаты</button>
</header>
<main>
  <p id="warn" style="display:none;border:1px solid var(--danger);border-radius:8px;padding:8px 12px;color:var(--danger)">Этот браузер не сохраняет прогресс для файлов с диска. Не закрывайте вкладку и периодически нажимайте «Скачать результаты». Лучше открыть страницу в Chrome, Edge, Firefox или Яндекс Браузере.</p>
  <p id="done" style="display:none;border:1px solid var(--primary);border-radius:8px;padding:8px 12px;background:var(--primary-soft)">Все пары оценены. Нажмите «Скачать результаты» и отправьте файл организатору.</p>
  <p class="muted">Клавиши: <b>0–3</b> — оценка и переход к следующей паре, <b>←/→</b> — навигация. Прогресс сохраняется в браузере.</p>
  <div class="grid"><div class="card" id="need"></div><div class="card" id="cand"></div></div>
  <div class="labels" id="labels"></div>
  <textarea id="comment" placeholder="Комментарий (необязательно): что повлияло на оценку"></textarea>
  <div class="nav"><button id="prev">← Назад</button><span id="pos" class="muted"></span><button id="next">Дальше →</button></div>
  <details><summary>Рубрика</summary><pre id="rubric"></pre></details>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
let who = '', state = {labels:{}}, i = 0;
const key = () => 'fsp-label:' + D.set_id + ':' + who;
let storageOk = true;
try{ localStorage.setItem('fsp-label:test','1'); localStorage.removeItem('fsp-label:test') }catch(e){ storageOk = false }
if (!storageOk) document.getElementById('warn').style.display = 'block';
function load(){ try{ state = JSON.parse(localStorage.getItem(key())) || {labels:{}} }catch(e){ state = {labels:{}} } }
function save(){ try{ localStorage.setItem(key(), JSON.stringify(state)) }catch(e){} }
try{ who = localStorage.getItem('fsp-label:who') || '' }catch(e){}
$('who').value = who; load();
$('who').addEventListener('change', e => { who = e.target.value.trim(); try{localStorage.setItem('fsp-label:who', who)}catch(_){}; load(); i = firstTodo(); render(); });
$('rubric').textContent = D.rubric;
function firstTodo(){ const k = D.items.findIndex(it => !(state.labels[it.pair_id]||{}).hasOwnProperty('label')); return k < 0 ? 0 : k; }
function render(){
  const it = D.items[i], rec = state.labels[it.pair_id] || {};
  $('need').innerHTML = '<h3>Вакансия</h3>'; $('need').append(document.createTextNode(it.need));
  $('cand').innerHTML = '<h3>Кандидат</h3>'; $('cand').append(document.createTextNode(it.cand));
  const box = $('labels'); box.innerHTML = '';
  for (const k of ['3','2','1','0']) {
    const b = document.createElement('button');
    b.innerHTML = '<kbd>' + k + '</kbd>'; b.append(document.createTextNode(D.labels[k]));
    if (rec.label === +k) b.className = 'on';
    b.onclick = () => setLabel(+k); box.append(b);
  }
  $('comment').value = rec.comment || '';
  const done = Object.values(state.labels).filter(r => r.label !== undefined).length;
  $('count').textContent = done + ' / ' + D.items.length;
  $('prog').style.width = (100 * done / D.items.length) + '%';
  $('pos').textContent = 'Пара ' + (i + 1) + ' из ' + D.items.length;
  $('done').style.display = done === D.items.length ? 'block' : 'none';
  window.scrollTo({top:0});
}
function setLabel(k){
  if (!who) { alert('Укажите имя эксперта вверху страницы'); $('who').focus(); return; }
  const it = D.items[i];
  state.labels[it.pair_id] = {label:k, comment:$('comment').value.trim()}; save();
  if (i < D.items.length - 1) i++; render();
}
$('comment').addEventListener('input', () => { const it = D.items[i]; const r = state.labels[it.pair_id] || {}; r.comment = $('comment').value.trim(); state.labels[it.pair_id] = r; save(); });
$('prev').onclick = () => { if (i > 0) { i--; render(); } };
$('next').onclick = () => { if (i < D.items.length - 1) { i++; render(); } };
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
  if ('0123'.includes(e.key) && e.key.length === 1) setLabel(+e.key);
  else if (e.key === 'ArrowLeft') $('prev').click();
  else if (e.key === 'ArrowRight') $('next').click();
});
$('dl').onclick = () => {
  if (!who) { alert('Укажите имя эксперта'); return; }
  const blob = new Blob([JSON.stringify({set_id:D.set_id, annotator:who, labels:state.labels}, null, 1)], {type:'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'labels-' + who.replace(/[^\p{L}\p{N}]+/gu,'_') + '.json'; a.click();
};
i = firstTodo(); render();
</script>
</body>
</html>
"""
