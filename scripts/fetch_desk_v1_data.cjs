#!/usr/bin/env node
"use strict";
const fs=require("fs"), path=require("path");
const {getHistoricalRates}=require("dukascopy-node");

const universe={
 XAUUSD:"xauusd",XAGUSD:"xagusd",
 EURUSD:"eurusd",GBPUSD:"gbpusd",USDJPY:"usdjpy",AUDUSD:"audusd",USDCAD:"usdcad",
 NAS100:"usatechidxusd",US500:"usa500idxusd",US30:"usa30idxusd",DAX:"deuidxeur",
 WTI:"lightcmdusd",BRENT:"brentcmdusd"
};

function arg(n){const i=process.argv.indexOf(n);return i>=0?process.argv[i+1]:undefined}
function day(x,n){if(!/^\d{4}-\d{2}-\d{2}$/.test(x||""))throw Error(`${n} YYYY-MM-DD`);return new Date(x+"T00:00:00Z")}
function addMonth(d){const x=new Date(d);x.setUTCMonth(x.getUTCMonth()+1);return x}
async function rates(inst,from,to,type){return getHistoricalRates({instrument:inst,dates:{from,to},timeframe:"m1",priceType:type,format:"json",utcOffset:0,volumes:true,ignoreFlats:false,batchSize:10,pauseBetweenBatchesMs:250})}

async function fetchOne(symbol,from,to){
 const inst=universe[symbol]; if(!inst)throw Error("unknown "+symbol);
 const dir=path.join("data","raw",symbol);fs.mkdirSync(dir,{recursive:true});
 const target=path.join(dir,"m1.csv"),tmp=target+".partial";
 const out=fs.createWriteStream(tmp,{encoding:"utf8"});
 out.write("timestamp_open,bid_open,bid_high,bid_low,bid_close,spread_price,ask_open,ask_high,ask_low,ask_close,volume\n");
 let cursor=new Date(from),written=0,last=-1;
 while(cursor<to){
   const end=new Date(Math.min(addMonth(cursor).valueOf(),to.valueOf()));
   console.log(symbol,cursor.toISOString().slice(0,10),"->",end.toISOString().slice(0,10));
   const [bid,ask]=await Promise.all([rates(inst,cursor,end,"bid"),rates(inst,cursor,end,"ask")]);
   const amap=new Map(ask.map(x=>[x.timestamp,x]));
   for(const b of bid){
     if(b.timestamp<=last)continue; const a=amap.get(b.timestamp); if(!a)continue;
     const spread=a.open-b.open; if(!(spread>=0))continue;
     const ts=new Date(b.timestamp).toISOString().replace(".000Z","+00:00");
     out.write([ts,b.open,b.high,b.low,b.close,spread,a.open,a.high,a.low,a.close,Number.isFinite(b.volume)?b.volume:0].join(",")+"\n");
     last=b.timestamp;written++;
   }
   cursor=end;
 }
 await new Promise((res,rej)=>{out.end(res);out.on("error",rej)});
 if(!written){fs.rmSync(tmp,{force:true});throw Error(symbol+" no rows")}
 fs.renameSync(tmp,target);console.log(symbol,"rows",written);
}

(async()=>{
 const from=day(arg("--from"),"--from"),to=day(arg("--to"),"--to"); if(from>=to)throw Error("from<to");
 let symbols=[];
 if(process.argv.includes("--new-assets")) symbols=["XAGUSD","USDJPY","AUDUSD","USDCAD","US30","DAX","WTI","BRENT"];
 else if(process.argv.includes("--extended")) symbols=Object.keys(universe);
 else symbols=[String(arg("--symbol")||"").toUpperCase()];
 if(!symbols[0])throw Error("use --symbol XAGUSD, --new-assets or --extended");
 for(const s of symbols)await fetchOne(s,from,to);
})().catch(e=>{console.error(e);process.exit(1)});
