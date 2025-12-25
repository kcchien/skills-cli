# Skills CLI

Cross-platform CLI for managing Claude Code and Claude Desktop skills.

**One definition, multiple deployments** - Deploy skills from a central Git repository to both Claude Code CLI and Claude Desktop App.

## Features

- **Cross-platform**: Windows, macOS, Linux
- **Flexible repo support**: GitHub, GitLab, self-hosted Git with subdirectory paths
- **Selective installation**: Install all skills or choose specific ones
- **Dual deployment targets**:
  - **Claude Code**: Sync to `~/.claude/skills/` or `.claude/skills/`
  - **Claude Desktop**: Pack as `.zip` for manual/enterprise upload

## Installation

### Quick Install (macOS/Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/user/skills-cli/main/install.sh | bash
```

### Quick Install (Windows PowerShell)

```powershell
irm https://raw.githubusercontent.com/user/skills-cli/main/install.ps1 | iex
```

### From Source

```bash
git clone https://github.com/user/skills-cli.git
cd skills-cli
pip install -e .
```

### Direct Usage (No Install)

```bash
python skills_cli.py <command> [options]
```

## Usage

### List Available Skills

```bash
# List skills from official Anthropic repo
skills-cli list --repo https://github.com/anthropics/skills/tree/main/skills

# List skills from custom repo
skills-cli list --repo https://gitlab.example.com/team/skills
```

### Install Skills

```bash
# Interactive selection
skills-cli install --repo https://github.com/user/skills

# Install all skills
skills-cli install --repo https://github.com/user/skills --all

# Install specific skills
skills-cli install --repo https://github.com/user/skills --skills pdf,xlsx,docx

# Install to project directory (.claude/skills/)
skills-cli install --repo https://github.com/user/skills --project

# Force overwrite existing skills
skills-cli install --repo https://github.com/user/skills --force
```

### Pack for Claude Desktop

```bash
# Pack all skills to zip files
skills-cli pack --repo https://github.com/user/skills --output dist/desktop

# Pack specific skills
skills-cli pack --repo https://github.com/user/skills --skills pdf,xlsx --output dist/
```

Output:
```
dist/desktop/
├── pdf.zip
├── xlsx.zip
├── docx.zip
└── manifest.json
```

### Sync Skills (Git Pull/Clone)

```bash
# Sync to personal skills directory
skills-cli sync --repo https://github.com/user/skills

# Sync to project directory
skills-cli sync --repo https://github.com/user/skills --project
```

## Supported Repository URL Formats

| Format | Example |
|--------|---------|
| GitHub (with subdirectory) | `https://github.com/anthropics/skills/tree/main/skills` |
| GitHub (root) | `https://github.com/user/my-skills` |
| GitLab (with subdirectory) | `https://gitlab.com/team/repo/-/tree/main/skills` |
| GitLab (root) | `https://gitlab.example.com/team/skills` |
| SSH | `git@github.com:user/skills.git` |
| Self-hosted | `https://git.company.com/team/skills` |

## CI/CD Integration

### GitHub Actions

```yaml
name: Build Skills

on:
  push:
    branches: [main]
    paths:
      - 'skills/**'

jobs:
  pack-desktop:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install skills-cli
        run: pip install skills-cli

      - name: Pack all skills
        run: skills-cli pack --repo . --output dist/desktop

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: desktop-skills
          path: dist/desktop/
```

## Requirements

- Python 3.10+
- Git 2.25+ (for sparse-checkout support)

## License

MIT
