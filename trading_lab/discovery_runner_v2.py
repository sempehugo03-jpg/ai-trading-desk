import json
from pathlib import Path
from .discovery_v2 import V2Store,StrategyV2,Verdict,discover_patterns,build_variants,evaluate,classify
from .data import load_csv_segments

class DiscoveryDeskV2:
    def __init__(self,store:V2Store,*,data_root="data/raw"):
        self.store=store;self.data_root=data_root
    def discover(self,instruments,patterns_per_tf=5,max_candidates=150):
        created=0
        for symbol in instruments:
            segs=load_csv_segments(Path(self.data_root)/symbol/"m1.csv")
            for tf in (15,60,240):
                for p in discover_patterns(symbol,segs,tf,top_patterns=patterns_per_tf):
                    self.store.add_pattern(p)
                    for s in build_variants(p):
                        if created>=max_candidates:return created
                        before=sum(self.store.counts().values());self.store.add_candidate(s);after=sum(self.store.counts().values());created+=max(0,after-before)
        return created
    def step(self):
        rows=self.store.pending()
        if not rows:return False
        cid,spec_json,stage=rows[0];spec=StrategyV2.from_mapping(json.loads(spec_json))
        if stage=="RESEARCH":
            metrics=evaluate(spec,self.data_root,.40,.60);verdict,reasons=classify(metrics,"RESEARCH")
            nxt="VALIDATION" if verdict in (Verdict.PASS,Verdict.PROMISING) else ("UNCERTAIN" if verdict is Verdict.UNCERTAIN else "REJECTED")
        elif stage=="VALIDATION":
            metrics=evaluate(spec,self.data_root,.60,.75);verdict,reasons=classify(metrics,"VALIDATION")
            nxt="OOS" if verdict is Verdict.PASS else ("UNCERTAIN" if verdict in (Verdict.PROMISING,Verdict.UNCERTAIN) else "REJECTED")
        elif stage=="OOS":
            metrics=evaluate(spec,self.data_root,.75,.90);verdict,reasons=classify(metrics,"OOS");nxt="BLIND_WAIT" if verdict is Verdict.PASS else "REJECTED"
        else:return False
        self.store.advance(cid,stage,verdict.value,metrics,",".join(reasons) if reasons else stage+"_PASS",nxt);return True
