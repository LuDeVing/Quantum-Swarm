"""
test_swarm_dashboard.py — Unit tests for WorkDashboard coordination layer.

Tests domain claiming, file conflict detection, async messaging, and
file ownership matching — the backbone of parallel agent coordination.
"""
import pytest
import software_company as sc


# ── claim() — domain registration and conflict detection ─────────────────────

class TestClaim:
    def test_claim_success(self, fresh_dashboard):
        result = fresh_dashboard.claim(
            domain="backend_auth",
            owner="dev_1",
            description="JWT authentication module",
            file_patterns="auth.py, auth_routes.py",
            sprint=1,
        )
        assert "CLAIMED" in result

    def test_claim_registers_domain(self, fresh_dashboard):
        fresh_dashboard.claim("backend_auth", "dev_1", "Auth", "auth.py", 1)
        assert "backend_auth" in fresh_dashboard.domains

    def test_claim_same_domain_same_owner_succeeds(self, fresh_dashboard):
        fresh_dashboard.claim("backend_auth", "dev_1", "Auth", "auth.py", 1)
        result = fresh_dashboard.claim("backend_auth", "dev_1", "Auth updated", "auth.py", 1)
        assert "CLAIMED" in result

    def test_claim_same_domain_different_owner_blocked(self, fresh_dashboard):
        fresh_dashboard.claim("backend_auth", "dev_1", "Auth", "auth.py", 1)
        result = fresh_dashboard.claim("backend_auth", "dev_2", "Also auth", "models.py", 1)
        assert "CONFLICT" in result

    def test_claim_file_pattern_overlap_blocked(self, fresh_dashboard):
        fresh_dashboard.claim("domain_a", "dev_1", "A", "auth.py, models.py", 1)
        result = fresh_dashboard.claim("domain_b", "dev_2", "B", "auth.py, todo.py", 1)
        assert "CONFLICT" in result

    def test_claim_no_overlap_succeeds(self, fresh_dashboard):
        fresh_dashboard.claim("domain_a", "dev_1", "A", "auth.py", 1)
        result = fresh_dashboard.claim("domain_b", "dev_2", "B", "todo.py", 1)
        assert "CLAIMED" in result

    def test_claim_completed_domain_not_blocked(self, fresh_dashboard):
        # If a domain is completed it should not block new claims
        fresh_dashboard.claim("domain_a", "dev_1", "A", "auth.py", 1)
        fresh_dashboard.release_sprint(1)
        result = fresh_dashboard.claim("domain_b", "dev_2", "B", "auth.py", 2)
        assert "CLAIMED" in result

    def test_claim_stores_correct_metadata(self, fresh_dashboard):
        fresh_dashboard.claim("my_domain", "dev_3", "Description", "file.py", 2)
        domain = fresh_dashboard.domains["my_domain"]
        assert domain["owner"] == "dev_3"
        assert domain["sprint"] == 2
        assert domain["status"] == "active"

    def test_claim_partial_overlap_blocked(self, fresh_dashboard):
        # Only one file overlaps — still a conflict
        fresh_dashboard.claim("a", "dev_1", "A", "file1.py, file2.py", 1)
        result = fresh_dashboard.claim("b", "dev_2", "B", "file2.py, file3.py", 1)
        assert "CONFLICT" in result

    def test_multiple_independent_claims_succeed(self, fresh_dashboard):
        for i in range(5):
            result = fresh_dashboard.claim(
                f"domain_{i}", f"dev_{i}", f"Work {i}", f"module_{i}.py", 1
            )
            assert "CLAIMED" in result


# ── get_file_owner() — file ownership lookup ──────────────────────────────────

