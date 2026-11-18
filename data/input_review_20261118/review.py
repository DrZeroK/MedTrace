import ast, collections, copy, hashlib, json, math, re, sys, zipfile
from pathlib import Path
P=Path('/Users/zerok/Documents/GitHub/MedTrace')
O=Path(__file__).resolve().parent
sys.path.insert(0,str(P))
from data_pipeline import cmb_clin as cmb, typicalcase_dc as tc, quality
from medtrace.inputs import parse_case
from eval.perturb import apply_edit
def read(f): return json.loads(f.read_text())
def save(n,d): (O/n).write_text(json.dumps(d,ensure_ascii=False,indent=1)+'\n')
syn=next(P.glob('data/synthetic*/input_100_final.json'))
orig=read(syn); revised=copy.deepcopy(orig); changes=[]
fix={
'甲状腺受体抗体':'促甲状腺激素受体抗体（TRAb）','肺功能弥散量':'肺弥散量（原报告未注明检测方法）','动脉血气pH':'动脉血气分析示 pH','左侧胸膜线':'左侧可见脏层胸膜线','无肉眼血尿或其他':'无肉眼血尿或其他','高血糖高渗状态':'高渗高血糖状态','血糖42mmol/L':'血糖42mmol/L','实测血清渗透压':'实测血清渗透浓度','血清渗透压252':'血清渗透浓度252','尿渗透压420':'尿渗透浓度420','血红蛋白及':'血红蛋白及','双下肢肿胀，足':'双下肢肿胀，足','深部组织培养无结果':'未提供深部组织培养结果','血培养无结果':'未提供血培养结果','关节液混浊，白细胞':'关节液混浊，关节液白细胞','导管血培养':'经导管采血的血培养','外周及经导管采血的血培养':'外周静脉及经导管采血的血培养','急诊共氧测定碳氧血红蛋白':'急诊血液多波长共氧测定显示，碳氧血红蛋白占比为','静脉内血栓、压迫不完全':'静脉内血栓，受累静脉未能完全压闭','颈内动脉斑块及约70%狭窄':'颈内动脉斑块，管腔狭窄率约为70%','可见杵状改变':'可见杵状指','心电图示心房颤动、心室率约':'心电图示心房颤动，心室率约','ANA 1:640阳性':'抗核抗体（ANA）阳性，滴度为1:640','无明确外伤，无肉眼血尿':'无明确外伤，亦无肉眼血尿','否认服利尿药，但带来的复方降压药成分尚未核实':'自述未服用利尿药。患者携带的复方降压药成分尚未核实','既往病史、药物史、既往肾功能和贫血检查均未提供':'既往病史、用药史、历次肾功能及贫血检查结果均未提供','是否曾确诊房颤及是否使用抗凝药不详':'既往是否确诊房颤、是否使用抗凝药均不详','否认已知肝硬化':'患者否认既往被诊断为肝硬化','是否合并腹水感染及其他诱因需进一步排查':'有无腹水感染及其他诱因尚待排查','；不能根据':'。不能根据','初步判断为抗菌药相关腹泻':'初步考虑抗菌药相关腹泻','初步考虑妊娠期高血压相关严重并发症':'初步考虑子痫前期可能，伴重度范围血压升高','醒后全身肌痛':'被发现后诉全身肌痛','近12小时排尿困难':'近12小时排尿困难','口腔少量血疱':'口腔可见少数血疱'}
for c in revised:
 for s in c['sources']:
  a=t=s['content']
  for k,v in fix.items(): t=t.replace(k,v)
  t=t.replace('—','至') if '——' not in t else t
  t=re.sub(r'(?<=\d)(mmol/L|μmol/L|pg/mL|ng/L|mg/L|g/L|mmHg|mOsm/kg|L/min|mIU/L|IU/L|U/L|fL|µg/L|μg/L|pmol/L|mm/h|cm|mm|mL|kg|mV|℃|g)(?![A-Za-z])',r' \1',t)
  t=re.sub(r'(?<=\d)\s*×10\^(\d+)/L',r' × 10^\1/L',t)
  if t!=a: changes.append([c['case_id'],s['source_id'],a,t]);s['content']=t
  assert re.findall(r'\d+(?:\.\d+)?',a)==re.findall(r'\d+(?:\.\d+)?',t)
 assert parse_case(c,0).usable
save('input.json',revised);save('合成逐段修订.json',changes)
md=next(syn.parent.glob('入院资料100例.md')).read_text()
for _,_,a,b in changes:
 assert md.count(a)==1;md=md.replace(a,b)
