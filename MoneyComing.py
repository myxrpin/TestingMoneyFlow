import os
import json
import time
from flask import Flask, request
from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import DerivativesTradingUsdsFutures
from binance_sdk_derivatives_trading_usds_futures.rest_api.exceptions import RestAPIException, ClientError, UnauthorizedError, TooManyRequestsError
from dotenv import load_dotenv

# Load environment variables from .env file (optional for local development)
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
 
BINANCE_API_KEY = os.getenv("WMi5r5amHglmbWeWOzcdmIMKoOCtpfr8stZA9MW2NZcTQFfXjTP2ZOsLurnniHHo")
BINANCE_API_SECRET = os.getenv("Rpd0ibB2vLPWYnvEuYiZq47uAriOt0M7OMJkEpIdNsCQt47QKk1R7RbxVsMG1QJ9")

# Validate API keys
if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise ValueError("❌ BINANCE_API_KEY or BINANCE_API_SECRET not set in environment variables")

# Configure Binance client (Production)
config = ConfigurationRestAPI(
    api_key=BINANCE_API_KEY,
    api_secret=BINANCE_API_SECRET,
    base_path=DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
    timeout=1000,  # Set timeout to 1 second
    retries=3  # Retry failed requests up to 3 times
)
client = DerivativesTradingUsdsFutures(config_rest_api=config)

# Uncomment for Testnet
# from binance_common.constants import DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL
# config = ConfigurationRestAPI(
#     api_key=BINANCE_API_KEY,
#     api_secret=BINANCE_API_SECRET,
#     base_path=DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
#     timeout=1000,
#     retries=3
# )
# client = DerivativesTradingUsdsFutures(config_rest_api=config)

# Cancel all open orders for a symbol
def cancel_all_orders(symbol):
    try:
        open_orders = client.rest_api.get_open_orders(symbol=symbol)
        for order in open_orders:
            client.rest_api.cancel_order(symbol=symbol, orderId=order["orderId"])
        print(f"✅ All open orders cancelled for {symbol}")
    except RestAPIException as e:
        print(f"❌ Error cancelling orders: {e}")
    except UnauthorizedError:
        print(f"❌ Authentication error: Check API key and secret")
    except TooManyRequestsError:
        print(f"❌ Rate limit exceeded: Try again later")
    except Exception as e:
        print(f"❌ Unexpected error cancelling orders: {e}")

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
        print(f"📌 Limit {side} order placed at {entry_price} for {symbol}")
        return order["orderId"]
    except RestAPIException as e:
        print(f"❌ Error placing limit order: {e}")
        return None
    except UnauthorizedError:
        print(f"❌ Authentication error: Check API key and secret")
        return None
    except TooManyRequestsError:
        print(f"❌ Rate limit exceeded: Try again later")
        return None
    except Exception as e:
        print(f"❌ Unexpected error placing limit order: {e}")
        return None

# Wait until the order is filled
def wait_for_fill(symbol, order_id):
    try:
        while True:
            order = client.rest_api.get_order(symbol=symbol, orderId=order_id)
            if order["status"] == "FILLED":
                print(f"✅ Entry order filled for {symbol}")
                return True
            time.sleep(1)
    except RestAPIException as e:
        print(f"❌ Error checking order status: {e}")
        return False
    except UnauthorizedError:
        print(f"❌ Authentication error: Check API key and secret")
        return False
    except TooManyRequestsError:
        print(f"❌ Rate limit exceeded: Try again later")
        return False
    except Exception as e:
        print(f"❌ Unexpected error checking order status: {e}")
        return False

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

        print(f"🎯 TP at {tp_price} and 🛑 SL at {sl_price} set for {symbol}")
    except RestAPIException as e:
        print(f"❌ Error placing TP/SL: {e}")
    except UnauthorizedError:
        print(f"❌ Authentication error: Check API key and secret")
    except TooManyRequestsError:
        print(f"❌ Rate limit exceeded: Try again later")
    except Exception as e:
        print(f"❌ Unexpected error placing TP/SL: {e}")

# Handle alerts from TradingView
def handle_alert(alert_json):
    try:
        data = json.loads(alert_json)
        symbol = data["symbol"]
        side = data["side"].upper()
        entry = float(data["entry"])
        sl = float(data["sl"])
        tp = float(data["tp"])
        qty = float(data["qty"])

        # Cancel action
        if data.get("action") == "CANCEL":
            cancel_all_orders(symbol)
            return {"status": "success", "message": f"All orders cancelled for {symbol}"}

        # Cancel any open orders before placing new ones
        cancel_all_orders(symbol)

        # Place limit entry order
        order_id = place_limit_entry(symbol, side, entry, qty)
        if not order_id:
            return {"status": "error", "message": f"Failed to place limit order for {symbol}"}

        # Wait for fill
        if not wait_for_fill(symbol, order_id):
            return {"status": "error", "message": f"Order not filled for {symbol}"}

        # Place TP & SL after entry fill
        place_tp_sl(symbol, side, tp, sl)
        return {"status": "success", "message": f"Order placed and TP/SL set for {symbol}"}

    except json.JSONDecodeError:
        print("❌ Invalid alert JSON")
        return {"status": "error", "message": "Invalid JSON format"}
    except KeyError as e:
        print(f"❌ Missing key in alert JSON: {e}")
        return {"status": "error", "message": f"Missing key: {e}"}
    except Exception as e:
        print(f"❌ Unexpected error in handle_alert: {e}")
        return {"status": "error", "message": f"Unexpected error: {e}"}

# Flask route to handle TradingView webhook
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        alert_json = request.get_data(as_text=True)
        print(f"Received webhook: {alert_json}")
        response = handle_alert(alert_json)
        return jsonify(response), 200
    except Exception as e:
        print(f"❌ Error processing webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

# Example usage for testing locally (remove in production)
if __name__ == "__main__":
    # Example TradingView alert message
    alert_message = json.dumps({
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry": 29000.0,
        "sl": 28800.0,
        "tp": 29500.0,
        "qty": 0.001
    })
    print(handle_alert(alert_message))
    # Run Flask app (set host to 0.0.0.0 for Render)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))




 
