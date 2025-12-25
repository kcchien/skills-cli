#!/usr/bin/env python3
"""
Skills CLI - Cross-platform tool for managing Claude Code skills
Supports Windows, macOS, and Linux
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


# ANSI colors (disabled on Windows cmd without colorama)
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"

    @classmethod
    def disable(cls):
        cls.RESET = cls.BOLD = cls.RED = cls.GREEN = ""
        cls.YELLOW = cls.BLUE = cls.CYAN = ""


# Disable colors on Windows without proper terminal support
if sys.platform == "win32" and not os.environ.get("WT_SESSION"):
    try:
        import colorama
        colorama.init()
    except ImportError:
        Colors.disable()


def log_info(msg: str):
    print(f"{Colors.BLUE}ℹ{Colors.RESET} {msg}")


def log_success(msg: str):
    print(f"{Colors.GREEN}✓{Colors.RESET} {msg}")


def log_warning(msg: str):
    print(f"{Colors.YELLOW}⚠{Colors.RESET} {msg}")


def log_error(msg: str):
    print(f"{Colors.RED}✗{Colors.RESET} {msg}", file=sys.stderr)


def parse_repo_url(url: str) -> dict:
    """
    Parse a git repo URL and extract components.

    Supports:
    - https://github.com/owner/repo
    - https://github.com/owner/repo/tree/branch/subdir
    - https://gitlab.example.com/owner/repo
    - git@github.com:owner/repo.git
    """
    result = {
        "url": url,
        "clone_url": None,
        "branch": "main",
        "subdir": None,
        "host": None,
    }

    # Handle GitHub tree URLs (with branch and subdirectory)
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

    # Handle GitLab tree URLs
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

    # Handle plain HTTPS URLs
    if url.startswith("https://") or url.startswith("http://"):
        parsed = urlparse(url)
        result["host"] = parsed.netloc

        # Clean up path (remove .git suffix if present)
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            result["clone_url"] = url
        else:
            result["clone_url"] = f"{parsed.scheme}://{parsed.netloc}{path}.git"
        return result

    # Handle SSH URLs (git@host:owner/repo.git)
    ssh_match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
    if ssh_match:
        host, repo_path = ssh_match.groups()
        result["clone_url"] = f"git@{host}:{repo_path}.git"
        result["host"] = host
        return result

    # Fallback: assume it's a valid clone URL
    result["clone_url"] = url
    return result


def run_git(args: list, cwd: Optional[Path] = None, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a git command."""
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


def detect_default_branch(clone_url: str) -> str:
    """Auto-detect the default branch of a remote repository."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", clone_url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            # Parse output like: "ref: refs/heads/master\tHEAD"
            for line in result.stdout.split("\n"):
                if line.startswith("ref: refs/heads/"):
                    branch = line.split("refs/heads/")[1].split()[0]
                    return branch
    except (subprocess.TimeoutExpired, Exception):
        pass
    return "main"  # fallback


def clone_repo(repo_info: dict, target_dir: Path) -> Path:
    """Clone a repository to target directory."""
    clone_url = repo_info["clone_url"]
    branch = repo_info["branch"]
    subdir = repo_info["subdir"]

    log_info(f"Cloning from {clone_url} (branch: {branch})")

    # Use sparse checkout if subdirectory specified
    if subdir:
        log_info(f"Using sparse checkout for subdirectory: {subdir}")

        # Initialize empty repo
        target_dir.mkdir(parents=True, exist_ok=True)
        run_git(["init"], cwd=target_dir)
        run_git(["remote", "add", "origin", clone_url], cwd=target_dir)

        # Configure sparse checkout
        run_git(["config", "core.sparseCheckout", "true"], cwd=target_dir)
        sparse_file = target_dir / ".git" / "info" / "sparse-checkout"
        sparse_file.parent.mkdir(parents=True, exist_ok=True)
        sparse_file.write_text(f"{subdir}/*\n")

        # Pull the specific branch
        run_git(["pull", "origin", branch, "--depth=1"], cwd=target_dir)

        return target_dir / subdir
    else:
        # Regular shallow clone
        run_git([
            "clone",
            "--depth=1",
            "--branch", branch,
            clone_url,
            str(target_dir)
        ])
        return target_dir


def discover_skills(skills_dir: Path) -> list[dict]:
    """Discover all skills in a directory."""
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


# Common subdirectories where skills might be located
COMMON_SKILL_DIRS = [
    "skills",
    "claude-skills",
    ".claude/skills",
    "claude/skills",
    "src/skills",
]


def find_skills_root(repo_root: Path) -> tuple[Path, list[dict]]:
    """
    Find the skills root directory and discover skills.
    Returns (skills_root, skills_list).

    Search order:
    1. Root directory
    2. Common subdirectories (skills/, claude-skills/, etc.)
    3. Any directory containing SKILL.md files (breadth-first)
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
        # Find the common parent directory
        parents = set()
        for skill_md in skill_md_files:
            # The skill folder is the parent of SKILL.md
            # The skills root is the parent of the skill folder
            skill_folder = skill_md.parent
            skills_root = skill_folder.parent
            parents.add(skills_root)

        # If all skills share the same parent, use that
        if len(parents) == 1:
            skills_root = parents.pop()
            relative = skills_root.relative_to(repo_root)
            if str(relative) != ".":
                log_info(f"Found skills in: {relative}/")
            skills = discover_skills(skills_root)
            if skills:
                return skills_root, skills
        else:
            # Multiple parent directories - collect all skills
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

    # No skills found anywhere
    return repo_root, []


