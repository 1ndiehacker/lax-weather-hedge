from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List, Any
import os
import json
from datetime import datetime, timedelta

app = FastAPI(title="LAX Weather Hedge API v1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Ladder(BaseModel):
    name: str
    model_prob: float
    market_price: float
    contracts: int = 0
    entry_price: float = 0.0

class HedgeProposal(BaseModel):
    ladders: List[Ladder]
    total_target: float = 4.0

@app.get("/health")
async def health():
    return {"status": "OK", "timestamp": datetime.now().isoformat()}

@app.get("/api/status")
async def get_market_status():
    ladders = [
        {"name": "78-80°F", "model_prob": 0.22, "market_price": 0.20, "edge": 0.02},
        {"name": "80-82°F", "model_prob": 0.38, "market_price": 0.28, "edge": 0.10},
        {"name": "82-84°F", "model_prob": 0.32, "market_price": 0.32, "edge": 0.00},
    ]
    ev_total = sum(l["edge"] * 8 for l in ladders)
    return {
        "timestamp": datetime.now().isoformat(),
        "ladders": ladders,
        "ev_total": round(ev_total, 3),
        "recommendations": ["78-80: WEAK", "80-82: STRONG"],
        "next_check": (datetime.now() + timedelta(hours=1)).strftime("%H:%M PDT"),
        "time_progress": 0.45,
    }

@app.post("/api/hedge-proposal")
async def generate_hedge_proposal(proposal: HedgeProposal):
    results = {}
    for ladder in proposal.ladders:
        fair_price = ladder.model_prob
        target_contracts = 8 if "80-82" in ladder.name else 5
        alloc_dollars = proposal.total_target * (0.5 if "80-82" in ladder.name else 0.25)
        limit_orders = [
            {"step": 1, "qty": int(target_contracts * 0.5), "limit_price": max(fair_price - 0.01, 0.01)},
            {"step": 2, "qty": int(target_contracts * 0.3), "limit_price": max(fair_price - 0.005, 0.01)},
            {"step": 3, "qty": target_contracts - int(target_contracts * 0.8), "limit_price": fair_price},
        ]
        results[ladder.name] = {
            "target_contracts": target_contracts,
            "alloc_dollars": round(alloc_dollars, 2),
            "avg_entry_estimate": round(sum(o["limit_price"] * o["qty"] for o in limit_orders) / target_contracts, 3),
            "limit_orders": limit_orders,
        }
    return {"proposals": results, "total_cost_estimate": proposal.total_target * 0.91}

@app.post("/api/cut-analysis")
async def analyze_cut_candidates(ladders: List[Ladder]):
    analysis = []
    for ladder in ladders:
        edge = ladder.model_prob - ladder.market_price
        time_ratio = 0.55
        pnl_pct = (ladder.market_price - ladder.entry_price) / ladder.entry_price * 100 if ladder.entry_price else 0
        priority = 3 if edge < 0 and (time_ratio > 0.4 or pnl_pct < -30) else 1 if edge < -0.05 else 0
        recommendation = "CUT" if priority == 3 else "WEAK" if priority == 1 else "HOLD"
        analysis.append({
            "ladder": ladder.name,
            "edge": round(edge, 3),
            "pnl_pct": round(pnl_pct, 1),
            "priority": priority,
            "recommendation": recommendation,
        })
    return {"analysis": analysis, "top_cut": analysis[0] if analysis and analysis[0]["priority"] == 3 else None}

@app.get("/api/ai-commentary")
async def get_ai_commentary():
    # APIキーエラー回避のためモック
    return {"commentary": "78-80 ladder CUT recommended. Edge -0.12, time 55%, PnL -35%. Hold remaining 2 ladders."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
