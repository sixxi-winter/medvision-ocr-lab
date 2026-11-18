const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let chosenFile = null;
let analysis = null;
let activeResult = 0;

const input = $('#fileInput');
const dropzone = $('#dropzone');
const preview = $('#imagePreview');
const analyzeButton = $('#analyzeButton');

function setFile(file) {
  if (!file) return;
  chosenFile = file;
  preview.src = URL.createObjectURL(file);
  dropzone.classList.add('has-image');
  analyzeButton.disabled = false;
}

input.addEventListener('change', () => setFile(input.files[0]));
['dragenter','dragover'].forEach(e => dropzone.addEventListener(e, ev => {ev.preventDefault(); dropzone.classList.add('drag')}));
['dragleave','drop'].forEach(e => dropzone.addEventListener(e, ev => {ev.preventDefault(); dropzone.classList.remove('drag')}));
dropzone.addEventListener('drop', e => setFile(e.dataTransfer.files[0]));
$('#removeImage').addEventListener('click', e => {e.preventDefault(); chosenFile=null; input.value=''; preview.src=''; dropzone.classList.remove('has-image'); analyzeButton.disabled=true});

$$('.preset').forEach(btn => btn.addEventListener('click', () => {
  $$('.preset').forEach(x => x.classList.remove('active')); btn.classList.add('active');
  const all = btn.dataset.preset === 'compare';
  $$('#variantGrid input').forEach((x,i) => x.checked = all || i === 0);
}));

function escapeHtml(s='') {return s.replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}

analyzeButton.addEventListener('click', async () => {
  const selected = $$('#variantGrid input:checked').map(x => x.value);
  if (!chosenFile || !selected.length) return alert('이미지와 전처리를 선택해 주세요.');
  $('#loading').classList.remove('hidden'); $('#results').classList.add('hidden');
  analyzeButton.disabled = true; $('#loading').scrollIntoView({behavior:'smooth',block:'center'});
  const data = new FormData();
  data.append('image', chosenFile); data.append('ground_truth', $('#groundTruth').value); data.append('selected_variants', selected.join(','));
  try {
    const response = await fetch('/api/jobs', {method:'POST',body:data});
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || '분석에 실패했습니다.');
    analysis = await waitForJob(body.job_id); activeResult = 0; renderResults();
  } catch (error) { alert(error.message); }
  finally { $('#loading').classList.add('hidden'); analyzeButton.disabled = false; }
});

async function waitForJob(jobId) {
  while (true) {
    await new Promise(resolve => setTimeout(resolve, 1500));
    const response = await fetch(`/api/jobs/${jobId}`);
    const job = await response.json();
    if (!response.ok) throw new Error(job.detail || '작업 상태를 불러오지 못했습니다.');
    if (job.status === 'failed') throw new Error(job.error || 'OCR 분석에 실패했습니다.');
    if (job.status === 'complete') return job.result;
    const label = job.current ? `${job.current} 처리 중 · ${job.progress}%` : '분석 순서를 기다리고 있어요.';
    $('#loadingText').textContent = label;
  }
}

function renderResults() {
  const best = analysis.results[0];
  $('#summaryStrip').innerHTML = `
    <div class="metric"><span>최고 전처리</span><strong>${best.variant}</strong></div>
    <div class="metric"><span>평균 신뢰도</span><strong>${(best.confidence*100).toFixed(1)}%</strong></div>
    <div class="metric"><span>인식 영역</span><strong>${best.count}개</strong></div>
    <div class="metric"><span>${best.cer === null ? '처리 시간' : 'CER'}</span><strong>${best.cer === null ? best.seconds+'초' : (best.cer*100).toFixed(1)+'%'}</strong></div>`;
  $('#resultTabs').innerHTML = analysis.results.map((r,i) => `<button class="result-tab ${i===activeResult?'active':''}" data-index="${i}">${r.variant} · ${r.cer===null?(r.confidence*100).toFixed(0)+'%':'CER '+(r.cer*100).toFixed(1)+'%'}</button>`).join('');
  $$('.result-tab').forEach(x => x.addEventListener('click', () => {activeResult=Number(x.dataset.index); renderResults()}));
  const r = analysis.results[activeResult];
  const chips = [...r.fields.medicine_names.map(x=>['이름 후보',x]),...r.fields.doses.map(x=>['용량',x]),...r.fields.manufacturers.map(x=>['제조사',x])];
  $('#resultDetail').innerHTML = `
    <div class="preview-card"><div class="card-heading"><b>${r.variant} 이미지</b><span>${analysis.processed_size.width}×${analysis.processed_size.height}</span></div><img src="${r.preview}" alt="${r.variant} 전처리 결과"></div>
    <div class="text-card"><div class="card-heading"><b>인식 문구</b><span>${r.seconds}초 · ${r.count}개</span></div><div class="ocr-text">${escapeHtml(r.text)||'인식된 문구가 없습니다.'}</div><div class="chips">${chips.length?chips.map(c=>`<span class="chip">${c[0]} · ${escapeHtml(c[1])}</span>`).join(''):'<span class="chip empty-chip">추출된 필드 후보 없음</span>'}</div></div>`;
  $('#results').classList.remove('hidden'); $('#results').scrollIntoView({behavior:'smooth',block:'start'});
}

$('#downloadCsv').addEventListener('click', () => {
  if (!analysis) return;
  const q = s => `"${String(s??'').replaceAll('"','""')}"`;
  const rows = [['variant','confidence','count','seconds','cer','text'],...analysis.results.map(r=>[r.variant,r.confidence,r.count,r.seconds,r.cer??'',r.text.replaceAll('\n',' | ')])];
  const blob = new Blob(['\ufeff'+rows.map(row=>row.map(q).join(',')).join('\n')],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='medicine-ocr-results.csv';a.click();URL.revokeObjectURL(a.href);
});

