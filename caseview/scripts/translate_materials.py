import json, os, sys, time, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

API="http://localhost:4200/v1/chat/completions"
KEY="sk-litellm-azure-direct"
MODEL="gpt-5.5"
os.environ['no_proxy']='localhost,127.0.0.1'

SYS=(
"你是专业技术文档翻译。把用户给的英文任务材料翻译成简体中文。严格遵守:\n"
"1. 完整保留原文的换行结构——原文有几个换行就有几个换行,列表项、空行、缩进层级都要对应保留。\n"
"2. 专业词汇、技术术语、库名/函数名/文件名/格式名/字段名、缩写(如 CVRP, VRPLIB, Tier, LSM, Black-Scholes, JSON, npy, delta, vega, uv, pytest)保持英文原样,不要翻译也不要加引号。\n"
"3. Markdown 标记(#、-、*、`代码`、```代码块```、| 表格 |)原样保留,只翻译其中的自然语言。\n"
"4. 代码、命令、路径、URL、数学公式原样保留不翻译。\n"
"5. 只输出翻译结果本身,不要加任何前言、说明、'翻译如下'之类的话,也不要用代码块包裹整体输出。\n"
"6. 翻译要通顺专业,符合中文技术写作习惯。"
)

def translate(text, retries=4):
    body=json.dumps({"model":MODEL,"messages":[
        {"role":"system","content":SYS},
        {"role":"user","content":text}],
        "temperature":0}).encode()
    last=None
    for i in range(retries):
        try:
            req=urllib.request.Request(API,data=body,headers={
                "Authorization":f"Bearer {KEY}","Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=180) as r:
                d=json.loads(r.read())
            return d["choices"][0]["message"]["content"]
        except Exception as e:
            last=e; time.sleep(2*(i+1))
    raise last

if __name__=="__main__":
    mode=sys.argv[1] if len(sys.argv)>1 else "sample"
    base=json.load(open('caseview/data/cases_full.json'))
    cache_path='caseview/data/translations.json'
    cache=json.load(open(cache_path)) if os.path.exists(cache_path) else {}

    # build job list: (cache_key, text)
    jobs=[]
    def key(tid,field,text):
        h=hashlib.md5(text.encode()).hexdigest()[:8]
        return f"{tid}::{field}::{h}"
    for c in base:
        tid=c['task_id']
        for field in ('task_prompt','evaluation'):
            t=c.get(field)
            if not t: continue
            k=key(tid,field,t)
            if k in cache: continue
            jobs.append((k,tid,field,t))

    if mode=="sample":
        jobs=jobs[:3]
        print(f"SAMPLE: {len(jobs)} jobs")
    else:
        print(f"FULL: {len(jobs)} jobs to translate (cache has {len(cache)})")

    done=0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs={ex.submit(translate,t):(k,tid,field,t) for k,tid,field,t in jobs}
        for fut in as_completed(futs):
            k,tid,field,t=futs[fut]
            try:
                out=fut.result()
                cache[k]=out
                done+=1
                # save incrementally every 10
                if done%10==0:
                    json.dump(cache,open(cache_path,'w'),ensure_ascii=False,indent=1)
                    print(f"  {done}/{len(jobs)} ...")
            except Exception as e:
                print(f"  FAIL {tid}/{field}: {e}")
    json.dump(cache,open(cache_path,'w'),ensure_ascii=False,indent=1)
    print(f"done. cache total: {len(cache)}")

    if mode=="sample":
        for k,tid,field,t in jobs:
            print("\n"+"="*70)
            print(f"### {tid} / {field}")
            print("--- 原文换行数:",t.count(chr(10)),"译文换行数:",cache[k].count(chr(10)))
            print("--- 译文前 600 字 ---")
            print(cache[k][:600])
