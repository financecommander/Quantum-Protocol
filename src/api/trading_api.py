from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List

app = FastAPI(title="Quantum Protocol Trading API")

class OrderRequest(BaseModel):
    symbol: str
    qty: float
    side: str

# Mock data stores
positions = {}
pnl_data = {}
risk_metrics = {"var": 0.0, "drawdown": 0.0}

@app.post("/orders")
async def place_order(order: OrderRequest):
    if order.qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    # TODO: Integrate with OrderRouter
    return {"status": "order placed", "symbol": order.symbol, "qty": order.qty, "side": order.side}

@app.get("/positions")
async def get_positions():
    return positions

@app.get("/pnl")
async def get_pnl():
    return pnl_data

@app.get("/risk")
async def get_risk_metrics():
    return risk_metrics
