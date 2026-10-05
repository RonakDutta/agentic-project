"""
Main application entry point for the sample service.
"""

from auth.jwt_handler import JWTHandler
from orders.processor import OrderProcessor


def run_demo():
    auth = JWTHandler()
    orders = OrderProcessor()

    # Generate token
    token = auth.encode_token(user_id="usr_8821", role="customer")
    print(f"Generated Token: {token[:20]}...")

    # Process order
    order = orders.process_order(auth_token=token, item_id="item_404", quantity=2)
    print(f"Order Success: {order}")


if __name__ == "__main__":
    run_demo()
