# app.py
from flask import Flask, request, jsonify
from binance.client import Client
import os
import traceback

app = Flask(__name__)

# =========================
# Binance API keys
# =========================
BINANCE_API_KEY =  "WMi5r5amHglmbWeWOzcdmIMKoOCtpfr8stZA9MW2NZcTQFfXjTP2ZOsLurnniHHo" 
BINANCE_API_SECRET =  "Rpd0ibB2vLPWYnvEuYiZq47uAriOt0M7OMJkEpIdNsCQt47QKk1R7RbxVsMG1QJ9" 
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Initialize Binance client
client = Client(API_KEY, API_SECRET, testnet=False)  # testnet=True for testing

@app.route("/", methods=["GET"])
def home():
    return "Binance Webhook Server Running!", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        print("===== Incoming TradingView Alert =====")
        print(data)

        # Validate JSON
        if not data or "symbol" not in data or "side" not in data:
            return jsonify({"status": "error", "message": "Missing required fields"}), 200  # Still return 200

        symbol = data["symbol"].upper()
        side = data["side"].upper()  # BUY or SELL
        quantity = float(data.get("quantity", 0.001))  # Default quantity

        # Binance order
        if side == "BUY":
            order = client.futures_create_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quantity=quantity
            )
        elif side == "SELL":
            order = client.futures_create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=quantity
            )
        else:
            return jsonify({"status": "error", "message": "Invalid side"}), 200

        print("Order response:", order)
        return jsonify({"status": "success", "order": order}), 200

    except Exception as e:
        print("===== ERROR OCCURRED =====")
        print(e)
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 200  # Always return 200 to avoid TradingView retries


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
