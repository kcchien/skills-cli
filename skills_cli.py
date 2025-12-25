#!/usr/bin/env python3
"""
Skills CLI - 跨平台 Claude Code Skills 管理工具

設計理念：
    1. 零依賴：只使用 Python 標準庫，避免使用者需要額外安裝套件
    2. 跨平台：Windows、macOS、Linux 都能正常運作
    3. 安全優先：提供 --dry-run、--backup 等安全機制，避免誤操作
    4. 來源追蹤：記錄每個 skill 的安裝來源，方便後續維護與更新

使用情境：
    - 個人開發者：從官方或社群 repo 安裝 skills
    - 團隊協作：從公司內部 repo 統一管理 skills
    - CI/CD：自動化打包 skills 給 Claude Desktop

注意事項：
    - 此工具會修改 ~/.claude/skills/ 目錄，請確保有備份
    - 使用 --force 時請小心，會覆蓋現有檔案
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
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


# =============================================================================
# 全域設定
# =============================================================================

# 預設使用 Anthropic 官方 skills repo
# 選擇這個作為預設是因為：
# 1. 官方維護，品質有保證
# 2. 降低使用門檻，新手可以直接 `skills-cli list` 而不需要知道 repo URL
DEFAULT_REPO = "https://github.com/anthropics/skills/tree/main/skills"

# 安裝來源的 metadata 檔案名稱
# 使用 . 開頭讓它在 Unix 系統上是隱藏檔案
# 這個檔案記錄了 skill 是從哪裡安裝的，方便之後 sync 或 debug
METADATA_FILE = ".skills-cli.json"


# =============================================================================
# 終端機顏色處理
# =============================================================================

class Colors:
    """
    ANSI 顏色碼封裝類別

    設計考量：
        - 使用 class attributes 而非 instance，因為顏色是全域設定
        - 提供 disable() 方法讓 Windows 舊版 cmd 可以關閉顏色
        - 選用亮色系 (91-96) 而非標準色 (31-36)，在深色終端機上更清晰
    """
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"      # 錯誤、刪除
    GREEN = "\033[92m"    # 成功、新增
    YELLOW = "\033[93m"   # 警告、注意
    BLUE = "\033[94m"     # 資訊、提示
    CYAN = "\033[96m"     # 強調、選項

    @classmethod
    def disable(cls):
        """關閉所有顏色輸出（用於不支援 ANSI 的終端機）"""
        cls.RESET = cls.BOLD = cls.RED = cls.GREEN = ""
        cls.YELLOW = cls.BLUE = cls.CYAN = ""


# Windows 終端機相容性處理
# WT_SESSION 環境變數存在表示使用 Windows Terminal，它原生支援 ANSI
# 舊版 cmd.exe 需要 colorama 來處理顏色，如果沒安裝就關閉顏色
if sys.platform == "win32" and not os.environ.get("WT_SESSION"):
    try:
        import colorama
        colorama.init()
    except ImportError:
        Colors.disable()


# =============================================================================
# 日誌輸出函式
# =============================================================================
# 統一使用 emoji + 顏色的格式，讓輸出更易讀
# 這些函式是全域使用的，所以放在最上層

def log_info(msg: str):
    """資訊訊息（藍色 ℹ）：用於一般狀態更新"""
    print(f"{Colors.BLUE}ℹ{Colors.RESET} {msg}")


def log_success(msg: str):
    """成功訊息（綠色 ✓）：用於操作完成確認"""
    print(f"{Colors.GREEN}✓{Colors.RESET} {msg}")


def log_warning(msg: str):
    """警告訊息（黃色 ⚠）：用於需要注意但非錯誤的情況"""
    print(f"{Colors.YELLOW}⚠{Colors.RESET} {msg}")


def log_error(msg: str):
    """錯誤訊息（紅色 ✗）：輸出到 stderr，用於失敗情況"""
    print(f"{Colors.RED}✗{Colors.RESET} {msg}", file=sys.stderr)


# =============================================================================
# URL 解析與 Git 操作
# =============================================================================

def parse_repo_url(url: str) -> dict:
    """
    解析 Git repo URL，萃取各個組成元素。

    設計意圖：
        使用者可能貼上各種格式的 URL（從瀏覽器複製、從 git clone 指令複製等），
        這個函式統一處理這些變體，讓使用者不需要關心 URL 格式。

    支援的 URL 格式：
        - GitHub 瀏覽器 URL: https://github.com/owner/repo/tree/branch/subdir
        - GitLab 瀏覽器 URL: https://gitlab.com/owner/repo/-/tree/branch/subdir
        - 一般 HTTPS URL: https://github.com/owner/repo
        - SSH URL: git@github.com:owner/repo.git

    回傳格式：
        {
            "url": 原始 URL,
            "clone_url": 可用於 git clone 的 URL,
            "branch": 分支名稱（預設 main）,
            "subdir": 子目錄路徑（如果有的話）,
            "host": 主機名稱（github/gitlab/其他）
        }

    注意事項：
        - branch 預設為 "main"，但後續會用 detect_default_branch() 自動偵測
        - subdir 用於 sparse checkout，只下載特定子目錄
    """
    result = {
        "url": url,
        "clone_url": None,
        "branch": "main",
        "subdir": None,
        "host": None,
    }

    # GitHub tree URL 格式：最常見的情況是使用者從瀏覽器複製 URL
    # 例如：https://github.com/anthropics/skills/tree/main/skills
    # 需要解析出 branch (main) 和 subdir (skills)
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

    # GitLab tree URL 格式：GitLab 的 URL 結構略有不同，使用 /-/tree/
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

    # 一般 HTTPS URL：可能是 repo 首頁或已經是 clone URL
    if url.startswith("https://") or url.startswith("http://"):
        parsed = urlparse(url)
        result["host"] = parsed.netloc

        # 確保 clone URL 以 .git 結尾
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            result["clone_url"] = url
        else:
            result["clone_url"] = f"{parsed.scheme}://{parsed.netloc}{path}.git"
        return result

    # SSH URL 格式：git@github.com:owner/repo.git
    # 這通常是開發者慣用的格式，需要有 SSH key 設定
    ssh_match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", url)
    if ssh_match:
        host, repo_path = ssh_match.groups()
        result["clone_url"] = f"git@{host}:{repo_path}.git"
        result["host"] = host
        return result

    # 最後手段：假設使用者知道自己在做什麼，直接使用
    result["clone_url"] = url
    return result


def run_git(args: list, cwd: Optional[Path] = None, capture: bool = True) -> subprocess.CompletedProcess:
    """
    執行 Git 指令的統一介面。

    設計意圖：
        - 統一錯誤處理，避免每次呼叫 git 都要寫 try-except
        - 提供一致的錯誤訊息格式
        - 方便未來加入 debug logging

    參數：
        args: Git 指令參數（不含 'git' 本身）
        cwd: 工作目錄
        capture: 是否捕捉輸出（某些情況需要看到即時輸出）

    注意事項：
        - 使用 check=True 讓失敗時自動拋出例外
        - 錯誤訊息會輸出完整的指令，方便使用者自行除錯
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
    """
    取得 Git repo 目前的 commit hash（短版本）。

    用途：
        記錄在 metadata 中，讓使用者知道安裝的是哪個版本，
        方便之後追蹤問題或回報 bug 時提供版本資訊。

    使用短 hash（7 字元）而非完整 hash，因為：
        1. 對人類更友善，容易閱讀
        2. 在大多數情況下已足夠唯一識別
        3. 顯示時不會太長
    """
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


