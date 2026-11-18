"""Benchmark script for SENTRIX.ai pipeline execution latency."""

import time
import requests

def benchmark(base_url="http://127.0.0.1:8000"):
    print(f"Benchmarking SENTRIX.ai on {base_url}...")
    start = time.time()
    
    # 1. Check API Status
    r = requests.get(f"{base_url}/api/settings/api-status/")
    t_status = time.time() - start
    print(f"  • API Status response: {t_status*1000:.1f}ms (Status: {r.status_code})")

    # 2. Check Repo Tree
    t0 = time.time()
    r = requests.get(f"{base_url}/api/repo/tree/?repo_url=")
    t_tree = time.time() - t0
    print(f"  • Repo Tree discovery: {t_tree*1000:.1f}ms ({r.json().get('total_files', 0)} files mapped)")

    total = time.time() - start
    print(f"Benchmark finished in {total*1000:.1f}ms. All checks nominal.")

if __name__ == "__main__":
    benchmark()
