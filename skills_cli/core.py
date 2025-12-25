"""
Skills CLI Core Library

This module contains all core logic independent of the CLI interface,
allowing reuse by other Python programs.

Main Features:
    - Git operations: clone, sparse checkout, branch detection
    - Skill discovery: find and parse skills in directories
    - Installation management: install, backup, metadata tracking
    - Packaging: pack skills for Claude Desktop
    - Validation: validate SKILL.md format

Design Principles:
    - Zero dependencies: only uses Python standard library
    - Pure functions: prefer pure functions for easier testing
    - Clear error handling: return explicit error messages on failure
"""

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


# =============================================================================
# Global Configuration
# =============================================================================

# Default to Anthropic's official skills repo
DEFAULT_REPO = "https://github.com/anthropics/skills/tree/main/skills"

# Metadata file name for tracking installation source
METADATA_FILE = ".skills-cli.json"

# Required fields in SKILL.md
REQUIRED_SKILL_FIELDS = ["name", "description"]

# Common skill subdirectory locations
COMMON_SKILL_DIRS = [
    "skills",
    "claude-skills",
    ".claude/skills",
    "claude/skills",
    "src/skills",
]


# =============================================================================
# Terminal Color Handling
# =============================================================================

class Colors:
    """
    ANSI color code wrapper class.

    Design considerations:
        - Uses class attributes instead of instance, as colors are global settings
        - Provides disable() method for older Windows cmd compatibility
    """
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"

    @classmethod
    def disable(cls):
        """Disable all color output."""
        cls.RESET = cls.BOLD = cls.RED = cls.GREEN = ""
        cls.YELLOW = cls.BLUE = cls.CYAN = ""


# Windows terminal compatibility handling
if sys.platform == "win32" and not os.environ.get("WT_SESSION"):
    try:
        import colorama
        colorama.init()
    except ImportError:
        Colors.disable()


# =============================================================================
# Logging Functions
# =============================================================================

def log_info(msg: str):
    """Info message (blue ℹ)."""
    print(f"{Colors.BLUE}ℹ{Colors.RESET} {msg}")


def log_success(msg: str):
    """Success message (green ✓)."""
    print(f"{Colors.GREEN}✓{Colors.RESET} {msg}")


def log_warning(msg: str):
    """Warning message (yellow ⚠)."""
    print(f"{Colors.YELLOW}⚠{Colors.RESET} {msg}")


def log_error(msg: str):
    """Error message (red ✗)."""
    print(f"{Colors.RED}✗{Colors.RESET} {msg}", file=sys.stderr)


# =============================================================================
# URL Parsing
# =============================================================================

def parse_repo_url(url: str) -> dict:
    """
    Parse Git repo URL and extract its components.

    Supported URL formats:
        - GitHub browser URL: https://github.com/owner/repo/tree/branch/subdir
        - GitLab browser URL: https://gitlab.com/owner/repo/-/tree/branch/subdir
        - Plain HTTPS URL: https://github.com/owner/repo
        - SSH URL: git@github.com:owner/repo.git

    Returns:
        dict with keys: url, clone_url, branch, subdir, host
    """
    result = {
        "url": url,
        "clone_url": None,
        "branch": "main",
        "subdir": None,
        "host": None,
    }

    # GitHub tree URL
    github_tree_match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)(?:/(.+))?",
        url
    )
    if github_tree_match:
        owner, repo, branch, subdir = github_tree_match.groups()
        result["clone_url"] = f"https://github.com/{owner}/{repo}.git"
        result["branch"] = branch
        result["subdir"] = subdir
        result["host"] = "github"
        return result

    # GitLab tree URL
    gitlab_tree_match = re.match(
        r"(https://[^/]+)/([^/]+/[^/]+)/-/tree/([^/]+)(?:/(.+))?",
        url
    )
    if gitlab_tree_match:
        host, repo_path, branch, subdir = gitlab_tree_match.groups()
        result["clone_url"] = f"{host}/{repo_path}.git"
        result["branch"] = branch
        result["subdir"] = subdir
        result["host"] = "gitlab"
        return result

    # Plain HTTPS URL
    if url.startswith("https://") or url.startswith("http://"):
        parsed = urlparse(url)
        result["host"] = parsed.netloc
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            result["clone_url"] = url
        else:
            result["clone_url"] = f"{parsed.scheme}://{parsed.netloc}{path}.git"
        return result

    # SSH URL
    ssh_match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
    if ssh_match:
        host, repo_path = ssh_match.groups()
        result["clone_url"] = f"git@{host}:{repo_path}.git"
        result["host"] = host
        return result

    result["clone_url"] = url
    return result


# =============================================================================
# Git Operations
# =============================================================================

