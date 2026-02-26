"""
MATRIX PROTOCOL™ v1.0 — Order Manager

Sits between the Orchestrator and IBKR Client.
Handles: position reconciliation, order sizing, risk checks before submission,
fill tracking, and audit logging.

Flow: Orchestrator target positions → OrderManager → Risk checks → IBKR Client
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from execution.ibkr_client import IBKRClient, OrderSide, OrderType, OrderStatus, Position
from risk.kill_switch import KillSwitch
from compliance.audit_logger import AuditLogger

logger = logging.getLogger("matrix.execution.order_manager")


@dataclass
class TargetPosition:
    """What the orchestrator wants us to hold."""
    sleeve_id: int
    symbol: str
    sec_type: str
    target_quantity: float      # Signed: positive = long, negative = short
    target_dollar_value: float
    rationale: str = ""
    contract_kwargs: dict = field(default_factory=dict)


@dataclass
class OrderManagerConfig:
    """Controls for order generation."""
    min_order_size: float = 1.0           # Minimum order quantity
    max_order_size: float = 100.0         # Maximum single order quantity
    max_orders_per_tick: int = 5          # Rate limit
    default_order_type: OrderType = OrderType.MARKET
    enable_trading: bool = False          # Must be explicitly enabled
    paper_mode: bool = True               # Paper trading mode


class OrderManager:
    """
    Translates target positions into orders.
    
    Key responsibilities:
    1. Compare target vs current positions → generate deltas
    2. Run pre-trade risk checks (kill switch, position limits)
    3. Submit orders via IBKR client
    4. Track fills and update position state
    5. Log everything for audit trail
    """

    def __init__(
        self,
        ibkr_client: IBKRClient,
        kill_switch: KillSwitch,
        audit_logger: AuditLogger,
        config: Optional[OrderManagerConfig] = None,
    ):
        self.ibkr = ibkr_client
        self.kill_switch = kill_switch
        self.audit = audit_logger
        self.config = config or OrderManagerConfig()
        
        # Track current state
        self._current_positions: dict[str, float] = {}  # symbol → quantity
        self._pending_orders: dict[int, OrderStatus] = {}  # order_id → status
        self._orders_this_tick = 0
        self._portfolio_value = 0.0
        self._daily_pnl = 0.0

    async def sync_positions(self):
        """Pull current positions from IBKR and update local state."""
        positions = await self.ibkr.get_positions()
        self._current_positions = {p.symbol: p.quantity for p in positions}
        
        summary = await self.ibkr.get_account_summary()
        if summary:
            self._portfolio_value = summary.net_liquidation
            self._daily_pnl = summary.unrealized_pnl + summary.realized_pnl
        
        logger.debug(f"Synced {len(positions)} positions, portfolio=${self._portfolio_value:,.0f}")

    def calculate_deltas(self, targets: list[TargetPosition]) -> list[TargetPosition]:
        """
        Compare target positions vs current holdings.
        Returns list of deltas (orders needed).
        """
        deltas = []
        
        for target in targets:
            current_qty = self._current_positions.get(target.symbol, 0)
            delta_qty = target.target_quantity - current_qty
            
            # Skip if delta is below minimum order size
            if abs(delta_qty) < self.config.min_order_size:
                continue
            
            # Cap at max order size
            if abs(delta_qty) > self.config.max_order_size:
                delta_qty = self.config.max_order_size * (1 if delta_qty > 0 else -1)
                logger.warning(
                    f"Order capped for {target.symbol}: wanted {target.target_quantity - current_qty:.1f}, "
                    f"capped to {delta_qty:.1f}"
                )
            
            deltas.append(TargetPosition(
                sleeve_id=target.sleeve_id,
                symbol=target.symbol,
                sec_type=target.sec_type,
                target_quantity=delta_qty,  # This is now the ORDER quantity, not position target
                target_dollar_value=target.target_dollar_value,
                rationale=target.rationale,
                contract_kwargs=target.contract_kwargs,
            ))
        
        return deltas

    async def pre_trade_checks(self, order: TargetPosition) -> tuple[bool, str]:
        """
        Run risk checks before submitting an order.
        Returns (approved, reason).
        """
        # Check 1: Kill switch
        if self.kill_switch.is_active():
            return False, f"Kill switch active: {self.kill_switch.kill_reason.value}"
        
        # Check 2: Trading enabled
        if not self.config.enable_trading:
            return False, "Trading not enabled (set config.enable_trading = True)"
        
        # Check 3: Rate limit
        if self._orders_this_tick >= self.config.max_orders_per_tick:
            return False, f"Rate limit: {self.config.max_orders_per_tick} orders/tick exceeded"
        
        # Check 4: Position concentration (feeds kill switch)
        if self._portfolio_value > 0:
            estimated_position_value = abs(order.target_dollar_value)
            self.kill_switch.check_position(estimated_position_value, self._portfolio_value)
            if self.kill_switch.is_active():
                return False, "Kill switch triggered: position concentration breach"
        
        # Check 5: Daily P&L (feeds kill switch)
        self.kill_switch.check_pnl(self._daily_pnl, self._portfolio_value)
        if self.kill_switch.is_active():
            return False, "Kill switch triggered: daily P&L breach"
        
        return True, "approved"

    async def execute_targets(
        self,
        targets: list[TargetPosition],
        crisis_level: str = "NORMAL",
    ) -> list[OrderStatus]:
        """
        Main entry point. Takes target positions from orchestrator,
        calculates deltas, runs risk checks, and submits orders.
        
        Returns list of OrderStatus for each submitted order.
        """
        self._orders_this_tick = 0
        results = []
        
        # 1. Sync current positions from IBKR
        await self.sync_positions()
        
        # 2. Calculate deltas
        deltas = self.calculate_deltas(targets)
        
        if not deltas:
            logger.debug("No position changes needed")
            return results
        
        logger.info(f"Processing {len(deltas)} order(s)")
        
        # 3. Submit each delta as an order
        for delta in deltas:
            # Pre-trade risk check
            approved, reason = await self.pre_trade_checks(delta)
            
            if not approved:
                logger.warning(f"Order REJECTED for {delta.symbol}: {reason}")
                self.kill_switch.record_rejection()
                
                self.audit.log_order(
                    sleeve_id=delta.sleeve_id,
                    symbol=delta.symbol,
                    side="REJECTED",
                    qty=delta.target_quantity,
                    order_type="N/A",
                    crisis_level=crisis_level,
                    portfolio_value=self._portfolio_value,
                    daily_pnl=self._daily_pnl,
                )
                
                results.append(OrderStatus(
                    order_id=-1,
                    symbol=delta.symbol,
                    side="REJECTED",
                    quantity=abs(delta.target_quantity),
                    order_type="N/A",
                    status="Rejected",
                    error_msg=reason,
                ))
                continue
            
            # Determine side
            side = OrderSide.BUY if delta.target_quantity > 0 else OrderSide.SELL
            qty = abs(delta.target_quantity)
            
            # Submit order
            status = await self.ibkr.submit_order(
                symbol=delta.symbol,
                side=side,
                quantity=qty,
                order_type=self.config.default_order_type,
                sec_type=delta.sec_type,
                **delta.contract_kwargs,
            )
            
            if status:
                self._orders_this_tick += 1
                self._pending_orders[status.order_id] = status
                
                if status.status != "Error":
                    self.kill_switch.record_fill()  # Optimistic — update on actual fill
                
                self.audit.log_order(
                    sleeve_id=delta.sleeve_id,
                    symbol=delta.symbol,
                    side=side.value,
                    qty=qty,
                    order_type=self.config.default_order_type.value,
                    crisis_level=crisis_level,
                    portfolio_value=self._portfolio_value,
                    daily_pnl=self._daily_pnl,
                )
                
                results.append(status)
        
        return results

    async def emergency_flatten(self, reason: str = "manual"):
        """
        Emergency: flatten all positions and cancel all orders.
        Called by kill switch or SmartBunker crisis protocol.
        """
        logger.critical(f"EMERGENCY FLATTEN: {reason}")
        
        self.audit.log_kill_switch(
            reason=reason,
            portfolio_value=self._portfolio_value,
            daily_pnl=self._daily_pnl,
        )
        
        closed = await self.ibkr.flatten_all(reason=reason)
        logger.critical(f"Emergency flatten complete: {closed} positions closed")
        return closed

    def get_status(self) -> dict:
        """Status snapshot for dashboard."""
        return {
            "connected": self.ibkr.is_connected(),
            "trading_enabled": self.config.enable_trading,
            "paper_mode": self.config.paper_mode,
            "portfolio_value": self._portfolio_value,
            "daily_pnl": self._daily_pnl,
            "positions": dict(self._current_positions),
            "pending_orders": len(self._pending_orders),
            "orders_this_tick": self._orders_this_tick,
            "kill_switch": self.kill_switch.status(),
        }
