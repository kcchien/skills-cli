"""
Skills CLI Command Line Interface

此模組負責 CLI 的參數解析和指令處理，核心邏輯由 core 模組提供。
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .core import (
    DEFAULT_REPO,
    COMMON_SKILL_DIRS,
    Colors,
    log_info,
    log_success,
    log_warning,
    log_error,
    parse_repo_url,
    run_git,
    get_git_commit_hash,
    detect_default_branch,
    clone_repo,
    read_skill_metadata,
    discover_skills,
    find_skills_root,
    get_claude_skills_dir,
    backup_skill,
    install_skill,
    pack_skill,
    validate_skill_md,
)


# =============================================================================
# 輔助函式
# =============================================================================

def prepare_repo_info(args) -> dict:
    """準備 repo 資訊，處理 branch 覆蓋和自動偵測。"""
    repo_info = parse_repo_url(args.repo)

    if hasattr(args, 'branch') and args.branch:
        repo_info["branch"] = args.branch
    elif repo_info["branch"] == "main" and "/tree/" not in args.repo:
        log_info("Auto-detecting default branch...")
        repo_info["branch"] = detect_default_branch(repo_info["clone_url"])

    return repo_info


def format_skills_list(skills: list[dict], detailed: bool = False, show_source: bool = False) -> None:
    """格式化並輸出 skills 列表。"""
    if detailed:
        name_width = max(len(s.get("name") or s["folder_name"]) for s in skills)
        name_width = max(name_width, 4)

        print(f"\n  {'Name':<{name_width}}  Description")
        print(f"  {'-' * name_width}  {'-' * 50}")

        for skill in skills:
            name = skill.get("name") or skill["folder_name"]
            desc = skill.get("description") or "-"
            if len(desc) > 60:
                desc = desc[:57] + "..."
            print(f"  {Colors.CYAN}{name:<{name_width}}{Colors.RESET}  {desc}")

            if show_source:
                metadata = read_skill_metadata(skill.get("path"))
                if metadata:
                    source = metadata.get("source_url", "-")
                    branch = metadata.get("branch", "-")
                    commit = metadata.get("commit", "-")
                    if len(source) > 50:
                        source = source[:47] + "..."
                    print(f"  {' ' * name_width}  {Colors.YELLOW}↳ {source} ({branch}@{commit}){Colors.RESET}")
    else:
        names = [s.get("name") or s["folder_name"] for s in skills]
        print(f"\n  {', '.join(names)}")


def interactive_select(skills: list[dict]) -> list[dict]:
    """互動式 skill 選擇介面。"""
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


# =============================================================================
# CLI Commands
# =============================================================================

def cmd_list(args):
    """list 指令：列出遠端 repo 中可用的 skills。"""
    repo_info = prepare_repo_info(args)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / "repo"
        cloned_root = clone_repo(repo_info, tmp_dir)
        skills_root, skills = find_skills_root(cloned_root)

        if not skills:
            log_warning("No skills found in repository")
            return 1

        print(f"\n{Colors.BOLD}Skills in {args.repo}:{Colors.RESET}")
        format_skills_list(skills, detailed=args.detail)
        print(f"\n{Colors.GREEN}Total: {len(skills)} skills{Colors.RESET}\n")
        return 0


def cmd_installed(args):
    """installed 指令：列出本機已安裝的 skills。"""
    total_skills = 0

    if args.target:
        target_dir = Path(args.target)
        if not target_dir.exists():
            log_warning(f"Skills directory not found: {target_dir}")
            return 1

        skills = discover_skills(target_dir)
        if skills:
            print(f"\n{Colors.BOLD}Installed skills (custom):{Colors.RESET}")
            print(f"  {Colors.YELLOW}Location: {target_dir}{Colors.RESET}")
            format_skills_list(skills, detailed=args.detail, show_source=args.detail)
            total_skills = len(skills)
        else:
            log_warning(f"No skills installed in {target_dir}")
        print(f"\n{Colors.GREEN}Total: {total_skills} skills{Colors.RESET}\n")
        return 0

    scopes_to_show = []

    if not args.project:
        global_dir = get_claude_skills_dir("personal")
        if global_dir.exists():
            global_skills = discover_skills(global_dir)
            if global_skills:
                scopes_to_show.append(("global", global_dir, global_skills))

    project_dir = get_claude_skills_dir("project")
    if project_dir.exists():
        project_skills = discover_skills(project_dir)
        if project_skills:
            scopes_to_show.append(("project", project_dir, project_skills))

    if not scopes_to_show:
        if args.project:
            log_warning(f"No project skills found in {project_dir}")
        else:
            log_warning("No skills installed")
        return 0

    for scope, directory, skills in scopes_to_show:
        scope_label = f"[{scope.upper()}]"
        print(f"\n{Colors.BOLD}{scope_label} Installed skills:{Colors.RESET}")
        print(f"  {Colors.YELLOW}Location: {directory}{Colors.RESET}")
        format_skills_list(skills, detailed=args.detail, show_source=args.detail)
        total_skills += len(skills)
        print()

    print(f"{Colors.GREEN}Total: {total_skills} skills{Colors.RESET}\n")
    return 0


def cmd_remove(args):
    """remove 指令：移除已安裝的 skills。"""
    if args.project:
        target_dir = get_claude_skills_dir("project")
        scope = "project"
    else:
        target_dir = get_claude_skills_dir("personal")
        scope = "personal"

    if args.target:
        target_dir = Path(args.target)
        scope = "custom"

    if not target_dir.exists():
        log_warning(f"Skills directory not found: {target_dir}")
        return 1

    installed_skills = discover_skills(target_dir)

    if not installed_skills:
        log_warning(f"No skills installed in {target_dir}")
        return 0

    if args.skills:
        requested = set(s.strip().lower() for s in args.skills.split(","))
        skills_to_remove = [
            s for s in installed_skills
            if s["folder_name"].lower() in requested
            or (s.get("name") and s["name"].lower() in requested)
        ]

        if not skills_to_remove:
            log_error(f"No matching skills found for: {args.skills}")
            log_info("Installed skills: " + ", ".join(s["folder_name"] for s in installed_skills))
            return 1
    elif args.all:
        skills_to_remove = installed_skills
    else:
        skills_to_remove = interactive_select(installed_skills)

    if not skills_to_remove:
        log_info("No skills selected")
        return 0

    dry_run = getattr(args, 'dry_run', False)

    if dry_run:
        print(f"\n{Colors.YELLOW}[DRY RUN] The following skills would be removed:{Colors.RESET}\n")
        for skill in skills_to_remove:
            skill_name = skill.get("name") or skill["folder_name"]
            skill_path = skill["path"]
            print(f"  {Colors.RED}•{Colors.RESET} {skill_name}")
            print(f"    {Colors.YELLOW}Path: {skill_path}{Colors.RESET}")
        print()
        log_info(f"[DRY RUN] Would remove {len(skills_to_remove)} skills")
        return 0

    if not args.force:
        names = [s.get("name") or s["folder_name"] for s in skills_to_remove]
        print(f"\n{Colors.YELLOW}The following skills will be removed:{Colors.RESET}")
        for name in names:
            print(f"  {Colors.RED}•{Colors.RESET} {name}")
        print()

        try:
            confirm = input(f"{Colors.BOLD}Confirm removal? [y/N]{Colors.RESET} ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return 0

        if confirm not in ("y", "yes"):
            log_info("Cancelled")
            return 0

    removed = 0
    for skill in skills_to_remove:
        skill_path = skill["path"]
        skill_name = skill.get("name") or skill["folder_name"]
        try:
            shutil.rmtree(skill_path)
            log_success(f"Removed: {skill_name}")
            removed += 1
        except Exception as e:
            log_error(f"Failed to remove {skill_name}: {e}")

    print()
    log_success(f"Removed {removed}/{len(skills_to_remove)} skills")
    return 0


def cmd_install(args):
    """install 指令：從遠端 repo 安裝 skills 到本機。"""
    repo_info = prepare_repo_info(args)

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

        if args.skills:
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
            skills_to_install = interactive_select(all_skills)

        if not skills_to_install:
            log_info("No skills selected")
            return 0

        commit_hash = get_git_commit_hash(tmp_dir)

        dry_run = getattr(args, 'dry_run', False)
        backup = getattr(args, 'backup', False)

        if dry_run:
            print(f"\n{Colors.YELLOW}[DRY RUN] The following actions would be performed:{Colors.RESET}\n")

        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)

        installed = 0
        for skill in skills_to_install:
            skill_name = skill.get("name") or skill["folder_name"]
            success, message = install_skill(
                skill["path"],
                target_dir,
                repo_info=repo_info,
                commit_hash=commit_hash,
                force=args.force,
                backup=backup,
                dry_run=dry_run
            )
            if success:
                if dry_run:
                    print(f"  {Colors.CYAN}•{Colors.RESET} {skill_name}: {message}")
                else:
                    log_success(f"{skill_name}: {message}")
                installed += 1
            else:
                log_warning(f"{skill_name}: {message}")

        print()
        if dry_run:
            log_info(f"[DRY RUN] Would install {installed}/{len(skills_to_install)} skills to {target_dir}")
        else:
            log_success(f"Installed {installed}/{len(skills_to_install)} skills to {target_dir}")
        return 0


def cmd_pack(args):
    """pack 指令：將 skills 打包成 zip 檔案。"""
    repo_info = prepare_repo_info(args)
    output_dir = Path(args.output)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / "repo"
        cloned_root = clone_repo(repo_info, tmp_dir)
        skills_root, all_skills = find_skills_root(cloned_root)

        if not all_skills:
            log_error("No skills found in repository")
            return 1

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

        log_info(f"Packing {len(skills_to_pack)} skills to {output_dir}")

        for skill in skills_to_pack:
            pack_skill(skill["path"], output_dir)

        print()
        log_success(f"Packed {len(skills_to_pack)} skills")

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
    """sync 指令：從遠端 repo 同步 skills。"""
    repo_info = prepare_repo_info(args)

    if args.project:
        target_dir = get_claude_skills_dir("project")
    else:
        target_dir = get_claude_skills_dir("personal")

    if args.target:
        target_dir = Path(args.target)

    git_dir = target_dir / ".git"

    if git_dir.exists():
        log_info(f"Updating existing skills in {target_dir}")
        try:
            run_git(["pull", "--rebase"], cwd=target_dir)
            log_success("Skills updated successfully")
        except subprocess.CalledProcessError:
            log_error("Failed to update. Try removing and reinstalling.")
            return 1
    else:
        log_info(f"Cloning skills to {target_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)

        clone_url = repo_info["clone_url"]
        branch = repo_info["branch"]
        subdir = repo_info["subdir"]

        if subdir:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_dir = Path(tmp) / "repo"
                cloned_root = clone_repo(repo_info, tmp_dir)
                skills_root, skills = find_skills_root(cloned_root)

                for skill in skills:
                    skill_path = skill["path"]
                    dest = target_dir / skill_path.name
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(skill_path, dest)
                    log_success(f"Synced: {skill_path.name}")
        else:
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

    _, skills = find_skills_root(target_dir)
    if skills:
        print(f"\n{Colors.BOLD}Installed skills:{Colors.RESET}")
        for skill in skills:
            name = skill.get("name") or skill["folder_name"]
            print(f"  {Colors.CYAN}•{Colors.RESET} {name}")

    return 0


def cmd_validate(args):
    """validate 指令：驗證 SKILL.md 格式。"""

    def do_validate(skills_to_validate: list[dict]) -> int:
        """執行實際的驗證邏輯。"""
        if not skills_to_validate:
            log_warning("No skills to validate")
            return 1

        print(f"\n{Colors.BOLD}Validating {len(skills_to_validate)} skills...{Colors.RESET}\n")

        total_issues = 0
        for skill in skills_to_validate:
            skill_name = skill.get("name") or skill["folder_name"]
            issues = validate_skill_md(skill["path"])

            if issues:
                print(f"  {Colors.RED}✗{Colors.RESET} {Colors.BOLD}{skill_name}{Colors.RESET}")
                for issue in issues:
                    print(f"    {Colors.YELLOW}•{Colors.RESET} {issue}")
                total_issues += len(issues)
            else:
                print(f"  {Colors.GREEN}✓{Colors.RESET} {skill_name}")

        print()
        if total_issues > 0:
            log_warning(f"Found {total_issues} issues in {len(skills_to_validate)} skills")
            return 1
        else:
            log_success(f"All {len(skills_to_validate)} skills are valid")
            return 0

    # 根據不同來源取得要驗證的 skills
    if args.path:
        skill_path = Path(args.path)
        if skill_path.is_file():
            skill_path = skill_path.parent
        skills_to_validate = [{"path": skill_path, "folder_name": skill_path.name}]
        return do_validate(skills_to_validate)

    elif args.repo:
        # 從遠端 repo 驗證：需要在暫存目錄存在期間完成驗證
        repo_info = prepare_repo_info(args)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp) / "repo"
            cloned_root = clone_repo(repo_info, tmp_dir)
            skills_root, skills_to_validate = find_skills_root(cloned_root)
            return do_validate(skills_to_validate)

    else:
        # 驗證本地安裝的 skills
        if args.project:
            target_dir = get_claude_skills_dir("project")
        else:
            target_dir = get_claude_skills_dir("personal")
        skills_to_validate = discover_skills(target_dir)
        return do_validate(skills_to_validate)


def cmd_doctor(args):
    """doctor 指令：診斷 skills 目錄結構。"""
    issues = []
    warnings = []

    print(f"\n{Colors.BOLD}Skills CLI Doctor{Colors.RESET}\n")

    global_dir = get_claude_skills_dir("personal")
    print(f"  {Colors.CYAN}Global skills:{Colors.RESET} {global_dir}")
    if global_dir.exists():
        global_skills = discover_skills(global_dir)
        print(f"    {Colors.GREEN}✓{Colors.RESET} Directory exists ({len(global_skills)} skills)")

        for skill in global_skills:
            skill_issues = validate_skill_md(skill["path"])
            if skill_issues:
                warnings.append(f"Global skill '{skill['folder_name']}' has issues")
    else:
        print(f"    {Colors.YELLOW}⚠{Colors.RESET} Directory does not exist")

    project_dir = get_claude_skills_dir("project")
    print(f"\n  {Colors.CYAN}Project skills:{Colors.RESET} {project_dir}")
    if project_dir.exists():
        project_skills = discover_skills(project_dir)
        print(f"    {Colors.GREEN}✓{Colors.RESET} Directory exists ({len(project_skills)} skills)")

        for skill in project_skills:
            skill_issues = validate_skill_md(skill["path"])
            if skill_issues:
                warnings.append(f"Project skill '{skill['folder_name']}' has issues")
    else:
        print(f"    {Colors.YELLOW}○{Colors.RESET} Directory does not exist (this is normal)")

    print(f"\n  {Colors.CYAN}Checking for orphaned directories...{Colors.RESET}")
    orphaned = []
    for skills_dir in [global_dir, project_dir]:
        if skills_dir.exists():
            for item in skills_dir.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    skill_md = item / "SKILL.md"
                    if not skill_md.exists():
                        orphaned.append(item)
                        issues.append(f"Orphaned directory (no SKILL.md): {item}")

    if orphaned:
        for item in orphaned:
            print(f"    {Colors.RED}✗{Colors.RESET} {item.name} (no SKILL.md)")
    else:
        print(f"    {Colors.GREEN}✓{Colors.RESET} No orphaned directories")

    print(f"\n  {Colors.CYAN}Checking for backup directories...{Colors.RESET}")
    backup_dirs = []
    for skills_dir in [global_dir, project_dir]:
        backup_dir = skills_dir / ".backup"
        if backup_dir.exists():
            backup_count = len(list(backup_dir.iterdir()))
            backup_dirs.append((backup_dir, backup_count))
            print(f"    {Colors.YELLOW}○{Colors.RESET} {backup_dir} ({backup_count} backups)")

    if not backup_dirs:
        print(f"    {Colors.GREEN}✓{Colors.RESET} No backup directories")

    print(f"\n{Colors.BOLD}Summary:{Colors.RESET}")
    if issues:
        print(f"  {Colors.RED}✗{Colors.RESET} {len(issues)} issues found")
        for issue in issues:
            print(f"    • {issue}")
    else:
        print(f"  {Colors.GREEN}✓{Colors.RESET} No issues found")

    if warnings:
        print(f"  {Colors.YELLOW}⚠{Colors.RESET} {len(warnings)} warnings")
        for warning in warnings:
            print(f"    • {warning}")

    print()
    return 1 if issues else 0


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """CLI 程式進入點。"""
    parser = argparse.ArgumentParser(
        prog="skills-cli",
        description="Cross-platform CLI for managing Claude Code skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List skills from official Anthropic repo (default)
  skills-cli list
  skills-cli list --detail

  # List installed skills (shows global + project)
  skills-cli installed --detail

  # Install with safety options
  skills-cli install --all --dry-run        # preview what would be installed
  skills-cli install --all --backup         # backup before overwriting
  skills-cli install --skills pdf,xlsx

  # Remove skills
  skills-cli remove --skills pdf --dry-run  # preview removal
  skills-cli remove --all --force           # skip confirmation

  # Pack skills for Claude Desktop
  skills-cli pack --output dist/desktop

  # Validate and diagnose
  skills-cli validate                       # check installed skills
  skills-cli validate --repo <url>          # check remote repo
  skills-cli doctor                         # diagnose directory issues

  # Sync skills from repository
  skills-cli sync
"""
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # List command
    list_parser = subparsers.add_parser("list", help="List available skills from a repository")
    list_parser.add_argument("--repo", "-r", default=DEFAULT_REPO,
                             help=f"Repository URL (default: Anthropic official)")
    list_parser.add_argument("--branch", "-b", help="Git branch (default: auto-detect or main)")
    list_parser.add_argument("--detail", "-d", action="store_true",
                             help="Show detailed info (name and description)")
    list_parser.set_defaults(func=cmd_list)

    # Installed command
    installed_parser = subparsers.add_parser("installed", help="List installed skills")
    installed_parser.add_argument("--project", "-p", action="store_true",
                                  help="Show project skills (.claude/skills/)")
    installed_parser.add_argument("--target", "-t", help="Custom skills directory")
    installed_parser.add_argument("--detail", "-d", action="store_true",
                                  help="Show detailed info (name and description)")
    installed_parser.set_defaults(func=cmd_installed)

    # Remove command
    remove_parser = subparsers.add_parser("remove", aliases=["uninstall"],
                                          help="Remove installed skills")
    remove_parser.add_argument("--skills", "-s", help="Comma-separated list of skills to remove")
    remove_parser.add_argument("--all", "-a", action="store_true", help="Remove all skills")
    remove_parser.add_argument("--project", "-p", action="store_true",
                               help="Remove from project .claude/skills/")
    remove_parser.add_argument("--target", "-t", help="Custom skills directory")
    remove_parser.add_argument("--force", "-f", action="store_true",
                               help="Skip confirmation prompt")
    remove_parser.add_argument("--dry-run", action="store_true",
                               help="Show what would be removed without actually removing")
    remove_parser.set_defaults(func=cmd_remove)

    # Install command
    install_parser = subparsers.add_parser("install", help="Install skills from a repository")
    install_parser.add_argument("--repo", "-r", default=DEFAULT_REPO,
                                help=f"Repository URL (default: Anthropic official)")
    install_parser.add_argument("--branch", "-b", help="Git branch (default: auto-detect or main)")
    install_parser.add_argument("--skills", "-s", help="Comma-separated list of skills to install")
    install_parser.add_argument("--all", "-a", action="store_true", help="Install all skills")
    install_parser.add_argument("--project", "-p", action="store_true",
                                help="Install to project .claude/skills/")
    install_parser.add_argument("--target", "-t", help="Custom target directory")
    install_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing skills")
    install_parser.add_argument("--backup", action="store_true",
                                help="Backup existing skills before overwriting")
    install_parser.add_argument("--dry-run", action="store_true",
                                help="Show what would be installed without actually installing")
    install_parser.set_defaults(func=cmd_install)

    # Pack command
    pack_parser = subparsers.add_parser("pack", help="Pack skills into zip files for Claude Desktop")
    pack_parser.add_argument("--repo", "-r", default=DEFAULT_REPO,
                             help=f"Repository URL (default: Anthropic official)")
    pack_parser.add_argument("--branch", "-b", help="Git branch (default: auto-detect or main)")
    pack_parser.add_argument("--skills", "-s", help="Comma-separated list of skills to pack")
    pack_parser.add_argument("--output", "-o", default="dist/desktop", help="Output directory")
    pack_parser.set_defaults(func=cmd_pack)

    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Sync skills from a repository")
    sync_parser.add_argument("--repo", "-r", default=DEFAULT_REPO,
                             help=f"Repository URL (default: Anthropic official)")
    sync_parser.add_argument("--branch", "-b", help="Git branch (default: auto-detect or main)")
    sync_parser.add_argument("--project", "-p", action="store_true",
                             help="Sync to project .claude/skills/")
    sync_parser.add_argument("--target", "-t", help="Custom target directory")
    sync_parser.set_defaults(func=cmd_sync)

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate SKILL.md format")
    validate_parser.add_argument("--path", help="Path to skill directory or SKILL.md file")
    validate_parser.add_argument("--repo", "-r", help="Validate skills from a repository")
    validate_parser.add_argument("--branch", "-b", help="Git branch for --repo")
    validate_parser.add_argument("--project", "-p", action="store_true",
                                 help="Validate project skills")
    validate_parser.set_defaults(func=cmd_validate)

    # Doctor command
    doctor_parser = subparsers.add_parser("doctor", help="Diagnose skills directory issues")
    doctor_parser.set_defaults(func=cmd_doctor)

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
    import sys
    sys.exit(main())
