import subprocess,collections,ast,sys
files=subprocess.run(r"grep -rlE '^\s*(from|import) url4' apps packages/screamingface url4_playground.py --include=*.py",shell=True,capture_output=True,text=True).stdout.split()
files=[f for f in files if '/.venv/' not in f and 'node_modules' not in f]
sys.path.insert(0,'packages/url4/src')
import url4
al=set(url4.__all__)
def grp(f):
    p=f.split('/')
    if f.startswith('apps'): return p[1]+('/test' if 'tests' in p else '/src')
    if f.startswith('packages'): return p[1]+('/test' if 'tests' in p else '/src')
    return 'playground'
priv=collections.defaultdict(list);nonall=collections.defaultdict(set);deep=collections.defaultdict(collections.Counter)
for f in files:
    t=ast.parse(open(f).read());g=grp(f)
    for n in ast.walk(t):
        if isinstance(n,ast.ImportFrom) and n.module and (n.module=='url4' or n.module.startswith('url4.')):
            if any(p.startswith('_') for p in n.module.split('.')): priv[g].append((f,n.lineno,n.module))
            if n.module=='url4':
                for a in n.names:
                    if a.name not in al: nonall[g].add(a.name)
            else:
                deep[g][n.module]+=1
                for a in n.names:
                    if a.name.startswith('_'): priv[g].append((f,n.lineno,n.module+'.'+a.name))
print(len(files),"files",collections.Counter(grp(f) for f in files))
for g,v in priv.items(): print("PRIVATE",g,len(v),v[:6])
for g,v in nonall.items(): print("NON-ALL top-level",g,sorted(v))
print("__all__ size",len(al))
for g,v in deep.items(): print("DEEP",g,len(v),sum(v.values()),v.most_common(12))
