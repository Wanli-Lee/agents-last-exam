import json, sys, html

# Usage: python3 merge_translations.py <workflow_result.json>
# workflow_result.json = the {"count":N,"translations":[...]} object dumped from the workflow result

def unescape(s):
    if not s: return s
    # agents sometimes HTML-escape & < > ; undo so frontend esc() handles it once
    s = html.unescape(s)
    # one agent wrote literal backslash-n instead of real newlines; fix only if
    # the field has literal \n sequences but essentially no real newlines
    if '\\n' in s and s.count('\n') < 3:
        s = s.replace('\\n', '\n')
    return s

def main(path):
    wf = json.load(open(path))
    trans = wf.get('translations') or wf  # accept either wrapper or bare list
    if isinstance(trans, dict) and 'translations' in trans:
        trans = trans['translations']
    tmap = {t['task_id']: t for t in trans}
    print(f"翻译条目: {len(tmap)}")

    base = json.load(open('caseview/data/cases_full.json'))
    filled_p = filled_e = 0
    missing = []
    for c in base:
        t = tmap.get(c['task_id'])
        if not t:
            if c.get('task_prompt') or c.get('evaluation'):
                missing.append(c['task_id'])
            continue
        pcn = unescape(t.get('task_prompt_cn') or '').strip()
        ecn = unescape(t.get('evaluation_cn') or '').strip()
        if pcn:
            c['task_prompt_cn'] = pcn; filled_p += 1
        if ecn:
            c['evaluation_cn'] = ecn; filled_e += 1

    json.dump(base, open('caseview/data/cases_full.json','w'), ensure_ascii=False, indent=1)
    print(f"回填 task_prompt_cn: {filled_p}, evaluation_cn: {filled_e}")
    if missing:
        print(f"未翻译(缺失): {len(missing)} -> {missing[:5]}")
    # newline fidelity spot-check
    print("\n=== 换行保真抽查 ===")
    for c in base[:3]:
        if c.get('task_prompt') and c.get('task_prompt_cn'):
            print(f"  {c['task_id']}: 原文 {c['task_prompt'].count(chr(10))} 换行 / 译文 {c['task_prompt_cn'].count(chr(10))} 换行")

if __name__ == '__main__':
    main(sys.argv[1])
