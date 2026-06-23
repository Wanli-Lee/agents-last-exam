import json, os, collections

BASE = json.load(open('caseview/data/cases_full.json'))
OUT_DIR = 'caseview/data/trajectories'
os.makedirs(OUT_DIR, exist_ok=True)

OBS_CAP = 1400      # per-observation char cap
ARG_CAP = 900       # per tool-arg value cap
REASON_CAP = 1200   # reasoning per step cap

def cap(s, n):
    s = '' if s is None else str(s)
    return s if len(s) <= n else s[:n] + f' …[+{len(s)-n}字符]'

def slim_args(name, args):
    """Return list of (key, value-string) for display, keeping the meaningful ones."""
    if not isinstance(args, dict):
        return [('', cap(json.dumps(args, ensure_ascii=False), ARG_CAP))]
    out = []
    for k, v in args.items():
        if isinstance(v, (dict, list)):
            vs = json.dumps(v, ensure_ascii=False)
        else:
            vs = str(v)
        # content/command/code get a bigger budget; flags stay short
        budget = ARG_CAP if k in ('content', 'command', 'code', 'task', 'text', 'patch', 'old_str', 'new_str') else 220
        out.append((k, cap(vs, budget)))
    return out

def obs_text(ob):
    """Flatten an observation dict into displayable text + error flag."""
    if ob is None:
        return None, False
    if isinstance(ob, str):
        return cap(ob, OBS_CAP), False
    if isinstance(ob, dict):
        err = bool(ob.get('error'))
        parts = []
        for r in ob.get('results') or []:
            if r.get('is_error'):
                err = True
            c = r.get('content')
            if isinstance(c, list):
                for blk in c:
                    if isinstance(blk, dict):
                        if blk.get('text'):
                            parts.append(blk['text'])
                        elif blk.get('image'):
                            parts.append('[image]')
                        else:
                            parts.append(json.dumps(blk, ensure_ascii=False))
                    else:
                        parts.append(str(blk))
            elif c is not None:
                parts.append(str(c))
        if ob.get('error') and not parts:
            parts.append(str(ob['error']))
        txt = '\n'.join(parts).strip()
        return cap(txt, OBS_CAP), err
    return cap(json.dumps(ob, ensure_ascii=False), OBS_CAP), False

def condense(traj_path):
    d = json.load(open(traj_path))
    steps_out = []
    tool_tally = collections.Counter()
    for s in d.get('steps', []):
        src = s.get('source')
        tcs = s.get('tool_calls') or []
        reasoning = s.get('reasoning')
        obs, err = obs_text(s.get('observation'))
        msg = s.get('message')
        # skip totally empty noise steps (no reasoning, no tools, no obs, no msg)
        if not tcs and not reasoning and not obs and not msg:
            continue
        calls = []
        for tc in tcs:
            tool_tally[tc['name']] += 1
            calls.append({'name': tc['name'], 'args': slim_args(tc['name'], tc.get('arguments'))})
        steps_out.append({
            'id': s.get('step_id'),
            'src': src,
            'reasoning': cap(reasoning, REASON_CAP) if reasoning else None,
            'message': cap(msg, OBS_CAP) if (msg and src == 'agent') else None,
            'calls': calls,
            'obs': obs,
            'err': err,
            'cost': (s.get('metrics') or {}).get('cost_usd'),
            'in_tok': (s.get('metrics') or {}).get('input_tokens'),
            'out_tok': (s.get('metrics') or {}).get('output_tokens'),
        })
    return {
        'task_id': d.get('task_path'),
        'n_steps': len(d.get('steps', [])),
        'tool_tally': dict(tool_tally.most_common()),
        'final_metrics': d.get('final_metrics'),
        'steps': steps_out,
    }

index = {}
ok = 0
for c in BASE:
    tid = c['task_id']
    safe = tid.replace('/', '__')
    rd = c.get('result_dir')
    if not rd:
        index[tid] = None
        continue
    tp = os.path.join('repo', rd, 'trajectory.json')
    if not os.path.exists(tp):
        index[tid] = None
        continue
    cond = condense(tp)
    cond['task_id'] = tid
    json.dump(cond, open(f'{OUT_DIR}/{safe}.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    index[tid] = safe
    ok += 1

json.dump(index, open(f'{OUT_DIR}/_index.json', 'w'), ensure_ascii=False)
print(f'wrote {ok} condensed trajectories to {OUT_DIR}/')
# size report
import glob
sizes = [os.path.getsize(p) for p in glob.glob(f'{OUT_DIR}/*.json')]
print(f'total size: {sum(sizes)/1024:.0f} KB, max single: {max(sizes)/1024:.0f} KB, avg: {sum(sizes)/len(sizes)/1024:.0f} KB')