def parse_skill_md(skill_md: Path) -> dict:
    """Parse SKILL.md frontmatter to extract metadata."""
    content = skill_md.read_text(encoding="utf-8")

    result = {
        "name": None,
        "description": None,
    }

    # Parse YAML frontmatter
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


def get_claude_skills_dir(scope: str = "personal") -> Path:
    """Get the Claude skills directory."""
    if scope == "project":
        return Path.cwd() / ".claude" / "skills"
    else:
        # Personal skills directory
        home = Path.home()
        return home / ".claude" / "skills"


def install_skill(skill_path: Path, target_dir: Path, force: bool = False) -> bool:
    """Install a single skill to the target directory."""
    skill_name = skill_path.name
    dest_path = target_dir / skill_name

    if dest_path.exists():
        if force:
            log_warning(f"Overwriting existing skill: {skill_name}")
            shutil.rmtree(dest_path)
        else:
            log_warning(f"Skill already exists: {skill_name} (use --force to overwrite)")
            return False

    # Copy the skill directory
    shutil.copytree(skill_path, dest_path)
    log_success(f"Installed: {skill_name}")
    return True


def pack_skill(skill_path: Path, output_dir: Path) -> Path:
    """Pack a skill into a zip file for Claude Desktop."""
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


def interactive_select(skills: list[dict]) -> list[dict]:
    """Interactive skill selection."""
    print(f"\n{Colors.BOLD}Available Skills:{Colors.RESET}\n")

    for i, skill in enumerate(skills, 1):
        name = skill.get("name") or skill["folder_name"]
        desc = skill.get("description", "No description")
        print(f"  {Colors.CYAN}{i:3}{Colors.RESET}. {Colors.BOLD}{name}{Colors.RESET}")
        print(f"       {Colors.YELLOW}{desc}{Colors.RESET}")

    print(f"\n{Colors.BOLD}Enter selection:{Colors.RESET}")
    print("  - 'all' or '*' to install all")
    print("  - Comma-separated numbers (e.g., 1,3,5)")
    print("  - Range (e.g., 1-5)")
    print("  - 'q' to quit\n")

    try:
        selection = input(f"{Colors.GREEN}>{Colors.RESET} ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return []

    if selection in ("q", "quit", "exit"):
        return []

    if selection in ("all", "*", ""):
        return skills

    selected = []
    try:
        # Parse selection
        for part in selection.split(","):
            part = part.strip()
            if "-" in part:
                start, end = map(int, part.split("-"))
                for i in range(start, end + 1):
                    if 1 <= i <= len(skills):
                        selected.append(skills[i - 1])
            else:
                i = int(part)
                if 1 <= i <= len(skills):
                    selected.append(skills[i - 1])
    except ValueError:
        log_error("Invalid selection format")
        return []

    return selected


# ============================================================================
# CLI Commands
# ============================================================================

def prepare_repo_info(args) -> dict:
    """Parse repo URL and apply branch override or auto-detect."""
    repo_info = parse_repo_url(args.repo)

    # Override branch if specified via CLI
    if hasattr(args, 'branch') and args.branch:
        repo_info["branch"] = args.branch
    # Auto-detect if URL didn't specify a branch (wasn't a tree URL)
    elif repo_info["branch"] == "main" and "/tree/" not in args.repo:
        log_info("Auto-detecting default branch...")
        repo_info["branch"] = detect_default_branch(repo_info["clone_url"])

    return repo_info


def cmd_list(args):
    """List available skills from a repository."""
    repo_info = prepare_repo_info(args)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / "repo"
        cloned_root = clone_repo(repo_info, tmp_dir)
        skills_root, skills = find_skills_root(cloned_root)

        if not skills:
            log_warning("No skills found in repository")
            return 1

        print(f"\n{Colors.BOLD}Skills in {args.repo}:{Colors.RESET}\n")

        for skill in skills:
            name = skill.get("name") or skill["folder_name"]
            desc = skill.get("description", "No description")
            print(f"  {Colors.CYAN}•{Colors.RESET} {Colors.BOLD}{name}{Colors.RESET}")
            print(f"    {desc}")

        print(f"\n{Colors.GREEN}Total: {len(skills)} skills{Colors.RESET}\n")
        return 0


def cmd_install(args):
    """Install skills from a repository."""
    repo_info = prepare_repo_info(args)

    # Determine target directory
    if args.project:
        target_dir = get_claude_skills_dir("project")
    else:
        target_dir = get_claude_skills_dir("personal")

    if args.target:
        target_dir = Path(args.target)

    log_info(f"Target directory: {target_dir}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / "repo"
        cloned_root = clone_repo(repo_info, tmp_dir)
        skills_root, all_skills = find_skills_root(cloned_root)

        if not all_skills:
            log_error("No skills found in repository")
            return 1

        # Determine which skills to install
        if args.skills:
            # Filter by specified skill names
            requested = set(s.strip().lower() for s in args.skills.split(","))
            skills_to_install = [
                s for s in all_skills
                if s["folder_name"].lower() in requested
                or (s.get("name") and s["name"].lower() in requested)
            ]

            if not skills_to_install:
                log_error(f"No matching skills found for: {args.skills}")
                log_info("Available skills: " + ", ".join(s["folder_name"] for s in all_skills))
                return 1
        elif args.all:
            skills_to_install = all_skills
        else:
            # Interactive selection
            skills_to_install = interactive_select(all_skills)

        if not skills_to_install:
            log_info("No skills selected")
            return 0

        # Create target directory
        target_dir.mkdir(parents=True, exist_ok=True)

        # Install skills
        installed = 0
        for skill in skills_to_install:
            if install_skill(skill["path"], target_dir, force=args.force):
                installed += 1

        print()
        log_success(f"Installed {installed}/{len(skills_to_install)} skills to {target_dir}")
        return 0


def cmd_pack(args):
    """Pack skills into zip files for Claude Desktop."""
    repo_info = prepare_repo_info(args)
    output_dir = Path(args.output)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / "repo"
        cloned_root = clone_repo(repo_info, tmp_dir)
        skills_root, all_skills = find_skills_root(cloned_root)

        if not all_skills:
            log_error("No skills found in repository")
            return 1

        # Determine which skills to pack
        if args.skills:
            requested = set(s.strip().lower() for s in args.skills.split(","))
            skills_to_pack = [
                s for s in all_skills
                if s["folder_name"].lower() in requested
                or (s.get("name") and s["name"].lower() in requested)
            ]
        else:
            skills_to_pack = all_skills

        if not skills_to_pack:
            log_error("No matching skills found")
            return 1

        # Pack skills
        log_info(f"Packing {len(skills_to_pack)} skills to {output_dir}")

        for skill in skills_to_pack:
            pack_skill(skill["path"], output_dir)

        print()
        log_success(f"Packed {len(skills_to_pack)} skills")

        # Generate manifest
        manifest = {
            "skills": [
                {
                    "name": s.get("name") or s["folder_name"],
                    "folder": s["folder_name"],
                    "description": s.get("description"),
                    "zip": f"{s['folder_name']}.zip"
                }
                for s in skills_to_pack
            ]
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        log_success(f"Generated manifest: {manifest_path}")

        return 0


def cmd_sync(args):
    """Sync skills from a repository (git pull if exists, clone if not)."""
    repo_info = prepare_repo_info(args)

    # Determine target directory
    if args.project:
        target_dir = get_claude_skills_dir("project")
    else:
        target_dir = get_claude_skills_dir("personal")

    if args.target:
        target_dir = Path(args.target)

    # Check if it's a git repo
    git_dir = target_dir / ".git"

    if git_dir.exists():
        # Pull updates
        log_info(f"Updating existing skills in {target_dir}")
        try:
            run_git(["pull", "--rebase"], cwd=target_dir)
            log_success("Skills updated successfully")
        except subprocess.CalledProcessError:
            log_error("Failed to update. Try removing and reinstalling.")
            return 1
    else:
        # Fresh clone
        log_info(f"Cloning skills to {target_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)

        clone_url = repo_info["clone_url"]
        branch = repo_info["branch"]
        subdir = repo_info["subdir"]

        if subdir:
            # Need to clone to temp and copy subdirectory
            with tempfile.TemporaryDirectory() as tmp:
                tmp_dir = Path(tmp) / "repo"
                cloned_root = clone_repo(repo_info, tmp_dir)
                skills_root, skills = find_skills_root(cloned_root)

                # Copy all skills
                for skill in skills:
                    skill_path = skill["path"]
                    dest = target_dir / skill_path.name
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(skill_path, dest)
                    log_success(f"Synced: {skill_path.name}")
        else:
            # Clone to temp first to find skills, then copy
            with tempfile.TemporaryDirectory() as tmp:
                tmp_dir = Path(tmp) / "repo"
                run_git([
                    "clone",
                    "--depth=1",
                    "--branch", branch,
                    clone_url,
                    str(tmp_dir)
                ])
                skills_root, skills = find_skills_root(tmp_dir)

                if skills:
                    # Copy all skills
                    for skill in skills:
                        skill_path = skill["path"]
                        dest = target_dir / skill_path.name
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(skill_path, dest)
                        log_success(f"Synced: {skill_path.name}")
                else:
                    log_warning("No skills found in repository")
                    return 1

        log_success(f"Skills synced to {target_dir}")

    # List installed skills
    _, skills = find_skills_root(target_dir)
    if skills:
        print(f"\n{Colors.BOLD}Installed skills:{Colors.RESET}")
        for skill in skills:
            name = skill.get("name") or skill["folder_name"]
            print(f"  {Colors.CYAN}•{Colors.RESET} {name}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="skills-cli",
        description="Cross-platform CLI for managing Claude Code skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List skills from official Anthropic repo
  skills-cli list --repo https://github.com/anthropics/skills/tree/main/skills

  # Install all skills from a custom repo
  skills-cli install --repo https://gitlab.example.com/team/skills --all

  # Install specific skills
  skills-cli install --repo https://github.com/user/skills --skills pdf,xlsx,docx

  # Interactive installation
  skills-cli install --repo https://github.com/user/skills

  # Pack skills for Claude Desktop
  skills-cli pack --repo https://github.com/user/skills --output dist/desktop

  # Sync skills (pull if exists, clone if not)
  skills-cli sync --repo https://github.com/user/skills
"""
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # List command
    list_parser = subparsers.add_parser("list", help="List available skills from a repository")
    list_parser.add_argument("--repo", "-r", required=True, help="Repository URL")
    list_parser.add_argument("--branch", "-b", help="Git branch (default: auto-detect or main)")
    list_parser.set_defaults(func=cmd_list)

    # Install command
    install_parser = subparsers.add_parser("install", help="Install skills from a repository")
    install_parser.add_argument("--repo", "-r", required=True, help="Repository URL")
    install_parser.add_argument("--branch", "-b", help="Git branch (default: auto-detect or main)")
    install_parser.add_argument("--skills", "-s", help="Comma-separated list of skills to install")
    install_parser.add_argument("--all", "-a", action="store_true", help="Install all skills")
    install_parser.add_argument("--project", "-p", action="store_true", help="Install to project .claude/skills/")
    install_parser.add_argument("--target", "-t", help="Custom target directory")
    install_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing skills")
    install_parser.set_defaults(func=cmd_install)

    # Pack command
    pack_parser = subparsers.add_parser("pack", help="Pack skills into zip files for Claude Desktop")
    pack_parser.add_argument("--repo", "-r", required=True, help="Repository URL")
    pack_parser.add_argument("--branch", "-b", help="Git branch (default: auto-detect or main)")
    pack_parser.add_argument("--skills", "-s", help="Comma-separated list of skills to pack")
    pack_parser.add_argument("--output", "-o", default="dist/desktop", help="Output directory")
    pack_parser.set_defaults(func=cmd_pack)

    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Sync skills from a repository")
    sync_parser.add_argument("--repo", "-r", required=True, help="Repository URL")
    sync_parser.add_argument("--branch", "-b", help="Git branch (default: auto-detect or main)")
    sync_parser.add_argument("--project", "-p", action="store_true", help="Sync to project .claude/skills/")
    sync_parser.add_argument("--target", "-t", help="Custom target directory")
    sync_parser.set_defaults(func=cmd_sync)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print()
        return 130
    except Exception as e:
        log_error(f"Error: {e}")
        if os.environ.get("DEBUG"):
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