# =============================================================================
# Metadata 追蹤功能
# =============================================================================
# 這組函式負責記錄每個 skill 的安裝來源
# 解決的問題：當使用者混用多個 repo 時，需要知道每個 skill 來自哪裡

def write_skill_metadata(skill_dir: Path, repo_info: dict, commit_hash: Optional[str] = None):
    """
    在 skill 目錄中寫入安裝來源的 metadata 檔案。

    設計意圖：
        當使用者從多個 repo 安裝 skills 時，需要追蹤：
        1. 這個 skill 從哪裡來？（source_url）
        2. 是哪個 branch/commit？（方便 sync 或除錯）
        3. 什麼時候安裝的？（排查問題用）

    檔案格式選擇 JSON 而非 YAML 是因為：
        - Python 標準庫就有 json module
        - 避免增加額外依賴
    """
    metadata = {
        "source_url": repo_info.get("url"),      # 使用者提供的原始 URL
        "clone_url": repo_info.get("clone_url"), # 實際用於 clone 的 URL
        "branch": repo_info.get("branch"),       # 分支名稱
        "commit": commit_hash,                    # 安裝當下的 commit hash
        "installed_at": datetime.now().isoformat(),
        "installed_by": "skills-cli",            # 標記是由此工具安裝的
    }
    metadata_path = skill_dir / METADATA_FILE
    metadata_path.write_text(json.dumps(metadata, indent=2))


