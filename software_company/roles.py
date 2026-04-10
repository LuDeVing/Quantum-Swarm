"""Role metadata, engineering worker ids, and Definition-of-Done checklists."""

from __future__ import annotations

from typing import Dict

__all__ = [
    "ROLES",
    "ENG_WORKERS",
    "_DOD_CHECKLISTS",
    "_ARCH_ROLES",
    "_DESIGN_ROLES",
    "_QA_ROLES",
    "_get_dod",
]

ROLES: Dict[str, Dict[str, str]] = {
    "ceo": {
        "title":          "Chief Executive Officer",
        "expertise":      "software strategy, project decomposition, cross-team coordination",
        "responsibility": "break project into workstreams, synthesize team outputs into final deliverable",
    },
    "arch_manager": {
        "title":          "Architecture Manager",
        "expertise":      "software architecture, system design, technical leadership",
        "responsibility": "lead architecture team, synthesize design into a coherent system specification",
    },
    "system_designer": {
        "title":          "System Designer",
        "expertise":      "distributed systems, component design, data flow, system boundaries, scalability patterns",
        "responsibility": "design overall system components, their interactions, and data flow — produce component diagram",
    },
    "api_designer": {
        "title":          "API Designer",
        "expertise":      "REST, GraphQL, OpenAPI spec, API versioning, auth flows, rate limiting",
        "responsibility": "design all API endpoints, request/response schemas, authentication and authorization flows",
    },
    "db_designer": {
        "title":          "Database Designer",
        "expertise":      "data modeling, SQL/NoSQL, indexing strategies, migrations, query optimization",
        "responsibility": "design data models, schemas, relationships, indexes, and migration strategy",
    },
    "design_manager": {
        "title":          "Design Manager",
        "expertise":      "product design, UX leadership, design systems, design handoff",
        "responsibility": "lead design team, synthesize research and visuals into a complete design specification",
    },
    "ux_researcher": {
        "title":          "UX Researcher",
        "expertise":      "user research, personas, user flows, information architecture, usability testing",
        "responsibility": "define user personas, map complete user flows, identify UX requirements and pain points",
    },
    "ui_designer": {
        "title":          "UI Designer",
        "expertise":      "interface design, component systems, accessibility (WCAG), responsive design, interaction patterns",
        "responsibility": "design UI components, screen layouts, interaction states, accessibility requirements",
    },
    "visual_designer": {
        "title":          "Visual Designer",
        "expertise":      "visual design, typography, color theory, brand identity, design tokens, icon systems",
        "responsibility": "define complete visual style guide: colors, typography, spacing, icons, animation tokens",
    },
    "eng_manager": {
        "title":          "Engineering Manager",
        "expertise":      "software engineering, code quality, technical execution, delivery",
        "responsibility": "lead engineering team, synthesize worker code into a coherent, runnable implementation",
    },
    "software_developer": {
        "title":          "Software Developer",
        "expertise":      "full-stack development, Python, JavaScript/TypeScript, SQL, REST APIs, Docker, CI/CD, cloud",
        "responsibility":  "implement any engineering task: backend logic, frontend components, APIs, infra config, or tooling — write actual working code",
    },
    "qa_manager": {
        "title":          "QA Manager",
        "expertise":      "quality assurance, testing strategy, risk assessment, release criteria",
        "responsibility": "lead QA team, synthesize quality report with explicit go/no-go recommendation",
    },
    "unit_tester": {
        "title":          "Unit Test Engineer",
        "expertise":      "pytest, jest, vitest, mocking, coverage analysis, TDD, property-based testing",
        "responsibility": "write comprehensive unit tests for all core functions, edge cases, and error paths",
    },
    "integration_tester": {
        "title":          "Integration Test Engineer",
        "expertise":      "API testing, end-to-end testing, contract testing, load testing, Postman/k6",
        "responsibility": "write integration and E2E test scenarios, API contract tests, performance test plan",
    },
    "security_auditor": {
        "title":          "Security Auditor",
        "expertise":      "OWASP Top 10, penetration testing, threat modeling, secure coding, compliance",
        "responsibility": "threat model the system, identify vulnerabilities, provide mitigation recommendations",
    },
}

ENG_WORKERS = [f"dev_{i}" for i in range(1, 9)]

_DOD_CHECKLISTS: Dict[str, str] = {
    "engineering": (
        "DEFINITION OF DONE — verify every item before submitting:\n"
        "  [ ] Every function is fully implemented — no TODOs, no stubs\n"
        "  [ ] All new modules are imported/registered in the running app\n"
        "  [ ] Error handling and input validation are written\n"
        "  [ ] No hardcoded secrets or magic numbers\n"
        "  [ ] Verified it runs: paste actual shell output or explain why impossible\n"
        "Mark each as PASS or FAIL. Fix any FAIL before ending your response."
    ),
    "architecture": (
        "DEFINITION OF DONE — verify every item before submitting:\n"
        "  [ ] Every data structure has exact field names, types, and nullability\n"
        "  [ ] Every API endpoint has method, path, auth, request + response schema\n"
        "  [ ] No vague types (object/array/any) — all fields are concrete\n"
        "  [ ] Integration order is specified (what must be built before what)\n"
        "  [ ] Output written to design/architecture_spec.md\n"
        "Mark each as PASS or FAIL. Fix any FAIL before ending your response."
    ),
    "design": (
        "DEFINITION OF DONE — verify every item before submitting:\n"
        "  [ ] Every component has exact px, hex, and ms values — no vague descriptions\n"
        "  [ ] All states are covered: default, loading, error, empty, success\n"
        "  [ ] Every user flow has a defined end state — no dead ends\n"
        "  [ ] Accessibility: all interactive elements are keyboard-navigable\n"
        "  [ ] Output written to design/design_spec.md\n"
        "Mark each as PASS or FAIL. Fix any FAIL before ending your response."
    ),
    "qa": (
        "DEFINITION OF DONE — verify every item before submitting:\n"
        "  [ ] Tests are deterministic — no random data, no time-dependent assertions\n"
        "  [ ] Happy path, error path, and at least one edge case are covered\n"
        "  [ ] Auth is tested: unauthenticated request is rejected\n"
        "  [ ] Real output is shown — actual pytest/browser results, not claims\n"
        "  [ ] All new findings written to design/qa_findings.md with SEVERITY/FILE/DESCRIPTION\n"
        "Mark each as PASS or FAIL. Fix any FAIL before ending your response."
    ),
}

_ARCH_ROLES  = {"system_designer", "api_designer", "db_designer"}
_DESIGN_ROLES = {"ux_researcher", "ui_designer", "visual_designer"}
_QA_ROLES    = {"unit_tester", "integration_tester", "security_auditor"}


def _get_dod(role_key: str) -> str:
    """Return the Definition of Done checklist for this role."""
    if role_key in _ARCH_ROLES:
        return _DOD_CHECKLISTS["architecture"]
    if role_key in _DESIGN_ROLES:
        return _DOD_CHECKLISTS["design"]
    if role_key in _QA_ROLES:
        return _DOD_CHECKLISTS["qa"]
    return _DOD_CHECKLISTS["engineering"]
