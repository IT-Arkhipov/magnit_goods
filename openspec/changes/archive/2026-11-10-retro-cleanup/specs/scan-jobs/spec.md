# Spec Delta

## MODIFIED Requirements

### Requirement: Отмена — окончательный статус
Задание, переведённое в статус `cancelled`, SHALL сохранять этот статус: завершение фоновой работы (ручное обновление цен, задания планировщика, сканирование всех магазинов) SHALL NOT менять его на `completed` или `failed`.

#### Scenario: Отмена обновления цен
- **WHEN** клиент запускает `POST /api/prices/update`, затем вызывает `POST /api/jobs/{job_id}/cancel` до окончания сканирования
- **THEN** после остановки фоновой работы `GET /api/jobs/{job_id}` возвращает `status: "cancelled"`

#### Scenario: Отмена задания планировщика
- **WHEN** задание сканирования всех магазинов, созданное планировщиком, отменено через `POST /api/jobs/{job_id}/cancel`
- **THEN** его итоговый статус — `cancelled`