def read_skill_metadata(skill_dir: Path) -> Optional[dict]:
    """
    讀取 skill 目錄中的 metadata 檔案。

    注意事項：
        - 舊版安裝的 skill 可能沒有這個檔案，回傳 None
        - 檔案可能被手動修改或損壞，需要處理例外
    """
    metadata_path = skill_dir / METADATA_FILE
    if metadata_path.exists():
        try:
            return json.loads(metadata_path.read_text())
        except (json.JSONDecodeError, IOError):
            # 檔案損壞或無法讀取，靜默失敗
            pass
    return None


# =============================================================================
# Git 操作函式
# =============================================================================

def detect_default_branch(clone_url: str) -> str:
    """
    自動偵測遠端 repo 的預設分支名稱。

    設計意圖：
        不同 repo 可能使用不同的預設分支（main、master、develop 等），
        與其讓使用者每次都要指定 --branch，不如自動偵測。

    實作方式：
        使用 `git ls-remote --symref` 查詢遠端的 HEAD 指向哪個分支。
        這個方法不需要真的 clone repo，只是一個輕量的網路請求。

    Fallback 策略：
        如果偵測失敗（網路問題、private repo 等），預設使用 "main"。
        選擇 main 而非 master 是因為 GitHub 在 2020 年後的預設就是 main。
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", clone_url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=30  # 避免網路問題導致卡住
        )
        if result.returncode == 0:
            # 輸出格式：ref: refs/heads/master\tHEAD
            for line in result.stdout.split("\n"):
                if line.startswith("ref: refs/heads/"):
                    branch = line.split("refs/heads/")[1].split()[0]
                    return branch
    except (subprocess.TimeoutExpired, Exception):
        pass
    return "main"


def clone_repo(repo_info: dict, target_dir: Path) -> Path:
    """
    Clone 一個 Git repo 到指定目錄。

    設計考量：
        1. 使用 shallow clone (--depth=1) 節省時間和空間
        2. 支援 sparse checkout，只下載需要的子目錄
           這對於大型 monorepo 特別重要，避免下載整個專案

    Sparse Checkout 說明：
        當使用者提供像 https://github.com/.../tree/main/skills 這樣的 URL 時，
        我們只需要下載 skills/ 子目錄，而不是整個 repo。
        這透過 Git 的 sparse-checkout 功能實現。

    回傳值：
        實際的 skills 根目錄路徑（可能是 target_dir 或其子目錄）
    """
    clone_url = repo_info["clone_url"]
    branch = repo_info["branch"]
    subdir = repo_info["subdir"]

    log_info(f"Cloning from {clone_url} (branch: {branch})")

    if subdir:
        # Sparse checkout 模式：只下載特定子目錄
        log_info(f"Using sparse checkout for subdirectory: {subdir}")

        # 初始化空的 git repo
        target_dir.mkdir(parents=True, exist_ok=True)
        run_git(["init"], cwd=target_dir)
        run_git(["remote", "add", "origin", clone_url], cwd=target_dir)

        # 設定 sparse checkout 規則
        run_git(["config", "core.sparseCheckout", "true"], cwd=target_dir)
        sparse_file = target_dir / ".git" / "info" / "sparse-checkout"
        sparse_file.parent.mkdir(parents=True, exist_ok=True)
        sparse_file.write_text(f"{subdir}/*\n")

        # 拉取指定分支（shallow）
        run_git(["pull", "origin", branch, "--depth=1"], cwd=target_dir)

        return target_dir / subdir
    else:
        # 一般的 shallow clone
        run_git([
            "clone",
            "--depth=1",
            "--branch", branch,
            clone_url,
            str(target_dir)
        ])
        return target_dir


# =============================================================================
# Skill 探索與解析
# =============================================================================

def discover_skills(skills_dir: Path) -> list[dict]:
    """
    探索目錄中的所有 skills。

    判斷一個資料夾是否為 skill 的依據：
        資料夾內必須有 SKILL.md 檔案。
        這是 Claude Code 定義的標準格式。

    回傳格式：
        每個 skill 是一個 dict，包含：
        - path: 完整路徑
        - folder_name: 資料夾名稱
        - name: SKILL.md 中定義的名稱（可能為 None）
        - description: SKILL.md 中的描述（可能為 None）

    排序：
        按名稱字母順序排序，讓輸出可預期
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


