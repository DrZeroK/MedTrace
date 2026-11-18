import json,re,sqlite3,collections,hashlib,zipfile
from pathlib import Path
P=Path('/Users/zerok/Documents/GitHub/MedTrace'); O=Path(__file__).resolve().parent
def get(f):return json.loads(f.read_text())
queries="""肺炎 实变 咳痰
慢性阻塞性肺疾病 呼吸衰竭 二氧化碳
支气管哮喘 呼气峰流量 喘息
肺栓塞 D-二聚体 低氧血症
咯血 空洞 肺结核
胸腔积液 胸腔穿刺 漏出液
病毒性肺炎 磨玻璃 呼吸困难
吸入性肺炎 误吸 吞咽
间质性肺疾病 牵拉性 弥散
气胸 胸膜线 肺纹理
急性冠脉综合征 肌钙蛋白 ST段
心力衰竭 呼吸困难 水肿
心房颤动 脉搏短绌 心室率
晕厥 心动过缓 心律失常
主动脉夹层 血压 胸痛
感染性心内膜炎 血培养 赘生物
心包积液 心脏压塞 超声
高血压急症 靶器官 血压
不稳定型心绞痛 肌钙蛋白 心电图
心肌炎 肌钙蛋白 心律失常
上消化道出血 黑便 贫血
便血 憩室 结肠
阑尾炎 转移性 右下腹
肠梗阻 液气平面 腹胀
溃疡性结肠炎 黏液脓血便 腹泻
艰难梭菌 腹泻 抗菌
吞咽困难 食管 进行性
缺铁性贫血 铁蛋白 慢性失血
肠系膜 缺血 腹痛
憩室炎 结肠 左下腹
胆囊炎 胆囊结石 压痛
胆管炎 黄疸 胆总管
急性胰腺炎 脂肪酶 腹痛
肝硬化 腹水 白蛋白
肝性脑病 血氨 扑翼样震颤
胆汁淤积 黄疸 胆管
药物性肝损伤 转氨酶 黄疸
肝脓肿 发热 寒战
自发性细菌性腹膜炎 中性粒细胞 腹水
胆管炎 梗阻 支架
肾病综合征 低白蛋白血症 蛋白尿
急性肾小球肾炎 血尿 水肿
急性肾损伤 少尿 血容量
尿路梗阻 肾积水 尿潴留
肾盂肾炎 尿培养 叩击痛
高钾血症 T波 肾衰竭
输尿管结石 肾绞痛 血尿
慢性肾脏病 肌酐 病史
急性间质性肾炎 嗜酸性粒细胞 药物
抗肾小球基底膜 肺出血 血尿
缺铁性贫血 铁蛋白 转铁蛋白
巨幼细胞性贫血 维生素B12 神经
溶血性贫血 网织红细胞 胆红素
血小板减少 紫癜 黏膜
全血细胞减少 骨髓 网织红细胞
急性白血病 原始细胞 出血
华法林 出血 INR
淋巴瘤 淋巴结 盗汗
多发性骨髓瘤 骨痛 肾功能
贫血 肾功能 血红蛋白
糖尿病酮症酸中毒 酮体 酸中毒
高渗高血糖状态 渗透压 血糖
低血糖 葡萄糖 意识
低钠血症 渗透压 尿钠
低钾血症 U波 肌无力
甲状腺毒症 受体抗体 促甲状腺激素
甲状腺功能减退 游离 促甲状腺激素
肾上腺危象 糖皮质激素 低血压
高钙血症 甲状旁腺激素 便秘
糖尿病足 溃疡 感染
脑梗死 偏瘫 CT
蛛网膜下腔出血 脑膜刺激征 头痛
脑膜炎 颈项强直 脑脊液
癫痫 强直 阵挛
吉兰 脑脊液 腱反射
重症肌无力 眼睑下垂 胆碱受体
眩晕 眼震 前庭
马尾 尿潴留 会阴
短暂性脑缺血发作 颈内动脉 黑蒙
谵妄 意识 感染
脓毒症 乳酸 低血压
发热 感染 淋巴瘤
蜂窝织炎 皮肤 红肿
化脓性关节炎 关节液 晶体
系统性红斑狼疮 补体 蛋白尿
巨细胞动脉炎 头痛 颞动脉
炎性肌病 肌酸激酶 肌无力
中性粒细胞缺乏 发热 感染
嗜酸性粒细胞 药物 皮疹
IgA血管炎 紫癜 腹痛
异位妊娠 腹痛 阴道流血
子痫前期 高血压 蛋白尿
妊娠剧吐 呕吐 低钾
股骨颈骨折 骨质疏松 跌倒
横纹肌溶解 肌酸激酶 肌红蛋白
一氧化碳中毒 碳氧血红蛋白 缺氧
热射病 核心体温 意识
过敏性休克 肾上腺素 荨麻疹
深静脉血栓 超声 腘静脉
营养不良 水肿 白蛋白""".splitlines()
conn=sqlite3.connect('file:'+str(P/'data/reference_indexes/textbooks-v1/textbooks.sqlite')+'?mode=ro',uri=True)
pages=[(b,n,p,re.sub(r'\s+','',t)) for b,n,p,t in conn.execute('select book,pdf_page,printed_page,text from pages where printed_page>10') if t]
rows=get(O/'input.json');assert len(rows)==len(queries)==100
ledger=[]
for case,q in zip(rows,queries):
 terms=q.split();candidates=[]
 for book,n,p,t in pages:
  i=t.find(terms[0])
  while i!=-1:
   window=t[max(0,i-300):i+350];found=[k for k in terms if k in window]
   if len(found)>=2 and len(t)>450:
    candidates.append((len(found),sum(min(3,window.count(k)) for k in found),book,n,p,found))
   i=t.find(terms[0],i+len(terms[0]))
 best=max(candidates,default=None)
 ledger.append([case['case_id'],q, (best[2],best[3],best[4],best[5]) if best else None])
(O/'合成病例教材定位.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=1))
print('教材定位',sum(bool(x[2]) for x in ledger),'待查',[(x[0],x[1]) for x in ledger if not x[2]])
print('archive verification',[(f.name, all(hashlib.sha256(z.read(n)).digest()==hashlib.sha256((P/'data/raw/cblue'/n).read_bytes()).digest() for n in z.namelist() if n.endswith(('.json','.jsonl')) and not n.startswith('__MACOSX'))) for f in (P/'data/raw/CBLUE 4.0').glob('*.zip') for z in [zipfile.ZipFile(f)]])
