"""
Sample Order Processor Service.
Consumes authentication tokens and processes customer transactions.
"""

from auth.jwt_handler import JWTHandler

auth_handler = JWTHandler()


class OrderProcessor:
    """Handles cart checkout and user order placement."""

    def __init__(self):
        self.orders = []

    def process_order(self, auth_token: str, item_id: str, quantity: int) -> dict:
        """
        Processes an item purchase after verifying customer token.
        Raises ValueError if auth token is invalid or expired.
        """
        # Call JWTHandler.verify_token to validate customer
        user_session = auth_handler.verify_token(auth_token)

        order_record = {
            "order_id": f"ORD-{len(self.orders) + 101}",
            "customer_id": user_session["user_id"],
            "item_id": item_id,
            "quantity": quantity,
            "status": "confirmed",
        }
        self.orders.append(order_record)
        return order_record
