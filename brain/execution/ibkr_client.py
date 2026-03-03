"""
MATRIX PROTOCOL™ v1.0 — IBKR Client

Wrapper around ib_insync for TWS/Gateway connection.
Handles connection management, market data, and order submission.

Requirements:
    pip install ib_insync

Connection:
    Paper trading: port 7497 (TWS) or 4002 (Gateway)
    Live trading:  port 7496 (TWS) or 4001 (Gateway)
"""

import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger("matrix.execution.ibkr")


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"
    STOP_LIMIT = "STP LMT"
    MIDPRICE = "MIDPRICE"


@dataclass
class IBKRConfig:
    """IBKR connection configuration."""
    host: str = "127.0.0.1"
    port: int = 7497              # 7497=TWS paper, 4002=Gateway paper
    client_id: int = 1
    timeout: int = 30
    readonly: bool = False        # True = market data only, no orders
    account: str = ""             # Auto-detected if empty
    max_reconnect_attempts: int = 5
    reconnect_delay: float = 5.0  # seconds


@dataclass
class Position:
    """Current position in an instrument."""
    symbol: str
    quantity: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    account: str = ""


@dataclass
class OrderStatus:
    """Status of a submitted order."""
    order_id: int
    symbol: str
    side: str
    quantity: float
    order_type: str
    status: str             # Submitted, Filled, Cancelled, Error
    filled_qty: float = 0
    avg_fill_price: float = 0
    submit_time: Optional[str] = None
    fill_time: Optional[str] = None
    error_msg: str = ""


@dataclass
class AccountSummary:
    """Account-level summary data."""
    account_id: str
    net_liquidation: float
    total_cash: float
    buying_power: float
    unrealized_pnl: float
    realized_pnl: float
    daily_pnl: float = 0.0
    timestamp: str = ""


