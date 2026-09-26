from __future__ import annotations
import datetime as dt, hashlib, json, os, re, secrets, sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SECTIONS=["abstract","introduction","contributions","method","results"]
def now(): return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
def digest(v:Any): return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
def j(v): return json.dumps(v,ensure_ascii=False,separators=(",",":"))
def u(v,d=None):
    try:return json.loads(v) if v else d
    except:return d
class GateError(RuntimeError):
    def __init__(self,msg,gate=None): super().__init__(msg); self.gate=gate
@dataclass
class Confirmation:
    token:str; paper_id:str; kind:str; payload:dict; summary:str; status:str; expires_at:str

class PaperFlowStore:
    def __init__(self,path):
        self.path=str(path); Path(self.path).parent.mkdir(parents=True,exist_ok=True); self._init()
    def db(self):
        c=sqlite3.connect(self.path,timeout=30); c.row_factory=sqlite3.Row; return c
    def _init(self):
        c=self.db(); c.executescript("""
        CREATE TABLE IF NOT EXISTS papers(
          id TEXT PRIMARY KEY,title TEXT,stage TEXT,created_at TEXT,updated_at TEXT,state TEXT);
        CREATE TABLE IF NOT EXISTS confirmations(
          token TEXT PRIMARY KEY,paper_id TEXT,kind TEXT,payload TEXT,summary TEXT,status TEXT,created_at TEXT,expires_at TEXT,decided_at TEXT);
        """); c.commit(); c.close()
    def _default(self,title=""):
        return {"title":title,"thesis":{},"angles":[],"approved_angle":None,"intro_map":{},"intro_map_confirmed":False,
        "paragraphs":{},"method_core":{},"method_core_confirmed":False,"abstract_plan":{},"abstract_plan_confirmed":False,
        "sections":{x:"todo" for x in SECTIONS},"selfcheck":None,"manuscript_text":"","manuscript_hash":None,
        "method_acronym":"","lint":None,"review":None,"delivered_at":None}
    def _row(self,c,pid):
        r=c.execute("select * from papers where id=?",(pid,)).fetchone()
        if not r: raise GateError("未找到 paper_id。")
        return r
    def _load(self,c,pid):
        r=self._row(c,pid); s=u(r["state"],{}); s.update({"id":r["id"],"title":r["title"],"stage":r["stage"],"created_at":r["created_at"],"updated_at":r["updated_at"]}); return s
    def _save(self,c,pid,s,stage=None):
        s2={k:v for k,v in s.items() if k not in {"id","created_at","updated_at","stage","title"}}
        c.execute("update papers set stage=?,updated_at=?,state=? where id=?",(stage or s.get("stage","DRAFTING"),now(),j(s2),pid))
    def _invalidate(self,s):
        s["lint"]=None; s["review"]=None; s["delivered_at"]=None
    def create_project(self,title=""):
        pid="pf_"+secrets.token_urlsafe(9).replace("-","").replace("_","")[:12]; t=now(); s=self._default(title.strip())
        c=self.db(); c.execute("insert into papers values(?,?,?,?,?,?)",(pid,title.strip(),"THESIS",t,t,j(s))); c.commit(); c.close(); return self.status(pid)
    def list_projects(self,limit=20):
        c=self.db(); rs=c.execute("select id,title,stage,updated_at from papers order by updated_at desc limit ?",(max(1,min(int(limit),100)),)).fetchall(); c.close(); return [dict(x) for x in rs]
    def status(self,pid):
        c=self.db(); s=self._load(c,pid); p=c.execute("select kind,expires_at from confirmations where paper_id=? and status='pending'",(pid,)).fetchall(); c.close()
        s.pop("manuscript_text",None); s["pending_confirmations"]=[dict(x) for x in p]; s["next_action"]=self._next(s); return s
    def _next(self,s):
        if not s.get("approved_angle"): return "set_thesis/set_angles → Gate 1 confirmation"
        if not s.get("intro_map_confirmed"): return "set_intro_map → Gate 2 confirmation"
        if not s.get("method_core_confirmed"): return "set_method_core → Gate 3 confirmation"
        if not s.get("abstract_plan_confirmed"): return "set_abstract_plan → confirmation"
        todo=[x for x,v in s["sections"].items() if v!="done"]
        if todo:return "draft sections: "+", ".join(todo)
        if not s.get("selfcheck"):return "record_selfcheck"
        if not s.get("lint") or s["lint"].get("hash")!=s.get("manuscript_hash"):return "run_lint"
        if not s.get("review") or s["review"].get("hash")!=s.get("manuscript_hash"):return "record_review"
        return "deliver"
    def _confirm(self,pid,kind,payload,summary):
        c=self.db(); self._row(c,pid); token=secrets.token_urlsafe(24); exp=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=24)).replace(microsecond=0).isoformat()
        snap=digest(payload); pl={"data":payload,"snapshot":snap}
        c.execute("insert into confirmations values(?,?,?,?,?,?,?,?,?)",(token,pid,kind,j(pl),summary,"pending",now(),exp,None)); c.commit(); c.close()
        return Confirmation(token,pid,kind,pl,summary,"pending",exp)
    def get_confirmation(self,token):
        c=self.db(); r=c.execute("select * from confirmations where token=?",(token,)).fetchone(); c.close()
        if not r: raise GateError("确认链接不存在或已失效。")
        if r["expires_at"]<now(): raise GateError("确认链接已过期。")
        return Confirmation(r["token"],r["paper_id"],r["kind"],u(r["payload"],{}),r["summary"],r["status"],r["expires_at"])
    def decide_confirmation(self,token,approve):
        c=self.db(); r=c.execute("select * from confirmations where token=?",(token,)).fetchone()
        if not r or r["status"]!="pending": c.close(); raise GateError("确认请求无效或已处理。")
        if r["expires_at"]<now(): c.execute("update confirmations set status='expired' where token=?",(token,)); c.commit(); c.close(); raise GateError("确认链接已过期。")
        s=self._load(c,r["paper_id"]); pl=u(r["payload"],{}); kind=r["kind"]; data=pl.get("data",{})
        current=None
        if kind=="gate1": current={"thesis":s.get("thesis"),"angles":s.get("angles"),"angle":data.get("angle")}
        elif kind=="gate2": current=s.get("intro_map")
        elif kind.startswith("intro_para:"): current=(s.get("paragraphs") or {}).get(kind.split(":")[1],{}).get("plan")
        elif kind=="gate3": current=s.get("method_core")
        elif kind=="abstract_plan": current=s.get("abstract_plan")
        if current is not None and digest(current)!=pl.get("snapshot"): c.close(); raise GateError("内容已改变，旧确认链接失效，请重新生成。",kind)
        status="approved" if approve else "rejected"; c.execute("update confirmations set status=?,decided_at=? where token=?",(status,now(),token))
        if approve:
            if kind=="gate1": s["approved_angle"]=data["angle"]; stage="INTRO_MAP"
            elif kind=="gate2": s["intro_map_confirmed"]=True; stage="METHOD_CORE"
            elif kind.startswith("intro_para:"):
                n=kind.split(":")[1]; s["paragraphs"][n]["confirmed"]=True; stage=s.get("stage","DRAFTING")
            elif kind=="gate3": s["method_core_confirmed"]=True; stage="ABSTRACT_PLAN"
            elif kind=="abstract_plan": s["abstract_plan_confirmed"]=True; stage="DRAFTING"
            self._save(c,r["paper_id"],s,stage)
        c.commit(); c.close(); return self.status(r["paper_id"])
    def set_thesis(self,pid,claim,evidence,boundary,selling_point):
        if min(map(len,[claim.strip(),evidence.strip(),boundary.strip(),selling_point.strip()]))<4: raise GateError("Gate 1 信息过短。","gate1")
        c=self.db(); s=self._load(c,pid); s["thesis"]={"claim":claim,"evidence":evidence,"boundary":boundary,"selling_point":selling_point}; s["approved_angle"]=None; self._invalidate(s); self._save(c,pid,s,"THESIS"); c.commit(); c.close(); return self.status(pid)
    def set_angles(self,pid,angles):
        if not 2<=len(angles)<=3: raise GateError("必须提供 2–3 个叙事角度。","gate1")
        c=self.db(); s=self._load(c,pid); s["angles"]=angles; s["approved_angle"]=None; self._invalidate(s); self._save(c,pid,s,"THESIS"); c.commit(); c.close(); return self.status(pid)
    def request_gate1(self,pid,angle):
        c=self.db(); s=self._load(c,pid); c.close()
        if not s.get("thesis") or len(s.get("angles",[]))<2: raise GateError("先完成 thesis 与 2–3 个角度。","gate1")
        names=[a.get("name","") for a in s["angles"]]
        if angle not in names: raise GateError("angle 必须精确对应候选角度名称。","gate1")
        data={"thesis":s["thesis"],"angles":s["angles"],"angle":angle}; return self._confirm(pid,"gate1",data,f"Gate 1：确认论文立意与叙事角度\n选择：{angle}\n{j(s['thesis'])}")
    def _g1(self,s):
        if not s.get("approved_angle"): raise GateError("Gate 1 未确认。","gate1")
    def _g2(self,s):
        if not s.get("intro_map_confirmed"): raise GateError("Gate 2 未确认。","gate2")
    def _g3(self,s):
        if not s.get("method_core_confirmed"): raise GateError("Gate 3 未确认。","gate3")
    def set_intro_map(self,pid,challenges,contributions,mapping):
        c=self.db(); s=self._load(c,pid); self._g1(s)
        if not challenges or not contributions or len(mapping)!=len(challenges): c.close(); raise GateError("挑战/贡献映射不完整。","gate2")
        s["intro_map"]={"challenges":challenges,"contributions":contributions,"mapping":mapping}; s["intro_map_confirmed"]=False; s["paragraphs"]={}; self._invalidate(s); self._save(c,pid,s,"INTRO_MAP"); c.commit(); c.close(); return self.status(pid)
    def request_gate2(self,pid):
        c=self.db(); s=self._load(c,pid); c.close(); self._g1(s)
        if not s.get("intro_map"): raise GateError("先设置 intro map。","gate2")
        return self._confirm(pid,"gate2",s["intro_map"],"Gate 2：确认挑战—贡献映射\n"+j(s["intro_map"]))
    def set_intro_paragraph_plan(self,pid,n,opening_challenge,support,closing_problem):
        c=self.db(); s=self._load(c,pid); self._g1(s); self._g2(s); total=len(s["intro_map"].get("challenges",[]))
        if n<1 or n>total: c.close(); raise GateError("段号超出挑战数量。","gate2")
        s["paragraphs"][str(n)]={"plan":{"opening_challenge":opening_challenge,"support":support,"closing_problem":closing_problem},"confirmed":False,"done":False}
        self._invalidate(s); self._save(c,pid,s,"DRAFTING"); c.commit(); c.close(); return self.status(pid)
    def request_intro_para(self,pid,n):
        c=self.db(); s=self._load(c,pid); c.close(); p=s.get("paragraphs",{}).get(str(n))
        if not p: raise GateError("先设置该段计划。","gate2")
        return self._confirm(pid,f"intro_para:{n}",p["plan"],f"确认引言挑战段 {n} 计划\n"+j(p["plan"]))
    def begin_intro_paragraph(self,pid,n):
        c=self.db(); s=self._load(c,pid); c.close(); self._g2(s); p=s.get("paragraphs",{}).get(str(n),{})
        if not p.get("confirmed"): raise GateError("该段尚未确认。","gate2")
        if n>1 and not s["paragraphs"].get(str(n-1),{}).get("done"): raise GateError("上一段尚未完成。","gate2")
        return {"allowed":True,"paper_id":pid,"paragraph":n,"plan":p.get("plan")}
    def finish_intro_paragraph(self,pid,n):
        c=self.db(); s=self._load(c,pid); p=s.get("paragraphs",{}).get(str(n),{})
        if not p.get("confirmed"): c.close(); raise GateError("该段尚未确认。","gate2")
        p["done"]=True; self._invalidate(s); self._save(c,pid,s,"DRAFTING"); c.commit(); c.close(); return self.status(pid)
    def set_method_core(self,pid,innovation,not_simple_combination,evidence,modules):
        c=self.db(); s=self._load(c,pid); self._g1(s)
        if min(len(innovation.strip()),len(not_simple_combination.strip()),len(evidence.strip()))<8: c.close(); raise GateError("方法核心信息过短。","gate3")
        s["method_core"]={"innovation":innovation,"not_simple_combination":not_simple_combination,"evidence":evidence,"modules":modules}; s["method_core_confirmed"]=False; self._invalidate(s); self._save(c,pid,s,"METHOD_CORE"); c.commit(); c.close(); return self.status(pid)
    def request_gate3(self,pid):
        c=self.db(); s=self._load(c,pid); c.close()
        if not s.get("method_core"): raise GateError("先设置方法核心。","gate3")
        return self._confirm(pid,"gate3",s["method_core"],"Gate 3：确认核心创新\n"+j(s["method_core"]))
    def set_abstract_plan(self,pid,s1,s2_items,s3,mapping):
        c=self.db(); s=self._load(c,pid); self._g2(s); self._g3(s)
        s["abstract_plan"]={"s1":s1,"s2_items":s2_items,"s3":s3,"mapping":mapping}; s["abstract_plan_confirmed"]=False; self._invalidate(s); self._save(c,pid,s,"ABSTRACT_PLAN"); c.commit(); c.close(); return self.status(pid)
    def request_abstract_plan(self,pid):
        c=self.db(); s=self._load(c,pid); c.close()
        if not s.get("abstract_plan"): raise GateError("先设置摘要计划。","abstract")
        return self._confirm(pid,"abstract_plan",s["abstract_plan"],"确认摘要写作计划\n"+j(s["abstract_plan"]))
    def begin_section(self,pid,section):
        section=section.lower().strip()
        if section not in SECTIONS: raise GateError("未知 section。")
        c=self.db(); s=self._load(c,pid); self._g1(s)
        if section in ("introduction","contributions"): self._g2(s)
        if section=="method": self._g3(s)
        if section=="abstract":
            self._g2(s); self._g3(s)
            if not s.get("abstract_plan_confirmed"): c.close(); raise GateError("摘要计划未确认。","abstract")
        s["sections"][section]="draft"; self._invalidate(s); self._save(c,pid,s,"DRAFTING"); c.commit(); c.close(); return {"allowed":True,"paper_id":pid,"section":section}
    def finish_section(self,pid,section):
        c=self.db(); s=self._load(c,pid)
        if s.get("sections",{}).get(section)!="draft": c.close(); raise GateError("必须先 begin_section。")
        if section=="introduction":
            total=len(s.get("intro_map",{}).get("challenges",[])); missing=[n for n in range(1,total+1) if not s.get("paragraphs",{}).get(str(n),{}).get("done")]
            if missing: c.close(); raise GateError("仍有引言挑战段未完成："+",".join(map(str,missing)),"gate2")
        s["sections"][section]="done"; self._invalidate(s); self._save(c,pid,s,"SELFCHECK" if all(v=="done" for v in s["sections"].values()) else "DRAFTING"); c.commit(); c.close(); return self.status(pid)
    def submit_manuscript(self,pid,manuscript_text,method_acronym=""):
        if len(manuscript_text.strip())<100: raise GateError("稿件过短。","gate4")
        c=self.db(); s=self._load(c,pid); h=hashlib.sha256(manuscript_text.encode()).hexdigest()[:16]; s["manuscript_text"]=manuscript_text; s["manuscript_hash"]=h; s["method_acronym"]=method_acronym; self._invalidate(s); self._save(c,pid,s,s.get("stage")); c.commit(); c.close(); return {"paper_id":pid,"manuscript_hash":h,"chars":len(manuscript_text)}
    def record_selfcheck(self,pid,notes):
        if len(notes.strip())<40: raise GateError("自检记录过短。","gate4")
        c=self.db(); s=self._load(c,pid); s["selfcheck"]={"at":now(),"notes":notes}; self._save(c,pid,s,"LINT"); c.commit(); c.close(); return s["selfcheck"]
    def run_lint(self,pid,lint_script=None):
        c=self.db(); s=self._load(c,pid); text=s.get("manuscript_text","")
        if not text: c.close(); raise GateError("先提交稿件。","gate4")
        errors=0; warns=0; info=0; findings=[]
        for pat,msg in [(r"\bTBD\b|TODO|FIXME","存在占位符"),(r"\b(obviously|clearly|undoubtedly)\b","存在主观强化词")]:
            n=len(re.findall(pat,text,re.I)); warns+=n; findings += [msg]*min(n,5)
        obj={"at":now(),"hash":s.get("manuscript_hash"),"errors":errors,"warns":warns,"infos":info,"output":"; ".join(findings) or "No blocking findings"}
        s["lint"]=obj; s["review"]=None; self._save(c,pid,s,"LINT"); c.commit(); c.close(); return obj
    def record_review(self,pid,notes):
        c=self.db(); s=self._load(c,pid); lint=s.get("lint") or {}
        if lint.get("hash")!=s.get("manuscript_hash") or lint.get("errors",1)!=0: c.close(); raise GateError("lint 未通过或已过期。","gate4")
        required=["摘要","引言","贡献","方法"]; miss=[x for x in required if x not in notes]
        if lint.get("warns",0)>0 and not re.search(r"WARN|告警|处置|保留|改",notes,re.I): miss.append("WARN 处置")
        if miss: c.close(); raise GateError("复核记录不完整："+",".join(miss),"gate4")
        s["review"]={"at":now(),"hash":s.get("manuscript_hash"),"notes":notes}; self._save(c,pid,s,"REVIEWED"); c.commit(); c.close(); return s["review"]
    def deliver(self,pid):
        c=self.db(); s=self._load(c,pid); probs=[]
        if any(v!="done" for v in s.get("sections",{}).values()): probs.append("章节未全部完成")
        if not s.get("selfcheck"): probs.append("缺少自检")
        if (s.get("lint") or {}).get("hash")!=s.get("manuscript_hash"): probs.append("lint 缺失或过期")
        if (s.get("review") or {}).get("hash")!=s.get("manuscript_hash"): probs.append("review 缺失或过期")
        if probs: c.close(); raise GateError("Gate 4 未通过："+ "；".join(probs),"gate4")
        s["delivered_at"]=now(); self._save(c,pid,s,"DELIVERED"); c.commit(); c.close(); return {"delivered":True,"paper_id":pid,"manuscript_hash":s.get("manuscript_hash"),"delivered_at":s["delivered_at"]}
