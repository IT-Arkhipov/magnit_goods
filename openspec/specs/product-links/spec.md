# product-links Specification

## Purpose
Определяет переход пользователя к странице товара на сайте Магнита: редирект с установкой cookies выбранного магазина и открытие товара во внешнем браузере, с защитой от перенаправления на сторонние адреса.

## Requirements

### Requirement: Редирект только на сайт Магнита
`GET /redirect-to-product` SHALL выполнять редирект, только если `url` использует схему `https` и хост ровно `magnit.ru`. Иначе SHALL возвращать 400 без установки cookies.

#### Scenario: Ссылка на товар Магнита
- **WHEN** клиент вызывает `GET /redirect-to-product?url=https://magnit.ru/product/123&shop_code=992104&x_shop_type=1`
- **THEN** ответ — редирект на этот адрес с cookies `shopCode` и `x_shop_type`

#### Scenario: Сторонний адрес
- **WHEN** `url=https://evil.example/` или `url=https://magnit.ru.evil.example/`
- **THEN** ответ — 400, cookies не установлены

### Requirement: Открытие во внешнем браузере только для ссылок Магнита
`GET /open-product-in-browser` SHALL принимать `product_url` только с той же проверкой адреса, иначе — 400 без запуска браузера.

#### Scenario: Сторонний адрес
- **WHEN** `product_url=file:///C:/Windows/`
- **THEN** ответ — 400, браузер не запускается

### Requirement: Ошибки фонового открытия товара фиксируются
Если открытие товара во внешнем браузере завершилось ошибкой в фоне, сервер SHALL записать ошибку с traceback в лог и продолжить работу.

#### Scenario: Браузер не установлен
- **WHEN** Playwright не может запустить Chromium
- **THEN** в логе есть сообщение об ошибке с traceback, сервер отвечает на последующие запросы
