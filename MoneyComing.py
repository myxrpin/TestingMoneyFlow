import os
import time
from flask import Flask, request, jsonify
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    ConfigurationRestAPI,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
)

# ---------------- Configuration ----------------
API_KEY = os.getenv("BINANCE_API_KEY", "WMi5r5amHglmbWeWOzcdmIMKoOCtpfr8stZA9MW2NZcTQFfXjTP2ZOsLurnniHHo")
API_SECRET = os.getenv("BINANCE_API_SECRET", "Rpd0ibB2vLPWYnvEuYiZq47uAriOt0M7OMJkEpIdNsCQt47QKk1R7RbxVsMG1QJ9")
BASE_PATH = os.getenv("BASE_PATH", DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL)

FILL_WAIT_TIMEOUT = int(os.getenv("FILL_WAIT_TIMEOUT", "120"))  # seconds to wait for fill
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))         # seconds between checks

if not API_KEY or not API_SECRET:
    raise ValueError("Missing Binance API credentials")

config = ConfigurationRestAPI(api_key=API_KEY, api_secret=API_SECRET, base_path=BASE_PATH)
client = DerivativesTradingUsdsFutures(config_rest_api=config)

app = Flask(__name__)

# ---------------- Helper Functions ----------------
def _resp_to_dict(resp):
    """Convert SDK response to a plain dictionary."""
    try:
        if hasattr(resp, "to_dict") and callable(resp.to_dict):
            return resp.to_dict()
        if hasattr(resp, "data") and callable(resp.data):
            return resp.data()
        if isinstance(resp, dict):
            return resp
    except Exception:
        pass
    return {"raw": str(resp)}

def _extract_order_id(resp_dict):
    """Extract order ID from various response formats."""
    for key in ("orderId", "order_id", "clientOrderId", "client_order_id"):
        if key in resp_dict:
            return resp_dict[key]
    data = resp_dict.get("data") or resp_dict.get("result")
    if isinstance(data, dict):
        for key in ("orderId", "order_id", "clientOrderId"):
            if key in data:
                return data[key]
    return None

def _call_rest(method_names, **kwargs):
    """Try calling REST API methods in order until one works."""
    for name in method_names:
        func = getattr(client.rest_api, name, None)
        if callable(func):
            return func(**kwargs)
    raise AttributeError(f"No method found for {method_names}")

# ---------------- Binance Actions ----------------
def cancel_all_open_orders(symbol):
    """Cancel all open orders for a symbol."""
    try:
        resp = _call_rest(["cancel_all_open_orders"], symbol=symbol)
        return _resp_to_dict(resp)
    except Exception as e:
        return {"error": str(e)}

def place_limit_entry(symbol, side, entry_price, qty):
    """Place a GTC limit entry order."""
    try:
        resp = _call_rest(
            ["new_order"],
            symbol=symbol,
            side=side,
            type="LIMIT",
            timeInForce="GTC",
            quantity=str(qty),
            price=str(entry_price)
        )
        d = _resp_to_dict(resp)
        oid = _extract_order_id(d)
        return oid, d
    except Exception as e:
        return None, {"error": str(e)}

def get_order_status(symbol, order_id):
    """Check the status of an order."""
    try:
        resp = _call_rest(["get_order"], symbol=symbol, orderId=order_id)
        return _resp_to_dict(resp)
    except Exception as e:
        return {"error": str(e)}

def wait_for_fill(symbol, order_id, timeout=FILL_WAIT_TIMEOUT, poll=POLL_INTERVAL):
    """Wait until the order is filled or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status_resp = get_order_status(symbol, order_id)
        if status_resp.get("error"):
            return False, status_resp
        status = (status_resp.get("status")
                  or status_resp.get("orderStatus")
                  or (status_resp.get("data") or {}).get("status", "")).upper()
        if status == "FILLED":
            return True, status_resp
        if status in ("CANCELED", "REJECTED", "EXPIRED"):
            return False, status_resp
        time.sleep(poll)
    return False, {"status": "TIMEOUT"}

def place_tp_sl_after_fill(symbol, side, tp_price, sl_price):
    """Place Take Profit and Stop Loss after entry is filled."""
    try:
        opposite = "SELL" if side == "BUY" else "BUY"

        tp_resp = _call_rest(
            ["new_order"],
            symbol=symbol,
            side=opposite,
            type="TAKE_PROFIT_MARKET",
            stopPrice=str(tp_price),
            closePosition=True
        )

        sl_resp = _call_rest(
            ["new_order"],
            symbol=symbol,
            side=opposite,
            type="STOP_MARKET",
            stopPrice=str(sl_price),
            closePosition=True
        )

        return {"tp": _resp_to_dict(tp_resp), "sl": _resp_to_dict(sl_resp)}
    except Exception as e:
        return {"error": str(e)}

# ---------------- Webhook Endpoint ----------------
@app.route("/webhook", methods=["POST"])
def webhook():
    if not request.is_json:
        return jsonify({"status": "error", "message": "Expected JSON"}), 400

    data = request.get_json()
    app.logger.info("Received payload: %s", data)

    # Cancel request
    if data.get("action", "").upper() == "CANCEL":
        symbol = data.get("symbol")
        if not symbol:
            return jsonify({"status": "error", "message": "Missing symbol for cancel"}), 400
        res = cancel_all_open_orders(symbol)
        return jsonify({"status": "cancelled", "result": res}), 200

    # Trade request
    try:
        symbol = data["symbol"]
        side = data["side"].upper()
        entry = data["entry"]
        tp = data["tp"]
        sl = data["sl"]
        qty = data["qty"]
    except KeyError as ke:
        return jsonify({"status": "error", "message": f"Missing field {ke}"}), 400

    # Step 1: Cancel existing orders
    cancel_result = cancel_all_open_orders(symbol)
    app.logger.info("Cancel result: %s", cancel_result)

    # Step 2: Place limit entry
    order_id, place_resp = place_limit_entry(symbol, side, entry, qty)
    if not order_id:
        return jsonify({"status": "error", "message": "Failed to place limit", "detail": place_resp}), 500
    app.logger.info("Placed LIMIT order id=%s resp=%s", order_id, place_resp)

    # Step 3: Wait for fill
    filled, final_status = wait_for_fill(symbol, order_id)
    if not filled:
        _call_rest(["cancel_order"], symbol=symbol, orderId=order_id)
        return jsonify({"status": "error", "message": "Entry not filled", "detail": final_status}), 409

    # Step 4: Place TP & SL
    tp_sl = place_tp_sl_after_fill(symbol, side, tp, sl)
    return jsonify({
        "status": "ok",
        "entry_order_id": order_id,
        "entry_response": place_resp,
        "tp_sl": tp_sl
    }), 200

# ---------------- Healthcheck ----------------
@app.route("/", methods=["GET"])
def index():
    return "OK - webhook running"

# ---------------- Main ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
