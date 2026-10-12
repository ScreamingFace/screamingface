import ast, pathlib, re, subprocess, sys, collections
root=pathlib.Path('/Users/junior/workspace/screamingface')
src=root/'packages/url4/src/url4'
exports={}
for p in src.rglob('__init__.py'):
    t=ast.parse(p.read_text())
    for n in t.body:
        if isinstance(n,ast.Assign) and any(getattr(x,'id',None)=='__all__' for x in n.targets):
            mod='url4.'+'.'.join(p.relative_to(src).parts[:-1]) if len(p.relative_to(src).parts)>1 else 'url4'
            for e in n.value.elts: exports.setdefault(e.value,[]).append(mod.rstrip('.'))
def corpus(paths, exts=('.py','.ipynb','.md')):
    out=[]
    for base in paths:
        b=root/base
        files=[b] if b.is_file() else [f for f in b.rglob('*') if f.suffix in exts and not any(x in f.parts for x in('node_modules','.venv','.git','__pycache__'))]
        for f in files:
            try: out.append((str(f),f.read_text()))
            except: pass
    return out
cons=corpus(['apps/screamingface-engine/src','apps/screamingface-studio','packages/screamingface','url4_playground.py'])
engtests=corpus(['apps/screamingface-engine/tests'])
ownsrc=corpus(['packages/url4/src'])
owntests=corpus(['packages/url4/tests','packages/url4/examples'])
def cnt(c,s,exclude=None):
    r=re.compile(r'\b'+re.escape(s)+r'\b'); return sum(len(r.findall(t)) for f,t in c if not (exclude and exclude in f))
rows=[]
for s,m in sorted(exports.items()):
    a=cnt(cons,s); b=cnt(engtests,s); c=cnt(owntests,s)
    # own-src uses outside __init__/definition: count files
    d=sum(1 for f,t in ownsrc if re.search(r'\b'+re.escape(s)+r'\b',t))
    rows.append((s,m[0],a,b,c,d))
print("symbol|module|consumer_src|engine_tests|url4_tests+examples|url4_src_files")
for r in rows:
    print("|".join(map(str,r)))
