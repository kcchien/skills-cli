"""
Unit tests for skills-cli core functions.

These tests ensure the core logic works correctly before and after refactoring.
Run with: python -m pytest tests/ -v
"""

import tempfile
from pathlib import Path

from skills_cli import (
    parse_repo_url,
    discover_skills,
    find_skills_root,
    parse_skill_md,
    validate_skill_md,
    COMMON_SKILL_DIRS,
)


class TestParseRepoUrl:
    """Tests for parse_repo_url function."""

    def test_github_tree_url_with_subdir(self):
        """Parse GitHub tree URL with subdirectory."""
        url = "https://github.com/anthropics/skills/tree/main/skills"
        result = parse_repo_url(url)

        assert result["clone_url"] == "https://github.com/anthropics/skills.git"
        assert result["branch"] == "main"
        assert result["subdir"] == "skills"
        assert result["host"] == "github"

    def test_github_tree_url_without_subdir(self):
        """Parse GitHub tree URL without subdirectory."""
        url = "https://github.com/user/repo/tree/develop"
        result = parse_repo_url(url)

        assert result["clone_url"] == "https://github.com/user/repo.git"
        assert result["branch"] == "develop"
        assert result["subdir"] is None
        assert result["host"] == "github"

    def test_github_tree_url_with_nested_subdir(self):
        """Parse GitHub tree URL with nested subdirectory."""
        url = "https://github.com/org/repo/tree/main/packages/skills/claude"
        result = parse_repo_url(url)

        assert result["clone_url"] == "https://github.com/org/repo.git"
        assert result["branch"] == "main"
        assert result["subdir"] == "packages/skills/claude"

    def test_gitlab_tree_url(self):
        """Parse GitLab tree URL."""
        url = "https://gitlab.com/company/team-repo/-/tree/main/skills"
        result = parse_repo_url(url)

        assert result["clone_url"] == "https://gitlab.com/company/team-repo.git"
        assert result["branch"] == "main"
        assert result["subdir"] == "skills"
        assert result["host"] == "gitlab"

    def test_plain_https_url(self):
        """Parse plain HTTPS URL (repo homepage)."""
        url = "https://github.com/user/repo"
        result = parse_repo_url(url)

        assert result["clone_url"] == "https://github.com/user/repo.git"
        assert result["branch"] == "main"  # default
        assert result["subdir"] is None

    def test_https_url_with_git_suffix(self):
        """Parse HTTPS URL that already has .git suffix."""
        url = "https://github.com/user/repo.git"
        result = parse_repo_url(url)

        assert result["clone_url"] == "https://github.com/user/repo.git"

    def test_ssh_url(self):
        """Parse SSH URL."""
        url = "git@github.com:user/repo.git"
        result = parse_repo_url(url)

        assert result["clone_url"] == "git@github.com:user/repo.git"
        assert result["host"] == "github.com"

    def test_ssh_url_without_git_suffix(self):
        """Parse SSH URL without .git suffix."""
        url = "git@github.com:user/repo"
        result = parse_repo_url(url)

        assert result["clone_url"] == "git@github.com:user/repo.git"

    def test_self_hosted_gitlab(self):
        """Parse self-hosted GitLab URL."""
        url = "https://git.company.com/team/project/-/tree/develop/skills"
        result = parse_repo_url(url)

        assert result["clone_url"] == "https://git.company.com/team/project.git"
        assert result["branch"] == "develop"
        assert result["subdir"] == "skills"


class TestDiscoverSkills:
    """Tests for discover_skills function."""

    def test_discover_skills_in_directory(self):
        """Discover skills in a directory with SKILL.md files."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)

            # Create skill directories
            (skills_dir / "pdf").mkdir()
            (skills_dir / "pdf" / "SKILL.md").write_text(
                "---\nname: PDF Tool\ndescription: Work with PDFs\n---\nContent"
            )

            (skills_dir / "xlsx").mkdir()
            (skills_dir / "xlsx" / "SKILL.md").write_text(
                "---\nname: Excel Tool\ndescription: Work with Excel\n---\nContent"
            )

            skills = discover_skills(skills_dir)

            assert len(skills) == 2
            names = [s.get("name") for s in skills]
            assert "PDF Tool" in names
            assert "Excel Tool" in names

    def test_discover_skills_empty_directory(self):
        """Return empty list for directory without skills."""
        with tempfile.TemporaryDirectory() as tmp:
            skills = discover_skills(Path(tmp))
            assert skills == []

    def test_discover_skills_ignores_files(self):
        """Ignore files (only look at directories)."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)

            # Create a file, not a directory
            (skills_dir / "README.md").write_text("# README")

            skills = discover_skills(skills_dir)
            assert skills == []

    def test_discover_skills_ignores_dirs_without_skill_md(self):
        """Ignore directories without SKILL.md."""
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)

            # Create directory without SKILL.md
            (skills_dir / "not-a-skill").mkdir()
            (skills_dir / "not-a-skill" / "README.md").write_text("# Not a skill")

            skills = discover_skills(skills_dir)
            assert skills == []

    def test_discover_skills_nonexistent_directory(self):
        """Return empty list for nonexistent directory."""
        skills = discover_skills(Path("/nonexistent/path"))
        assert skills == []


