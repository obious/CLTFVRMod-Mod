import json,os,re
listed={s['Path'] for s in json.load(open('../../../mod.json'))['Scripts']}
for root,_,fs in os.walk('.'):
    for f in fs:
        p=os.path.relpath(os.path.join(root,f)).replace(os.sep,'/')
        if p in listed: continue
        t=open(p,encoding='utf-8',errors='replace').read()
        refs=sorted(set(re.findall(r'\bTF2VR_\w+|\btf2vr_\w+',t)))
        print(f"{p}  [{len(t.splitlines())}]  {', '.join(refs) if refs else '-- none'}")