def run_git(args: list, cwd: Optional[Path] = None, capture: bool = True) -> subprocess.CompletedProcess:
    """
    Unified interface for executing Git commands.

    Args:
        args: Git command arguments (without 'git' itself)
        cwd: Working directory
        capture: Whether to capture output
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            check=True
        )
        return result
    except subprocess.CalledProcessError as e:
        log_error(f"Git command failed: {' '.join(cmd)}")
        if e.stderr:
            log_error(e.stderr.strip())
        raise


def get_git_commit_hash(repo_dir: Path) -> Optional[str]:
    """Get the current commit hash (short version) of a Git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def detect_default_branch(clone_url: str) -> str:
    """
    Auto-detect the default branch name of a remote repo.

    Uses `git ls-remote --symref` to query, defaults to "main" on failure.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", clone_url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if line.startswith("ref: refs/heads/"):
                    branch = line.split("refs/heads/")[1].split()[0]
                    return branch
    except (subprocess.TimeoutExpired, Exception):
        pass
    return "main"


def clone_repo(repo_info: dict, target_dir: Path) -> Path:
    """
    Clone a Git repo to the specified directory.

    Supports sparse checkout to only download required subdirectories.

    Returns:
        The actual skills root directory path
    """
    clone_url = repo_info["clone_url"]
    branch = repo_info["branch"]
    subdir = repo_info["subdir"]

    log_info(f"Cloning from {clone_url} (branch: {branch})")

    if subdir:
        log_info(f"Using sparse checkout for subdirectory: {subdir}")

        target_dir.mkdir(parents=True, exist_ok=True)
        run_git(["init"], cwd=target_dir)
        run_git(["remote", "add", "origin", clone_url], cwd=target_dir)

        run_git(["config", "core.sparseCheckout", "true"], cwd=target_dir)
        sparse_file = target_dir / ".git" / "info" / "sparse-checkout"
        sparse_file.parent.mkdir(parents=True, exist_ok=True)
        sparse_file.write_text(f"{subdir}/*\n")

        run_git(["pull", "origin", branch, "--depth=1"], cwd=target_dir)

        return target_dir / subdir
    else:
        run_git([
            "clone",
            "--depth=1",
            "--branch", branch,
            clone_url,
            str(target_dir)
        ])
        return target_dir


# =============================================================================
# Metadata Tracking
# =============================================================================

def write_skill_metadata(skill_dir: Path, repo_info: dict, commit_hash: Optional[str] = None):
    """Write installation source metadata file in the skill directory."""
    metadata = {
        "source_url": repo_info.get("url"),
        "clone_url": repo_info.get("clone_url"),
        "branch": repo_info.get("branch"),
        "commit": commit_hash,
        "installed_at": datetime.now().isoformat(),
        "installed_by": "skills-cli",
    }
    metadata_path = skill_dir / METADATA_FILE
    metadata_path.write_text(json.dumps(metadata, indent=2))


def read_skill_metadata(skill_dir: Path) -> Optional[dict]:
    """Read the metadata file from a skill directory."""
    metadata_path = skill_dir / METADATA_FILE
    if metadata_path.exists():
        try:
            return json.loads(metadata_path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return None


# =============================================================================
# Skill Discovery and Parsing
# =============================================================================

def discover_skills(skills_dir: Path) -> list[dict]:
    """
    Discover all skills in a directory.

    Criteria: folder must contain a SKILL.md file.

    Returns:
        Each skill is a dict containing path, folder_name, name, description
    """
    skills = []

    if not skills_dir.exists():
        return skills

    for item in skills_dir.iterdir():
        if item.is_dir():
            skill_md = item / "SKILL.md"
            if skill_md.exists():
                skill_info = parse_skill_md(skill_md)
                skill_info["path"] = item
                skill_info["folder_name"] = item.name
                skills.append(skill_info)

    return sorted(skills, key=lambda x: x.get("name", x["folder_name"]))


def find_skills_root(repo_root: Path) -> tuple[Path, list[dict]]:
    """
    Find the skills root directory in a repo.

    Search order:
        1. Root directory itself
        2. Common subdirectory names
        3. Recursive search for directories containing SKILL.md

    Returns:
        (skills_root, skills_list)
    """
    # 1. Try root directory first
    skills = discover_skills(repo_root)
    if skills:
        return repo_root, skills

    # 2. Try common subdirectories
    for subdir in COMMON_SKILL_DIRS:
        candidate = repo_root / subdir
        if candidate.exists() and candidate.is_dir():
            skills = discover_skills(candidate)
            if skills:
                log_info(f"Found skills in: {subdir}/")
                return candidate, skills

    # 3. Search for any SKILL.md files (up to 3 levels deep)
    skill_md_files = []
    for depth in range(1, 4):
        pattern = "/".join(["*"] * depth) + "/SKILL.md"
        skill_md_files.extend(repo_root.glob(pattern))
        if skill_md_files:
            break

    if skill_md_files:
        parents = set()
        for skill_md in skill_md_files:
            skill_folder = skill_md.parent
            skills_root = skill_folder.parent
            parents.add(skills_root)

        if len(parents) == 1:
            skills_root = parents.pop()
            relative = skills_root.relative_to(repo_root)
            if str(relative) != ".":
                log_info(f"Found skills in: {relative}/")
            skills = discover_skills(skills_root)
            if skills:
                return skills_root, skills
        else:
            log_info("Found skills in multiple directories")
            all_skills = []
            for skill_md in skill_md_files:
                skill_folder = skill_md.parent
                skill_info = parse_skill_md(skill_md)
                skill_info["path"] = skill_folder
                skill_info["folder_name"] = skill_folder.name
                all_skills.append(skill_info)
            if all_skills:
                return repo_root, sorted(all_skills, key=lambda x: x.get("name", x["folder_name"]))

    return repo_root, []


def parse_skill_md(skill_md: Path) -> dict:
    """
    Parse the YAML frontmatter from a SKILL.md file.

    Returns:
        dict with name and description (may be None)
    """
    content = skill_md.read_text(encoding="utf-8")

    result = {
        "name": None,
        "description": None,
    }

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            for line in frontmatter.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip().strip('"').strip("'")
                    if key in ("name", "description"):
                        result[key] = value

    return result


# =============================================================================
# Installation and Management
# =============================================================================

def get_claude_skills_dir(scope: str = "personal") -> Path:
    """
    Get the Claude Code skills installation directory.

    Args:
        scope: "personal" (global) or "project"
    """
    if scope == "project":
        return Path.cwd() / ".claude" / "skills"
    else:
        return Path.home() / ".claude" / "skills"


def backup_skill(skill_path: Path) -> Optional[Path]:
    """
    Backup an existing skill directory.

    Returns:
        Backup path, or None if directory doesn't exist
    """
    if not skill_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = skill_path.parent / ".backup"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / f"{skill_path.name}_{timestamp}"

    shutil.copytree(skill_path, backup_path)
    return backup_path


def install_skill(
    skill_path: Path,
    target_dir: Path,
    repo_info: Optional[dict] = None,
    commit_hash: Optional[str] = None,
    force: bool = False,
    backup: bool = False,
    dry_run: bool = False
) -> tuple[bool, str]:
    """
    Install a single skill to the target directory.

    Returns:
        (success, message) tuple
    """
    skill_name = skill_path.name
    dest_path = target_dir / skill_name
    action = "install"

    if dest_path.exists():
        if not force:
            return (False, f"already exists (use --force to overwrite)")
        action = "overwrite"

        if dry_run:
            return (True, f"would overwrite existing skill")

        if backup:
            backup_path = backup_skill(dest_path)
            if backup_path:
                log_info(f"Backed up to: {backup_path}")

        shutil.rmtree(dest_path)
    else:
        if dry_run:
            return (True, f"would install to {dest_path}")

    shutil.copytree(skill_path, dest_path)

    if repo_info:
        write_skill_metadata(dest_path, repo_info, commit_hash)

    return (True, "installed" if action == "install" else "updated")


def pack_skill(skill_path: Path, output_dir: Path) -> Path:
    """
    Pack a skill into a zip file.

    Returns:
        Path to the zip file
    """
    skill_name = skill_path.name
    zip_path = output_dir / f"{skill_name}.zip"

    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in skill_path.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(skill_path.parent)
                zf.write(file_path, arcname)

    log_success(f"Packed: {zip_path}")
    return zip_path


# =============================================================================
# Validation
# =============================================================================

def validate_skill_md(skill_path: Path) -> list[str]:
    """
    Validate a skill's SKILL.md format.

    Returns:
        List of issues, empty list if validation passes
    """
    issues = []
    skill_md = skill_path / "SKILL.md"

    if not skill_md.exists():
        issues.append("Missing SKILL.md file")
        return issues

    try:
        content = skill_md.read_text(encoding="utf-8")
    except Exception as e:
        issues.append(f"Cannot read SKILL.md: {e}")
        return issues

    if not content.startswith("---"):
        issues.append("Missing YAML frontmatter (should start with ---)")
        return issues

    parts = content.split("---", 2)
    if len(parts) < 3:
        issues.append("Invalid YAML frontmatter (missing closing ---)")
        return issues

    frontmatter = parts[1].strip()
    body = parts[2].strip()

    metadata = {}
    for line in frontmatter.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip().strip('"').strip("'")

    for field in REQUIRED_SKILL_FIELDS:
        if field not in metadata or not metadata[field]:
            issues.append(f"Missing required field: {field}")

    if not body:
        issues.append("Empty skill body (no instructions after frontmatter)")

    if metadata.get("name") and len(metadata["name"]) > 50:
        issues.append("Name is too long (>50 characters)")

    if metadata.get("description") and len(metadata["description"]) > 500:
        issues.append("Description is too long (>500 characters)")

    return issues