class IBKRClient:
    """
    IBKR connection manager.
    
    Usage:
        client = IBKRClient()
        await client.connect()
        
        # Market data
        price = await client.get_price("ES", "FUT")
        
        # Orders
        status = await client.submit_order("ES", OrderSide.BUY, 1, OrderType.MARKET)
        
        # Positions
        positions = await client.get_positions()
        
        await client.disconnect()
    """

    def __init__(self, config: Optional[IBKRConfig] = None):
        self.config = config or IBKRConfig()
        self.state = ConnectionState.DISCONNECTED
        self._ib = None  # ib_insync.IB instance
        self._contracts_cache: dict[str, object] = {}
        self._qualified_contracts: set[str] = set()  # Track qualified contract keys
        self._last_prices: dict[str, float] = {}  # Last-known prices as fallback
        self._order_callbacks: list[Callable] = []
        self._reconnect_count = 0

    async def connect(self) -> bool:
        """
        Connect to TWS/Gateway.
        Returns True if connected successfully.
        """
        try:
            from ib_insync import IB
        except ImportError:
            logger.error("ib_insync not installed. Run: pip install ib_insync")
            self.state = ConnectionState.ERROR
            return False

        self.state = ConnectionState.CONNECTING
        self._ib = IB()

        try:
            await self._ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                timeout=self.config.timeout,
                readonly=self.config.readonly,
            )
            
            self.state = ConnectionState.CONNECTED
            self._reconnect_count = 0

            # Auto-detect account if not specified
            if not self.config.account and self._ib.managedAccounts():
                self.config.account = self._ib.managedAccounts()[0]

            # Set up disconnect handler
            self._ib.disconnectedEvent += self._on_disconnect

            logger.info(
                f"Connected to IBKR: {self.config.host}:{self.config.port} "
                f"account={self.config.account}"
            )
            return True

        except Exception as e:
            logger.error(f"IBKR connection failed: {e}")
            self.state = ConnectionState.ERROR
            return False

    async def disconnect(self):
        """Gracefully disconnect from TWS/Gateway."""
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
        self.state = ConnectionState.DISCONNECTED
        logger.info("Disconnected from IBKR")

    def _on_disconnect(self):
        """Handle unexpected disconnection."""
        self.state = ConnectionState.DISCONNECTED
        logger.warning("IBKR disconnected unexpectedly")

    async def reconnect(self) -> bool:
        """Attempt reconnection with exponential backoff."""
        while self._reconnect_count < self.config.max_reconnect_attempts:
            self._reconnect_count += 1
            delay = self.config.reconnect_delay * self._reconnect_count
            logger.info(f"Reconnect attempt {self._reconnect_count}/{self.config.max_reconnect_attempts} in {delay}s")
            await asyncio.sleep(delay)

            if await self.connect():
                return True

        logger.critical("Max reconnection attempts exceeded")
        return False

    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._ib is not None and self._ib.isConnected()

    # ─── Contract Creation ──────────────────────────────────────────

    def _make_contract(self, symbol: str, sec_type: str, **kwargs):
        """
        Create an IBKR contract object.
        
        Common sec_types:
            STK  = Stock/ETF (IEF, SPY)
            FUT  = Futures (ES, ZN, ZF, NQ)
            OPT  = Options (SPX puts, VIX calls)
            CASH = Forex
        """
        from ib_insync import Stock, Future, Option, Forex, Contract

        cache_key = f"{symbol}_{sec_type}_{kwargs}"
        if cache_key in self._contracts_cache:
            return self._contracts_cache[cache_key]

        if sec_type == "STK":
            contract = Stock(symbol, "SMART", "USD", **kwargs)
        elif sec_type == "FUT":
            exchange = kwargs.pop("exchange", "CME")
            contract = Future(symbol, exchange=exchange, **kwargs)
        elif sec_type == "OPT":
            contract = Option(symbol, **kwargs)
        elif sec_type == "CASH":
            contract = Forex(symbol, **kwargs)
        else:
            contract = Contract(symbol=symbol, secType=sec_type, **kwargs)

        self._contracts_cache[cache_key] = contract
        return contract

    # ─── Market Data ────────────────────────────────────────────────

    async def get_price(self, symbol: str, sec_type: str = "STK", **kwargs) -> Optional[float]:
        """Get current market price for a symbol."""
        if not self.is_connected():
            logger.error("Not connected to IBKR")
            return self._last_prices.get(symbol)

        contract = self._make_contract(symbol, sec_type, **kwargs)
        cache_key = f"{symbol}_{sec_type}_{kwargs}"

        try:
            # Only qualify contract once per session
            if cache_key not in self._qualified_contracts:
                self._ib.qualifyContracts(contract)
                self._qualified_contracts.add(cache_key)

            ticker = self._ib.reqMktData(contract, genericTickList="", snapshot=True)

            # Reduced polling: 15 iterations × 0.1s = 1.5s max (was 5s)
            for _ in range(15):
                await asyncio.sleep(0.1)
                if ticker.last is not None and ticker.last > 0:
                    self._ib.cancelMktData(contract)
                    self._last_prices[symbol] = float(ticker.last)
                    return float(ticker.last)
                if ticker.close is not None and ticker.close > 0:
                    self._ib.cancelMktData(contract)
                    self._last_prices[symbol] = float(ticker.close)
                    return float(ticker.close)

            self._ib.cancelMktData(contract)

            # Fall back to last known price
            if symbol in self._last_prices:
                logger.warning(f"No fresh price for {symbol}, using last known: {self._last_prices[symbol]}")
                return self._last_prices[symbol]

            logger.warning(f"No price data for {symbol}")
            return None

        except Exception as e:
            logger.error(f"Price request failed for {symbol}: {e}")
            return self._last_prices.get(symbol)

    async def get_vix(self) -> Optional[float]:
        """Get current VIX level — critical for crisis protocols."""
        return await self.get_price("VIX", "IND", exchange="CBOE")

    # ─── Order Management ───────────────────────────────────────────

    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        sec_type: str = "STK",
        **contract_kwargs,
    ) -> Optional[OrderStatus]:
        """
        Submit an order to IBKR.
        
        Returns OrderStatus with order_id for tracking.
        """
        if not self.is_connected():
            logger.error("Not connected — cannot submit order")
            return None

        if self.config.readonly:
            logger.error("Client is readonly — cannot submit orders")
            return None

        from ib_insync import MarketOrder, LimitOrder, StopOrder, StopLimitOrder

        contract = self._make_contract(symbol, sec_type, **contract_kwargs)

        try:
            self._ib.qualifyContracts(contract)
        except Exception as e:
            logger.error(f"Contract qualification failed for {symbol}: {e}")
            return None

        # Build order object
        action = side.value
        qty = abs(quantity)

        if order_type == OrderType.MARKET:
            order = MarketOrder(action, qty)
        elif order_type == OrderType.LIMIT:
            if limit_price is None:
                logger.error("Limit order requires limit_price")
                return None
            order = LimitOrder(action, qty, limit_price)
        elif order_type == OrderType.STOP:
            if stop_price is None:
                logger.error("Stop order requires stop_price")
                return None
            order = StopOrder(action, qty, stop_price)
        elif order_type == OrderType.STOP_LIMIT:
            if limit_price is None or stop_price is None:
                logger.error("Stop-limit order requires both prices")
                return None
            order = StopLimitOrder(action, qty, stop_price, limit_price)
        else:
            logger.error(f"Unsupported order type: {order_type}")
            return None

        # Submit
        try:
            trade = self._ib.placeOrder(contract, order)
            
            logger.info(
                f"Order submitted: {action} {qty} {symbol} @ {order_type.value} "
                f"| order_id={trade.order.orderId}"
            )

            return OrderStatus(
                order_id=trade.order.orderId,
                symbol=symbol,
                side=action,
                quantity=qty,
                order_type=order_type.value,
                status="Submitted",
                submit_time=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Order submission failed: {e}")
            return OrderStatus(
                order_id=-1,
                symbol=symbol,
                side=action,
                quantity=qty,
                order_type=order_type.value,
                status="Error",
                error_msg=str(e),
            )

    async def cancel_order(self, order_id: int) -> bool:
        """Cancel an open order."""
        if not self.is_connected():
            return False

        try:
            for trade in self._ib.openTrades():
                if trade.order.orderId == order_id:
                    self._ib.cancelOrder(trade.order)
                    logger.info(f"Order {order_id} cancelled")
                    return True
            logger.warning(f"Order {order_id} not found in open trades")
            return False
        except Exception as e:
            logger.error(f"Cancel failed for order {order_id}: {e}")
            return False

    async def cancel_all_orders(self) -> int:
        """Cancel ALL open orders. Emergency use."""
        if not self.is_connected():
            return 0

        cancelled = 0
        for trade in self._ib.openTrades():
            try:
                self._ib.cancelOrder(trade.order)
                cancelled += 1
            except Exception:
                pass

        logger.warning(f"CANCEL ALL: {cancelled} orders cancelled")
        return cancelled

    # ─── Position & Account ─────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        """Get all current positions."""
        if not self.is_connected():
            return []

        positions = []
        for pos in self._ib.positions():
            positions.append(Position(
                symbol=pos.contract.symbol,
                quantity=float(pos.position),
                avg_cost=float(pos.avgCost),
                market_value=float(pos.position * pos.avgCost),
                unrealized_pnl=0.0,  # Populated from PnL subscription
                realized_pnl=0.0,
                account=pos.account,
            ))

        return positions

    async def get_account_summary(self) -> Optional[AccountSummary]:
        """Get account-level summary."""
        if not self.is_connected():
            return None

        try:
            summary_items = self._ib.accountSummary(self.config.account)
            
            values = {}
            for item in summary_items:
                values[item.tag] = float(item.value) if item.value else 0

            return AccountSummary(
                account_id=self.config.account,
                net_liquidation=values.get("NetLiquidation", 0),
                total_cash=values.get("TotalCashValue", 0),
                buying_power=values.get("BuyingPower", 0),
                unrealized_pnl=values.get("UnrealizedPnL", 0),
                realized_pnl=values.get("RealizedPnL", 0),
                timestamp=datetime.utcnow().isoformat(),
            )
        except Exception as e:
            logger.error(f"Account summary failed: {e}")
            return None

    async def get_daily_pnl(self) -> float:
        """Get today's P&L — feeds the kill switch."""
        summary = await self.get_account_summary()
        if summary:
            return summary.unrealized_pnl + summary.realized_pnl
        return 0.0

    # ─── Convenience: Flatten Everything ────────────────────────────

    async def flatten_all(self, reason: str = "manual") -> int:
        """
        Close ALL positions. Emergency use / SmartBunker activation.
        Also cancels all open orders.
        """
        if not self.is_connected():
            return 0

        logger.critical(f"FLATTEN ALL POSITIONS — reason: {reason}")

        # Cancel open orders first
        await self.cancel_all_orders()

        # Close each position
        closed = 0
        for pos in self._ib.positions():
            if pos.position == 0:
                continue

            side = OrderSide.SELL if pos.position > 0 else OrderSide.BUY
            qty = abs(pos.position)

            await self.submit_order(
                symbol=pos.contract.symbol,
                side=side,
                quantity=qty,
                order_type=OrderType.MARKET,
                sec_type=pos.contract.secType,
            )
            closed += 1

        logger.critical(f"Flattened {closed} positions")
        return closed