(O/'入院资料100例_审校版.md').write_text(md)
# Compare the staged public sources with the actual input transformation for each record.
refs={};matches={}; counts={}; audit=[]; inventory=[]; routes=collections.defaultdict(set)
def hashb(x):return hashlib.sha256(x).hexdigest()
for dataset,raw in [('cmb_clin',O/'CMB-Clin-source.json'),('typicalcase_dc',P/'data/raw/cblue/TypicalCase-DC/TypicalCase-DC_train.jsonl')]:
 base=P/'data/standardized'/dataset; manifest=read(base/'manifest.json')
 assert hashb(raw.read_bytes())==manifest['raw_sha256']
 rows=read(raw) if dataset=='cmb_clin' else [json.loads(l) for l in raw.read_text().splitlines() if l.strip()]
 lookup={str(v['id']):v for v in rows}
 for r,c in zip(read(base/'references.json'),read(base/'cases.json'),strict=True):
  cid=c['case_id'];assert r['case_id']==cid;refs[cid]=r;v=lookup[str(r['origin']['item_id'])];out=[]
  if dataset=='cmb_clin':
   sec=cmb.split_sections(quality.scrub_pii(v['description'])[0])[0];seen=collections.Counter()
   for s in sec:
    key=s['slug'];seen[key]+=1;sid=cid+'-'+key+(str(seen[key]) if seen[key]>1 else '');out.append(dict(source_id=sid,content=cmb.correct_punctuation(sid,s['text'])))
  else:
   out=[dict(source_id=cid+'-'+k,content='\n'.join(lines)) for k,lines in tc.split_sections(quality.scrub_pii(v['text'])[0]).items()]
  matches[cid]=out==c['sources']
rules={
'否定范围待核':r'(?:否认|不伴|无)(?:明显|明确)?[^，,。；;\n]{1,16}[，,]\s*(?:糖尿病|高血压|恶心|呕吐|咳痰|寒战|胸痛|气促|腹泻|黑便|晕厥)(?:病史|史)?(?=[。，,；;、])',
'疑似指数丢失':r'[×xX]\s*10(?:9|12|6)\s*[/／]\s*[Ll]',
'血细胞计数量纲待核（须先确认标本）':r'(?<!网织)(?:RBC|红细胞)(?:计数)?\s*[:：]?\s*[1-9](?:\.\d+)?\s*[×xX]\s*10(?:\^?9|⁹)\s*[/／]\s*[Ll]',
'标点相邻':r'[，,。；;、][ \t]*[，,。；;、]',
'数值疑用句号或逗号作小数点':r'\d[。]\d\s*(?:mmol|μmol|mg|g/|℃|mmHg)',
'解剖位置矛盾':r'升结肠脾(?:区|曲)|降结肠肝曲',
'检查信息缺失易误读为阴性':r'(?:体格检查|辅助检查|检查检验)[：:\s]+无[。\n]?$',
'疑似字符损坏':r'[�\x00-\x08\x0b\x0c\x0e-\x1f]',
'药名或方案缩写待核':r'COIBx',
'异常分隔符':r'\d\s*[,，]\s*\d{1,2}\s*(?:mmol/L|mg/dL|mmHg|℃)',
}
rx={k:re.compile(v) for k,v in rules.items()}
data={}; kinds={}
def case(route,id,ss,kind):
 key=(str(id),hashb(json.dumps(ss,ensure_ascii=False,sort_keys=True).encode()));routes[key].add(route);data[key]=ss;kinds.setdefault(key,kind)
def walk(v,route,kind):
 if isinstance(v,list):return sum(walk(x,route,kind) for x in v)
 if not isinstance(v,dict):return 0
 if 'case_id'in v and isinstance(v.get('sources'),list) and all(isinstance(s,dict) and isinstance(s.get('content'),str) for s in v['sources']):
  case(route,v['case_id'],v['sources'],kind);return 1
 return sum(walk(x,route,kind) for x in v.values() if isinstance(x,(list,dict)))
for f in sorted(P.rglob('*.json')):
 if O in f.parents or '/.git/' in str(f) or '/raw/' in str(f) or '/reference_indexes/' in str(f):continue
 d=read(f);route=str(f.relative_to(P));n=walk(d,route,'病例 JSON'); 
 if n:inventory.append([route,n])
