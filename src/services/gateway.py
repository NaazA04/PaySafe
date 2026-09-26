"""
Mock External Payment Gateway Simulator.
In production this would call Stripe, Razorpay, or a bank network.
Simulates realistic payment responses including failure scenarios.
"""

import random
import time
import uuid
from typing import Dict, Any


class GatewayResponse:
    def __init__(self, success: bool, gateway_txn_id: str, message: str, error_code: str = None):
        self.success = success
        self.gateway_txn_id = gateway_txn_id
        self.message = message
        self.error_code = error_code


class ExternalPaymentGateway:
    """
    Simulates an external payment provider.
    Applies realistic failure probabilities similar to real-world gateways.
    """

    # Failure scenario table by payment method
    FAILURE_RATES = {
        "CARD": 0.10,     # 10% failure (declined cards etc.)
        "UPI":  0.05,     # 5% failure  (timeout / bank down)
        "WALLET": 0.03,   # 3% failure  (insufficient balance)
    }

    def process_payment(self, amount: float, currency: str, payment_method: str, user_id: str) -> GatewayResponse:
        """
        Simulate payment processing with a realistic delay and failure rate.
        In production, this would be an HTTPS call to the bank/card network.
        """
        # Simulate network latency (50ms - 300ms)
        time.sleep(random.uniform(0.05, 0.3))

        failure_rate = self.FAILURE_RATES.get(payment_method.upper(), 0.10)
        gateway_txn_id = f"gtw_{uuid.uuid4().hex[:16]}"

        if random.random() < failure_rate:
            # Select a random failure reason
            failure_reasons = [
                ("CARD_DECLINED",     "Card was declined by the issuing bank."),
                ("INSUFFICIENT_FUNDS","Insufficient funds in account."),
                ("GATEWAY_TIMEOUT",   "Payment gateway timed out."),
                ("INVALID_CARD",      "Card details are invalid or expired."),
                ("RISK_BLOCKED",      "Transaction blocked by fraud detection."),
            ]
            code, msg = random.choice(failure_reasons)
            return GatewayResponse(
                success=False,
                gateway_txn_id=gateway_txn_id,
                message=msg,
                error_code=code,
            )

        # Happy path: Payment authorized
        return GatewayResponse(
            success=True,
            gateway_txn_id=gateway_txn_id,
            message=f"Payment of {currency} {amount:.2f} authorized successfully via {payment_method}.",
        )

    def process_refund(self, original_gateway_txn_id: str, amount: float, currency: str) -> GatewayResponse:
        """
        Simulate refund processing. Refunds have very low failure rates.
        """
        time.sleep(random.uniform(0.02, 0.15))
        gateway_refund_id = f"ref_{uuid.uuid4().hex[:16]}"

        # 2% refund failure rate
        if random.random() < 0.02:
            return GatewayResponse(
                success=False,
                gateway_txn_id=gateway_refund_id,
                message="Refund rejected by gateway.",
                error_code="REFUND_REJECTED",
            )

        return GatewayResponse(
            success=True,
            gateway_txn_id=gateway_refund_id,
            message=f"Refund of {currency} {amount:.2f} processed successfully.",
        )
