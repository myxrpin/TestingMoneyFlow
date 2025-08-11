# MoneyComing.py
import os
import time
import json
from flask import Flask, request, jsonify

# Official Binance USD-M Futures SDK
from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    ConfigurationRestAPI,
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
)

# ---------- Configuration ----------
 
BINANCE_API_KEY = os.getenv("WMi5r5amHglmbWeWOzcdmIMKoOCtpfr8stZA9MW2NZcTQFfXjTP2ZOsLurnniHHo", "")
BINANCE_API_SECRET = os.getenv("Rpd0ibB2vLPWYnvEuYiZq47uAriOt0M7OMJkEpIdNsCQt47QKk1R7RbxVsMG1QJ9", "")
# Optionally set BASE_PATH to testnet URL: e.g. https://testnet.binancefuture.com
BASE_PATH = os.getenv("BASE_PATH", DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL)

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in environment")

config = ConfigurationRestAPI(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET, base_path=BASE_PATH)
client = DerivativesTradingUsdsFutures(config_rest_api=config)

# Tuning
FILL_WAIT_TIMEOUT = int(os.getenv("FILL_WAIT_TIMEOUT", "120"))  # seconds to wait for limit fill
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))       # seconds between polls

app = Flask(__name__)

# ---------- Helpers ----------
def _resp_to_dict(resp):
    """Uniformly convert SDK response into a dict if possible."""
    try:
        if hasattr(resp, "data") and callable(resp.data):
            return resp.data()
        if hasattr(resp, "to_dict") and callable(resp.to_dict):
            return resp.to_dict()
        if isinstance(resp, dict):
            return resp
    except Exception:
        pass
    # Last resort: return the raw object
    return {"raw": str(resp)}

def _extract_order_id(resp_dict):
    """Try common keys for orderId."""
    for key in ("orderId", "order_id", "clientOrderId", "client_order_id"):
        if key in resp_dict:
            return resp_dict[key]
    # try nested data
    data = resp_dict.get("data") or resp_dict.get("result")
    if isinstance(data, dict):
        for key in ("orderId", "order_id", "clientOrderId"):
            if key in data:
                return data[key]
    return None

def _call_rest(method_names, **kwargs):
    """Attempt multiple candidate method names on client.rest_api to improve compatibility."""
    for name in method_names:
        func = getattr(client.rest_api, name, None)
        if callable(func):
            return func(**kwargs)
    raise AttributeError(f"No REST API method found among: {method_names}")

def cancel_all_open_orders(symbol):
    """Cancel all open orders for the symbol. Returns dict with result or error."""
    try:
        # Try common list-open-orders endpoints
        resp = _call_rest(["get_open_orders", "open_orders", "all_open_orders", "openOrders"], symbol=symbol)
        resp_d = _resp_to_dict(resp)
        # resp_d might be list or dict
        orders = resp_d if isinstance(resp_d, list) else resp_d.get("data") or resp_d.get("orders") or resp_d
        cancelled = 0
        if isinstance(orders, list):
            for o in orders:
                oid = o.get("orderId") or o.get("order_id") or o.get("orderId")
                if not oid:
                    continue
                # cancel each
                _call_rest(["cancel_order", "cancelOrder", "cancelOrders", "cancel"], symbol=symbol, orderId=oid)
                cancelled += 1
        return {"cancelled": cancelled}
    except Exception as e:
        return {"error": str(e)}

def place_limit_entry(symbol, side, entry_price, qty):
    """Place a LIMIT entry order; returns (order_id, raw_response_dict)."""
    try:
        resp = _call_rest(
            ["new_order", "order", "create_order"],
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
    """Return order status dict or {'error':...}"""
    try:
        resp = _call_rest(["get_order", "order", "getOrder", "get_order_by_id"], symbol=symbol, orderId=order_id)
        return _resp_to_dict(resp)
    except Exception as e:
        return {"error": str(e)}

def wait_for_fill(symbol, order_id, timeout=FILL_WAIT_TIMEOUT, poll=POLL_INTERVAL):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = get_order_status(symbol, order_id)
        # if error returned
        if s.get("error"):
            return False, s
        status = s.get("status") or s.get("orderStatus") or (s.get("data") or {}).get("status")
        if status == "FILLED":
            return True, s
        if status in ("CANCELED", "REJECTED", "EXPIRED"):
            return False, s
        time.sleep(poll)
    return False, {"status": "TIMEOUT"}

def place_tp_sl_after_fill(symbol, side, tp_price, sl_price):
    """Place TAKE_PROFIT_MARKET and STOP_MARKET orders to close the position."""
    try:
        opposite = "SELL" if side == "BUY" else "BUY"
        tp_resp = _call_rest(
            ["new_order", "order"],
            symbol=symbol,
            side=opposite,
            type="TAKE_PROFIT_MARKET",
            stopPrice=str(tp_price),
            closePosition=True
        )
        sl_resp = _call_rest(
            ["new_order", "order"],
            symbol=symbol,
            side=opposite,
            type="STOP_MARKET",
            stopPrice=str(sl_price),
            closePosition=True
        )
        return {"tp": _resp_to_dict(tp_resp), "sl": _resp_to_dict(sl_resp)}
    except Exception as e:
        return {"error": str(e)}

# ---------- Flask webhook ----------
@app.route("/webhook", methods=["POST"])
def webhook():
    if not request.is_json:
        return jsonify({"status":"error", "message":"Expected JSON"}), 400
    data = request.get_json()
    app.logger.info("Received payload: %s", data)

    # CANCEL action from TradingView (example: {"action":"CANCEL","symbol":"ETHUSDT"})
    if data.get("action") and data.get("action").upper() == "CANCEL":
        symbol = data.get("symbol")
        if not symbol:
            return jsonify({"status":"error", "message":"Missing symbol for cancel"}), 400
        res = cancel_all_open_orders(symbol)
        return jsonify({"status":"cancelled", "result": res}), 200

    # Required trade fields
    try:
        symbol = data["symbol"]
        side = data["side"].upper()
        entry = data["entry"]
        tp = data["tp"]
        sl = data["sl"]
        qty = data["qty"]
    except KeyError as ke:
        return jsonify({"status":"error", "message": f"Missing field {ke}"}), 400

    # 1) Cancel existing open orders for symbol (cleanup)
    cancel_result = cancel_all_open_orders(symbol)
    app.logger.info("Cancel result: %s", cancel_result)

    # 2) Place LIMIT entry
    order_id, place_resp = place_limit_entry(symbol, side, entry, qty)
    if not order_id:
        return jsonify({"status":"error", "message":"failed to place limit", "detail": place_resp}), 500

    app.logger.info("Placed LIMIT order id=%s resp=%s", order_id, place_resp)

    # 3) Wait for fill
    filled, final_status = wait_for_fill(symbol, order_id)
    if not filled:
        # Optionally cancel the order if it's still open
        try:
            _call_rest(["cancel_order","cancelOrder"], symbol=symbol, orderId=order_id)
        except Exception:
            pass
        return jsonify({"status":"error", "message":"entry not filled", "detail": final_status}), 409

    # 4) Place TP & SL
    tp_sl = place_tp_sl_after_fill(symbol, side, tp, sl)
    return jsonify({"status":"ok", "entry_order_id": order_id, "entry_response": place_resp, "tp_sl": tp_sl}), 200

@app.route("/", methods=["GET"])
def index():
    return "OK - webhook running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5000")), debug=False)



