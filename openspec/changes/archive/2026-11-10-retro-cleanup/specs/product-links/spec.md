# Spec Delta

## REMOVED Requirements

### Requirement: Редирект только на сайт Магнита
**Reason**: `GET /redirect-to-product` не использовался интерфейсом; cookies, которые сервер ставит на localhost, не доходят до magnit.ru.
**Migration**: прямые ссылки `https://magnit.ru/product/...?shopCode=&shopType=` со страницы `/products`.

### Requirement: Открытие во внешнем браузере только для ссылок Магнита
**Reason**: `GET /open-product-in-browser` и Playwright удалены — интерфейс их не вызывал, браузер закрывался сразу после открытия.
**Migration**: прямые ссылки на товар.

### Requirement: Ошибки фонового открытия товара фиксируются
**Reason**: фоновое открытие товара удалено.
**Migration**: нет.