# 常見的 skills 子目錄位置
# 不同專案可能把 skills 放在不同位置，這裡列出常見的命名慣例
# 順序很重要：最常見的放前面，可以更快找到
COMMON_SKILL_DIRS = [
    "skills",           # 最常見
    "claude-skills",    # 明確標示用途
    ".claude/skills",   # 隱藏目錄
    "claude/skills",    # 子目錄
    "src/skills",       # 程式碼風格
]


def find_skills_root(repo_root: Path) -> tuple[Path, list[dict]]:
    """
    在 repo 中尋找 skills 的根目錄。

    設計意圖：
        不同 repo 可能有不同的目錄結構，這個函式嘗試自動找到 skills 所在位置，
        讓使用者不需要指定確切路徑。

    搜尋順序（優先度由高到低）：
        1. 根目錄本身就是 skills 目錄
        2. 常見的子目錄命名（skills/, claude-skills/ 等）
        3. 遞迴搜尋包含 SKILL.md 的目錄（最多 3 層深度）

    為什麼要有這個順序：
        - 根目錄優先：專門的 skills repo 通常直接把 skills 放在根目錄
        - 常見命名次之：大型專案通常遵循命名慣例
        - 遞迴搜尋最後：避免不必要的檔案系統遍歷

    回傳：
        (skills_root, skills_list) - 根目錄路徑和找到的 skills 列表
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
    """
    解析 SKILL.md 檔案的 YAML frontmatter 來取得 metadata。

    設計意圖：
        SKILL.md 使用 YAML frontmatter 格式（類似 Jekyll/Hugo 等靜態網站產生器），
        這是一種被廣泛使用的格式，讓人和機器都能輕鬆讀取 metadata。

    檔案格式範例：
        ---
        name: PDF 工具
        description: 處理 PDF 檔案的工具
        ---
        這裡是 skill 的詳細說明...

    為什麼自己解析而不用 YAML 套件：
        1. 零依賴原則：避免使用者需要安裝 PyYAML
        2. 我們只需要簡單的 key: value 格式
        3. 完整 YAML 解析器對於這個用途過於複雜
    """
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
    """
    取得 Claude Code skills 的安裝目錄。

    Claude Code 支援兩種 skills 作用域：
        - personal (global)：安裝在 ~/.claude/skills/，所有專案共用
        - project：安裝在當前專案的 .claude/skills/，只有該專案使用

    使用情境：
        - 個人開發者通常使用 global scope
        - 團隊專案可能需要 project scope，確保所有成員使用相同的 skills
    """
    if scope == "project":
        # 專案特定的 skills，安裝在當前目錄
        return Path.cwd() / ".claude" / "skills"
    else:
        # 個人 (global) skills，安裝在家目錄
        home = Path.home()
        return home / ".claude" / "skills"


def backup_skill(skill_path: Path) -> Optional[Path]:
    """
    備份現有的 skill 目錄。

    設計意圖：
        當使用 --backup 選項時，在覆蓋前先備份舊版本。
        這讓使用者可以在出問題時回滾到之前的版本。

    備份位置：
        放在同一層目錄的 .backup/ 子目錄下，以「名稱_時間戳」命名。
        例如：~/.claude/skills/.backup/pdf_20250125_143000

    注意事項：
        - 備份不會自動清理，使用者需要手動管理
        - 使用 doctor 指令可以看到備份目錄的狀態
    """
    if not skill_path.exists():
        return None

    # 使用時間戳確保備份名稱唯一
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
    安裝單一個 skill 到目標目錄。

    設計意圖：
        這是核心的安裝邏輯，處理了各種邊界情況：
        - 目標已存在時的衝突處理
        - 備份與覆蓋的安全機制
        - dry-run 模式的預覽功能
        - metadata 記錄來源追蹤

    參數：
        skill_path: 要安裝的 skill 來源目錄
        target_dir: 安裝的目標目錄
        repo_info: 來源 repo 資訊（用於寫入 metadata）
        commit_hash: 當前的 git commit（用於版本追蹤）
        force: 是否強制覆蓋現有 skill
        backup: 覆蓋前是否備份
        dry_run: 只預覽不實際執行

    回傳：
        (success, message) - 是否成功和說明訊息

    設計決策：
        - 預設不覆蓋，要求使用者明確使用 --force
        - 即使 --force 也可以搭配 --backup 保護舊版本
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

        # Backup if requested
        if backup:
            backup_path = backup_skill(dest_path)
            if backup_path:
                log_info(f"Backed up to: {backup_path}")

        shutil.rmtree(dest_path)
    else:
        if dry_run:
            return (True, f"would install to {dest_path}")

    # Copy the skill directory
    shutil.copytree(skill_path, dest_path)

    # Write metadata
    if repo_info:
        write_skill_metadata(dest_path, repo_info, commit_hash)

    return (True, "installed" if action == "install" else "updated")


def pack_skill(skill_path: Path, output_dir: Path) -> Path:
    """
    將 skill 打包成 zip 檔案（給 Claude Desktop 使用）。

    設計意圖：
        Claude Desktop（Mac/Windows 桌面版）使用不同於 Claude Code 的 skill 安裝方式，
        需要將 skill 打包成 .zip 檔案後拖放到應用程式中。

    打包格式：
        - 使用 ZIP_DEFLATED 壓縮
        - 保留完整目錄結構
        - 輸出檔名為 {skill_name}.zip

    注意事項：
        - 會自動建立輸出目錄
        - 同名檔案會被覆蓋
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


