from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import os
import uuid
import requests
from datetime import datetime

load_dotenv()

app = Flask(__name__)
RIS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@app.route("/site/<path:filename>")
def serve_site(filename):
    return send_from_directory(RIS_ROOT, filename)
CORS(app)
APP_NAME = "RIS - Reliable Internet Services"

FLUTTERWAVE_SECRET_KEY = os.getenv("FLW_SECRET_KEY")

FLUTTERWAVE_URL = "https://api.flutterwave.com/v3/payments"

payments = {}


# =========================================================
# HOME
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "success": True,
        "message": f"{APP_NAME} backend is running",
        "service": "RIS Payment API"
    })


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "status": "online",
        "service": "RIS Backend",
        "flutterwave_configured": bool(FLUTTERWAVE_SECRET_KEY)
    })


# =========================================================
# CREATE FLUTTERWAVE PAYMENT
# =========================================================

@app.route("/api/payments/flutterwave", methods=["POST"])
def create_flutterwave_payment():
    data = request.get_json() or {}

    customer_id = str(data.get("customer_id", "")).strip()
    customer_name = str(data.get("customer_name", "")).strip()
    email = str(data.get("email", "")).strip()
    phone = str(data.get("phone", "")).strip()

    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0

    if not customer_id:
        return jsonify({
            "success": False,
            "message": "Customer ID is required."
        }), 400

    if not customer_name:
        return jsonify({
            "success": False,
            "message": "Customer name is required."
        }), 400

    if not email:
        return jsonify({
            "success": False,
            "message": "Email is required."
        }), 400

    if not phone:
        return jsonify({
            "success": False,
            "message": "Phone number is required."
        }), 400

    if amount <= 0:
        return jsonify({
            "success": False,
            "message": "Payment amount must be greater than zero."
        }), 400

    if not FLUTTERWAVE_SECRET_KEY:
        return jsonify({
            "success": False,
            "message": "Flutterwave secret key is not configured."
        }), 500

    tx_ref = "RIS-" + uuid.uuid4().hex[:14].upper()

    redirect_url = (
        "http://localhost:5000/site/pages/payment-result.html"
    )

    payload = {
        "tx_ref": tx_ref,
        "amount": amount,
        "currency": "UGX",
        "redirect_url": redirect_url,
        "customer": {
            "email": email,
            "name": customer_name,
            "phonenumber": phone
        },
        "payment_options": "card, mobilemoneyuganda",
        "customizations": {
            "title": "RIS Internet Services",
            "description": "Internet service payment",
            "logo": ""
        },
        "meta": {
            "customer_id": customer_id
        }
    }

    headers = {
        "Authorization": f"Bearer {FLUTTERWAVE_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            FLUTTERWAVE_URL,
            json=payload,
            headers=headers,
            timeout=30
        )

        try:
            result = response.json()
        except ValueError:
            result = {
                "raw_response": response.text
            }

        if response.status_code >= 400:
            print("==========================================")
            print("FLUTTERWAVE ERROR")
            print("HTTP STATUS:", response.status_code)
            print("RESPONSE:", result)
            print("==========================================")

            return jsonify({
                "success": False,
                "message": "Flutterwave rejected the payment request.",
                "details": result
            }), response.status_code

    except requests.exceptions.RequestException as error:
        print("==========================================")
        print("FLUTTERWAVE CONNECTION ERROR")
        print("ERROR:", error)
        print("==========================================")

        return jsonify({
            "success": False,
            "message": "Could not connect to Flutterwave.",
            "details": str(error)
        }), 500

    payment_link = (
        result.get("data", {}).get("link")
        if isinstance(result, dict)
        else None
    )

    if not payment_link:
        print("==========================================")
        print("FLUTTERWAVE DID NOT RETURN PAYMENT LINK")
        print("RESPONSE:", result)
        print("==========================================")

        return jsonify({
            "success": False,
            "message": "Flutterwave did not return a payment link.",
            "details": result
        }), 500

    payment = {
        "transaction_id": result.get("data", {}).get("id"),
        "tx_ref": tx_ref,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "email": email,
        "phone": phone,
        "amount": amount,
        "currency": "UGX",
        "status": "pending",
        "payment_gateway": "Flutterwave",
        "created_at": datetime.utcnow().isoformat(),
        "payment_link": payment_link
    }

    payments[tx_ref] = payment

    return jsonify({
        "success": True,
        "message": "Flutterwave payment created.",
        "tx_ref": tx_ref,
        "payment": payment,
        "payment_link": payment_link
    }), 200
