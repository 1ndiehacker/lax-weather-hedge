from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, List, Any
import os
import json
from datetime import datetime, timedelta
from openai import OpenAI

app = FastAPI(title="LAX Weather Hedge API v1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
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
        edge_cond = edge < 0
        time_cond = time_ratio > 0.4
        pnl_cond = pnl_pct < -30
        priority = 3 if edge_cond and (time_cond or pnl_cond) else 1 if edge < -0.05 else 0
        recommendation = "CUT" if priority == 3 else "WEAK" if priority == 1 else "HOLD"
        analysis.append({
            "ladder": ladder.name,
            "edge": round(edge, 3),
            "pnl_pct": round(pnl_pct, 1),
            "priority": priority,
            "recommendation": recommendation,
        })
    cut_candidates = sorted(analysis, key=lambda x: x["priority"], reverse=True)
    top_cut = cut_candidates[0] if cut_candidates and cut_candidates[0]["priority"] == 3 else None
    return {"analysis": analysis, "top_cut": top_cut, "ev_impact": -0.12}

@app.post("/api/ai-commentary")
async def generate_ai_commentary(data: Dict[str, Any]):
    prompt = f"""LAX Weather Hedge Status:
{json.dumps(data, indent=2)}

English commentary (150 chars max):
1. One line conclusion
2. 3 bullet reasons
3. Next action

Beginner friendly language."""
    try:
        response = client.chat.completions.create(
            model="anthropic/claude-3.5-sonnet:20240620",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        return {"commentary": response.choices[0].message.content.strip()}
    except Exception:
        return {"commentary": "AI connection error. Check rule-based signals."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
