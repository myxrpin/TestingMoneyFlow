import os
import json
import time
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    ConfigurationRestAPI,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
)
from binance_sdk_derivatives_trading_usds_futures.exceptions import RestAPIException

 
# Binance API Keys
BINANCE_API_KEY = os.getenv("WMi5r5amHglmbWeWOzcdmIMKoOCtpfr8stZA9MW2NZcTQFfXjTP2ZOsLurnniHHo", "WMi5r5amHglmbWeWOzcdmIMKoOCtpfr8stZA9MW2NZcTQFfXjTP2ZOsLurnniHHo")
BINANCE_API_SECRET = os.getenv("Rpd0ibB2vLPWYnvEuYiZq47uAriOt0M7OMJkEpIdNsCQt47QKk1R7RbxVsMG1QJ9", "Rpd0ibB2vLPWYnvEuYiZq47uAriOt0M7OMJkEpIdNsCQt47QKk1R7RbxVsMG1QJ9")

# Configure Binance client
config = ConfigurationRestAPI(
    api_key=BINANCE_API_KEY,
    api_secret=BINANCE_API_SECRET,
    base_path=DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
)
client = DerivativesTradingUsdsFutures(config_rest_api=config)

# Cancel all open orders for a symbol
def cancel_all_orders(symbol):
    try:
        open_orders = client.rest_api.get_open_orders(symbol=symbol)
        for order in open_orders:
            client.rest_api.cancel_order(symbol=symbol, orderId=order["orderId"])
        print(f"✅ All open orders cancelled for {symbol}")
    except RestAPIException as e:
        print(f"❌ Error cancelling orders: {e}")

# Place a limit entry order
def place_limit_entry(symbol, side, entry_price, qty):
    try:
        order = client.rest_api.new_order(
            symbol=symbol,
            side=side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=str(qty),
            price=str(entry_price)
        )
        print(f"📌 Limit {side} order placed at {entry_price}")
        return order["orderId"]
    except RestAPIException as e:
        print(f"❌ Error placing limit order: {e}")
        return None

# Wait until the order is filled
def wait_for_fill(symbol, order_id):
    while True:
        order = client.rest_api.get_order(symbol=symbol, orderId=order_id)
        if order["status"] == "FILLED":
            print(f"✅ Entry order filled for {symbol}")
            return
        time.sleep(1)

# Place TP and SL after entry is filled
def place_tp_sl(symbol, side, tp_price, sl_price):
    try:
        opposite_side = "SELL" if side == "BUY" else "BUY"

        # Take Profit
        client.rest_api.new_order(
            symbol=symbol,
            side=opposite_side,
            type="TAKE_PROFIT_MARKET",
            stopPrice=str(tp_price),
            closePosition=True
        )

        # Stop Loss
        client.rest_api.new_order(
            symbol=symbol,
            side=opposite_side,
            type="STOP_MARKET",
            stopPrice=str(sl_price),
            closePosition=True
        )

        print(f"🎯 TP at {tp_price} and 🛑 SL at {sl_price} set.")
    except RestAPIException as e:
        print(f"❌ Error placing TP/SL: {e}")

# Handle alerts from TradingView
def handle_alert(alert_json):
    try:
        data = json.loads(alert_json)
        symbol = data["symbol"]
        side = data["side"].upper()
        entry = data["entry"]
        sl = data["sl"]
        tp = data["tp"]
        qty = data["qty"]

        # Cancel action
        if data.get("action") == "CANCEL":
            cancel_all_orders(symbol)
            return

        # Cancel any open orders before placing new ones
        cancel_all_orders(symbol)

        # Place limit entry order
        order_id = place_limit_entry(symbol, side, entry, qty)
        if not order_id:
            return

        # Wait for fill
        wait_for_fill(symbol, order_id)

        # Place TP & SL after entry fill
        place_tp_sl(symbol, side, tp, sl)

    except json.JSONDecodeError:
        print("❌ Invalid alert JSON.")

# Example usage with a TradingView alert message
alert_message = json.dumps({
    "symbol": "BTCUSDT",
    "side": "BUY",
    "entry": 29000.0,
    "sl": 28800.0,
    "tp": 29500.0,
    "qty": 0.001
})
handle_alert(alert_message)


 

