import json
import time
import os
from flask import Flask, request
from binance.um_futures import UMFutures
from binance.error import ClientError

app = Flask(__name__)

# Binance Credentials (loaded from environment variables)
BINANCE_API_KEY = "WMi5r5amHglmbWeWOzcdmIMKoOCtpfr8stZA9MW2NZcTQFfXjTP2ZOsLurnniHHo"
BINANCE_API_SECRET  = "Rpd0ibB2vLPWYnvEuYiZq47uAriOt0M7OMJkEpIdNsCQt47QKk1R7RbxVsMG1QJ9"

client = UMFutures(key=BINANCE_API_KEY, secret=BINANCE_API_SECRET)

# Cancel all open orders for a symbol
def cancel_all_orders(symbol):
    try:
        open_orders = client.get_orders(symbol=symbol)
        for order in open_orders:
            client.cancel_order(symbol=symbol, orderId=order['orderId'])
        print(f"✅ All open orders cancelled for {symbol}")
    except ClientError as e:
        print(f"❌ Error cancelling orders: {e}")

# Place limit entry order
def place_limit_entry(symbol, side, entry_price, qty):
    try:
        order = client.new_order(
            symbol=symbol,
            side=side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=qty,
            price=entry_price
        )
        print(f"📌 Limit {side} order placed at {entry_price}")
        return order['orderId']
    except ClientError as e:
        print(f"❌ Error placing limit order: {e}")
        return None

# Wait for entry to fill
def wait_for_fill(symbol, order_id):
    while True:
        order = client.get_order(symbol=symbol, orderId=order_id)
        if order['status'] == "FILLED":
            print(f"✅ Entry order filled for {symbol}")
            return
        time.sleep(1)

# Place TP and SL
def place_tp_sl(symbol, side, tp_price, sl_price, qty):
    try:
        # Take Profit
        client.new_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="TAKE_PROFIT_MARKET",
            stopPrice=tp_price,
            closePosition=True
        )
        # Stop Loss
        client.new_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="STOP_MARKET",
            stopPrice=sl_price,
            closePosition=True
        )
        print(f"🎯 TP at {tp_price} and 🛑 SL at {sl_price} set.")
    except ClientError as e:
        print(f"❌ Error placing TP/SL: {e}")

# Main handler
def handle_alert(alert_json):
    try:
        data = json.loads(alert_json)
        symbol = data["symbol"]
        side = data["side"].upper()
        entry = str(data["entry"])
        sl = str(data["sl"])
        tp = str(data["tp"])
        qty = str(data["qty"])

        # If cancel action
        if data.get("action") == "CANCEL":
            cancel_all_orders(symbol)
            return

        # Cancel any open orders
        cancel_all_orders(symbol)

        # Place limit order
        order_id = place_limit_entry(symbol, side, entry, qty)
        if not order_id:
            return

        # Wait for it to fill
        wait_for_fill(symbol, order_id)

        # Place TP & SL after fill
        place_tp_sl(symbol, side, tp, sl, qty)

    except json.JSONDecodeError:
        print("❌ Invalid alert JSON.")

# Flask webhook endpoint for TradingView alerts
@app.route('/webhook', methods=['POST'])
def webhook():
    alert_json = request.get_data(as_text=True)
    print(f"Received alert: {alert_json}")  # Log for debugging
    handle_alert(alert_json)
    return {"status": "success"}, 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

 

