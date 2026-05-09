ALTER TABLE subscription_matches DROP CONSTRAINT IF EXISTS subscription_matches_paper_id_fkey;
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_paper_id_fkey;
