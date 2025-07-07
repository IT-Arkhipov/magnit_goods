import requests

from data import products, Products
from utils.config import settings
from fake_useragent import UserAgent


ua = UserAgent()


def get_product_count(product: Products) -> int:
    request_body = {
        "categoryIDs": product.codes,
        "includeAdultGoods": True,
        "storeCodes": [settings.store_code],
        "storeType": settings.store_type,
        "catalogType": "1",
    }

    user_agent = ua.random
    headers = {
        "User-Agent": user_agent,
    }

    response = requests.post(
        url="https://magnit.ru/webgate/v1/goods/filters",
        headers=headers,
        json=request_body,
    )
    if response.status_code == 200:
        return response.json().get("pagination").get('totalCount')
    else:
        return 0


def get_product(product: Products):
    LIMIT = 50

    print(f"{product.product} - {product.codes}")
    total_goods = get_product_count(product)
    print(total_goods)

    for offset in range(0, total_goods, LIMIT):
        request_body = {
            "sort": {"order": "desc", "type": "popularity"},
            "pagination": {"limit": LIMIT, "offset": offset},
            "categories": product.codes,
            "includeAdultGoods": True,
            "storeCode": settings.store_code,
            "storeType": settings.store_type,
            "catalogType": "1",
        }

        user_agent = ua.random
        headers = {
            "User-Agent": user_agent,
        }

        response = requests.post(url=settings.goods_url, headers=headers, json=request_body)
        if response.status_code == 200:
            print(len(response.json().get('items')))
        else:
            print(response.status_code, response.text,)


def list_products():
    for product in products:
        get_product(product)
