import json, os

BASE = json.load(open('caseview/data/cases_full.json'))
OUT_DIR = 'caseview/data/artifacts'
os.makedirs(OUT_DIR, exist_ok=True)

TEXT_EXT = {'.json','.csv','.py','.txt','.md','.tsv','.dat','.r','.sh','.in','.inp',
            '.xml','.html','.log','.fasta','.cpp','.urdf','.yaml','.yml','.toml',
            '.js','.c','.h','.bib','.tex','.nml','.cfg','.ini','.svg','.bpmn20.xml'}
IMG_EXT = {'.png','.jpg','.jpeg','.gif','.webp'}
MAX_INLINE = 200_000   # 200KB cap for inlining text

def lang_of(fn):
    fl = fn.lower()
    for ext, lang in [('.py','python'),('.json','json'),('.csv','csv'),('.tsv','tsv'),
                      ('.md','markdown'),('.sh','bash'),('.r','r'),('.xml','xml'),
                      ('.html','html'),('.yaml','yaml'),('.yml','yaml'),('.js','javascript'),
                      ('.cpp','cpp'),('.c','c'),('.svg','xml'),('.toml','toml'),('.dat','text'),
                      ('.txt','text'),('.log','text'),('.fasta','text'),('.urdf','xml'),
                      ('.nml','text'),('.inp','text'),('.in','text')]:
        if fl.endswith(ext):
            return lang
    return 'text'

def classify(od, fn):
    """Return dict describing one declared deliverable."""
    base_name = fn[:-len('.unreadable')] if fn.endswith('.unreadable') else fn
    rec = {'name': base_name}
    # locate the actual file
    cand = [os.path.join(od, fn), os.path.join(od, base_name),
            os.path.join(od, base_name + '.unreadable')]
    path = next((p for p in cand if os.path.exists(p)), None)
    ext = os.path.splitext(base_name)[1].lower()
    rec['ext'] = ext

    if fn.endswith('.unreadable') or (path and path.endswith('.unreadable')):
        rec['kind'] = 'unreadable'
        rec['size'] = os.path.getsize(path) if path else 0
        return rec
    if path is None:
        rec['kind'] = 'missing'; rec['size'] = 0
        return rec

    sz = os.path.getsize(path)
    rec['size'] = sz
    if ext in IMG_EXT:
        rec['kind'] = 'image'
        return rec
    if ext in TEXT_EXT or any(fn.lower().endswith(e) for e in TEXT_EXT):
        if sz > MAX_INLINE:
            rec['kind'] = 'text_truncated'
            rec['lang'] = lang_of(base_name)
            try:
                with open(path, 'r', errors='replace') as f:
                    rec['content'] = f.read(MAX_INLINE)
            except Exception as e:
                rec['kind'] = 'binary'; rec['err'] = str(e)
            return rec
        try:
            with open(path, 'r', errors='replace') as f:
                txt = f.read()
            # guard: if it has many NUL bytes it's actually binary
            if '\x00' in txt[:1000]:
                rec['kind'] = 'binary'
            else:
                rec['kind'] = 'text'
                rec['lang'] = lang_of(base_name)
                rec['content'] = txt
        except Exception:
            rec['kind'] = 'binary'
        return rec
    rec['kind'] = 'binary'
    return rec

index = {}
ok = 0
for c in BASE:
    tid = c['task_id']; safe = tid.replace('/', '__')
    rd = c.get('result_dir')
    ofs = c.get('output_files') or []
    if not rd or not ofs:
        index[tid] = None
        continue
    od = os.path.join('repo', rd, 'output')
    recs = [classify(od, fn) for fn in ofs]
    out = {'task_id': tid, 'output_dir': os.path.join(rd, 'output'), 'files': recs}
    json.dump(out, open(f'{OUT_DIR}/{safe}.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    index[tid] = safe
    ok += 1

json.dump(index, open(f'{OUT_DIR}/_index.json', 'w'), ensure_ascii=False)
print(f'wrote {ok} artifact bundles')

# size + kind report
import glob, collections
sizes = [os.path.getsize(p) for p in glob.glob(f'{OUT_DIR}/*.json') if not p.endswith('_index.json')]
kinds = collections.Counter()
for p in glob.glob(f'{OUT_DIR}/*.json'):
    if p.endswith('_index.json'): continue
    for f in json.load(open(p))['files']:
        kinds[f['kind']] += 1
print(f'total artifact-bundle size: {sum(sizes)/1024:.0f} KB, max single: {max(sizes)/1024:.0f} KB')
print('deliverable kinds:', dict(kinds))
