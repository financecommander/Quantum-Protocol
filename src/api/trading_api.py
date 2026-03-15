from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, List

app = FastAPI(title="Quantum Protocol Trading API")

class OrderRequest(BaseModel):
    symbol: str
    quantity: float
    side: str

# Mock data stores - replace with actual services
positions = {}
pnl = 0.0
risk_metrics = {"var": 0.0, "drawdown": 0.0}

@app.post("/orders")
async def place_order(order: OrderRequest):
    """Place a trading order."""
    if order.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    # TODO: Integrate with OrderRouter for actual execution
    return {
        "status": "executed",
        "symbol": order.symbol,
        "quantity": order.quantity,
        "side": order.side
    }

@app.get("/positions")
async def get_positions() -> Dict:
    """Get current positions."""
    return positions

@app.get("/pnl")
async def get_pnl() -> float:
    """Get current P&L."""
    return pnl

@app.get("/risk")
async def get_risk_metrics() -> Dict:
    """Get current risk metrics."""
    return risk_metrics
