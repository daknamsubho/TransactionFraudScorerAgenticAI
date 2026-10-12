"""Pytest configuration and shared test fixtures."""

import pytest

from fraud_scorer.models.transaction import (
    GeoLocation,
    MerchantInfo,
    PaymentMethod,
    Transaction,
)


@pytest.fixture
def normal_transaction() -> Transaction:
    """Fixture providing a typical, legitimate transaction."""
    return Transaction(
        transaction_id="tx_norm_test_001",
        account_id="acc_normal_01",
        amount=55.00,
        currency="USD",
        location=GeoLocation(
            latitude=37.7749,
            longitude=-122.4194,
            city="San Francisco",
            country="US",
        ),
        payment_method=PaymentMethod(
            payment_type="credit_card",
            card_last_four="1234",
            is_card_present=True,
        ),
        merchant=MerchantInfo(
            merchant_id="m_supermarket_1",
            name="Whole Foods Market",
            mcc="5411",  # Grocery Stores
        ),
    )


@pytest.fixture
def fraudulent_transaction() -> Transaction:
    """Fixture providing an obviously fraudulent transaction (high amount, high risk MCC, impossible travel)."""
    return Transaction(
        transaction_id="tx_fraud_test_002",
        account_id="acc_suspicious_01",
        amount=4500.00,
        currency="USD",
        location=GeoLocation(
            latitude=35.6762,
            longitude=139.6503,
            city="Tokyo",
            country="JP",
        ),
        payment_method=PaymentMethod(
            payment_type="credit_card",
            card_last_four="9999",
            is_card_present=False,
        ),
        merchant=MerchantInfo(
            merchant_id="m_crypto_exchange_9",
            name="Instant Crypto OTC",
            mcc="6051",  # Quasi Cash - Cryptocurrency
        ),
    )
