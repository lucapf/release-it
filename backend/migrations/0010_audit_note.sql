-- Operators may attach an optional free-text note to a state transition (and to
-- any other audited action). It is stored alongside the audit row so it shows up
-- in the release history next to the state change it explains.

ALTER TABLE audit ADD COLUMN note TEXT;
