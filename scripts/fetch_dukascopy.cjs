#!/usr/bin/env node
"use strict";
const fs = require("fs");
const path = require("path");
const { getHistoricalRates } = require("dukascopy-node");

const universe = {
  XAUUSD: "xauusd",
  NAS100: "usatechidxusd",
  US500: "usa500idxusd",
  EURUSD: "eurusd",
  GBPUSD: "gbpusd",
};

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}
function isoDay(value, label) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) throw new Error(`${label} must be YYYY-MM-DD`);
  const d = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(d.valueOf())) throw new Error(`Invalid ${label}`);
  return d;
}
function addMonths(d, n) {
  const x = new Date(d);
  x.setUTCMonth(x.getUTCMonth() + n);
  return x;
}
function fmt(d) { return d.toISOString().slice(0, 10); }

async function rates(instrument, from, to, priceType) {
  return getHistoricalRates({
    instrument,
    dates: { from, to },
    timeframe: "m1",
    priceType,
    format: "json",
    utcOffset: 0,
    volumes: true,
    ignoreFlats: false,
    batchSize: 10,
    pauseBetweenBatchesMs: 250,
  });
}

async function fetchSymbol(symbol, from, to) {
  const instrument = universe[symbol];
  if (!instrument) throw new Error(`Unknown symbol ${symbol}`);
  const dir = path.join("data", "raw", symbol);
  fs.mkdirSync(dir, { recursive: true });
  const target = path.join(dir, "m1.csv");
  const tmp = `${target}.partial`;
  const out = fs.createWriteStream(tmp, { encoding: "utf8" });
  out.write("timestamp_open,bid_open,bid_high,bid_low,bid_close,spread_price,ask_open,ask_high,ask_low,ask_close,volume\n");
  let cursor = new Date(from), written = 0, lastTs = -1;
  while (cursor < to) {
    const chunkEnd = new Date(Math.min(addMonths(cursor, 1).valueOf(), to.valueOf()));
    process.stdout.write(`${symbol} ${fmt(cursor)} -> ${fmt(chunkEnd)} ... `);
    const [bid, ask] = await Promise.all([
      rates(instrument, cursor, chunkEnd, "bid"),
      rates(instrument, cursor, chunkEnd, "ask"),
    ]);
    const askByTs = new Map(ask.map(x => [x.timestamp, x]));
    let chunkWritten = 0;
    for (const b of bid) {
      if (b.timestamp <= lastTs) continue;
      const a = askByTs.get(b.timestamp);
      if (!a) continue;
      const spread = a.open - b.open;
      if (!(spread >= 0)) throw new Error(`${symbol}: negative spread at ${b.timestamp}`);
      const timestamp = new Date(b.timestamp).toISOString().replace(".000Z", "+00:00");
      const volume = Number.isFinite(b.volume) ? b.volume : 0;
      out.write([timestamp,b.open,b.high,b.low,b.close,spread,a.open,a.high,a.low,a.close,volume].join(",") + "\n");
      lastTs = b.timestamp;
      written++; chunkWritten++;
    }
    console.log(`${chunkWritten} rows`);
    cursor = chunkEnd;
  }
  await new Promise((resolve, reject) => { out.end(resolve); out.on("error", reject); });
  if (!written) { fs.rmSync(tmp, { force: true }); throw new Error(`${symbol}: no rows downloaded`); }
  fs.renameSync(tmp, target);
  console.log(`${symbol}: wrote ${written} M1 rows -> ${target}`);
}

(async () => {
  const from = isoDay(arg("--from"), "--from");
  const to = isoDay(arg("--to"), "--to");
  if (from >= to) throw new Error("--from must be earlier than --to");
  const symbols = process.argv.includes("--all") ? Object.keys(universe) : [String(arg("--symbol") || "").toUpperCase()];
  if (!symbols[0]) throw new Error("Use --all or --symbol XAUUSD");
  for (const symbol of symbols) await fetchSymbol(symbol, from, to);
})().catch(err => { console.error(err); process.exit(1); });
