USE entenda_uat_db;
ALTER TABLE game_notifications
    DROP CHECK ck_notification_target,
    ADD COLUMN infrastructure_project_id INT NULL,
    ADD COLUMN infrastructure_text VARCHAR(512) NULL,
    ADD UNIQUE KEY uq_notification_user_infrastructure (user_id, infrastructure_project_id),
    ADD CONSTRAINT fk_notification_infrastructure FOREIGN KEY (infrastructure_project_id)
        REFERENCES game_infrastructure_projects (id) ON DELETE RESTRICT,
    ADD CONSTRAINT ck_notification_target CHECK (((notification_type = 'FORUM_MESSAGE' AND message_id IS NOT NULL AND diplomatic_action_id IS NULL AND generated_event_id IS NULL) OR (notification_type = 'DIPLOMACY' AND diplomatic_action_id IS NOT NULL AND message_id IS NULL AND generated_event_id IS NULL) OR (notification_type = 'GENERATED_EVENT' AND generated_event_id IS NOT NULL AND message_id IS NULL AND diplomatic_action_id IS NULL)) AND infrastructure_project_id IS NULL AND infrastructure_text IS NULL OR (notification_type = 'INFRASTRUCTURE_COMPLETED' AND infrastructure_project_id IS NOT NULL AND infrastructure_text IS NOT NULL AND message_id IS NULL AND diplomatic_action_id IS NULL AND generated_event_id IS NULL));
