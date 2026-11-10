# Spec Delta

## ADDED Requirements

### Requirement: Удаление магазина удаляет его товары
`DELETE /api/stores/{store_id}` и `POST /api/stores/delete-batch` SHALL удалять вместе с магазином его товары и историю цен (пара код и тип магазина); данные магазина другого типа с тем же кодом SHALL сохраняться. Товары и история магазинов, которых нет в `stores`, SHALL удаляться один раз миграцией `cleanup_orphan_store_products`.

#### Scenario: Удаление магазина
- **WHEN** удаляется магазин (`210117`, `Моя цена`)
- **THEN** товаров и истории цен с `store_code=210117`, `store_type_code=9` не остаётся
