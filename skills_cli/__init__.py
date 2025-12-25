"""
Skills CLI - Cross-platform CLI for managing Claude Code skills

Public API:
    - parse_repo_url: Parse various Git repository URL formats
    - discover_skills: Find skills in a directory
    - find_skills_root: Search for skills root in a repository
    - parse_skill_md: Parse SKILL.md frontmatter
    - validate_skill_md: Validate SKILL.md format
    - install_skill: Install a skill to a directory
    - pack_skill: Pack a skill into a zip file
    - get_claude_skills_dir: Get Claude skills directory path

CLI Entry Point:
    - main: CLI main function
"""

__version__ = "0.2.1"

from .core import (
    # Constants
    DEFAULT_REPO,
    METADATA_FILE,
    COMMON_SKILL_DIRS,
    REQUIRED_SKILL_FIELDS,

    # Logging
    Colors,
    log_info,
    log_success,
    log_warning,
    log_error,

    # URL Parsing
    parse_repo_url,

    # Git Operations
    run_git,
    get_git_commit_hash,
    detect_default_branch,
    clone_repo,

    # Metadata
    write_skill_metadata,
    read_skill_metadata,

    # Skill Discovery
    discover_skills,
    find_skills_root,
    parse_skill_md,

    # Installation
    get_claude_skills_dir,
    backup_skill,
    install_skill,
    pack_skill,

    # Validation
    validate_skill_md,
)

from .cli import main

__all__ = [
    # Constants
    "DEFAULT_REPO",
    "METADATA_FILE",
    "COMMON_SKILL_DIRS",
    "REQUIRED_SKILL_FIELDS",

    # Logging
    "Colors",
    "log_info",
    "log_success",
    "log_warning",
    "log_error",

    # URL Parsing
    "parse_repo_url",

    # Git Operations
    "run_git",
    "get_git_commit_hash",
    "detect_default_branch",
    "clone_repo",

    # Metadata
    "write_skill_metadata",
    "read_skill_metadata",

    # Skill Discovery
    "discover_skills",
    "find_skills_root",
    "parse_skill_md",

    # Installation
    "get_claude_skills_dir",
    "backup_skill",
    "install_skill",
    "pack_skill",

    # Validation
    "validate_skill_md",

    # CLI
    "main",
]