class TestFindSkillsRoot:
    """Tests for find_skills_root function."""

    def test_find_skills_in_root(self):
        """Find skills when they are in root directory."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)

            # Create skill directly in root
            (repo_root / "my-skill").mkdir()
            (repo_root / "my-skill" / "SKILL.md").write_text(
                "---\nname: My Skill\ndescription: Test\n---\nContent"
            )

            skills_root, skills = find_skills_root(repo_root)

            assert skills_root == repo_root
            assert len(skills) == 1

    def test_find_skills_in_common_subdir(self):
        """Find skills in common subdirectory (skills/)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)

            # Create skills in 'skills/' subdirectory
            (repo_root / "skills").mkdir()
            (repo_root / "skills" / "pdf").mkdir()
            (repo_root / "skills" / "pdf" / "SKILL.md").write_text(
                "---\nname: PDF\ndescription: Test\n---\nContent"
            )

            skills_root, skills = find_skills_root(repo_root)

            assert skills_root == repo_root / "skills"
            assert len(skills) == 1

    def test_find_skills_searches_multiple_common_dirs(self):
        """Search multiple common directory names."""
        for common_dir in COMMON_SKILL_DIRS[:3]:  # Test first few
            with tempfile.TemporaryDirectory() as tmp:
                repo_root = Path(tmp)

                # Create skills in this common directory
                skill_dir = repo_root / common_dir / "test-skill"
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(
                    "---\nname: Test\ndescription: Test\n---\nContent"
                )

                skills_root, skills = find_skills_root(repo_root)

                assert len(skills) == 1
                assert skills[0]["folder_name"] == "test-skill"

    def test_find_skills_deep_search(self):
        """Find skills in nested directory structure."""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)

            # Create skill in unusual location
            (repo_root / "packages" / "tools" / "my-skill").mkdir(parents=True)
            (repo_root / "packages" / "tools" / "my-skill" / "SKILL.md").write_text(
                "---\nname: Deep Skill\ndescription: Test\n---\nContent"
            )

            skills_root, skills = find_skills_root(repo_root)

            assert len(skills) == 1
            assert skills[0].get("name") == "Deep Skill"


class TestParseSkillMd:
    """Tests for parse_skill_md function."""

    def test_parse_complete_frontmatter(self):
        """Parse SKILL.md with complete frontmatter."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_md = Path(tmp) / "SKILL.md"
            skill_md.write_text(
                "---\nname: My Skill\ndescription: A great skill\n---\nContent here"
            )

            result = parse_skill_md(skill_md)

            assert result["name"] == "My Skill"
            assert result["description"] == "A great skill"

    def test_parse_frontmatter_with_quotes(self):
        """Parse frontmatter with quoted values."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_md = Path(tmp) / "SKILL.md"
            skill_md.write_text(
                '---\nname: "Quoted Name"\ndescription: \'Single quoted\'\n---\nContent'
            )

            result = parse_skill_md(skill_md)

            assert result["name"] == "Quoted Name"
            assert result["description"] == "Single quoted"

    def test_parse_missing_frontmatter(self):
        """Return None values when frontmatter is missing."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_md = Path(tmp) / "SKILL.md"
            skill_md.write_text("# Just content\nNo frontmatter here")

            result = parse_skill_md(skill_md)

            assert result["name"] is None
            assert result["description"] is None

    def test_parse_partial_frontmatter(self):
        """Parse frontmatter with only some fields."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_md = Path(tmp) / "SKILL.md"
            skill_md.write_text("---\nname: Only Name\n---\nContent")

            result = parse_skill_md(skill_md)

            assert result["name"] == "Only Name"
            assert result["description"] is None


class TestValidateSkillMd:
    """Tests for validate_skill_md function."""

    def test_valid_skill(self):
        """Valid skill should return no issues."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Valid Skill\ndescription: A valid skill\n---\nContent body"
            )

            issues = validate_skill_md(skill_dir)

            assert issues == []

    def test_missing_skill_md(self):
        """Missing SKILL.md should be reported."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp)
            # No SKILL.md file

            issues = validate_skill_md(skill_dir)

            assert len(issues) == 1
            assert "Missing SKILL.md" in issues[0]

    def test_missing_frontmatter(self):
        """Missing frontmatter should be reported."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp)
            (skill_dir / "SKILL.md").write_text("# No frontmatter\nJust content")

            issues = validate_skill_md(skill_dir)

            assert any("frontmatter" in issue.lower() for issue in issues)

    def test_missing_required_fields(self):
        """Missing required fields should be reported."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Only Name\n---\nContent"
            )

            issues = validate_skill_md(skill_dir)

            assert any("description" in issue.lower() for issue in issues)

    def test_empty_body(self):
        """Empty body after frontmatter should be reported."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Test\ndescription: Test\n---\n"
            )

            issues = validate_skill_md(skill_dir)

            assert any("empty" in issue.lower() for issue in issues)

    def test_name_too_long(self):
        """Name exceeding 50 characters should be reported."""
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp)
            long_name = "A" * 60
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {long_name}\ndescription: Test\n---\nContent"
            )

            issues = validate_skill_md(skill_dir)

            assert any("name" in issue.lower() and "long" in issue.lower() for issue in issues)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