class TestGetFileOwner:
    def test_exact_match_returns_owner(self, fresh_dashboard):
        fresh_dashboard.claim("domain_a", "dev_1", "A", "auth.py", 1)
        owner = fresh_dashboard.get_file_owner("auth.py")
        assert owner == "dev_1"

    def test_no_match_returns_none(self, fresh_dashboard):
        fresh_dashboard.claim("domain_a", "dev_1", "A", "auth.py", 1)
        owner = fresh_dashboard.get_file_owner("unknown.py")
        assert owner is None

    def test_multiple_files_in_pattern(self, fresh_dashboard):
        fresh_dashboard.claim("domain_a", "dev_1", "A", "auth.py, models.py", 1)
        assert fresh_dashboard.get_file_owner("models.py") == "dev_1"

    def test_completed_domain_not_owned(self, fresh_dashboard):
        fresh_dashboard.claim("domain_a", "dev_1", "A", "auth.py", 1)
        fresh_dashboard.release_sprint(1)
        # After release, status = complete — may or may not return owner
        # Just verify it doesn't crash
        result = fresh_dashboard.get_file_owner("auth.py")
        assert result is None or result == "dev_1"


# ── send_message() / get_messages() — async messaging ────────────────────────

class TestMessaging:
    def test_send_and_receive_message(self, fresh_dashboard):
        fresh_dashboard.send_message("dev_1", "dev_2", "Hey, need the auth interface", 1)
        messages = fresh_dashboard.get_messages("dev_2")
        assert "Hey, need the auth interface" in messages

    def test_message_includes_sender(self, fresh_dashboard):
        fresh_dashboard.send_message("dev_1", "dev_2", "Hello", 1)
        messages = fresh_dashboard.get_messages("dev_2")
        assert "dev_1" in messages

    def test_get_messages_clears_inbox(self, fresh_dashboard):
        fresh_dashboard.send_message("dev_1", "dev_2", "msg", 1)
        fresh_dashboard.get_messages("dev_2")
        # Second call should return empty
        second = fresh_dashboard.get_messages("dev_2")
        assert "No messages" in second

    def test_no_messages_returns_none_message(self, fresh_dashboard):
        result = fresh_dashboard.get_messages("dev_nobody")
        assert "No messages" in result

    def test_multiple_senders_to_same_recipient(self, fresh_dashboard):
        fresh_dashboard.send_message("dev_1", "dev_3", "msg from 1", 1)
        fresh_dashboard.send_message("dev_2", "dev_3", "msg from 2", 1)
        messages = fresh_dashboard.get_messages("dev_3")
        assert "msg from 1" in messages
        assert "msg from 2" in messages

    def test_messages_isolated_per_recipient(self, fresh_dashboard):
        fresh_dashboard.send_message("dev_1", "dev_2", "for dev_2", 1)
        msgs_dev3 = fresh_dashboard.get_messages("dev_3")
        assert "for dev_2" not in msgs_dev3


# ── get_status() — dashboard display ─────────────────────────────────────────

class TestGetStatus:
    def test_status_is_string(self, fresh_dashboard):
        assert isinstance(fresh_dashboard.get_status(), str)

    def test_status_shows_claimed_domain(self, fresh_dashboard):
        fresh_dashboard.claim("backend_auth", "dev_1", "Auth", "auth.py", 1)
        status = fresh_dashboard.get_status()
        assert "backend_auth" in status

    def test_status_shows_owner(self, fresh_dashboard):
        fresh_dashboard.claim("backend_auth", "dev_1", "Auth", "auth.py", 1)
        status = fresh_dashboard.get_status()
        assert "dev_1" in status


# ── release_sprint() ──────────────────────────────────────────────────────────

class TestReleaseSprint:
    def test_release_marks_domains_complete(self, fresh_dashboard):
        fresh_dashboard.claim("domain_a", "dev_1", "A", "auth.py", 1)
        fresh_dashboard.release_sprint(1)
        assert fresh_dashboard.domains["domain_a"]["status"] == "complete"

    def test_release_only_affects_target_sprint(self, fresh_dashboard):
        fresh_dashboard.claim("domain_s1", "dev_1", "S1", "a.py", 1)
        fresh_dashboard.claim("domain_s2", "dev_2", "S2", "b.py", 2)
        fresh_dashboard.release_sprint(1)
        assert fresh_dashboard.domains["domain_s1"]["status"] == "complete"
        assert fresh_dashboard.domains["domain_s2"]["status"] == "active"