def interactive_select(skills: list[dict]) -> list[dict]:
    """
    互動式 skill 選擇介面。

    設計意圖：
        當使用者沒有指定 --all 或 --skills 時，提供友善的互動介面讓使用者選擇。
        這比起強制使用者記住 skill 名稱更為友善。

    支援的選擇格式：
        - 'all' 或 '*'：選擇全部
        - 單一數字：選擇該編號的 skill
        - 逗號分隔：1,3,5 選擇多個
        - 範圍：1-5 選擇連續範圍
        - 混合：1,3-5,7 組合使用
        - 'q'：取消選擇

    使用者體驗考量：
        - 顯示編號讓使用者不需要輸入完整名稱
        - 同時顯示 name 和 description 幫助判斷
        - 支援 Ctrl+C 和 EOF 優雅退出
    """
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


# =============================================================================
# CLI 指令處理
# =============================================================================
# 每個 cmd_* 函式對應一個 CLI 子指令
# 這些函式負責：解析參數、呼叫核心邏輯、格式化輸出


def prepare_repo_info(args) -> dict:
    """
    準備 repo 資訊，處理 branch 覆蓋和自動偵測。

    這是所有需要存取遠端 repo 的指令共用的前置處理。
    統一處理 --branch 參數和自動偵測預設分支的邏輯。
    """
    repo_info = parse_repo_url(args.repo)

    # Override branch if specified via CLI
    if hasattr(args, 'branch') and args.branch:
        repo_info["branch"] = args.branch
    # Auto-detect if URL didn't specify a branch (wasn't a tree URL)
    elif repo_info["branch"] == "main" and "/tree/" not in args.repo:
        log_info("Auto-detecting default branch...")
        repo_info["branch"] = detect_default_branch(repo_info["clone_url"])

    return repo_info


