-- UAT schema changes. Approved allocations remain intact; code normalizes historical categories.
ALTER TABLE game_intelligence_agents ADD COLUMN name VARCHAR(100) NULL;
ALTER TABLE game_budget_categories DROP CHECK `ck_gbc_display_order_v2`, ADD CONSTRAINT ck_gbc_display_order_v3 CHECK (display_order BETWEEN 1 AND 64);
-- Active dictionary order and idempotent refunds are applied transactionally by the migration helper.
