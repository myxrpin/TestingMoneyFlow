# 10AUG.py
from flask import Flask, request, jsonify
from binance.client import Client
from binance.enums import (
    SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_TAKE_PROFIT_MARKET,
    ORDER_TYPE_STOP_MARKET,
    TIME_IN_FORCE_GTC
)
import os, json

app = Flask(__name__)

# Binance credentials from Render Environment Variables
BINANCE_API_KEY    = os.environ.get("WMi5r5amHglmbWeWOzcdmIMKoOCtpfr8stZA9MW2NZcTQFfXjTP2ZOsLurnniHHo")
BINANCE_API_SECRET = os.environ.get("Rpd0ibB2vLPWYnvEuYiZq47uAriOt0M7OMJkEpIdNsCQt47QKk1R7RbxVsMG1QJ9")

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise ValueError("❌ BINANCE_API_KEY or BINANCE_API_SECRET not set!")


client = Client(BINANCE_API_KEY, BINANCE_API_SECRET, testnet=True)  # testnet=True for safety


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print(f"📩 Received alert: {data}")

        symbol = data.get("symbol")
        side = data.get("side").upper()
        qty = float(data.get("qty"))
        entry = float(data.get("entry"))
        tp = float(data.get("tp"))
        sl = float(data.get("sl"))

        if not all([symbol, side, qty, entry, tp, sl]):
            return jsonify({"error": "Invalid data"}), 400

        # 1️⃣ Place limit order
        order = client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "BUY" else SIDE_SELL,
            type=ORDER_TYPE_LIMIT,
            price=entry,
            quantity=qty,
            timeInForce=TIME_IN_FORCE_GTC
        )

        print(f"✅ Limit order placed: {order}")

        # 2️⃣ Place TP & SL orders (once entry is filled)
        opposite_side = SIDE_SELL if side == "BUY" else SIDE_BUY

        # Take Profit
        tp_order = client.futures_create_order(
            symbol=symbol,
            side=opposite_side,
            type=ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=tp,
            closePosition=True
        )

        # Stop Loss
        sl_order = client.futures_create_order(
            symbol=symbol,
            side=opposite_side,
            type=ORDER_TYPE_STOP_MARKET,
            stopPrice=sl,
            closePosition=True
        )

        print(f"🎯 TP order placed: {tp_order}")
        print(f"🛑 SL order placed: {sl_order}")

        return jsonify({
            "status": "Limit order placed with TP/SL",
            "entry_order": order,
            "tp_order": tp_order,
            "sl_order": sl_order
        }), 200

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return jsonify({"error": str(e)}), 500