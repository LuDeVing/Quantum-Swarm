"""
test_swarm_registry.py — Integrity tests for the role/tool registry.

These tests ensure no role references a tool that doesn't exist in the
registry — the class of bug that caused "X is not a valid tool" errors.
"""
import pytest
import software_company as sc


# ── Tool registry integrity ───────────────────────────────────────────────────

class TestToolRegistryIntegrity:
    def test_lc_tools_by_name_is_not_empty(self):
        assert len(sc._LC_TOOLS_BY_NAME) > 0

    def test_all_role_tool_names_exist_in_registry(self):
        """Every tool name in _ROLE_TOOL_NAMES must be in _LC_TOOLS_BY_NAME."""
        missing = {}
        for role, tool_names in sc._ROLE_TOOL_NAMES.items():
            bad = [n for n in tool_names if n not in sc._LC_TOOLS_BY_NAME]
            if bad:
                missing[role] = bad
        assert missing == {}, f"Roles reference unregistered tools: {missing}"

    def test_dev_tool_names_exist_in_registry(self):
        """Every tool name in _DEV_TOOL_NAMES must be in _LC_TOOLS_BY_NAME."""
        bad = [n for n in sc._DEV_TOOL_NAMES if n not in sc._LC_TOOLS_BY_NAME]
        assert bad == [], f"Dev tool names not in registry: {bad}"

    def test_no_duplicate_tool_names_in_registry(self):
        names = list(sc._LC_TOOLS_BY_NAME.keys())
        assert len(names) == len(set(names))

    def test_registry_tools_are_callable(self):
        """Each registered tool should be a callable (LangChain tool wraps functions)."""
        for name, tool in sc._LC_TOOLS_BY_NAME.items():
            assert callable(tool) or hasattr(tool, "invoke"), \
                f"Tool '{name}' is not callable"


# ── Role registry integrity ───────────────────────────────────────────────────

class TestRoleRegistry:
    REQUIRED_KEYS = {"title", "expertise", "responsibility"}

    def test_all_roles_have_required_keys(self):
        missing = {}
        for role_key, role_def in sc.ROLES.items():
            absent = self.REQUIRED_KEYS - set(role_def.keys())
            if absent:
                missing[role_key] = absent
        assert missing == {}, f"Roles missing required keys: {missing}"

    def test_all_role_values_are_strings(self):
        bad = {}
        for role_key, role_def in sc.ROLES.items():
            non_strings = {k: v for k, v in role_def.items() if not isinstance(v, str)}
            if non_strings:
                bad[role_key] = non_strings
        assert bad == {}, f"Role fields that are not strings: {bad}"

    def test_expected_roles_exist(self):
        expected = [
            "ceo", "arch_manager", "system_designer", "api_designer", "db_designer",
            "design_manager", "ux_researcher", "ui_designer", "visual_designer",
            "eng_manager",
            "qa_manager", "unit_tester", "integration_tester", "security_auditor",
        ]
        for role in expected:
            assert role in sc.ROLES, f"Expected role '{role}' not found in ROLES"

    def test_dev_roles_exist(self):
        for i in range(1, 9):
            assert f"dev_{i}" in sc.ROLES, f"dev_{i} missing from ROLES"

    def test_no_empty_role_titles(self):
        empty = [r for r, d in sc.ROLES.items() if not d.get("title", "").strip()]
        assert empty == [], f"Roles with empty titles: {empty}"

    def test_no_empty_expertise(self):
        empty = [r for r, d in sc.ROLES.items() if not d.get("expertise", "").strip()]
        assert empty == [], f"Roles with empty expertise: {empty}"


# ── get_role_lc_tools ─────────────────────────────────────────────────────────

class TestGetRoleLcTools:
    def test_known_role_returns_tools(self):
        tools = sc.get_role_lc_tools("system_designer")
        assert len(tools) > 0

    def test_dev_role_returns_tools(self):
        tools = sc.get_role_lc_tools("dev_1")
        assert len(tools) > 0

    def test_unknown_role_returns_empty_list(self):
        tools = sc.get_role_lc_tools("nonexistent_role_xyz")
        assert tools == []

    def test_manager_roles_return_empty_or_tools(self):
        # Managers typically have no tools (they use llm_call directly)
        for manager in ["arch_manager", "design_manager", "eng_manager", "qa_manager"]:
            tools = sc.get_role_lc_tools(manager)
            assert isinstance(tools, list)

    def test_all_returned_tools_are_in_registry(self):
        for role_key in sc._ROLE_TOOL_NAMES:
            tools = sc.get_role_lc_tools(role_key)
            for tool in tools:
                name = getattr(tool, "name", str(tool))
                assert name in sc._LC_TOOLS_BY_NAME, \
                    f"Tool '{name}' returned for '{role_key}' but not in registry"

    def test_security_auditor_has_read_file(self):
        tools = sc.get_role_lc_tools("security_auditor")
        names = [getattr(t, "name", "") for t in tools]
        assert "read_file" in names

    def test_integration_tester_has_validate_python(self):
        tools = sc.get_role_lc_tools("integration_tester")
        names = [getattr(t, "name", "") for t in tools]
        assert "validate_python" in names

    def test_dev_tools_include_write_code_file(self):
        tools = sc.get_role_lc_tools("dev_1")
        names = [getattr(t, "name", "") for t in tools]
        assert "write_code_file" in names


# ── Stances and constants ─────────────────────────────────────────────────────

class TestConstants:
    def test_stances_has_four_values(self):
        assert len(sc.STANCES) == 4

    def test_stances_are_expected_values(self):
        assert set(sc.STANCES) == {"minimal", "robust", "scalable", "pragmatic"}

    def test_hypotheses_match_active_inference_order(self):
        assert sc.HYPOTHESES == ["healthy", "uncertain", "confused"]

    def test_role_prior_sums_to_one(self):
        import math
        total = sum(sc.ROLE_PRIOR.values())
        assert math.isclose(total, 1.0, abs_tol=1e-9)

    def test_interference_alpha_in_range(self):
        assert 0.0 <= sc.INTERFERENCE_ALPHA <= 1.0

    def test_max_sprints_positive(self):
        assert sc.MAX_SPRINTS > 0

    def test_max_eng_rounds_positive(self):
        assert sc.MAX_ENG_ROUNDS > 0

    def test_max_team_rounds_positive(self):
        assert sc.MAX_TEAM_ROUNDS > 0
