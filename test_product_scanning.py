"""
Тестовый скрипт для проверки загрузки категорий и сканирования товаров.
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"


def test_load_categories():
    """Тест загрузки категорий из JSON"""
    print("\n=== TEST 1: Load categories from JSON ===")
    try:
        response = requests.post(f"{BASE_URL}/api/categories/load-from-json")
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
        return data
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def test_get_categories_tree():
    """Тест получения дерева категорий"""
    print("\n=== TEST 2: Get categories tree ===")
    try:
        response = requests.get(f"{BASE_URL}/api/categories/tree")
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Total root categories: {len(data)}")
        if data:
            print(f"First category: {data[0]['name']}")
            print(f"Children count: {len(data[0].get('children', []))}")
        return data
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def test_get_categories():
    """Тест получения списка категорий"""
    print("\n=== TEST 3: Get all categories ===")
    try:
        response = requests.get(f"{BASE_URL}/api/categories")
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Total categories: {len(data)}")
        if data:
            print(f"First category: {data[0]}")
        return data
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def test_update_tracking(category_ids):
    """Тест обновления отслеживания категорий"""
    print("\n=== TEST 4: Update category tracking ===")
    try:
        payload = {"category_ids": category_ids[:5]}  # Выбираем первые 5
        response = requests.post(
            f"{BASE_URL}/api/categories/update-tracking", json=payload
        )
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
        return data
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def test_scan_all_stores():
    """Тест сканирования товаров для всех магазинов"""
    print("\n=== TEST 5: Scan all stores ===")
    try:
        response = requests.post(f"{BASE_URL}/api/catalog/scan-all-stores")
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
        return data
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def test_get_job_status(job_id):
    """Тест получения статуса задания"""
    print(f"\n=== TEST 6: Get job status (job_id={job_id}) ===")
    try:
        response = requests.get(f"{BASE_URL}/api/jobs/{job_id}")
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)}")
        return data
    except Exception as e:
        print(f"ERROR: {e}")
        return None


if __name__ == "__main__":
    print("Starting product scanning tests...")

    # Test 1: Load categories
    load_result = test_load_categories()

    # Test 2: Get categories tree
    tree = test_get_categories_tree()

    # Test 3: Get all categories
    categories = test_get_categories()

    # Test 4: Update tracking
    if categories:
        category_ids = [cat["id"] for cat in categories]
        tracking_result = test_update_tracking(category_ids)

    # Test 5: Scan all stores
    scan_result = test_scan_all_stores()

    # Test 6: Poll job status
    if scan_result and "job_id" in scan_result:
        job_id = scan_result["job_id"]
        for i in range(5):
            time.sleep(2)
            job_status = test_get_job_status(job_id)
            if job_status and job_status.get("status") in ["completed", "failed"]:
                print(f"\nJob finished with status: {job_status.get('status')}")
                break

    print("\n=== All tests completed ===")