def format_skills_list(skills: list[dict], detailed: bool = False, show_source: bool = False) -> None:
    """
    格式化並輸出 skills 列表。

    設計意圖：
        統一 list 和 installed 指令的輸出格式，確保一致的使用者體驗。

    顯示模式：
        - 預設模式：只顯示名稱，用逗號分隔（適合快速瀏覽）
        - 詳細模式 (--detail)：表格形式，包含名稱和描述
        - 來源模式 (show_source)：額外顯示安裝來源資訊（URL、branch、commit）
    """
    if detailed:
        # Detailed table format
        # Calculate column widths
        name_width = max(len(s.get("name") or s["folder_name"]) for s in skills)
        name_width = max(name_width, 4)  # minimum "Name" header

        # Print header
        print(f"\n  {'Name':<{name_width}}  Description")
        print(f"  {'-' * name_width}  {'-' * 50}")

        for skill in skills:
            name = skill.get("name") or skill["folder_name"]
            desc = skill.get("description") or "-"
            # Truncate long descriptions
            if len(desc) > 60:
                desc = desc[:57] + "..."
            print(f"  {Colors.CYAN}{name:<{name_width}}{Colors.RESET}  {desc}")

            # Show source info if available and requested
            if show_source:
                metadata = read_skill_metadata(skill.get("path"))
                if metadata:
                    source = metadata.get("source_url", "-")
                    branch = metadata.get("branch", "-")
                    commit = metadata.get("commit", "-")
                    # Truncate long URLs
                    if len(source) > 50:
                        source = source[:47] + "..."
                    print(f"  {' ' * name_width}  {Colors.YELLOW}↳ {source} ({branch}@{commit}){Colors.RESET}")
    else:
        # Compact format (names only)
        names = [s.get("name") or s["folder_name"] for s in skills]
        print(f"\n  {', '.join(names)}")


def cmd_list(args):
    """
    list 指令：列出遠端 repo 中可用的 skills。

    使用情境：
        使用者想要安裝 skills 前，先看看有哪些可用的選項。

    流程：
        1. Clone repo 到暫存目錄（shallow clone 節省時間）
        2. 搜尋並發現所有 skills
        3. 格式化輸出
        4. 清理暫存目錄

    範例：
        skills-cli list                    # 列出官方 repo
        skills-cli list --repo <url>       # 列出指定 repo
        skills-cli list --detail           # 顯示詳細資訊
    """
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
    """
    installed 指令：列出本機已安裝的 skills。

    設計意圖：
        讓使用者知道目前安裝了哪些 skills，以及它們來自哪裡。
        這對於管理和除錯很重要。

    預設行為：
        - 同時顯示 global（~/.claude/skills/）和 project（./.claude/skills/）
        - 使用 --project 只顯示專案 skills
        - 使用 --detail 顯示來源追蹤資訊

    標籤說明：
        [GLOBAL] - 安裝在家目錄，所有專案共用
        [PROJECT] - 安裝在當前專案，只有該專案使用
    """
    total_skills = 0

    # If --target is specified, only show that directory
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

    # Show both global and project skills by default
    # (unless --project is specified, then only project)
    scopes_to_show = []

    if not args.project:
        # Show global skills
        global_dir = get_claude_skills_dir("personal")
        if global_dir.exists():
            global_skills = discover_skills(global_dir)
            if global_skills:
                scopes_to_show.append(("global", global_dir, global_skills))

    # Show project skills
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
    """
    remove 指令：移除已安裝的 skills。

    安全機制：
        1. 預設需要確認才會刪除（除非使用 --force）
        2. 支援 --dry-run 預覽會刪除什麼
        3. 可以指定特定 skills 或使用 --all

    注意事項：
        - 這是真正的刪除，不是移到垃圾桶
        - 如果需要備份，請在刪除前使用 --backup 選項重新安裝

    範例：
        skills-cli remove --skills pdf          # 移除特定 skill
        skills-cli remove --all --dry-run       # 預覽會移除什麼
        skills-cli remove --all --force         # 強制移除所有
    """
    # Determine target directory
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

    # Determine which skills to remove
    if args.skills:
        # Filter by specified skill names
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
        # Interactive selection
        skills_to_remove = interactive_select(installed_skills)

    if not skills_to_remove:
        log_info("No skills selected")
        return 0

    dry_run = getattr(args, 'dry_run', False)

    # Dry run mode - just show what would be removed
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

    # Confirm removal (unless --force)
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

    # Remove skills
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
    """
    install 指令：從遠端 repo 安裝 skills 到本機。

    這是最常用的指令，支援多種安裝模式：
        - 互動式選擇（預設）
        - 安裝全部（--all）
        - 指定特定 skills（--skills x,y,z）

    安全機制：
        - --dry-run：預覽會安裝什麼，不實際執行
        - --backup：覆蓋前備份舊版本
        - --force：允許覆蓋現有 skills

    metadata 追蹤：
        每個安裝的 skill 都會記錄來源資訊到 .skills-cli.json，
        方便之後追蹤版本或使用 sync 指令更新。

    範例：
        skills-cli install --all                    # 安裝官方 repo 所有 skills
        skills-cli install --skills pdf,xlsx        # 安裝指定 skills
        skills-cli install --all --dry-run          # 預覽安裝
        skills-cli install --all --force --backup   # 強制覆蓋並備份
    """
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

        # Get commit hash for metadata
        commit_hash = get_git_commit_hash(tmp_dir)

        # Dry run mode
        dry_run = getattr(args, 'dry_run', False)
        backup = getattr(args, 'backup', False)

        if dry_run:
            print(f"\n{Colors.YELLOW}[DRY RUN] The following actions would be performed:{Colors.RESET}\n")

        # Create target directory (skip in dry-run)
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)

        # Install skills
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
    """
    pack 指令：將 skills 打包成 zip 檔案（給 Claude Desktop 使用）。

    使用情境：
        Claude Desktop（桌面應用程式）使用與 Claude Code 不同的 skill 安裝方式，
        需要將 skill 打包成 .zip 檔案後手動匯入。

    輸出內容：
        - 每個 skill 一個 .zip 檔案
        - manifest.json：包含所有 skills 的清單資訊

    範例：
        skills-cli pack --output dist/desktop         # 打包所有 skills
        skills-cli pack --skills pdf,xlsx -o dist/    # 打包指定 skills
    """
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
    """
    sync 指令：從遠端 repo 同步（更新）skills。

    設計意圖：
        讓使用者可以一鍵更新已安裝的 skills 到最新版本。

    行為：
        - 如果目標目錄是 git repo：執行 git pull --rebase
        - 如果不是 git repo：重新下載所有 skills

    注意事項：
        - 目前不會保留本地修改，會被覆蓋
        - 未來可考慮加入 --stash 選項保留本地修改
    """
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


