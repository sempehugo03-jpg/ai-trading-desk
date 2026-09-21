import json
from pathlib import Path
from .discovery_v3 import V3Store,StrategyV3,Verdict,mine_symbolic_patterns,strategy_variants,evaluate_strategy,classify

SUPPORTED=("XAUUSD","XAGUSD","EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","NAS100","US500","US30","DAX","WTI","BRENT")

class DiscoveryDeskV3:
    def __init__(self,store:V3Store,*,data_root="data/raw"):
        self.store=store;self.data_root=data_root
    def available(self):
        root=Path(self.data_root);return tuple(s for s in SUPPORTED if (root/s/"m1.csv").exists())
    def search_once(self,*,trials_per_market=300,max_depth=3,max_rules=3,patterns_per_market=5,candidate_cap=300,seed=7,context_width=4):
        import hashlib
        created=0;current=sum(self.store.counts().values());avail=self.available();run_no=self.store.trial_count()
        for target in avail:
            others=[s for s in avail if s!=target]
            # Rotate small context windows to keep RAM bounded. In --forever mode
            # the windows move across runs, so every cross-asset context is eventually explored.
            offset=(run_no//max(1,trials_per_market)+sum(ord(c) for c in target))%max(1,len(others))
            contexts=tuple((others+others)[offset:offset+min(context_width,len(others))])
            for timeframe in (15,60,240):
                if current+created>=candidate_cap:return created
                raw=f"{target}|{timeframe}|{run_no}|{seed}".encode();local_seed=seed+int(hashlib.sha256(raw).hexdigest()[:8],16)%1_000_000
                self.store.add_search_run(target,timeframe,trials_per_market,max_depth,max_rules,local_seed)
                pats=mine_symbolic_patterns(data_root=self.data_root,target=target,contexts=contexts,timeframe=timeframe,trials=trials_per_market,max_depth=max_depth,max_rules=max_rules,seed=local_seed,top_k=patterns_per_market)
                for p in pats:
                    self.store.add_pattern(p)
                    for s in strategy_variants(p):
                        if current+created>=candidate_cap:return created
                        before=sum(self.store.counts().values());self.store.add_candidate(s);after=sum(self.store.counts().values());created+=max(0,after-before)
        return created
    def step(self):
        rows=self.store.pending()
        if not rows:return False
        cid,sj,stage=rows[0];spec=StrategyV3.from_mapping(json.loads(sj))
        if stage=="RESEARCH":
            metrics=evaluate_strategy(spec,self.data_root,.45,.60);verdict,reasons=classify(metrics,"RESEARCH");nxt="VALIDATION" if verdict in (Verdict.PASS,Verdict.PROMISING) else ("UNCERTAIN" if verdict==Verdict.UNCERTAIN else "REJECTED");adaptive=True
        elif stage=="VALIDATION":
            metrics=evaluate_strategy(spec,self.data_root,.60,.70);verdict,reasons=classify(metrics,"VALIDATION");nxt="OOS1" if verdict==Verdict.PASS else ("UNCERTAIN" if verdict in (Verdict.PROMISING,Verdict.UNCERTAIN) else "REJECTED");adaptive=True
        elif stage=="OOS1":
            metrics=evaluate_strategy(spec,self.data_root,.70,.80);verdict,reasons=classify(metrics,"OOS1");nxt="OOS2" if verdict==Verdict.PASS else ("UNCERTAIN" if verdict==Verdict.UNCERTAIN else "REJECTED");adaptive=False
        elif stage=="OOS2":
            metrics=evaluate_strategy(spec,self.data_root,.80,.90);verdict,reasons=classify(metrics,"OOS2");nxt="BLIND_WAIT" if verdict==Verdict.PASS else ("UNCERTAIN" if verdict==Verdict.UNCERTAIN else "REJECTED");adaptive=False
        else:return False
        self.store.advance(cid,stage,verdict,metrics,",".join(reasons) if reasons else stage+"_PASS",nxt,adaptive);return True
