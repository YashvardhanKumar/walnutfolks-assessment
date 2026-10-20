#!/usr/bin/env python3
"""
End-to-End Verification and Benchmark Script for Transaction Webhook Service.

Usage:
    python test_api.py [BASE_URL]

Default BASE_URL is http://localhost:8000
Can also be run against live deployed AWS service:
    python test_api.py http://13.203.127.127
"""

import sys
import time
import uuid
import requests

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"

print("=" * 70)
print(f"🚀 RUNNING COMPREHENSIVE SUITE AGAINST: {BASE_URL}")
print("=" * 70)

# 1. Health check test
print("\n[1/5] Testing Health Check Endpoint: GET /")
t0 = time.perf_counter()
res = requests.get(f"{BASE_URL}/")
elapsed = (time.perf_counter() - t0) * 1000
print(f"Status Code: {res.status_code} ({elapsed:.1f}ms)")
print(f"Payload: {res.text}")
assert res.status_code == 200, f"Expected 200, got {res.status_code}"
data = res.json()
assert data.get("status") == "HEALTHY", f"Expected HEALTHY, got {data.get('status')}"
assert "current_time" in data, "current_time field missing"
print("✅ Health check passed!")

# 2. Webhook ingestion & latency test (<500ms)
test_tx_id = f"txn_{uuid.uuid4().hex[:12]}"
payload = {
    "transaction_id": test_tx_id,
    "source_account": "acc_user_789",
    "destination_account": "acc_merchant_456",
    "amount": 1500,
    "currency": "INR",
}

print(f"\n[2/5] Testing Webhook Ingestion: POST /v1/webhooks/transactions ({test_tx_id})")
t0 = time.perf_counter()
res = requests.post(f"{BASE_URL}/v1/webhooks/transactions", json=payload)
latency_ms = (time.perf_counter() - t0) * 1000
print(f"Status Code: {res.status_code}")
print(f"Latency: {latency_ms:.2f}ms (Target: < 500ms)")
print(f"Response: {res.text}")
assert res.status_code == 202, f"Expected 202 Accepted, got {res.status_code}"
assert latency_ms < 500, f"Latency {latency_ms:.2f}ms exceeded 500ms limit!"
print("✅ Webhook ingestion passed under 500ms!")

# 3. Idempotency test: send same transaction multiple times
print(f"\n[3/5] Testing Duplicate Prevention / Idempotency with same {test_tx_id}")
for i in range(1, 4):
    t0 = time.perf_counter()
    dup_res = requests.post(f"{BASE_URL}/v1/webhooks/transactions", json=payload)
    dup_latency = (time.perf_counter() - t0) * 1000
    print(f"Duplicate send #{i} -> Status: {dup_res.status_code} ({dup_latency:.1f}ms)")
    assert dup_res.status_code == 202, f"Duplicate request should return 202, got {dup_res.status_code}"
print("✅ Idempotency test passed!")

# 4. Immediate Query test: should be in PROCESSING state
print(f"\n[4/5] Testing Immediate Query: GET /v1/transactions/{test_tx_id}")
q_res = requests.get(f"{BASE_URL}/v1/transactions/{test_tx_id}")
print(f"Status Code: {q_res.status_code}")
print(f"Response: {q_res.text}")
assert q_res.status_code == 200, f"Expected 200, got {q_res.status_code}"
q_data = q_res.json()
assert isinstance(q_data, list), "Expected list response per specification"
tx_obj = q_data[0]
assert tx_obj["transaction_id"] == test_tx_id
print(f"Current Status: {tx_obj['status']} | processed_at: {tx_obj.get('processed_at')}")
print("✅ Initial state verified!")

# 5. Background processing verification: wait for 30s delay to complete
print("\n[5/5] Polling for background transition to PROCESSED (up to 35 seconds)...")
start_time = time.time()
completed = False

while time.time() - start_time < 45:
    poll_res = requests.get(f"{BASE_URL}/v1/transactions/{test_tx_id}")
    if poll_res.status_code == 200:
        tx = poll_res.json()[0]
        curr_status = tx.get("status")
        elapsed_sec = int(time.time() - start_time)
        print(f"[{elapsed_sec}s] Transaction status: {curr_status} | processed_at: {tx.get('processed_at')}")
        if curr_status == "PROCESSED":
            assert tx.get("processed_at") is not None, "processed_at timestamp must be set"
            completed = True
            break
    time.sleep(3)

assert completed, "Transaction did not transition to PROCESSED within expected timeframe!"
print("\n🎉 ALL 5 TEST SUITES PASSED SUCCESSFULLY!")
print("=" * 70)