@app.route("/api/payments/<tx_ref>", methods=["GET"])
def get_payment(tx_ref):

    payment = payments.get(tx_ref)

    if not payment:
        return jsonify({
            "success": False,
            "message": "Payment not found."
        }), 404

    return jsonify({
        "success": True,
        "payment": payment
    })


# =========================================================
# TEST SUCCESS
# =========================================================
@app.route("/api/payments/verify/<tx_ref>", methods=["GET"])
def verify_flutterwave_payment(tx_ref):
    payment = payments.get(tx_ref)

    if not payment:
        return jsonify({
            "success": False,
            "message": "Payment transaction was not found."
        }), 404

    transaction_id = payment.get("transaction_id")

    # The local transaction_id is not necessarily Flutterwave's
    # transaction ID, so we need the Flutterwave transaction ID.
    if not transaction_id:
        return jsonify({
            "success": False,
            "message": "Flutterwave transaction ID is missing."
        }), 400

    url = f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify"

    headers = {
        "Authorization": f"Bearer {FLUTTERWAVE_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )

        result = response.json()

    except requests.exceptions.RequestException as error:
        return jsonify({
            "success": False,
            "message": "Could not connect to Flutterwave.",
            "details": str(error)
        }), 500

    except ValueError:
        return jsonify({
            "success": False,
            "message": "Flutterwave returned an invalid response.",
            "details": response.text
        }), 500

    if response.status_code >= 400:
        return jsonify({
            "success": False,
            "message": "Flutterwave verification failed.",
            "details": result
        }), response.status_code

    transaction = result.get("data", {})

    status = transaction.get("status")
    verified_tx_ref = transaction.get("tx_ref")
    currency = transaction.get("currency")
    amount = float(transaction.get("amount", 0) or 0)

    expected_amount = float(payment.get("amount", 0) or 0)

    if verified_tx_ref != tx_ref:
        return jsonify({
            "success": False,
            "message": "Transaction reference does not match.",
            "details": result
        }), 400

    if currency != payment.get("currency"):
        return jsonify({
            "success": False,
            "message": "Transaction currency does not match.",
            "details": result
        }), 400

    if amount < expected_amount:
        return jsonify({
            "success": False,
            "message": "The amount paid is less than the expected amount.",
            "details": result
        }), 400

    if status == "successful":
        payment["status"] = "successful"
        payment["flutterwave_transaction_id"] = transaction.get("id")
        payment["flw_ref"] = transaction.get("flw_ref")
        payment["verified_at"] = datetime.utcnow().isoformat()

        return jsonify({
            "success": True,
            "message": "Payment verified successfully.",
            "payment": payment,
            "flutterwave_transaction": transaction
        }), 200

    payment["status"] = status or "pending"

    return jsonify({
        "success": False,
        "message": f"Payment status is {status}.",
        "payment": payment,
        "flutterwave_transaction": transaction
    }), 200
@app.route("/api/payments/test-success/<tx_ref>", methods=["POST"])
def test_payment_success(tx_ref):

    payment = payments.get(tx_ref)

    if not payment:
        return jsonify({
            "success": False,
            "message": "Payment not found."
        }), 404

    payment["status"] = "successful"
    payment["verified"] = True
    payment["verified_at"] = datetime.utcnow().isoformat()

    return jsonify({
        "success": True,
        "message": "Test payment marked as successful.",
        "payment": payment
    })


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    print("")
    print("==========================================")
    print(" RIS - Reliable Internet Services")
    print(" Flutterwave Payment Backend")
    print("==========================================")
    print(" Server: http://127.0.0.1:5000")
    print(" Health: http://127.0.0.1:5000/api/health")
    print(" Flutterwave:", "CONFIGURED" if FLUTTERWAVE_SECRET_KEY else "NOT CONFIGURED")
    print("==========================================")
    print("")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )