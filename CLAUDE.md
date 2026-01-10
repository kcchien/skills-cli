# Skills CLI - Project Memory

## Project Overview
Cross-platform CLI tool for managing Claude Code and Claude Desktop skills. Written in Python with no external dependencies (uses only standard library).

## Tech Stack
- **Language**: Python 3.10+
- **Build System**: setuptools with pyproject.toml
- **Entry Point**: `skills-cli` command via `skills_cli:main`

## Project Structure
```
skills-cli/
├── skills_cli/
│   ├── __init__.py    # Package init, exports main()
│   ├── cli.py         # CLI argument parsing and commands
│   └── core.py        # Core logic (git operations, skill discovery, etc.)
├── tests/
├── pyproject.toml     # Project configuration
└── install.sh         # Installation script
```

## Key Commands
- `skills-cli list [URL]` - List available skills from a repository
- `skills-cli install [URL]` - Install skills from a repository
- `skills-cli installed` - List locally installed skills
- `skills-cli remove` - Remove installed skills
- `skills-cli sync [URL]` - Sync skills from a repository
- `skills-cli pack [URL]` - Pack skills into zip files
- `skills-cli validate` - Validate SKILL.md format
- `skills-cli doctor` - Diagnose skills directory issues

## Development
```bash
# Install in development mode
pip install -e .

# Run tests
pytest

# Run directly
python -m skills_cli.cli
```

## Git Remotes
- **origin**: git@github.com:kcchien/skills-cli.git (GitHub)
- Note: User mentioned there may also be a GitLab remote (not currently configured)

## Recent Changes
- Added support for positional URL arguments (previously only `--repo` flag was supported)
- Commands `install`, `list`, `sync`, `pack` now accept URL as first positional argument

## Commit Message Style
- Uses conventional commits format (feat:, fix:, chore:, docs:)
- User prefers detailed commit messages in Traditional Chinese (zh-TW)
