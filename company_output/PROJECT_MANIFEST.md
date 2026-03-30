# Project Manifest — updated after Sprint 1

This file lists every source file in the codebase. **Read this before writing any new file** to avoid duplicates.

## Files

- **code\app.js**: /** | * app.js - Main application logic for the Personal Finance Tracker. | */
- **code\local_storage.js**: // local_storage.js | /**
- **code\local_storage_handler.js**: /** | * Handles localStorage operations with error handling and user-friendly messages. | */
- **design\architecture_spec.md**: Okay, let's synthesize this into a single, actionable Architecture Decision Record (ADR) for Sprint 1. | **Architecture 
- **design\design_spec.md**: Okay, team, let's synthesize all the design outputs into a comprehensive Design System Specification for Sprint 1. The g
- **design\design_tokens.md**: ## Design Token Set | This document defines the design tokens for the Personal Finance Tracker MVP. These tokens should 
- **design\qa_findings.md**: Okay, I've reviewed the sprint goal, team deliverables, acceptance criteria, integration contracts, definition of done, 
- **design\types.ts**: ```typescript | interface Transaction { | id: string; // UUID generated client-side
- **tests\test_app.py**: import pytest | import json | from unittest.mock import patch
- **tests\test_local_storage.py**: import pytest | import json | from unittest.mock import patch

## How to use codebase search

Call `search_codebase(query)` with a natural language description of what you need (e.g. 'authentication token validation', 'WebSocket connection handler', 'Kanban task model'). It returns the most relevant existing code chunks.

Call `list_files()` to see all files.

Call `read_file(filename)` to read a specific file before modifying or importing it.