# =============================================================================
# 驗證與診斷功能
# =============================================================================

# SKILL.md 必須包含的欄位
# 這些欄位對於 Claude Code 正確識別和顯示 skill 是必要的
REQUIRED_SKILL_FIELDS = ["name", "description"]


def validate_skill_md(skill_path: Path) -> list[str]:
    """
    驗證單一個 skill 的 SKILL.md 格式是否正確。

    驗證項目：
        1. SKILL.md 檔案是否存在
        2. YAML frontmatter 格式是否正確
        3. 必要欄位（name、description）是否存在
        4. 內容是否為空
        5. 欄位長度是否合理

    回傳：
        issues 列表，如果驗證通過則為空列表
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

    # Check for YAML frontmatter
    if not content.startswith("---"):
        issues.append("Missing YAML frontmatter (should start with ---)")
        return issues

    parts = content.split("---", 2)
    if len(parts) < 3:
        issues.append("Invalid YAML frontmatter (missing closing ---)")
        return issues

    frontmatter = parts[1].strip()
    body = parts[2].strip()

    # Parse frontmatter
    metadata = {}
    for line in frontmatter.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip().strip('"').strip("'")

    # Check required fields
    for field in REQUIRED_SKILL_FIELDS:
        if field not in metadata or not metadata[field]:
            issues.append(f"Missing required field: {field}")

    # Check for empty body
    if not body:
        issues.append("Empty skill body (no instructions after frontmatter)")

    # Check for common issues
    if metadata.get("name") and len(metadata["name"]) > 50:
        issues.append("Name is too long (>50 characters)")

    if metadata.get("description") and len(metadata["description"]) > 500:
        issues.append("Description is too long (>500 characters)")

    return issues


def cmd_validate(args):
    """
    validate 指令：驗證 SKILL.md 格式是否正確。

    使用情境：
        - Skill 開發者在發布前檢查格式
        - 使用者排查 skill 無法識別的問題
        - CI/CD 流程中的品質檢查

    支援的驗證目標：
        - 本機安裝的 skills（預設）
        - 遠端 repo 中的 skills（--repo）
        - 指定路徑的 skill（--path）

    範例：
        skills-cli validate                         # 驗證已安裝的 skills
        skills-cli validate --repo <url>            # 驗證遠端 repo
        skills-cli validate --path ./my-skill/      # 驗證本地開發中的 skill
    """
    # Determine what to validate
    if args.path:
        skill_path = Path(args.path)
        if skill_path.is_file():
            skill_path = skill_path.parent
        skills_to_validate = [{"path": skill_path, "folder_name": skill_path.name}]
    elif args.repo:
        # Validate skills from a repo
        repo_info = prepare_repo_info(args)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp) / "repo"
            cloned_root = clone_repo(repo_info, tmp_dir)
            skills_root, skills_to_validate = find_skills_root(cloned_root)
    else:
        # Validate installed skills
        if args.project:
            target_dir = get_claude_skills_dir("project")
        else:
            target_dir = get_claude_skills_dir("personal")
        skills_to_validate = discover_skills(target_dir)

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


def cmd_doctor(args):
    """
    doctor 指令：診斷 skills 目錄結構和常見問題。

    設計意圖：
        當使用者遇到問題時，提供一站式的診斷工具，
        檢查目錄結構、權限、orphaned 目錄等常見問題。

    檢查項目：
        1. Global skills 目錄是否存在及其內容
        2. Project skills 目錄是否存在及其內容
        3. 是否有 orphaned 目錄（沒有 SKILL.md 的資料夾）
        4. 備份目錄的狀態

    輸出格式：
        使用圖示和顏色讓問題一目了然：
        ✓ 正常
        ⚠ 需要注意（但不是錯誤）
        ✗ 發現問題
    """
    issues = []
    warnings = []

    print(f"\n{Colors.BOLD}Skills CLI Doctor{Colors.RESET}\n")

    # Check global skills directory
    global_dir = get_claude_skills_dir("personal")
    print(f"  {Colors.CYAN}Global skills:{Colors.RESET} {global_dir}")
    if global_dir.exists():
        global_skills = discover_skills(global_dir)
        print(f"    {Colors.GREEN}✓{Colors.RESET} Directory exists ({len(global_skills)} skills)")

        # Check for issues in global skills
        for skill in global_skills:
            skill_issues = validate_skill_md(skill["path"])
            if skill_issues:
                warnings.append(f"Global skill '{skill['folder_name']}' has issues")
    else:
        print(f"    {Colors.YELLOW}⚠{Colors.RESET} Directory does not exist")

    # Check project skills directory
    project_dir = get_claude_skills_dir("project")
    print(f"\n  {Colors.CYAN}Project skills:{Colors.RESET} {project_dir}")
    if project_dir.exists():
        project_skills = discover_skills(project_dir)
        print(f"    {Colors.GREEN}✓{Colors.RESET} Directory exists ({len(project_skills)} skills)")

        # Check for issues in project skills
        for skill in project_skills:
            skill_issues = validate_skill_md(skill["path"])
            if skill_issues:
                warnings.append(f"Project skill '{skill['folder_name']}' has issues")
    else:
        print(f"    {Colors.YELLOW}○{Colors.RESET} Directory does not exist (this is normal)")

    # Check for orphaned directories (folders without SKILL.md)
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

    # Check for backup directory
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

    # Summary
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
# 程式進入點
# =============================================================================


def main():
    """
    CLI 程式進入點。

    職責：
        1. 定義所有子指令和參數
        2. 解析命令列參數
        3. 分派到對應的 cmd_* 函式
        4. 統一處理例外和返回碼

    返回碼說明：
        0 - 成功
        1 - 一般錯誤
        130 - 使用者中斷 (Ctrl+C)

    DEBUG 模式：
        設定環境變數 DEBUG=1 可以看到完整的錯誤堆疊
    """
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
    sys.exit(main())