for z in P.glob('dist/**/*.zip'):
 with zipfile.ZipFile(z) as archive:
  for n in archive.namelist():
   if Path(n).name in ('input.json','input.example.json'):
    route=str(z.relative_to(P))+'!'+n;inventory.append([route,walk(json.loads(archive.read(n)),route,'打包副本')])
for f in sorted((P/'data/raw/cblue').rglob('*.json*')):
 d=read(f) if f.suffix=='.json' else [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
 route=str(f.relative_to(P));n=0
 for i,v in enumerate(d if isinstance(d,list) else [d]):
  if isinstance(v.get('text'),str):case(route,v.get('id',i),[dict(source_id='text',content=v['text'])],'原始任务文本');n+=1
 if n:inventory.append([route,n])
for f in (P/'tests').glob('*.py'):
 n=0
 for obj in ast.walk(ast.parse(f.read_text())):
  if isinstance(obj,ast.Dict):
   try:v=ast.literal_eval(obj)
   except (ValueError,TypeError,SyntaxError):continue
   if 'case_id' in v:n+=walk(v,str(f.relative_to(P))+'@'+str(obj.lineno),'测试字面量')
 if n:inventory.append([str(f.relative_to(P)),n])
bases={x['case']['case_id']:x['case'] for x in read(P/'eval/cases.json')}
for p in read(P/'eval/perturbations.json'):
 v=apply_edit(bases[p['base']],p['edit']);case('eval/perturbations.json',p['id'],v['sources'],'评测变体')
inventory.append(['eval/perturbations.json',7]);walk(revised,'本次合成修订/input.json','修订病例')
for key,ss in data.items():
 cid,h=key;hits=[]
 for s in ss:
  t=s['content']
  for label,rule in rx.items():
   for m in rule.finditer(t):hits.append([s.get('source_id'),label,m.start(),m.group()])
  for a,b in [('（','）'),('“','”'),('(',')')]:
   if t.count(a)!=t.count(b) and (a not in '（(' or t.count('（')+t.count('(')!=t.count(')')+t.count('）')):hits.append([s.get('source_id'),'括号或引号待核',None,a+b])
  for name,pattern,lo,hi in [
   ('血钠',r'(?:血钠|血清钠|Na[+＋])',85,205),('血钾',r'(?:血钾|血清钾|K[+＋])',1,12),('动脉血pH',r'(?:动脉血pH|动脉血气pH)',6.5,7.9),('血氧饱和度',r'(?:SpO[₂2]|指脉氧饱和度|血氧饱和度)',0,100),('体温',r'(?:体温|核心体温)',22,45)]:
   unit={'血钠':r'mmol[/／]L','血钾':r'mmol[/／]L','动脉血pH':'','血氧饱和度':r'[%％]','体温':r'℃|°C'}[name]
   for m in re.finditer(pattern+r'\s*[:：为]?\s*(\d+(?:\.\d+)?)\s*(?:'+unit+r')',t,re.I):
    if not lo<=float(m[1])<=hi:hits.append([s.get('source_id'),name+'量值待核',m.start(),m.group()])
  for m in re.finditer(r'(?:血压|BP)\s*[:：为]?\s*(\d{2,3})\s*[/／]\s*(\d{2,3})\s*mmHg',t,re.I):
   if int(m[1])<=int(m[2]): hits.append([s.get('source_id'),'收缩压未高于舒张压',m.start(),m.group()])
 audit.append(dict(case_id=cid,source_sha256=h,files=sorted(routes[key]),kind=kinds[key],fragments=len(ss),flags=hits))
save('输入文件清单.json',inventory);save('全量筛查.json',audit)
canon={}
for d in ['cmb_clin','typicalcase_dc']:
 loc='data/standardized/'+d+'/cases.json';a=[v for v in audit if loc in v['files']]
 for x in a:
  c=x['case_id'];x['source_reproduction_match']=matches[c];x['origin']=refs[c]['origin'];x['prior_flags']=refs[c]['quality']['flags'];x['prior_tier']=refs[c]['quality']['tier']
  x['hold']=bool(x['flags'] or not matches[c] or x['prior_tier']=='review_required')
 canon[d]=dict(rows=len(a),reproduced=sum(x['source_reproduction_match'] for x in a),flagged=sum(bool(x['flags']) for x in a),hold=sum(x['hold'] for x in a))
 save(d+'_逐例审查.json',a)
print(canon);print('files',len(inventory),'versions',len(audit),'changes',len(changes));print(collections.Counter(h[1] for a in audit for h in a['flags']))
