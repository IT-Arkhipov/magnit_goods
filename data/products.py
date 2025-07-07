from dataclasses import dataclass
from codes import *


@dataclass
class Products:
    product: str
    codes: list[int]


moloko_yaytsa = Products(
    product="Молочные продукты, яйца",
    codes=moloko_yaytsa_codes,
)

syry_mm = Products(
    product="Сыры",
    codes=syry_mm_codes
)
